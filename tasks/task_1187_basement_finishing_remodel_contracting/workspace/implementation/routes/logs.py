"""Daily site logs: filing, listing, strike escalation (PRD §3.7)."""
from flask import Blueprint

from db import stores, new_id, next_seq, now_ts, clock_now, clock_date, parse_date
from errors import fail
from response import ok
from serializers import ser_site_log
from services import (
    compute_violation, strike_count, suspend_project, STRIKE_SUSPEND_THRESHOLD,
)
from validation import auth, require_role, get_body, v_num, v_bool, v_date
from routes.common import project_or_404, list_response

bp = Blueprint("logs", __name__)


@bp.post("/api/projects/<project_id>/site-logs")
def create_site_log(project_id):
    role, uid = auth()
    require_role(role, "Subcontractor")
    project = project_or_404(project_id)
    # Priority 3: the acting subcontractor must be assigned to at least one
    # non-terminal work phase of the project.
    assigned = any(
        p["project_id"] == project_id
        and p["subcontractor_id"] == uid
        and p["status"] not in ("COMPLETED", "CANCELLED")
        for p in stores["work_phases"].values()
    )
    if not assigned:
        fail("ERR_NOT_RESOURCE_OWNER", "Subcontractor is not assigned to a non-terminal phase of this project")
    body = get_body()
    # Priority 7: logs only while the build is IN_PROGRESS.
    if project["status"] != "IN_PROGRESS":
        fail("ERR_PROJECT_STATE_FORBIDS", "Site logs open only while the project is IN_PROGRESS")
    # Priority 19: work_date must not be after the current logical clock date.
    raw_date = body.get("work_date")
    parsed = parse_date(raw_date) if isinstance(raw_date, str) else None
    if parsed is not None and parsed > clock_date():
        fail("ERR_FUTURE_WORK_DATE", "work_date must not be after the current date")
    # Priority 26: shape.
    work_date = v_date(body, "work_date")
    containment_intact = v_bool(body, "containment_intact")
    hepa_run_hours = v_num(body, "hepa_run_hours")
    noise_db_max = v_num(body, "noise_db_max")
    cleanup_completed = v_bool(body, "cleanup_completed")
    e = {
        "id": new_id(),
        "created_at": now_ts(),
        "_created_dt": clock_now(),
        "_seq": next_seq(),
        "project_id": project_id,
        "subcontractor_id": uid,
        "work_date": work_date,
        "containment_intact": containment_intact,
        "hepa_run_hours": hepa_run_hours,
        "noise_db_max": noise_db_max,
        "cleanup_completed": cleanup_completed,
        "violation": False,
        "strike_applied": False,
    }
    e["violation"] = compute_violation(e)
    stores["site_logs"][e["id"]] = e
    # Recompute the strike count; reaching the threshold suspends the project.
    if strike_count(project) >= STRIKE_SUSPEND_THRESHOLD and project["status"] == "IN_PROGRESS":
        e["strike_applied"] = True
        suspend_project(project)
    return ok(ser_site_log(e), 201)


@bp.get("/api/projects/<project_id>/site-logs")
def list_site_logs(project_id):
    auth()
    project_or_404(project_id)
    items = [l for l in stores["site_logs"].values() if l["project_id"] == project_id]
    return list_response(items, ser_site_log)
