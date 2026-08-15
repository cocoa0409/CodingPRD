"""RosterEntry endpoints (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_ACCOMMODATION_MISSING,
    ERR_PICKUP_NOT_VERIFIED, ERR_DUPLICATE_ROSTER_ENTRY,
)
from middleware import authorized, ALL_ROLES, ROLE_OFFICER
from response import success_object
from services.core import new_record, public, apply_changes, refresh_roster_counters
from util import CLOCK
from validate import (
    get_body, reject_unknown, req_str, opt_bool, req_bool,
)
from routes.helpers import get_path, list_query

bp = Blueprint("roster", __name__)


@bp.post("/drill-events/<rid>/roster-entries")
def create_roster_entry(rid):
    authorized([ROLE_OFFICER])
    drill = get_path("drill_events", rid)
    body = get_body()
    reject_unknown(body, ["student_ref", "accommodation_required"])
    student_ref = req_str(body, "student_ref")
    accommodation = opt_bool(body, "accommodation_required", default=False)

    # priority 5: drill must be SCHEDULED or IN_PROGRESS
    if drill["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise_error(ERR_INVALID_STATE,
                    "roster entries may only be added to a SCHEDULED or IN_PROGRESS drill")

    # priority 6: accommodation gate
    if accommodation:
        has_plan = any(
            p["site_id"] == drill["site_id"] and p["student_ref"] == student_ref
            and p["status"] == "ACTIVE"
            for p in db["accommodation_plans"].values()
        )
        if not has_plan:
            raise_error(ERR_ACCOMMODATION_MISSING,
                        "no ACTIVE AccommodationPlan for this site and student_ref")

    # priority 9: one roster entry per (drill, student_ref)
    for e in db["roster_entries"].values():
        if e["drill_event_id"] == drill["id"] and e["student_ref"] == student_ref:
            raise_error(ERR_DUPLICATE_ROSTER_ENTRY,
                        "student_ref already present on this drill's roster")

    rec = new_record("roster_entries", {
        "drill_event_id": drill["id"],
        "student_ref": student_ref,
        "accommodation_required": accommodation,
        "status": "UNACCOUNTED",
        "accounted_at": None,
        "guardian_name": None,
        "released_to_verified": None,
        "released_at": None,
    })
    refresh_roster_counters(drill)
    return success_object(public(rec), 201)


@bp.get("/drill-events/<rid>/roster-entries")
def list_roster_entries(rid):
    authorized(ALL_ROLES)
    get_path("drill_events", rid)
    filters = {"drill_event_id": rid, "status": request.args.get("status")}
    return list_query("roster_entries", filters)


def _entry_and_drill(rid):
    entry = get_path("roster_entries", rid)
    drill = get_path("drill_events", entry["drill_event_id"])
    return entry, drill


@bp.post("/roster-entries/<rid>/account")
def account_entry(rid):
    authorized([ROLE_OFFICER])
    entry, drill = _entry_and_drill(rid)
    body = get_body()
    reject_unknown(body, [])

    if drill["status"] != "IN_PROGRESS" or entry["status"] != "UNACCOUNTED":
        raise_error(ERR_INVALID_STATE,
                    "account requires an UNACCOUNTED entry on an IN_PROGRESS drill")

    apply_changes(entry, {"status": "ACCOUNTED", "accounted_at": CLOCK.now_iso()})
    refresh_roster_counters(drill)
    return success_object(public(entry))


@bp.post("/roster-entries/<rid>/unaccount")
def unaccount_entry(rid):
    authorized([ROLE_OFFICER])
    entry, drill = _entry_and_drill(rid)
    body = get_body()
    reject_unknown(body, ["reason"])

    if drill["status"] != "IN_PROGRESS" or entry["status"] != "ACCOUNTED":
        raise_error(ERR_INVALID_STATE,
                    "unaccount requires an ACCOUNTED entry on an IN_PROGRESS drill")

    apply_changes(entry, {"status": "UNACCOUNTED", "accounted_at": None})
    refresh_roster_counters(drill)
    return success_object(public(entry))


@bp.post("/roster-entries/<rid>/release")
def release_entry(rid):
    authorized([ROLE_OFFICER])
    entry, drill = _entry_and_drill(rid)
    body = get_body()
    reject_unknown(body, ["guardian_name", "released_to_verified"])
    guardian_name = req_str(body, "guardian_name")
    verified = req_bool(body, "released_to_verified")

    if drill["status"] != "IN_PROGRESS" or entry["status"] != "ACCOUNTED":
        raise_error(ERR_INVALID_STATE,
                    "release requires an ACCOUNTED entry on an IN_PROGRESS drill")

    if verified is not True:
        raise_error(ERR_PICKUP_NOT_VERIFIED,
                    "released_to_verified must be true to release")

    apply_changes(entry, {
        "status": "RELEASED",
        "released_at": CLOCK.now_iso(),
        "guardian_name": guardian_name,
        "released_to_verified": verified,
    })
    refresh_roster_counters(drill)
    return success_object(public(entry))
