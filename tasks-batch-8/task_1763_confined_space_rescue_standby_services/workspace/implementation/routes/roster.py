"""Roster scheduling, check-in/out, and rotation (PRD section 3.5)."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_CHECKIN_WINDOW_EXPIRED, ERR_CHECKIN_WINDOW_NOT_OPEN,
    ERR_ENTRANTS_STILL_INSIDE, ERR_INSUFFICIENT_REST, ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_RANGE, ERR_MAX_ENTRANTS_EXCEEDED, ERR_NO_ATTENDANT_ON_DUTY,
    ERR_PERMIT_INVALID_STATE, ERR_PERSONNEL_ALREADY_ON_DUTY,
    ERR_PERSONNEL_NOT_FOUND, ERR_PERSONNEL_NOT_QUALIFIED,
    ERR_RELIEF_TARGET_NOT_ON_DUTY, ERR_ROSTER_ENTRY_NOT_FOUND,
    ERR_ROSTER_INVALID_STATE, ERR_SHIFT_DURATION_EXCEEDS, raise_error,
)
from helpers import (
    body, iso_z, list_response, now_dt, parse_dt, reject_unknown, req_datetime,
    req_enum, req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.permits import get_permit
from services import (
    ROSTER_CHECKIN_EARLY, ROSTER_REST_GAP, finalize_exposure,
    on_duty_entries_for_permit, permit_of, space_of_permit,
)

bp = Blueprint("roster", __name__)

ASSIGNMENT_ROLES = ("ENTRANT", "ATTENDANT")


def get_roster_entry(entry_id):
    entry = db.roster_entries.get(entry_id)
    if entry is None:
        raise_error(ERR_ROSTER_ENTRY_NOT_FOUND, "Roster entry not found")
    return entry


@bp.route("/rescue-ops/entry-permits/<permit_id>/roster-entries", methods=["POST"])
def create_roster_entry(permit_id):
    require_auth(("EntrySupervisor",))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {
        "personnel_id", "assignment_role", "scheduled_start_at",
        "scheduled_end_at", "relief_of_entry_id",
    })
    personnel_id = req_string(data, "personnel_id")
    person = db.personnel.get(personnel_id)
    if person is None:
        raise_error(ERR_PERSONNEL_NOT_FOUND, "Personnel not found")
    assignment_role = req_enum(data, "assignment_role", ASSIGNMENT_ROLES)
    scheduled_start = req_datetime(data, "scheduled_start_at")
    scheduled_end = req_datetime(data, "scheduled_end_at")
    if not scheduled_end > scheduled_start:
        raise_error(ERR_INVALID_TIME_RANGE,
                    "scheduled_end_at must be strictly after scheduled_start_at")
    relief_of_entry_id = data.get("relief_of_entry_id")
    relief_target = None
    if relief_of_entry_id is not None:
        if not isinstance(relief_of_entry_id, str):
            raise_error(ERR_INVALID_REQUEST, "Field 'relief_of_entry_id' must be a string")
        relief_target = db.roster_entries.get(relief_of_entry_id)
        if relief_target is None or relief_target["permit_id"] != permit["id"]:
            raise_error(ERR_ROSTER_ENTRY_NOT_FOUND, "Relief target entry not found on this permit")
        if relief_target["assignment_role"] != assignment_role:
            raise_error(ERR_INVALID_REQUEST,
                        "relief_of_entry_id must reference an entry with the same assignment_role")
    # State gate (priority 7)
    if permit["status"] not in ("ISSUED", "ACTIVE"):
        raise_error(ERR_PERMIT_INVALID_STATE,
                    "Roster entries may be scheduled only while the permit is ISSUED or ACTIVE")
    # Temporal gate (priority 12): 8-hour rest gap vs the worker's other
    # SCHEDULED | ON_DUTY entries. Exactly 8 hours between shifts is legal.
    for other in db.roster_entries.values():
        if other["personnel_id"] != personnel_id or other["status"] not in ("SCHEDULED", "ON_DUTY"):
            continue
        existing_start = parse_dt(other["scheduled_start_at"])
        existing_end = parse_dt(other["scheduled_end_at"])
        if (scheduled_start < existing_end + ROSTER_REST_GAP
                and existing_start < scheduled_end + ROSTER_REST_GAP):
            raise_error(ERR_INSUFFICIENT_REST,
                        "New shift violates the 8-hour rest gap for this personnel")
    # Qualification gates (priority 13)
    if person["status"] != "ACTIVE":
        raise_error(ERR_PERSONNEL_NOT_QUALIFIED, "Only ACTIVE personnel may be scheduled")
    if assignment_role == "ATTENDANT" and "ATTENDANT" not in person["role_qualifications"]:
        raise_error(ERR_PERSONNEL_NOT_QUALIFIED,
                    "ATTENDANT slots require the ATTENDANT qualification")
    shift_hours = (scheduled_end - scheduled_start).total_seconds() / 3600.0
    if shift_hours > person["max_duty_hours"]:
        raise_error(ERR_SHIFT_DURATION_EXCEEDS,
                    "Scheduled shift length exceeds max_duty_hours")
    entry = {
        "permit_id": permit["id"],
        "personnel_id": personnel_id,
        "assignment_role": assignment_role,
        "scheduled_start_at": iso_z(scheduled_start),
        "scheduled_end_at": iso_z(scheduled_end),
        "relief_of_entry_id": relief_of_entry_id,
        "checked_in_at": None,
        "checked_out_at": None,
        "exposure_twa_ppm": 0,
        "exposure_peak_ppm": 0,
        "exposure_class": "OK",
        "status": "SCHEDULED",
    }
    stamp_new(entry)
    db.roster_entries[entry["id"]] = entry
    return success_object(serializers.roster_entry(entry), 201)


@bp.route("/rescue-ops/roster-entries", methods=["GET"])
def list_roster_entries():
    require_auth(ALL_ROLES)
    return list_response(list(db.roster_entries.values()), serializers.roster_entry, {
        "permit_id": request.args.get("permit_id"),
        "personnel_id": request.args.get("personnel_id"),
        "status": request.args.get("status"),
        "assignment_role": request.args.get("assignment_role"),
        "relief_of_entry_id": request.args.get("relief_of_entry_id"),
    })


@bp.route("/rescue-ops/roster-entries/<entry_id>", methods=["GET"])
def get_one_roster_entry(entry_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.roster_entry(get_roster_entry(entry_id)))


@bp.route("/rescue-ops/roster-entries/<entry_id>/check-in", methods=["POST"])
def check_in_roster_entry(entry_id):
    require_auth(("EntrySupervisor",))
    entry = get_roster_entry(entry_id)
    body()
    # State gates (priority 7)
    if entry["status"] != "SCHEDULED":
        raise_error(ERR_ROSTER_INVALID_STATE, "Only a SCHEDULED entry can be checked in")
    permit = permit_of(entry)
    if permit is None or permit["status"] != "ACTIVE":
        raise_error(ERR_PERMIT_INVALID_STATE, "Parent permit must be ACTIVE for check-in")
    now = now_dt()
    # People-safety gate (priority 10): entrant check-in needs an ON_DUTY attendant
    if entry["assignment_role"] == "ENTRANT":
        attendant_on_duty = any(
            e["permit_id"] == permit["id"] and e["status"] == "ON_DUTY"
            and e["assignment_role"] == "ATTENDANT"
            for e in db.roster_entries.values())
        if not attendant_on_duty:
            raise_error(ERR_NO_ATTENDANT_ON_DUTY, "No attendant is ON_DUTY on this permit")
    # Capacity gates (priority 11)
    already = any(
        e["personnel_id"] == entry["personnel_id"] and e["status"] == "ON_DUTY"
        and e["id"] != entry["id"]
        for e in db.roster_entries.values())
    if already:
        raise_error(ERR_PERSONNEL_ALREADY_ON_DUTY, "Personnel is already ON_DUTY on another entry")
    if entry["assignment_role"] == "ENTRANT":
        space = space_of_permit(permit)
        on_duty_entrants = sum(
            1 for e in db.roster_entries.values()
            if e["permit_id"] == permit["id"] and e["status"] == "ON_DUTY"
            and e["assignment_role"] == "ENTRANT")
        if space is not None and on_duty_entrants >= space["max_entrants"]:
            raise_error(ERR_MAX_ENTRANTS_EXCEEDED, "ON_DUTY entrant count reached max_entrants")
    relief_target = None
    if entry["relief_of_entry_id"] is not None:
        relief_target = db.roster_entries.get(entry["relief_of_entry_id"])
        if relief_target is None or relief_target["status"] != "ON_DUTY":
            raise_error(ERR_RELIEF_TARGET_NOT_ON_DUTY, "Relief target is not ON_DUTY")
    # Temporal gates (priority 12): check-in window
    scheduled_start = parse_dt(entry["scheduled_start_at"])
    scheduled_end = parse_dt(entry["scheduled_end_at"])
    if now < scheduled_start - ROSTER_CHECKIN_EARLY:
        raise_error(ERR_CHECKIN_WINDOW_NOT_OPEN, "Check-in window is not yet open")
    if now > scheduled_end:
        raise_error(ERR_CHECKIN_WINDOW_EXPIRED, "Check-in window has expired")
    entry["status"] = "ON_DUTY"
    entry["checked_in_at"] = iso_z(now)
    touch(entry)
    if relief_target is not None:
        # Rotation: target is relieved at the relieving entry's check-in time.
        finalize_exposure(relief_target, now)
        relief_target["status"] = "RELIEVED"
        relief_target["checked_out_at"] = entry["checked_in_at"]
        touch(relief_target)
    return success_object(serializers.roster_entry(entry))


@bp.route("/rescue-ops/roster-entries/<entry_id>/check-out", methods=["POST"])
def check_out_roster_entry(entry_id):
    require_auth(("EntrySupervisor",))
    entry = get_roster_entry(entry_id)
    body()
    if entry["status"] != "ON_DUTY":
        raise_error(ERR_ROSTER_INVALID_STATE, "Only an ON_DUTY entry can be checked out")
    if entry["assignment_role"] == "ATTENDANT":
        entrants_inside = any(
            e["permit_id"] == entry["permit_id"] and e["status"] == "ON_DUTY"
            and e["assignment_role"] == "ENTRANT"
            for e in db.roster_entries.values())
        if entrants_inside:
            raise_error(ERR_ENTRANTS_STILL_INSIDE,
                        "Attendant may not check out while entrants are ON_DUTY")
    now = now_dt()
    finalize_exposure(entry, now)
    entry["status"] = "COMPLETED"
    entry["checked_out_at"] = iso_z(now)
    touch(entry)
    return success_object(serializers.roster_entry(entry))
