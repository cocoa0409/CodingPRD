"""Assistance applications: intake, lifecycle, members, documents, screening
(PRD 3.3-3.7)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_PATIENT_NOT_FOUND, ERR_APPLICATION_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND, ERR_DUPLICATE_OPEN_APPLICATION,
    ERR_APPLICATION_NOT_DRAFT, ERR_APPLICATION_NOT_SUBMITTED,
    ERR_APPLICATION_NOT_UNDER_REVIEW, ERR_APPLICATION_NOT_PENDING_DOCUMENTS,
    ERR_APPLICATION_TERMINAL, ERR_HOUSEHOLD_SELF_REQUIRED, ERR_NO_ACTIVE_POLICY,
    ERR_DOCS_OUTSTANDING, ERR_DOC_DEADLINE_NOT_REACHED, ERR_INVALID_PERIOD,
    ERR_MEMBER_APPLICATION_MISMATCH, ERR_SCREENING_ALREADY_EXISTS,
    ERR_INSUFFICIENT_FACTORS,
)
from middleware import authorized, check_ownership
from response import success_object
from routes.helpers import list_envelope, require
from services.core import (
    active_policy, application_view, create_notice, freeze_accounts_for_application,
    get_screening, members_of, new_record, pinned_policy, public,
    release_holds_for_patient, score_screening, touch, FACTOR_FIELDS,
)
from util import CLOCK, fmt_dt, parse_dt
from validate import (
    get_body, opt_int_or_none, req_date, req_enum, req_int, req_str, req_str_list,
)

bp = Blueprint("applications", __name__)

ALL_READ = ["Patient", "FinancialCounselor", "AssistanceReviewer",
            "BillingAdministrator", "CollectionsAgent", "ComplianceOfficer"]
APP_READ = ["Patient", "FinancialCounselor", "AssistanceReviewer",
            "BillingAdministrator", "ComplianceOfficer"]
LIST_ROLES = ["FinancialCounselor", "AssistanceReviewer", "BillingAdministrator",
              "CollectionsAgent", "ComplianceOfficer"]
SCREENING_SOURCES = {"STANDARD", "PRESUMPTIVE"}
RELATIONSHIPS = {"SELF", "SPOUSE", "CHILD", "OTHER_DEPENDENT"}
DOC_TYPES = {"PAY_STUB", "TAX_RETURN", "BENEFIT_LETTER", "BANK_STATEMENT", "IDENTITY"}
OPEN_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "PENDING_DOCUMENTS")


def _get_app(aid):
    return require("applications", aid, ERR_APPLICATION_NOT_FOUND)


# ---------------------------------------------------------------------------
# Create / list / fetch
# ---------------------------------------------------------------------------

@bp.post("/charity-care/applications")
def create_application():
    caller = authorized(["Patient", "FinancialCounselor"])
    body = get_body()
    patient_id = req_str(body, "patient_id")
    require("patients", patient_id, ERR_PATIENT_NOT_FOUND)
    check_ownership(caller, patient_id)
    # Priority 12: one open application per patient
    for a in db["applications"].values():
        if a["patient_id"] == patient_id and a["status"] in OPEN_STATUSES:
            raise_error(ERR_DUPLICATE_OPEN_APPLICATION,
                        "patient already has an open application")
    # Priority 13: remaining fields
    screening_source = req_enum(body, "screening_source", SCREENING_SOURCES)
    income = req_int(body, "reported_annual_income_cents", minimum=0)
    assets = req_int(body, "reported_liquid_assets_cents", minimum=0)
    rec = new_record("applications", {
        "patient_id": patient_id,
        "screening_source": screening_source,
        "reported_annual_income_cents": income,
        "reported_liquid_assets_cents": assets,
        "policy_id": None,
        "policy_version": None,
        "requested_doc_types": [],
        "doc_response_deadline": None,
        "submitted_at": None,
        "status": "DRAFT",
    })
    return success_object(application_view(rec), status=201)


@bp.get("/charity-care/applications")
def list_applications():
    authorized(LIST_ROLES)
    items = list(db["applications"].values())
    patient_id = request.args.get("patient_id")
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    if patient_id is not None:
        items = [a for a in items if a["patient_id"] == patient_id]
    if policy_id is not None:
        items = [a for a in items if a.get("policy_id") == policy_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_envelope(items, view=application_view)


@bp.get("/charity-care/applications/<aid>")
def get_application(aid):
    caller = authorized(ALL_READ)
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    return success_object(application_view(app))


# ---------------------------------------------------------------------------
# Lifecycle transitions (PRD 3.4, 3.5)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/applications/<aid>/submit")
def submit_application(aid):
    caller = authorized(["Patient", "FinancialCounselor"])
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    # PRD 3.4 order: state, then household composition, then active policy
    if app["status"] != "DRAFT":
        raise_error(ERR_APPLICATION_NOT_DRAFT, "submit requires a DRAFT application")
    if not any(m["relationship"] == "SELF" for m in members_of(aid)):
        raise_error(ERR_HOUSEHOLD_SELF_REQUIRED,
                    "at least one household member with relationship SELF is required")
    policy = active_policy()
    if policy is None:
        raise_error(ERR_NO_ACTIVE_POLICY, "no ACTIVE financial assistance policy exists")
    app["policy_id"] = policy["id"]
    app["policy_version"] = policy["version"]
    app["submitted_at"] = CLOCK.now_iso()
    app["status"] = "SUBMITTED"
    create_notice(account_id=None, application_id=aid,
                  notice_type="PLAIN_LANGUAGE_SUMMARY", is_plain_language=True)
    freeze_accounts_for_application(app["patient_id"])
    touch(app)
    return success_object(application_view(app))


@bp.post("/charity-care/applications/<aid>/withdraw")
def withdraw_application(aid):
    caller = authorized(["Patient", "FinancialCounselor"])
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    if app["status"] not in OPEN_STATUSES:
        raise_error(ERR_APPLICATION_TERMINAL,
                    "withdraw requires a non-terminal application")
    app["status"] = "WITHDRAWN"
    release_holds_for_patient(app["patient_id"])
    touch(app)
    return success_object(application_view(app))


@bp.post("/charity-care/applications/<aid>/begin-review")
def begin_review(aid):
    authorized(["FinancialCounselor"])
    app = _get_app(aid)
    if app["status"] != "SUBMITTED":
        raise_error(ERR_APPLICATION_NOT_SUBMITTED, "begin-review requires SUBMITTED")
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success_object(application_view(app))


@bp.post("/charity-care/applications/<aid>/request-documents")
def request_documents(aid):
    authorized(["FinancialCounselor"])
    app = _get_app(aid)
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_APPLICATION_NOT_UNDER_REVIEW,
                    "request-documents requires UNDER_REVIEW")
    body = get_body()
    required = req_str_list(body, "required_doc_types", allowed=DOC_TYPES, non_empty=True)
    policy = pinned_policy(app)
    days = policy["doc_response_days"] if policy else 0
    app["requested_doc_types"] = list(required)
    app["doc_response_deadline"] = fmt_dt(CLOCK.now() + timedelta(days=days))
    app["status"] = "PENDING_DOCUMENTS"
    create_notice(account_id=None, application_id=aid, notice_type="DOC_REQUEST",
                  is_plain_language=True)
    touch(app)
    return success_object(application_view(app))


@bp.post("/charity-care/applications/<aid>/resume-review")
def resume_review(aid):
    authorized(["FinancialCounselor"])
    app = _get_app(aid)
    if app["status"] != "PENDING_DOCUMENTS":
        raise_error(ERR_APPLICATION_NOT_PENDING_DOCUMENTS,
                    "resume-review requires PENDING_DOCUMENTS")
    verified_types = {
        d["doc_type"]
        for d in db["documents"].values()
        if d["application_id"] == aid and d["status"] == "VERIFIED"
    }
    for doc_type in app["requested_doc_types"]:
        if doc_type not in verified_types:
            raise_error(ERR_DOCS_OUTSTANDING,
                        f"requested document type {doc_type} has no VERIFIED document")
    app["requested_doc_types"] = []
    app["doc_response_deadline"] = None
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success_object(application_view(app))


@bp.post("/charity-care/applications/<aid>/expire")
def expire_application(aid):
    authorized(["FinancialCounselor"])
    app = _get_app(aid)
    if app["status"] != "PENDING_DOCUMENTS":
        raise_error(ERR_APPLICATION_NOT_PENDING_DOCUMENTS,
                    "expire requires PENDING_DOCUMENTS")
    deadline = app.get("doc_response_deadline")
    if deadline is None or CLOCK.now() <= parse_dt(deadline):
        raise_error(ERR_DOC_DEADLINE_NOT_REACHED,
                    "the document response deadline has not passed")
    app["status"] = "EXPIRED"
    release_holds_for_patient(app["patient_id"])
    touch(app)
    return success_object(application_view(app))


# ---------------------------------------------------------------------------
# Household members (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/applications/<aid>/members")
def add_member(aid):
    caller = authorized(["Patient", "FinancialCounselor"])
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    if app["status"] != "DRAFT":
        raise_error(ERR_APPLICATION_TERMINAL,
                    "household members may only be added to a DRAFT application")
    body = get_body()
    rec = new_record("members", {
        "application_id": aid,
        "full_name": req_str(body, "full_name"),
        "relationship": req_enum(body, "relationship", RELATIONSHIPS),
        "age": req_int(body, "age", minimum=0, maximum=130),
    }, versioned=False)
    return success_object(public(rec), status=201)


@bp.get("/charity-care/applications/<aid>/members")
def list_members(aid):
    caller = authorized(APP_READ)
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    return list_envelope(members_of(aid), view=public)


# ---------------------------------------------------------------------------
# Document upload (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/applications/<aid>/documents")
def upload_document(aid):
    caller = authorized(["Patient", "FinancialCounselor"])
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    if app["status"] not in OPEN_STATUSES:
        raise_error(ERR_APPLICATION_TERMINAL,
                    "documents may only be uploaded to a non-terminal application")
    body = get_body()
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    amount = req_int(body, "amount_cents", minimum=0)
    member_id = body.get("household_member_id")
    member = None
    if member_id is not None:
        if not isinstance(member_id, str):
            from errors import ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST, "household_member_id must be a string")
        member = db["members"].get(member_id)
        if member is None:
            raise_error(ERR_MEMBER_NOT_FOUND, "household member id does not exist")
    # Priority 17: closed-interval sanity
    if period_end < period_start:
        raise_error(ERR_INVALID_PERIOD, "period_end must be on or after period_start")
    # Priority 19: member belongs to this application
    if member is not None and member["application_id"] != aid:
        raise_error(ERR_MEMBER_APPLICATION_MISMATCH,
                    "household_member_id belongs to a different application")
    rec = new_record("documents", {
        "application_id": aid,
        "household_member_id": member_id,
        "doc_type": doc_type,
        "period_start": period_start,
        "period_end": period_end,
        "amount_cents": amount,
        "rejection_reason": None,
        "verified_by_user_id": None,
        "status": "SUBMITTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/charity-care/applications/<aid>/notices")
def list_application_notices(aid):
    caller = authorized(APP_READ)
    app = _get_app(aid)
    check_ownership(caller, app["patient_id"])
    items = [n for n in db["notices"].values() if n.get("application_id") == aid]
    return list_envelope(items, view=public)


# ---------------------------------------------------------------------------
# Presumptive screening (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/charity-care/applications/<aid>/presumptive-screening")
def run_screening(aid):
    caller = authorized(["FinancialCounselor"])
    app = _get_app(aid)
    # Priority 12: one screening per application
    if get_screening(aid) is not None:
        raise_error(ERR_SCREENING_ALREADY_EXISTS,
                    "application already has a presumptive screening")
    body = get_body()
    scores = {}
    for field, key in FACTOR_FIELDS.items():
        scores[key] = opt_int_or_none(body, field, minimum=0, maximum=100)
    present_count = sum(1 for s in scores.values() if s is not None)
    if present_count < 3:
        raise_error(ERR_INSUFFICIENT_FACTORS,
                    "at least 3 non-null factor scores are required")
    policy = pinned_policy(app) or active_policy()
    if policy is None:
        raise_error(ERR_NO_ACTIVE_POLICY, "no policy available for screening thresholds")
    count, thin_file, score, outcome = score_screening(scores, policy)
    rec = new_record("screenings", {
        "application_id": aid,
        "income_band_score": scores["income_band"],
        "payment_history_score": scores["payment_history"],
        "utilization_score": scores["utilization"],
        "public_benefit_score": scores["public_benefit"],
        "housing_stability_score": scores["housing_stability"],
        "present_factor_count": count,
        "thin_file": thin_file,
        "propensity_score": score,
        "outcome": outcome,
        "screened_by_user_id": caller.user_id,
        "model_version": "PRES-V1",
    }, versioned=False)
    return success_object(public(rec), status=201)


@bp.get("/charity-care/applications/<aid>/presumptive-screening")
def get_screening_route(aid):
    authorized(["FinancialCounselor", "AssistanceReviewer", "BillingAdministrator",
                "ComplianceOfficer"])
    _get_app(aid)
    scr = get_screening(aid)
    items = [scr] if scr is not None else []
    return list_envelope(items, view=public)
