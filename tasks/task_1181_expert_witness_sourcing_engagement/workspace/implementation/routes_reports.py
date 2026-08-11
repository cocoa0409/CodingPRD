"""Expert report endpoints."""
from flask import Blueprint, g

import db
from lib import (
    ApiError,
    body_dict,
    forbidden,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    opt_str,
    optional_body,
    pagination_params,
    req_enum,
    req_str,
    require_role,
)
from services import report_view

bp = Blueprint("reports", __name__)

READ_ROLES = ("PlatformAdmin", "CaseManager", "Expert")


@bp.post("/litigation/engagements/<eid>/reports")
def create_report(eid):
    b = body_dict()
    title = req_str(b, "title")
    report_type = req_enum(b, "report_type", ("LIABILITY", "DAMAGES", "REBUTTAL"))
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if any(
        r["engagement_id"] == eid
        and r["status"] in ("DRAFT", "IN_REVIEW", "REVISION_REQUESTED", "FINALIZED")
        for r in db.reports.values()
    ):
        raise ApiError(
            "ERR_REPORT_ALREADY_ACTIVE",
            409,
            "a non-terminal report already exists on this engagement",
        )
    case = db.cases[eng["case_id"]]
    rec = db.base_record()
    rec.update(
        engagement_id=eid,
        title=title,
        report_type=report_type,
        deadline_at=case["report_deadline"],  # version-pinned copy at creation
        status="DRAFT",
        revision_count=0,
        submitted_at=None,
    )
    db.reports[rec["id"]] = rec
    if case["status"] == "ENGAGED":
        case["status"] = "DISCOVERY"
        db.touch(case)
    return ok(report_view(rec), 201)


@bp.get("/litigation/engagements/<eid>/reports")
def list_reports(eid):
    limit, offset = pagination_params()
    require_role(*READ_ROLES)
    eng = get_or_404(db.engagements, eid, "engagement")
    if g.user_role == "Expert" and eng["expert_id"] != g.user_id:
        forbidden("experts may access only their own engagements")
    recs = [r for r in db.reports.values() if r["engagement_id"] == eid]
    return list_ok([report_view(r) for r in recs], limit, offset)


def _get_report_and_engagement(rid):
    rep = get_or_404(db.reports, rid, "report")
    return rep, db.engagements[rep["engagement_id"]]


@bp.post("/litigation/reports/<rid>/submit")
def submit_report(rid):
    optional_body()
    require_role("Expert")
    rep, eng = _get_report_and_engagement(rid)
    if eng["expert_id"] != g.user_id:
        forbidden("only the engaged expert may submit the report")
    if rep["status"] != "DRAFT":
        invalid_state("only a DRAFT report can be submitted")
    if eng["status"] != "ACTIVE":
        invalid_state("report submission requires an ACTIVE engagement")
    # now == deadline passes; strictly later fails
    if db.clock.now() > db.parse_iso(rep["deadline_at"]):
        raise ApiError(
            "ERR_REPORT_DEADLINE_PASSED",
            409,
            "the logical clock is past the report deadline",
        )
    rep["status"] = "IN_REVIEW"
    rep["submitted_at"] = db.clock.now_raw()
    db.touch(rep)
    return ok(report_view(rep))


@bp.post("/litigation/reports/<rid>/review")
def review_report(rid):
    b = body_dict()
    decision = req_enum(b, "decision", ("FINALIZE", "REQUEST_REVISION"))
    opt_str(b, "notes", None)
    require_role("CaseManager")
    rep, _eng = _get_report_and_engagement(rid)
    if rep["status"] != "IN_REVIEW":
        invalid_state("only an IN_REVIEW report can be reviewed")
    rep["status"] = "FINALIZED" if decision == "FINALIZE" else "REVISION_REQUESTED"
    db.touch(rep)
    return ok(report_view(rep))


@bp.post("/litigation/reports/<rid>/revise")
def revise_report(rid):
    b = body_dict()
    req_str(b, "revision_notes")
    require_role("Expert")
    rep, eng = _get_report_and_engagement(rid)
    if eng["expert_id"] != g.user_id:
        forbidden("only the engaged expert may revise the report")
    if rep["status"] != "REVISION_REQUESTED":
        invalid_state("only a REVISION_REQUESTED report can be revised")
    rep["status"] = "DRAFT"
    rep["revision_count"] += 1
    db.touch(rep)
    return ok(report_view(rep))


@bp.post("/litigation/reports/<rid>/disclose")
def disclose_report(rid):
    optional_body()
    require_role("CaseManager")
    rep, eng = _get_report_and_engagement(rid)
    if rep["status"] != "FINALIZED":
        invalid_state("only a FINALIZED report can be disclosed")
    case = db.cases[eng["case_id"]]
    if db.clock.now() >= db.parse_iso(case["trial_date"]):
        raise ApiError(
            "ERR_TRIAL_DATE_PASSED",
            409,
            "the logical clock is at or past the case trial date",
        )
    rep["status"] = "DISCLOSED"
    db.touch(rep)
    if case["status"] == "DISCOVERY":
        case["status"] = "TRIAL_PREP"
        db.touch(case)
    return ok(report_view(rep))
