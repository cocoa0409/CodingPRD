"""GapItem + AuditEngagement + AuditFinding routes."""
from flask import Blueprint, request

import errors
from db import db, new_id, parse_dt
from middleware import require_roles, get_json_body, require_fields, require_enum, require_str
from response import success_object, success_list, parse_pagination
from serializers import gap_view, engagement_view, finding_view
from services.core import (touch, find_gap, find_engagement, find_finding,
                           find_run, find_season, decrement_provider_gap_count)

bp = Blueprint("gaps_audit", __name__)

PROVIDER_REL = ["ProviderRelations"]
AUDITOR = ["Auditor"]
ENGAGEMENT_READ = ["QualityAdmin", "QualityAnalyst", "Auditor", "QualityDirector"]


# ---------------------------------------------------------------- gap items
@bp.post("/hedis/gap-items/<gapId>/mark-outreach-done")
def mark_outreach_done(gapId):
    require_roles(PROVIDER_REL)
    get_json_body()
    g = find_gap(gapId)
    if g["status"] != "OPEN":
        raise errors.invalid_state("Gap must be OPEN to mark outreach done")
    g["status"] = "OUTREACH_DONE"
    touch(g)
    return success_object(gap_view(g))


@bp.post("/hedis/gap-items/<gapId>/close")
def close_gap(gapId):
    require_roles(PROVIDER_REL)
    body = get_json_body()
    require_fields(body, ["outcome"])
    outcome = require_enum(body, "outcome", ["CLOSED_COMPLIANT", "CLOSED_NONCOMPLIANT"])
    g = find_gap(gapId)
    if g["status"] != "OUTREACH_DONE":
        raise errors.invalid_state("Gap must be OUTREACH_DONE to close")
    g["status"] = outcome
    g["closure_source"] = "MANUAL"
    touch(g)
    decrement_provider_gap_count(g["provider_ref"])
    return success_object(gap_view(g))


