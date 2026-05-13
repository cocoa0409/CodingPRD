"""Time-gated cascades and project state machine transitions driven by the virtual clock."""
from clock import format_iso, get_now, parse_iso
from common import stamp_update
from db import db
from services.screening import run_preliminary_scan


def _stage_by_kind(project_id, kind):
    for s in db.review_stages.values():
        if s.get("project_id") == project_id and s.get("stage_kind") == kind:
            return s
    return None


def advance_project_to_in_preliminary(project: dict):
    """ON_SHELF -> IN_PRELIMINARY cascade.

    Preconditions: now() >= submission_deadline AND PRELIMINARY.starts_at <= now()
    Side effects:
      - Every DRAFT Submission of this project transitions to SCREENING.
      - Each affected Submission has modify_window_closes_at fixed to now().
      - PRELIMINARY ReviewStage.status -> OPEN.
    Then the preliminary scan runs on each SCREENING submission immediately.
    """
    if project.get("status") != "ON_SHELF":
        return False
    now = get_now()
    prelim = _stage_by_kind(project["id"], "PRELIMINARY")
    if now < parse_iso(project["submission_deadline"]):
        return False
    if not prelim or now < parse_iso(prelim["starts_at"]):
        return False

    project["status"] = "IN_PRELIMINARY"
    stamp_update(project)
    now_iso = format_iso(now)
    drafted = [s for s in db.submissions.values()
               if s.get("project_id") == project["id"] and s.get("status") == "DRAFT"]
    for sub in drafted:
        sub["status"] = "SCREENING"
        sub["modify_window_closes_at"] = now_iso
        stamp_update(sub)
    if prelim:
        prelim["status"] = "OPEN"
        stamp_update(prelim)
    # Run the screening scan
    for sub in drafted:
        if sub.get("status") == "SCREENING":
            run_preliminary_scan(sub)
    return True


def run_clock_cascades():
    """Drive any time-gated cascades. Called after the clock advances."""
    # Iterate over a snapshot list (statuses may flip mid-loop)
    for project in list(db.projects.values()):
        if project.get("status") == "ON_SHELF":
            advance_project_to_in_preliminary(project)
