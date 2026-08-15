"""Engagement endpoints (PRD 3.4, 3.8): OCC-guarded creation with cooling-period
and roster-freeze gates, lifecycle transitions, cancellation cascade."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_AUDITABLE_ENTITY_RETIRED,
    ERR_ENGAGEMENT_COOLING_PERIOD,
    ERR_ENGAGEMENT_INVALID_STATE,
    ERR_ENGAGEMENT_WINDOW_INVALID,
    ERR_NO_LEAD_ASSIGNED,
    ERR_NO_SIGNED_WORKPAPERS,
    ERR_PLAN_INVALID_STATE,
    ERR_PLAN_NOT_APPROVED,
    ERR_QA_REVIEW_OPEN,
    ERR_REPORT_NOT_ISSUED,
    ERR_STALE_PLAN_VERSION,
    ERR_WORKPAPERS_PENDING_REVIEW,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.calculations import compute_priority_score
from services.cascades import cancel_engagement_cascade, recompute_plan_aggregates
from services.core import new_record, public, touch
from util import CLOCK, parse_dt
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    opt_nullable_str,
    req_datetime,
    req_int,
    req_number,
    req_str,
    require_path,
)

bp = Blueprint("engagements", __name__)

CREATE_FIELDS = {
    "audit_plan_id", "auditable_entity_id", "title", "scope_summary",
    "budget_hours", "start_date", "end_date", "supersedes_engagement_id",
    "expected_audit_plan_version",
}

COOLING_DAYS = 90


@bp.post("/audit/engagements")
def create_engagement():
    authorized(["AuditManager"])
    body = get_body()
    # Stage 4: body FK existence in declared input order
    body_ref(body, "audit_plan_id", "audit_plans")
    body_ref(body, "auditable_entity_id", "auditable_entities")
    body_ref(body, "supersedes_engagement_id", "engagements")  # optional ref
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    plan_id = req_str(body, "audit_plan_id")
    entity_id = req_str(body, "auditable_entity_id")
    title = req_str(body, "title")
    scope_summary = req_str(body, "scope_summary")
    budget_hours = req_number(body, "budget_hours", positive=True)
    start_date = req_datetime(body, "start_date")
    end_date = req_datetime(body, "end_date")
    supersedes_engagement_id = opt_nullable_str(body, "supersedes_engagement_id")
    expected_version = req_int(body, "expected_audit_plan_version")
    plan = db["audit_plans"][plan_id]
    entity = db["auditable_entities"][entity_id]
    # Stage 6: OCC on the parent plan version
    if expected_version != plan["version"]:
        raise_error(ERR_STALE_PLAN_VERSION,
                    f"expected_audit_plan_version {expected_version} != current {plan['version']}")
    start_dt = parse_dt(start_date)
    end_dt = parse_dt(end_date)
    # Window rule (PRD 3.4): non-empty window, end strictly after start
    if not end_dt > start_dt:
        raise_error(ERR_ENGAGEMENT_WINDOW_INVALID, "end_date must be strictly after start_date")
    # Business gate 1 — roster freeze: plan must be DRAFT, RETURNED, or APPROVED
    if plan["status"] not in ("DRAFT", "RETURNED", "APPROVED"):
        raise_error(ERR_PLAN_INVALID_STATE,
                    f"engagement creation is frozen while the plan is {plan['status']}")
    # Business gate 2 — the entity must be ACTIVE
    if entity["status"] != "ACTIVE":
        raise_error(ERR_AUDITABLE_ENTITY_RETIRED, "entity is RETIRED")
    # Business gate 3 — cooling period: 90-day buffer gap vs every non-CANCELLED
    # engagement of the same entity (adjacency inside the buffer is rejected).
    for other in db["engagements"].values():
        if other["auditable_entity_id"] != entity_id or other["status"] == "CANCELLED":
            continue
        other_start = parse_dt(other["start_date"])
        other_end = parse_dt(other["end_date"])
        separated = (
            other_end + timedelta(days=COOLING_DAYS) <= start_dt
            or end_dt + timedelta(days=COOLING_DAYS) <= other_start
        )
        if not separated:
            raise_error(ERR_ENGAGEMENT_COOLING_PERIOD,
                        "window violates the 90-day cooling buffer for this entity")
    rec = new_record("engagements", {
        "audit_plan_id": plan_id,
        "auditable_entity_id": entity_id,
        "supersedes_engagement_id": supersedes_engagement_id,
        "title": title,
        "scope_summary": scope_summary,
        "budget_hours": budget_hours,
        "start_date": start_date,
        "end_date": end_date,
        "status": "PLANNED",
        "reserved_hours": 0,
        "actual_hours": 0,
        "provisional_hours": 0,
        "signed_off_workpaper_count": 0,
        "open_finding_count": 0,
        "qa_regression_count": 0,
        "priority_score": compute_priority_score(entity),
        "utilization_final_pct": 0.0,
        "utilization_provisional_pct": 0.0,
    })
    # Creation mutates the plan: version +1 and aggregates re-synced (PRD 3.4)
    recompute_plan_aggregates(plan)
    touch(plan)
    return success_object(public(rec), status=201)


@bp.get("/audit/engagements")
def list_engagements():
    filters = {
        "audit_plan_id": query_str("audit_plan_id"),
        "auditable_entity_id": query_str("auditable_entity_id"),
        "supersedes_engagement_id": query_str("supersedes_engagement_id"),
        "status": query_str("status"),
    }
    return list_response("engagements", filters)


@bp.get("/audit/engagements/<rid>")
def get_engagement(rid):
    return get_one("engagements", rid)


@bp.post("/audit/engagements/<rid>/scope")
def scope_engagement(rid):
    authorized(["AuditManager"])
    eng = require_path("engagements", rid)
    if eng["status"] != "PLANNED":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE, "engagement is not PLANNED")
    eng["status"] = "SCOPED"
    touch(eng)
    return success_object(public(eng))


@bp.post("/audit/engagements/<rid>/begin-fieldwork")
def begin_fieldwork(rid):
    authorized(["AuditManager"])
    eng = require_path("engagements", rid)
    if eng["status"] != "SCOPED":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE, "engagement is not SCOPED")
    # Cross-entity gate 1: the owning plan must be APPROVED
    plan = db["audit_plans"].get(eng["audit_plan_id"])
    if plan is None or plan["status"] != "APPROVED":
        raise_error(ERR_PLAN_NOT_APPROVED, "owning plan is not APPROVED")
    # Cross-entity gate 2: at least one ACTIVE LEAD assignment
    has_lead = any(
        a["engagement_id"] == eng["id"] and a["status"] == "ACTIVE"
        and a["role_in_engagement"] == "LEAD"
        for a in db["engagement_assignments"].values()
    )
    if not has_lead:
        raise_error(ERR_NO_LEAD_ASSIGNED, "no ACTIVE LEAD assignment on the engagement")
    eng["status"] = "FIELDWORK"
    touch(eng)
    return success_object(public(eng))


@bp.post("/audit/engagements/<rid>/begin-reporting")
def begin_reporting(rid):
    authorized(["AuditManager"])
    eng = require_path("engagements", rid)
    if eng["status"] != "FIELDWORK":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE, "engagement is not FIELDWORK")
    # Gate 1: at least one signed-off workpaper (empty-set boundary)
    if eng["signed_off_workpaper_count"] < 1:
        raise_error(ERR_NO_SIGNED_WORKPAPERS, "no SIGNED_OFF workpapers")
    # Gate 2: clean pipeline — every workpaper SIGNED_OFF
    for wp in db["workpapers"].values():
        if wp["engagement_id"] == eng["id"] and wp["status"] != "SIGNED_OFF":
            raise_error(ERR_WORKPAPERS_PENDING_REVIEW,
                        "all workpapers must be SIGNED_OFF to begin reporting")
    eng["status"] = "REPORTING"
    touch(eng)
    return success_object(public(eng))


@bp.post("/audit/engagements/<rid>/close")
def close_engagement(rid):
    authorized(["AuditManager"])
    eng = require_path("engagements", rid)
    if eng["status"] != "REPORTING":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE, "engagement is not REPORTING")
    # Cross-entity gate 1: an ISSUED or DISTRIBUTED report exists
    report_issued = any(
        r["engagement_id"] == eng["id"] and r["status"] in ("ISSUED", "DISTRIBUTED")
        for r in db["audit_reports"].values()
    )
    if not report_issued:
        raise_error(ERR_REPORT_NOT_ISSUED, "no ISSUED/DISTRIBUTED report for the engagement")
    # Cross-entity gate 2: no open QA review
    qa_open = any(
        q["engagement_id"] == eng["id"] and q["status"] in ("SCHEDULED", "IN_PROGRESS")
        for q in db["qa_reviews"].values()
    )
    if qa_open:
        raise_error(ERR_QA_REVIEW_OPEN, "a QA review is still open")
    eng["status"] = "CLOSED"
    touch(eng)
    # Bubble up: the entity's last-audit date resets to the logical clock now
    entity = db["auditable_entities"].get(eng["auditable_entity_id"])
    if entity is not None:
        entity["last_audit_completed_at"] = CLOCK.now_iso()
        touch(entity)
    return success_object(public(eng))


@bp.post("/audit/engagements/<rid>/cancel")
def cancel_engagement(rid):
    authorized(["AuditManager"])
    eng = require_path("engagements", rid)
    if eng["status"] not in ("PLANNED", "SCOPED"):
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    "only PLANNED or SCOPED engagements can be cancelled")
    cancel_engagement_cascade(eng)
    return success_object(public(eng))
