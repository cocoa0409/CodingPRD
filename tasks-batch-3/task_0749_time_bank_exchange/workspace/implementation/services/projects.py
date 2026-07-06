"""GroupProject compound state resolver — §1.3 project_aggregate_state,
§1.3 project_completion_ratio, cascade helpers."""
import db
from db import parse_iso


def _project_shifts(project_id):
    return [s for s in db.project_shifts.values() if s["project_id"] == project_id]


def recompute_total_committed_minutes(project_id):
    p = db.group_projects.get(project_id)
    if p is None:
        return
    total = sum(s["duration_minutes"] for s in _project_shifts(project_id)
                if s["status"] == "FILLED")
    if p["total_committed_minutes"] != total:
        p["total_committed_minutes"] = total
        db.touch(p)


def recompute_aggregate_state(project):
    """Recompute per §1.3 pinned order. Called on every relevant write and
    clock advance. Never called during pre-publish PLANNING except cancel."""
    if project.get("_cancelled"):
        # Explicit cancellation flag set by the cancel endpoint.
        project["aggregate_state"] = "CANCELLED"
        return
    if not project.get("_published"):
        project["aggregate_state"] = "PLANNING"
        return

    now_ts = db.clock_dt().timestamp()
    window_end_ts = parse_iso(project["window_end_utc"]).timestamp()
    shifts = _project_shifts(project["id"])

    if now_ts > window_end_ts:
        total = len(shifts)
        completed = sum(1 for s in shifts if s["status"] == "COMPLETED")
        if total == 0:
            ratio = 0.0
        else:
            ratio = completed / total
        # Round half-up to two decimal places before comparison
        ratio_2dp = round(ratio * 100 + 1e-9) / 100.0
        if ratio_2dp >= project["minimum_completed_ratio"]:
            project["aggregate_state"] = "COMPLETED"
        else:
            project["aggregate_state"] = "CANCELLED"
        return

    # Not past window_end. Check earliest shift start.
    if shifts:
        earliest = min(parse_iso(s["shift_start_utc"]).timestamp() for s in shifts)
        if now_ts >= earliest:
            project["aggregate_state"] = "IN_PROGRESS"
            return

    project["aggregate_state"] = "OPEN"
