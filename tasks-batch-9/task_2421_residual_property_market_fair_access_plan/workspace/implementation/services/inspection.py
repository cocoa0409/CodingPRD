"""Inspection counters and the requirement -> inspection -> application cascade
(PRD 3.5)."""

from db import db, sorted_records, touch
from util import add_days, parse_instant
from services.constants import BIND_WINDOW_DAYS
from validate import store_instant


def inspections_of(application_id):
    return sorted_records(None, [i for i in db.inspections.values()
                                 if i["application_id"] == application_id])


def requirements_of(inspection_id):
    return sorted_records(None, [r for r in db.requirements.values()
                                 if r["inspection_id"] == inspection_id])


def chosen_inspection(application_id):
    """The application's most recently completed inspection: greatest
    completed_at, tie-break earliest created_at (PRD 3.6)."""
    completed = [i for i in inspections_of(application_id)
                 if i.get("completed_at")]
    if not completed:
        return None
    newest = max(parse_instant(i["completed_at"]) for i in completed)
    tied = [i for i in completed if parse_instant(i["completed_at"]) == newest]
    return sorted_records(None, tied)[0]


def approve_to_bind(application):
    """Write approved_to_bind_at and bind_deadline_at, thirty days later."""
    now = db.now()
    application["status"] = "APPROVED_TO_BIND"
    application["approved_to_bind_at"] = store_instant(now)
    application["bind_deadline_at"] = store_instant(add_days(now, BIND_WINDOW_DAYS))
    touch(application)


def cascade_after_requirement_closed(requirement):
    """Hops 2 and 3 shared by clearance and waiver."""
    inspection = db.inspections.get(requirement["inspection_id"])
    if inspection is None:
        return
    inspection["open_requirement_count"] = max(
        0, inspection["open_requirement_count"] - 1)
    if requirement["status"] == "CLEARED" and requirement["severity"] == "MAJOR":
        inspection["cleared_major_count"] += 1

    flipped = False
    if (inspection["open_requirement_count"] == 0
            and inspection["result"] == "PASS_WITH_CONDITIONS"):
        inspection["result"] = "PASS"
        flipped = True
    touch(inspection)

    if flipped:
        application = db.applications.get(inspection["application_id"])
        if application is not None and application["status"] == "IMPROVEMENTS_REQUIRED":
            approve_to_bind(application)