# ---------------------------------------------------------------- engagements
@bp.post("/hedis/audit-engagements")
def create_engagement():
    require_roles(AUDITOR)
    body = get_json_body()
    require_fields(body, ["season_id", "measure_run_id", "auditor_user_id",
                          "window_start", "window_end"])
    auditor_user_id = require_str(body, "auditor_user_id")
    window_start = parse_dt(body.get("window_start"))
    window_end = parse_dt(body.get("window_end"))
    if window_start is None or window_end is None:
        raise errors.invalid_request("window_start and window_end must be ISO8601 datetimes")
    season = find_season(body.get("season_id") if isinstance(body.get("season_id"), str) else "")
    run = find_run(body.get("measure_run_id") if isinstance(body.get("measure_run_id"), str) else "")
    # temporal validity (priority 9.2)
    if window_end <= window_start:
        raise errors.ApiError(errors.ERR_ENGAGEMENT_WINDOW_INVALID, 422,
                              "window_end must be strictly after window_start")
    # half-open overlap per auditor (priority 10.2): adjacent allowed
    for e in db.engagements.values():
        if e["auditor_user_id"] != auditor_user_id:
            continue
        if window_start < e["window_end"] and window_end > e["window_start"]:
            raise errors.ApiError(errors.ERR_AUDITOR_WINDOW_OVERLAP, 409,
                                  "Engagement window overlaps another engagement of this auditor")
    rec = {
        "id": new_id(),
        "season_id": season["id"],
        "measure_run_id": run["id"],
        "auditor_user_id": auditor_user_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "outcome": None,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.engagements[rec["id"]] = rec
    return success_object(engagement_view(rec), 201)


@bp.get("/hedis/audit-engagements/<engagementId>")
def get_engagement(engagementId):
    require_roles(ENGAGEMENT_READ)
    e = find_engagement(engagementId)
    return success_object(engagement_view(e))


@bp.post("/hedis/audit-engagements/<engagementId>/begin-review")
def begin_review(engagementId):
    require_roles(AUDITOR)
    get_json_body()
    e = find_engagement(engagementId)
    if e["status"] != "SCHEDULED":
        raise errors.invalid_state("Engagement must be SCHEDULED to begin review")
    run = db.runs.get(e["measure_run_id"])
    if run is None:
        raise errors.not_found()
    # cross-entity guards: run SUBMITTED and audit_status in {UNAUDITED, AUDIT_FAILED}
    if run["reporting_status"] != "SUBMITTED":
        raise errors.invalid_state("Engagement's run must be SUBMITTED")
    if run["audit_status"] not in ("UNAUDITED", "AUDIT_FAILED"):
        raise errors.invalid_state("Run audit_status must be UNAUDITED or AUDIT_FAILED")
    # temporal window (priority 9.1): half-open [window_start, window_end)
    if not (e["window_start"] <= db.clock < e["window_end"]):
        raise errors.ApiError(errors.ERR_OUTSIDE_ENGAGEMENT_WINDOW, 422,
                              "Logical clock is outside the engagement window")
    e["status"] = "IN_REVIEW"
    touch(e)
    run["audit_status"] = "IN_REVIEW"
    touch(run)
    return success_object(engagement_view(e))


@bp.post("/hedis/audit-engagements/<engagementId>/complete")
def complete_engagement(engagementId):
    require_roles(AUDITOR)
    body = get_json_body()
    require_fields(body, ["outcome"])
    outcome = require_enum(body, "outcome", ["PASS", "FAIL"])
    e = find_engagement(engagementId)
    if e["status"] != "IN_REVIEW":
        raise errors.invalid_state("Engagement must be IN_REVIEW to complete")
    run = db.runs.get(e["measure_run_id"])
    if run is None:
        raise errors.not_found()
    e["status"] = "COMPLETED"
    e["outcome"] = outcome
    touch(e)
    if outcome == "PASS":
        run["audit_status"] = "AUDIT_PASSED"
    else:
        run["audit_status"] = "AUDIT_FAILED"
        # auto-mint CRITICAL finding
        finding = {
            "id": new_id(),
            "engagement_id": e["id"],
            "severity": "CRITICAL",
            "summary": "AUDIT_OUTCOME_FAIL",
            "status": "OPEN",
            "created_at": db.clock,
            "updated_at": db.clock,
            "version": 1,
        }
        db.findings[finding["id"]] = finding
    touch(run)
    return success_object(engagement_view(e))


@bp.get("/hedis/audit-engagements/<id>/findings")
def list_findings(id):
    require_roles(ENGAGEMENT_READ)
    find_engagement(id)
    items = [f for f in db.findings.values() if f["engagement_id"] == id]
    status = request.args.get("status")
    severity = request.args.get("severity")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if severity is not None:
        items = [f for f in items if f["severity"] == severity]
    items.sort(key=lambda f: f["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([finding_view(f) for f in page], limit, offset, total)


# ---------------------------------------------------------------- findings
@bp.post("/hedis/audit-findings")
def create_finding():
    require_roles(AUDITOR)
    body = get_json_body()
    require_fields(body, ["engagement_id", "severity", "summary"])
    severity = require_enum(body, "severity", ["CRITICAL", "MAJOR", "MINOR"])
    summary = require_str(body, "summary")
    eng = find_engagement(body.get("engagement_id") if isinstance(body.get("engagement_id"), str) else "")
    rec = {
        "id": new_id(),
        "engagement_id": eng["id"],
        "severity": severity,
        "summary": summary,
        "status": "OPEN",
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.findings[rec["id"]] = rec
    return success_object(finding_view(rec), 201)


@bp.post("/hedis/audit-findings/<findingId>/resolve")
def resolve_finding(findingId):
    require_roles(AUDITOR)
    get_json_body()
    f = find_finding(findingId)
    if f["status"] != "OPEN":
        raise errors.invalid_state("Finding must be OPEN to resolve")
    f["status"] = "RESOLVED"
    touch(f)
    return success_object(finding_view(f))
