"""MarriageApplication endpoints (PRD 3.2, 3.3, 3.8)."""
from flask import Blueprint, g

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from util import new_common, serialize, touch
from services.common import (
    get_body, require_fields, require_str, require_enum, lookup,
    parse_pagination, sort_by_created,
)
from services import calculations as calc
from services import ledger as ledger_svc

bp = Blueprint("applications", __name__)


@bp.route("/applications", methods=["POST"])
@require_roles("Clerk", "Applicant")
def create_application():
    body = get_body()
    require_fields(body, "applicant_a_id", "applicant_b_id", "ceremony_county")
    require_str(body["applicant_a_id"], "applicant_a_id")
    require_str(body["applicant_b_id"], "applicant_b_id")
    require_str(body["ceremony_county"], "ceremony_county")

    is_confidential = body.get("is_confidential", False)
    if is_confidential is None:
        is_confidential = False
    if not isinstance(is_confidential, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_confidential must be a boolean")

    ent = new_common("application")
    ent.update({
        "applicant_a_id": body["applicant_a_id"],
        "applicant_b_id": body["applicant_b_id"],
        "ceremony_county": body["ceremony_county"],
        "is_confidential": is_confidential,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "denial_reason_code": None,
        "total_charged_cents": 0,
    })
    store.applications[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/applications/<application_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def get_application(application_id):
    ent = lookup("application", application_id)
    return success(serialize(ent), status=200)


@bp.route("/applications", methods=["GET"])
@require_roles("Clerk", "Registrar")
def list_applications():
    from flask import request
    limit, offset = parse_pagination()
    a_filter = request.args.get("applicant_a_id")
    b_filter = request.args.get("applicant_b_id")
    items = list(store.applications.values())
    if a_filter is not None:
        items = [x for x in items if x["applicant_a_id"] == a_filter]
    if b_filter is not None:
        items = [x for x in items if x["applicant_b_id"] == b_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(x) for x in page], limit, offset, total)


@bp.route("/applications/<application_id>/submit", methods=["POST"])
@require_roles("Applicant", "Clerk")
def submit_application(application_id):
    app = lookup("application", application_id)
    # State gate (PRD 3.10: state check before business rules).
    if app["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Application is not in DRAFT")
    # Both applicants must resolve to existing Applicants.
    a = lookup("applicant", app["applicant_a_id"])
    b = lookup("applicant", app["applicant_b_id"])
    if app["applicant_a_id"] == app["applicant_b_id"]:
        raise ApiError("ERR_DUPLICATE_APPLICANT", "Both parties are the same applicant")
    if a["prior_marriage_status"] == "MARRIED" or b["prior_marriage_status"] == "MARRIED":
        raise ApiError("ERR_APPLICANT_ALREADY_MARRIED", "An applicant is already married")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success(serialize(app), status=200)


def _check_age(applicant):
    age = calc.whole_years(applicant["date_of_birth"], store.now())
    from constants import MIN_AGE_NO_CONSENT, MIN_AGE_WITH_CONSENT
    if age >= MIN_AGE_NO_CONSENT:
        return
    if age < MIN_AGE_WITH_CONSENT:
        raise ApiError("ERR_AGE_INELIGIBLE", "Applicant is below the minimum marriageable age")
    # 16 <= age < 18: requires judicial consent.
    if not applicant.get("has_judicial_consent"):
        raise ApiError("ERR_JUDICIAL_CONSENT_REQUIRED", "Minor applicant lacks judicial consent")


def _check_remarriage_wait(applicant):
    from datetime import timedelta
    from constants import REMARRIAGE_WAIT_DAYS
    if applicant["prior_marriage_status"] not in ("DIVORCED", "WIDOWED"):
        return
    if applicant.get("prior_dissolution_date") is None:
        return
    eligible_from = applicant["prior_dissolution_date"] + timedelta(days=REMARRIAGE_WAIT_DAYS)
    if store.now() < eligible_from:
        raise ApiError("ERR_REMARRIAGE_WAIT_NOT_MET", "Remarriage waiting period not yet met")


def _check_license_overlap(applicant_ids, new_valid_from, new_expires_at):
    """applicant_license_window_overlap: half-open interval test (PRD 3.8)."""
    for lic in store.licenses.values():
        if lic["status"] != "ISSUED":
            continue
        owning = store.applications.get(lic["application_id"])
        if owning is None:
            continue
        parties = {owning["applicant_a_id"], owning["applicant_b_id"]}
        if parties.isdisjoint(applicant_ids):
            continue
        # Half-open overlap: new.valid_from < existing.expires_at AND existing.valid_from < new.expires_at
        if new_valid_from < lic["expires_at"] and lic["valid_from"] < new_expires_at:
            raise ApiError("ERR_APPLICANT_LICENSE_OVERLAP",
                           "An applicant already holds an overlapping license window")


@bp.route("/applications/<application_id>/decide", methods=["POST"])
@require_roles("Clerk")
def decide_application(application_id):
    app = lookup("application", application_id)
    body = get_body()
    require_fields(body, "decision")
    require_enum(body["decision"], {"APPROVE", "DENY"}, "decision")
    decision = body["decision"]

    if app["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Application is not UNDER_REVIEW")

    if decision == "DENY":
        app["status"] = "DENIED"
        app["denial_reason_code"] = body.get("denial_reason_code")
        touch(app)
        return success(serialize(app), status=200)

    # APPROVE: run eligibility screen on both parties.
    a = lookup("applicant", app["applicant_a_id"])
    b = lookup("applicant", app["applicant_b_id"])
    for applicant in (a, b):
        _check_age(applicant)
    for applicant in (a, b):
        _check_remarriage_wait(applicant)

    now = store.now()
    new_valid_from = calc.waiting_period_valid_from(now)
    new_expires_at = calc.validity_expires_at(now)
    _check_license_overlap({a["id"], b["id"]}, new_valid_from, new_expires_at)

    # All checks pass: approve, issue license, charge fee.
    app["status"] = "APPROVED"
    app["approved_by_user_id"] = g.user_id
    touch(app)

    from constants import LICENSE_FEE_CENTS
    lic = new_common("license")
    lic.update({
        "application_id": app["id"],
        "is_confidential": app["is_confidential"],
        "issued_at": now,
        "valid_from": new_valid_from,
        "expires_at": new_expires_at,
        "status": "ISSUED",
    })
    store.licenses[lic["id"]] = lic

    ledger_svc.append_entry(app["id"], "CHARGE", LICENSE_FEE_CENTS, "LICENSE", lic["id"])
    ledger_svc.recompute_total_charged(app)

    return success(serialize(app), status=200)


@bp.route("/applications/<application_id>/licenses", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def list_application_licenses(application_id):
    lookup("application", application_id)
    limit, offset = parse_pagination()
    items = [l for l in store.licenses.values() if l["application_id"] == application_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(l) for l in page], limit, offset, total)


@bp.route("/applications/<application_id>/ledger", methods=["GET"])
@require_roles("Clerk", "Registrar")
def list_application_ledger(application_id):
    lookup("application", application_id)
    limit, offset = parse_pagination()
    items = [e for e in store.ledger.values() if e["application_id"] == application_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(e) for e in page], limit, offset, total)
