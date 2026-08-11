"""TrainingAgreement endpoints: create/read/list, quote/revise/negotiate/sign/cancel,
refresh_assessment_pin, nested cohort/outcome-report lists."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import now, stamp_new, store, touch
from errors import fail
from middleware import check_employer_scope, require_roles
from response import ok, ok_list, serialize
from services import lifecycle, lookups
from services.calculations import quote_pricing
from util import (
    body_json,
    fmt_dt,
    pagination_args,
    parse_dt,
    req_enum,
    req_int,
    req_number,
    req_str,
    require_dt,
)

bp = Blueprint("agreements", __name__)

READ_ROLES = (
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
)

PRICING_MODELS = ("PER_PARTICIPANT", "FLAT_COHORT")
DELIVERY_MODES = ("ON_SITE", "ON_CAMPUS")


def _paginate(items):
    items = sorted(items, key=lambda r: r["created_at"])
    limit, offset = pagination_args()
    page = items[offset : offset + limit]
    return ok_list([serialize(r) for r in page], len(items), limit, offset)


def _check_not_terminal(agreement):
    if agreement["contract_status"] in ("COMPLETED", "CANCELLED"):
        fail(
            "ERR_AGREEMENT_TERMINAL",
            f"Agreement is {agreement['contract_status']} and accepts no further operations",
        )


def _validate_estimates(body, partial=False):
    """Validate (and return) estimate fields; on partial, only those present."""
    out = {}
    if not partial or "est_participant_count" in body:
        v = req_int(body, "est_participant_count", min_value=1)
        out["est_participant_count"] = v
    if not partial or "est_delivery_hours" in body:
        v = req_number(body, "est_delivery_hours", min_value=0)
        out["est_delivery_hours"] = v
    if not partial or "pricing_model" in body:
        out["pricing_model"] = req_enum(body, "pricing_model", PRICING_MODELS)
    if not partial or "delivery_mode" in body:
        out["delivery_mode"] = req_enum(body, "delivery_mode", DELIVERY_MODES)
    if not partial or "target_start_date" in body:
        raw = body.get("target_start_date")
        out["target_start_date"] = fmt_dt(require_dt(raw, "target_start_date"))
    return out


@bp.route("/ct/employers/<eid>/training-agreements", methods=["POST"])
def create_agreement(eid):
    require_roles("WorkforceCoordinator")
    lookups.get_or_404("employers", eid, "Employer")
    body = body_json()
    assessment_id = req_str(body, "needs_assessment_id")
    estimates = _validate_estimates(body)
    max_cohorts = req_int(body, "max_cohorts", min_value=1)
    campus_venue_id = body.get("campus_venue_id")
    if campus_venue_id is not None and not isinstance(campus_venue_id, str):
        fail("ERR_INVALID_REQUEST", "Field 'campus_venue_id' must be a string")

    assessment = store["assessments"].get(assessment_id)
    if assessment is None:
        fail("ERR_INVALID_REQUEST", f"needs_assessment_id {assessment_id} does not exist")
    if assessment["employer_id"] != eid:
        fail(
            "ERR_INVALID_REQUEST",
            "needs_assessment_id must reference an assessment of the same employer",
        )
    if campus_venue_id is not None and campus_venue_id not in store["venues"]:
        fail("ERR_INVALID_REQUEST", f"campus_venue_id {campus_venue_id} does not exist")

    rec = stamp_new(
        {
            "id": db.new_id(),
            "employer_id": eid,
            "needs_assessment_id": assessment_id,
            "assessment_version_pinned": assessment["version"],
            "pricing_model": estimates["pricing_model"],
            "delivery_mode": estimates["delivery_mode"],
            "est_participant_count": estimates["est_participant_count"],
            "est_delivery_hours": estimates["est_delivery_hours"],
            "target_start_date": estimates["target_start_date"],
            "max_cohorts": max_cohorts,
            "campus_venue_id": campus_venue_id,
            "quoted_total_cents": 0,
            "quote_issued_at": None,
            "quote_expires_at": None,
            "negotiation_round": 0,
            "contract_status": "DRAFT",
            "billing_status": "UNBILLED",
            "signed_at": None,
        }
    )
    store["agreements"][rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/ct/training-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    uid, role = require_roles(*READ_ROLES)
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    check_employer_scope(uid, role, agreement["employer_id"])
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements", methods=["GET"])
def list_agreements():
    uid, role = require_roles(*READ_ROLES)
    items = list(store["agreements"].values())
    if role == "EmployerContact":
        items = [a for a in items if a["employer_id"] == uid]
    f_assessment = request.args.get("needs_assessment_id")
    f_employer = request.args.get("employer_id")
    f_status = request.args.get("contract_status")
    if f_assessment is not None:
        items = [a for a in items if a["needs_assessment_id"] == f_assessment]
    if f_employer is not None:
        items = [a for a in items if a["employer_id"] == f_employer]
    if f_status is not None:
        items = [a for a in items if a["contract_status"] == f_status]
    return _paginate(items)


def _issue_quote(agreement):
    quoted = quote_pricing(agreement, now())
    agreement["quoted_total_cents"] = quoted
    issued = now()
    agreement["quote_issued_at"] = fmt_dt(issued)
    agreement["quote_expires_at"] = fmt_dt(issued + timedelta(days=30))


@bp.route("/ct/training-agreements/<aid>/quote", methods=["POST"])
def quote_agreement(aid):
    require_roles("WorkforceCoordinator")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    _check_not_terminal(agreement)
    if agreement["contract_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", f"Cannot quote an agreement in {agreement['contract_status']}")
    assessment = store["assessments"].get(agreement["needs_assessment_id"])
    if assessment is None or assessment["status"] != "APPROVED":
        fail("ERR_ASSESSMENT_NOT_APPROVED", "The linked needs assessment is not APPROVED")
    _issue_quote(agreement)
    agreement["contract_status"] = "QUOTED"
    touch(agreement)
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements/<aid>/revise", methods=["POST"])
def revise_agreement(aid):
    require_roles("WorkforceCoordinator")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    body = body_json()
    expected = body.get("expected_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST", "Field 'expected_agreement_version' is required and must be an integer")
    updates = _validate_estimates(body, partial=True)
    _check_not_terminal(agreement)
    if agreement["contract_status"] != "NEGOTIATING":
        fail("ERR_INVALID_STATE", f"Cannot revise an agreement in {agreement['contract_status']}")
    if expected != agreement["version"]:
        fail(
            "ERR_STALE_VERSION",
            f"expected_agreement_version {expected} does not match current version {agreement['version']}",
        )
    for key, value in updates.items():
        agreement[key] = value
    agreement["negotiation_round"] += 1
    _issue_quote(agreement)
    agreement["contract_status"] = "QUOTED"
    touch(agreement)
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements/<aid>/negotiate", methods=["POST"])
def negotiate_agreement(aid):
    uid, _role = require_roles("EmployerContact")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    if uid != agreement["employer_id"]:
        fail("ERR_FORBIDDEN_FOR_ROLE", "EmployerContact may only negotiate its own employer's agreements")
    _check_not_terminal(agreement)
    if agreement["contract_status"] != "QUOTED":
        fail("ERR_INVALID_STATE", f"Cannot negotiate an agreement in {agreement['contract_status']}")
    if now() > parse_dt(agreement["quote_expires_at"]):
        fail("ERR_QUOTE_EXPIRED", "The quote has expired")
    agreement["contract_status"] = "NEGOTIATING"
    touch(agreement)
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements/<aid>/sign", methods=["POST"])
def sign_agreement(aid):
    uid, _role = require_roles("EmployerContact")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    if uid != agreement["employer_id"]:
        fail("ERR_FORBIDDEN_FOR_ROLE", "EmployerContact may only sign its own employer's agreements")
    _check_not_terminal(agreement)
    if agreement["contract_status"] != "QUOTED":
        fail("ERR_INVALID_STATE", f"Cannot sign an agreement in {agreement['contract_status']}")
    if now() > parse_dt(agreement["quote_expires_at"]):
        fail("ERR_QUOTE_EXPIRED", "The quote has expired")
    assessment = store["assessments"].get(agreement["needs_assessment_id"])
    if (
        assessment is None
        or assessment["version"] != agreement["assessment_version_pinned"]
        or assessment["status"] != "APPROVED"
    ):
        fail("ERR_STALE_ASSESSMENT", "The pinned assessment version is no longer current")
    agreement["contract_status"] = "SIGNED"
    agreement["signed_at"] = fmt_dt(now())
    touch(agreement)
    employer = store["employers"].get(agreement["employer_id"])
    if employer is not None and employer["status"] in ("PROSPECT", "DORMANT"):
        employer["status"] = "ACTIVE"
        touch(employer)
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements/<aid>/cancel", methods=["POST"])
def cancel_agreement(aid):
    require_roles("WorkforceCoordinator", "CollegeAdmin")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    _check_not_terminal(agreement)
    if agreement["contract_status"] not in ("DRAFT", "QUOTED", "NEGOTIATING", "SIGNED", "IN_DELIVERY"):
        fail("ERR_INVALID_STATE", f"Cannot cancel an agreement in {agreement['contract_status']}")
    if agreement["contract_status"] in ("SIGNED", "IN_DELIVERY"):
        lifecycle.cancel_agreement_cascade(agreement)
    agreement["contract_status"] = "CANCELLED"
    touch(agreement)
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements/<aid>/refresh_assessment_pin", methods=["POST"])
def refresh_assessment_pin(aid):
    require_roles("WorkforceCoordinator")
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    _check_not_terminal(agreement)
    if agreement["contract_status"] not in ("DRAFT", "QUOTED", "NEGOTIATING"):
        fail(
            "ERR_INVALID_STATE",
            f"Cannot refresh the assessment pin in {agreement['contract_status']}",
        )
    assessment = store["assessments"].get(agreement["needs_assessment_id"])
    if assessment is None or assessment["status"] != "APPROVED":
        fail("ERR_ASSESSMENT_NOT_APPROVED", "The linked needs assessment is not APPROVED")
    agreement["assessment_version_pinned"] = assessment["version"]
    touch(agreement)
    return ok(serialize(agreement))


@bp.route("/ct/training-agreements/<aid>/cohorts", methods=["GET"])
def list_agreement_cohorts(aid):
    uid, role = require_roles(*READ_ROLES)
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    check_employer_scope(uid, role, agreement["employer_id"])
    return _paginate(lookups.cohorts_of_agreement(aid))


@bp.route("/ct/training-agreements/<aid>/outcome-reports", methods=["GET"])
def list_agreement_reports(aid):
    uid, role = require_roles(*READ_ROLES)
    agreement = lookups.get_or_404("agreements", aid, "TrainingAgreement")
    check_employer_scope(uid, role, agreement["employer_id"])
    return _paginate(lookups.reports_of_agreement(aid))
