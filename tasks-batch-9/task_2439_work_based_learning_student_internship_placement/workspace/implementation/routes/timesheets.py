"""Timesheet entries under child labor law (PRD 3.7)."""

from flask import Blueprint

import calc
import derive
from auth import require
from db import db, new_record, today_str, touch
from errors import fail
from response import created, listing, ok
from validation import (f_bool, f_date, f_int, f_str, f_time, get_body, pagination,
                        paginate, q_enum)

bp = Blueprint("timesheets", __name__)

ENTRY_STATUSES = ("LOGGED", "VOIDED")
TRAVEL_BUFFER_MINUTES = 30


def _sorted_entries(rows):
    return sorted(rows, key=lambda e: (e["work_date"], e["created_at"], e["_seq"]))


@bp.post("/timesheet-entries")
def log_entry():
    user_id, _role = require("EmployerSupervisor")
    body = get_body()
    placement = derive.get_placement(f_str(body, "placement_id"))

    # step 3: only the supervising EmployerSupervisor logs shifts
    if user_id != placement["supervisor_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the placement's own supervisor may log its hours.")

    # step 8
    work_date = f_date(body, "work_date")
    start_time = f_time(body, "start_time")
    end_time = f_time(body, "end_time")
    break_minutes = f_int(body, "break_minutes", required=False, default=0, minimum=0)
    is_school_day = f_bool(body, "is_school_day", required=False, default=True)
    if calc.minutes_of(end_time) <= calc.minutes_of(start_time):
        fail("ERR_INVALID_REQUEST", "Field 'end_time' must be after 'start_time'.")

    # step 16 / 18
    if placement["lifecycle_status"] != "ACTIVE":
        fail("ERR_PLACEMENT_NOT_ACTIVE", "The placement is not active.")
    if placement["compliance_status"] == "BLOCKED":
        fail("ERR_PLACEMENT_COMPLIANCE_BLOCKED",
             "The placement's compliance dimension is blocked.")

    # step 28: the permit must still be live at the moment of logging
    permits = derive.matching_permits(placement["student_id"],
                                      placement["permit_class_at_start"],
                                      require_unexpired=True)
    if not permits:
        fail("ERR_WORK_PERMIT_INVALID",
             "The student does not hold a valid work permit for this placement's age band.")

    candidate_hours = calc.shift_hours(start_time, end_time, break_minutes)
    band = calc.BANDS.get(placement["permit_class_at_start"])
    student_entries = derive.student_logged_entries(placement["student_id"])

    if band is not None:
        # step 32
        if start_time < band["earliest"] or end_time > band["night_cutoff"]:
            fail("ERR_NIGHT_WORK_PROHIBITED",
                 "The shift falls outside the permitted hours for this age band.")
        # step 33
        day_total = sum((calc.dec(e["hours_worked"]) for e in student_entries
                         if e["work_date"] == work_date), calc.ZERO)
        daily_cap = band["daily_school"] if is_school_day else band["daily_non_school"]
        if day_total + candidate_hours > daily_cap:
            fail("ERR_DAILY_HOUR_CAP_EXCEEDED",
                 "The shift would breach the daily hour cap for this age band.")
        # step 34
        week_from, week_to = calc.week_span(work_date)
        week_total = sum((calc.dec(e["hours_worked"]) for e in student_entries
                          if week_from <= e["work_date"] <= week_to), calc.ZERO)
        weekly_cap = band["weekly_school"] if is_school_day else band["weekly_non_school"]
        if week_total + candidate_hours > weekly_cap:
            fail("ERR_WEEKLY_HOUR_CAP_EXCEEDED",
                 "The shift would breach the weekly hour cap for this age band.")

    # step 36
    if not (placement["start_on"] <= work_date <= placement["end_on"]):
        fail("ERR_WORK_DATE_OUTSIDE_PLACEMENT",
             "The work date falls outside the placement window.")
    # step 37
    if work_date > today_str():
        fail("ERR_WORK_DATE_IN_FUTURE", "The work date is in the future.")

    # step 38: half-open interval collision with a 30-minute cross-site buffer
    cand_start = calc.minutes_of(start_time)
    cand_end = calc.minutes_of(end_time)
    for other in student_entries:
        if other["work_date"] != work_date:
            continue
        other_placement = db.placements.get(other["placement_id"])
        buffer = 0
        if (other_placement is not None
                and other_placement["worksite_id"] != placement["worksite_id"]):
            buffer = TRAVEL_BUFFER_MINUTES
        other_start = calc.minutes_of(other["start_time"]) - buffer
        other_end = calc.minutes_of(other["end_time"]) + buffer
        if cand_start < other_end and other_start < cand_end:
            fail("ERR_STUDENT_SCHEDULE_OVERLAP",
                 "The shift collides with another logged shift for this student.")

    entry = new_record()
    entry.update({
        "placement_id": placement["id"],
        "work_date": work_date,
        "start_time": start_time,
        "end_time": end_time,
        "break_minutes": break_minutes,
        "is_school_day": is_school_day,
        "hours_worked": candidate_hours,
        "status": "LOGGED",
        "voided_reason": None,
        "voided_by_user_id": None,
    })
    db.timesheet_entries[entry["id"]] = entry

    derive.recompute_placement_hours(placement)
    student = db.students.get(placement["student_id"])
    if student is not None:
        derive.recompute_student(student)
    return created(entry)


@bp.post("/timesheet-entries/<entryId>/void")
def void_entry(entryId):
    user_id, _role = require("WblCoordinator")
    entry = derive.get_entry(entryId)
    body = get_body()
    reason = f_str(body, "voided_reason")

    if entry["status"] != "LOGGED":
        fail("ERR_INVALID_REQUEST", "Only a logged timesheet entry may be voided.")

    entry["status"] = "VOIDED"
    entry["voided_reason"] = reason
    entry["voided_by_user_id"] = user_id
    touch(entry)

    placement = db.placements.get(entry["placement_id"])
    if placement is not None:
        derive.recompute_placement_hours(placement)
        student = db.students.get(placement["student_id"])
        if student is not None:
            derive.recompute_student(student)
    return ok(entry)


@bp.get("/placements/<id>/timesheet-entries")
def list_placement_entries(id):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor", "Student")
    placement = derive.get_placement(id)
    limit, offset = pagination()
    status = q_enum("status", ENTRY_STATUSES)
    rows = _sorted_entries([e for e in db.timesheet_entries.values()
                            if e["placement_id"] == placement["id"]
                            and (status is None or e["status"] == status)])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)
