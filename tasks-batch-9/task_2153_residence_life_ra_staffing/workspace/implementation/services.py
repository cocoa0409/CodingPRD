"""Shared domain services: gates, cascades and the duty-conflict rule."""
from datetime import timedelta

from flask import g

import calc
import derive
import store
from constants import (
    COVERAGE_ALERT_THRESHOLD, DUTY_POINTS, MIN_REST_MINUTES,
)
from errors import ApiError
from store import DB

CONFLICTING_SHIFT_STATUSES = ("ASSIGNED", "SWAP_PENDING", "CHECKED_IN", "COMPLETED")


# ------------------------------------------------------------------ gates
def posture_gate(building):
    if building is None:
        return
    if building["posture"] != "OPEN":
        raise ApiError("ERR_BUILDING_NOT_OPEN")


def room_posture_gate(room):
    posture_gate(derive.building_of_room(room))


def room_available_gate(room):
    if room["status"] not in ("AVAILABLE", "OCCUPIED"):
        raise ApiError("ERR_ROOM_NOT_AVAILABLE")
    if derive.room_occupied_beds(room) >= room["bed_capacity"]:
        raise ApiError("ERR_ROOM_AT_CAPACITY")


def ra_certified_gate(ra):
    if ra["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_RA_NOT_CERTIFIED")


def ra_active_gate(ra):
    if ra["employment_status"] != "ACTIVE":
        raise ApiError("ERR_RA_NOT_ACTIVE")


def acting_ra():
    ra = store.get("ras", g.user_id)
    if ra is None:
        raise ApiError("ERR_RA_NOT_FOUND")
    return ra


def acting_student():
    student = store.get("students", g.user_id)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    return student


# ------------------------------------------------------------ room status
def sync_room_status(room):
    """Reconcile AVAILABLE/OCCUPIED with the live occupancy count."""
    if room["status"] not in ("AVAILABLE", "OCCUPIED"):
        return
    room["status"] = "OCCUPIED" if derive.room_occupied_beds(room) >= 1 else "AVAILABLE"


# --------------------------------------------------------------- cascades
def create_relocation_case(student):
    case = store.insert("rc_cases", "RoomChangeCase", {
        "student_id": student["id"],
        "roommate_student_id": None,
        "from_room_id": student.get("current_room_id"),
        "to_room_id": None,
        "origin": "EMERGENCY_RELOCATION",
        "mediation_status": "NOT_REQUIRED",
        "placement_status": "REQUESTED",
        "mediation_round": 0,
        "session_at": None,
        "opened_by_user_id": "system",
        "superseded_case_id": None,
        "reverted_from_room_id": None,
    })
    student["housing_status"] = "RELOCATION_PENDING"
    return case


def take_room_offline(room, cascade):
    """Room -> OFFLINE plus its fan-out (links 2-4 and the inspection fan-out)."""
    room["pre_closure_status"] = room["status"] if cascade else None
    room["status"] = "OFFLINE"
    for insp in store.all_rows("inspections"):
        if insp["room_id"] == room["id"] and insp["status"] == "SCHEDULED":
            insp["status"] = "CANCELLED"
    for stay in store.all_rows("breaks"):
        if stay["room_id"] != room["id"]:
            continue
        if stay["status"] not in ("APPROVED", "CHECKED_IN"):
            continue
        stay["status"] = "REVOKED"
        stay["revocation_cause"] = "EMERGENCY_CLOSURE"
        student = DB["students"].get(stay["student_id"])
        if student is not None:
            create_relocation_case(student)


def close_building(building, reason):
    for room in derive.rooms_of_building(building["id"]):
        if room["status"] in ("AVAILABLE", "OCCUPIED"):
            take_room_offline(room, cascade=True)
    for floor in derive.floors_of(building["id"]):
        floor["programming_frozen"] = True
    building["closure_reason"] = reason
    building["last_posture_change_at"] = store.now_iso()
    building["posture"] = "EMERGENCY_CLOSED"


def reopen_building(building):
    for room in derive.rooms_of_building(building["id"]):
        if room["status"] == "OFFLINE" and room.get("pre_closure_status"):
            room["status"] = room["pre_closure_status"]
            room["pre_closure_status"] = None
    for floor in derive.floors_of(building["id"]):
        floor["programming_frozen"] = False
    building["closure_reason"] = None
    building["last_posture_change_at"] = store.now_iso()
    building["posture"] = "OPEN"


def apply_conduct_cascade(student):
    """Links 3 and 4 of the sanction cascade."""
    standing = derive.student_standing(student)
    if standing not in ("PROBATION", "SUSPENDED"):
        return
    student["break_housing_eligible"] = False
    for case in store.all_rows("rc_cases"):
        if case["student_id"] == student["id"] and case["placement_status"] == "REQUESTED":
            case["placement_status"] = "DENIED"
    for stay in store.all_rows("breaks"):
        if stay["student_id"] != student["id"]:
            continue
        if stay["status"] in ("REQUESTED", "APPROVED"):
            stay["status"] = "REVOKED"
            stay["revocation_cause"] = "CONDUCT_INELIGIBLE"


def separate_ra_cascade(ra):
    """Three-link coverage cascade fired by RA separation."""
    current = store.now()
    for shift in store.all_rows("shifts"):
        if shift.get("assigned_ra_id") != ra["id"]:
            continue
        if shift["status"] not in ("ASSIGNED", "SWAP_PENDING"):
            continue
        if store.parse_iso(shift["start_at"]) <= current:
            continue
        shift["status"] = "OPEN"
        shift["assigned_ra_id"] = None
        shift["swap_requested_ra_id"] = None


# -------------------------------------------------------- duty conflicts
def shift_conflicts(ra_id, start_at, end_at, exclude_shift_id=None):
    rest = timedelta(minutes=MIN_REST_MINUTES)
    for other in store.all_rows("shifts"):
        if other.get("assigned_ra_id") != ra_id:
            continue
        if other["id"] == exclude_shift_id:
            continue
        if other["status"] not in CONFLICTING_SHIFT_STATUSES:
            continue
        o_start = store.parse_iso(other["start_at"])
        o_end = store.parse_iso(other["end_at"])
        if start_at < o_end and o_start < end_at:
            return True
        if o_start >= end_at:
            gap = o_start - end_at
        else:
            gap = start_at - o_end
        if gap < rest:
            return True
    return False


def duty_conflict_gate(ra_id, shift):
    start = store.parse_iso(shift["start_at"])
    end = store.parse_iso(shift["end_at"])
    if shift_conflicts(ra_id, start, end, exclude_shift_id=shift["id"]):
        raise ApiError("ERR_DUTY_COVERAGE_CONFLICT")


def select_auto_fill_ra(shift, exclude_ids):
    start = store.parse_iso(shift["start_at"])
    end = store.parse_iso(shift["end_at"])
    candidates = []
    for ra in store.all_rows("ras"):
        if ra["employment_status"] != "ACTIVE":
            continue
        if ra["certification_status"] != "CERTIFIED":
            continue
        if ra.get("assigned_floor_id") != shift["floor_id"]:
            continue
        if ra["id"] in exclude_ids:
            continue
        if shift_conflicts(ra["id"], start, end, exclude_shift_id=shift["id"]):
            continue
        candidates.append(ra)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_RA")
    candidates.sort(key=lambda ra: (
        calc.forward_28_score(ra),
        derive.ra_missed(ra),
        derive.ra_duty_points(ra),
        ra["created_at"],
        ra["_seq"],
    ))
    return candidates[0]
