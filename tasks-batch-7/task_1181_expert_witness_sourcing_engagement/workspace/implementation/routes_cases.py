"""Case endpoints."""
from flask import Blueprint

import db
from lib import (
    ApiError,
    bad_request,
    body_dict,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    pagination_params,
    req_dt,
    req_int,
    req_str,
    require_role,
)
from services import case_view, request_view

bp = Blueprint("cases", __name__)


@bp.post("/litigation/cases")
def create_case():
    b = body_dict()
    case_number = req_str(b, "case_number")
    court = req_str(b, "court")
    title = req_str(b, "title")
    budget = req_int(b, "budget_cents", minimum=1)
    trial_date = req_dt(b, "trial_date")
    report_deadline = req_dt(b, "report_deadline")
    if db.parse_iso(trial_date) <= db.parse_iso(report_deadline):
        bad_request("trial_date must be strictly later than report_deadline")
    if any(c["case_number"] == case_number for c in db.cases.values()):
        bad_request("case_number must be unique per firm")
    require_role("CaseManager")
    rec = db.base_record()
    rec.update(
        case_number=case_number,
        court=court,
        title=title,
        budget_cents=budget,
        trial_date=trial_date,
        report_deadline=report_deadline,
        status="INTAKE",
        actuals_paid_cents=0,
        approved_outstanding_cents=0,
        committed_cents=0,
    )
    db.cases[rec["id"]] = rec
    return ok(case_view(rec), 201)


@bp.get("/litigation/cases/<cid>")
def get_case(cid):
    require_role("PlatformAdmin", "CaseManager", "BillingReviewer", "Expert")
    case = get_or_404(db.cases, cid, "case")
    return ok(case_view(case))


@bp.post("/litigation/cases/<cid>/budget-revisions")
def budget_revision(cid):
    b = body_dict()
    new_budget = req_int(b, "new_budget_cents", minimum=1)
    req_str(b, "reason")
    expected = req_int(b, "expected_case_version")
    require_role("CaseManager")
    case = get_or_404(db.cases, cid, "case")
    if expected != case["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_case_version does not match the case's current version",
        )
    case["budget_cents"] = new_budget
    db.touch(case)
    return ok(case_view(case))


@bp.post("/litigation/cases/<cid>/close")
def close_case(cid):
    require_role("CaseManager")
    case = get_or_404(db.cases, cid, "case")
    if case["status"] not in ("ENGAGED", "DISCOVERY", "TRIAL_PREP"):
        invalid_state("case status %s does not permit closing" % case["status"])
    engs = [e for e in db.engagements.values() if e["case_id"] == cid]
    eng_ids = {e["id"] for e in engs}
    if any(e["status"] not in ("CLOSED", "TERMINATED") for e in engs):
        raise ApiError(
            "ERR_CASE_NOT_CLOSABLE", 409, "an engagement is not yet CLOSED or TERMINATED"
        )
    if any(
        i["status"] not in ("PAID", "REJECTED")
        for i in db.invoices.values()
        if i["engagement_id"] in eng_ids
    ):
        raise ApiError(
            "ERR_CASE_NOT_CLOSABLE", 409, "an invoice is not yet PAID or REJECTED"
        )
    case["status"] = "CLOSED"
    db.touch(case)
    return ok(case_view(case))


@bp.get("/litigation/cases/<cid>/engagement-requests")
def case_requests(cid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager", "ConflictAnalyst", "CredentialAnalyst")
    get_or_404(db.cases, cid, "case")
    recs = [r for r in db.engagement_requests.values() if r["case_id"] == cid]
    return list_ok([request_view(r) for r in recs], limit, offset)
