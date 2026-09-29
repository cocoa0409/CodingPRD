"""Work shifts, seating, completion and support services
(PRD sections 3.4, 3.5 and 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import derive
import shapes
from auth import must_exist_filter, must_get, require
from errors import fail
from response import created, ok, ok_list, paginate, read_pagination
from serialize import dump, dump_many
from store import all_records, create_record, days, iso_week_start, set_fields, store

bp = Blueprint("trading", __name__)

SHIFT_READ_ROLES = ("ProgramDirector", "CaseManager", "JobCoach", "FunderAnalyst")
SUPPORT_READ_ROLES = ("ProgramDirector", "JobCoach", "CaseManager", "FunderAnalyst")


# =========================================================================== #
# WorkShift
# =========================================================================== #

@bp.route("/work-shifts", methods=["POST"])
def create_work_shift():
    require(("ProgramDirector",))
    payload = shapes.body()
    line = must_get("business_lines", payload.get("business_line_id"))
    starts_at = shapes.req_datetime(payload, "starts_at")
    ends_at = shapes.req_datetime(payload, "ends_at")
    if ends_at <= starts_at:
        fail("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at.")
    if (ends_at - starts_at).total_seconds() > C.MAX_SHIFT_HOURS * 3600:
        fail("ERR_INVALID_REQUEST", "A shift may not be longer than twelve hours.")
    capacity = shapes.req_int(payload, "trainee_capacity", 1)
    supervisor = shapes.req_string(payload, "supervisor_user_id", 1)
    standard = shapes.opt_enum(payload, "customer_service_standard",
                               C.CUSTOMER_SERVICE_STANDARDS, "STANDARD")
    shift = create_record("work_shifts", {
        "business_line_id": line["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "trainee_capacity": capacity,
        "supervisor_user_id": supervisor,
        "customer_service_standard": standard,
        "status": "SCHEDULED",
        "assigned_count": 0,
        "duration_hours": calc.duration_hours(starts_at, ends_at),
        "billable_labor_cost_cents": None,
        "quality_defect_count": 0,
        "customer_complaint_count": 0,
    })
    return created(dump(shift))


@bp.route("/work-shifts/<work_shift_id>", methods=["GET"])
def read_work_shift(work_shift_id):
    require(SHIFT_READ_ROLES)
    return ok(dump(must_get("work_shifts", work_shift_id)))


@bp.route("/work-shifts", methods=["GET"])
def list_work_shifts():
    require(SHIFT_READ_ROLES)
    line = must_exist_filter("business_lines", shapes.query_id("business_line_id"))
    status = shapes.query_enum("status", C.WORK_SHIFT_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("work_shifts")
    if line is not None:
        rows = [row for row in rows if row["business_line_id"] == line["id"]]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


# =========================================================================== #
# ShiftAssignment
# =========================================================================== #

def _rest_buffer_conflict(participant_id, new_shift):
    buffer_seconds = C.REST_BUFFER_MINUTES * 60
    for assignment in derive.assignments_of_participant(participant_id):
        if assignment["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        other = derive.shift_of(assignment)
        if other["id"] == new_shift["id"]:
            return True
        if ((new_shift["starts_at"] - other["ends_at"]).total_seconds() < buffer_seconds
                and (other["starts_at"] - new_shift["ends_at"]).total_seconds() < buffer_seconds):
            return True
    return False


def _supervision_capacity_exceeded(line, new_shift):
    """Aggregate concurrency ceiling over the new shift's half-open interval."""
    shifts = [s for s in derive.shifts_of_line(line["id"]) if s["status"] == "SCHEDULED"]
    seats = {}
    for shift in shifts:
        seats[shift["id"]] = len([a for a in derive.assignments_of_shift(shift["id"])
                                  if a["status"] == "ASSIGNED"])
    seats[new_shift["id"]] = seats.get(new_shift["id"], 0) + 1
    instants = [new_shift["starts_at"]]
    for shift in shifts:
        if new_shift["starts_at"] < shift["starts_at"] < new_shift["ends_at"]:
            instants.append(shift["starts_at"])
    for instant in instants:
        concurrent = 0
        for shift in shifts:
            if shift["starts_at"] <= instant < shift["ends_at"]:
                concurrent += seats[shift["id"]]
        if concurrent > line["supervisor_capacity"]:
            return True
    return False


def _committed_week_hours(participant_id, week_start, week_end, exclude_shift_id=None):
    total = Decimal("0")
    for assignment in derive.assignments_of_participant(participant_id):
        if assignment["status"] not in ("ASSIGNED", "COMPLETED"):
            continue
        shift = derive.shift_of(assignment)
        if exclude_shift_id is not None and shift["id"] == exclude_shift_id:
            continue
        if week_start <= shift["starts_at"] < week_end:
            total += calc.dec(shift["duration_hours"])
    return total


@bp.route("/shift-assignments", methods=["POST"])
def create_shift_assignment():
    require(("CaseManager",))
    payload = shapes.body()
    shift = must_get("work_shifts", payload.get("work_shift_id"))
    participant = must_get("participants", payload.get("participant_id"))
    if shift["status"] != "SCHEDULED":
        fail("ERR_SHIFT_NOT_SCHEDULED", "The work shift is not SCHEDULED.")
    duplicate = any(row["participant_id"] == participant["id"]
                    and row["status"] in ("ASSIGNED", "COMPLETED")
                    for row in derive.assignments_of_shift(shift["id"]))
    if duplicate:
        fail("ERR_DUPLICATE_SHIFT_ASSIGNMENT",
             "The participant already holds a seat on this shift.")
    if _rest_buffer_conflict(participant["id"], shift):
        fail("ERR_PARTICIPANT_REST_BUFFER_CONFLICT",
             "The participant needs at least 60 minutes between shifts.")
    line = store.business_lines[shift["business_line_id"]]
    if _supervision_capacity_exceeded(line, shift):
        fail("ERR_SUPERVISION_CAPACITY_EXCEEDED",
             "The line's supervisor_capacity would be exceeded at some instant of the shift.")
    if shift["assigned_count"] >= shift["trainee_capacity"]:
        fail("ERR_SHIFT_CAPACITY_FULL", "The shift has no seats left.")
    week_start = iso_week_start(shift["starts_at"])
    committed = _committed_week_hours(participant["id"], week_start, week_start + days(7))
    if committed + calc.dec(shift["duration_hours"]) > C.WEEKLY_HOURS_CAP:
        fail("ERR_WEEKLY_HOURS_CAP_EXCEEDED",
             "The participant's committed hours for the ISO week would exceed 28.")
    assignment = create_record("shift_assignments", {
        "work_shift_id": shift["id"],
        "participant_id": participant["id"],
        "status": "ASSIGNED",
        "actual_hours": None,
        "quality_defect_count": 0,
        "customer_complaint_count": 0,
        "wage_cost_cents": None,
        "released_reason": None,
    })
    derive.recompute_shift_counters(shift)
    derive.recompute_participant_metrics(participant)
    return created(dump(assignment))


@bp.route("/shift-assignments/<shift_assignment_id>", methods=["GET"])
def read_shift_assignment(shift_assignment_id):
    require(SHIFT_READ_ROLES)
    return ok(dump(must_get("shift_assignments", shift_assignment_id)))


@bp.route("/shift-assignments", methods=["GET"])
def list_shift_assignments():
    require(SHIFT_READ_ROLES)
    participant = must_exist_filter("participants", shapes.query_id("participant_id"))
    shift = must_exist_filter("work_shifts", shapes.query_id("work_shift_id"))
    status = shapes.query_enum("status", C.SHIFT_ASSIGNMENT_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("shift_assignments")
    if participant is not None:
        rows = [row for row in rows if row["participant_id"] == participant["id"]]
    if shift is not None:
        rows = [row for row in rows if row["work_shift_id"] == shift["id"]]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/shift-assignments/<shift_assignment_id>/complete", methods=["POST"])
def complete_shift_assignment(shift_assignment_id):
    require(("CaseManager",))
    assignment = must_get("shift_assignments", shift_assignment_id)
    payload = shapes.body()
    actual_hours = shapes.req_number(payload, "actual_hours", places=3)
    if actual_hours <= 0:
        fail("ERR_INVALID_REQUEST", "actual_hours must be strictly greater than 0.")
    defects = shapes.opt_int(payload, "quality_defect_count", 0, default=0)
    complaints = shapes.opt_int(payload, "customer_complaint_count", 0, default=0)
    shift = derive.shift_of(assignment)
    if assignment["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ASSIGNED seat may be completed.")
    if shift["status"] != "SCHEDULED":
        fail("ERR_SHIFT_NOT_SCHEDULED", "The work shift is not SCHEDULED.")
    if store.now < shift["starts_at"]:
        fail("ERR_SHIFT_NOT_STARTED", "The shift has not started yet.")
    period = derive.select_open_period(shift["business_line_id"], shift["starts_at"])
    if period is None:
        fail("ERR_NO_OPEN_SUBSIDY_PERIOD",
             "No OPEN subsidy period of the line covers the shift's starts_at.")
    if actual_hours > calc.dec(shift["duration_hours"]) + C.ACTUAL_HOURS_GRACE:
        fail("ERR_ACTUAL_HOURS_EXCEED_SHIFT",
             "actual_hours may not exceed the shift's duration_hours plus 0.5.")
    participant = derive.participant_of(assignment)
    set_fields(assignment,
               status="COMPLETED",
               actual_hours=actual_hours,
               quality_defect_count=defects,
               customer_complaint_count=complaints,
               wage_cost_cents=calc.wage_cost_cents(actual_hours, participant["wage_cents_per_hour"]))
    derive.post_cost_entry(period, "TRAINEE_WAGES", "SHARED", assignment["wage_cost_cents"])
    derive.recompute_participant_metrics(participant)
    derive.recompute_shift_counters(shift)
    derive.recompute_line_posture(store.business_lines[shift["business_line_id"]])
    derive.evaluate_shift_close(shift)
    return ok(dump(assignment))


@bp.route("/shift-assignments/<shift_assignment_id>/release", methods=["POST"])
def release_shift_assignment(shift_assignment_id):
    require(("CaseManager",))
    assignment = must_get("shift_assignments", shift_assignment_id)
    shapes.body()
    shift = derive.shift_of(assignment)
    if assignment["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ASSIGNED seat may be released.")
    if shift["status"] != "SCHEDULED":
        fail("ERR_SHIFT_NOT_SCHEDULED", "The work shift is not SCHEDULED.")
    derive.release_assignment(assignment, "MANUAL_RELEASE")
    derive.recompute_shift_counters(shift)
    derive.recompute_participant_metrics(derive.participant_of(assignment))
    derive.evaluate_shift_close(shift)
    return ok(dump(assignment))


# =========================================================================== #
# SupportActivity
# =========================================================================== #

@bp.route("/support-activities", methods=["POST"])
def create_support_activity():
    require(("JobCoach", "CaseManager"))
    payload = shapes.body()
    participant = must_get("participants", payload.get("participant_id"))
    category = shapes.req_enum(payload, "category", C.SUPPORT_CATEGORIES)
    minutes = shapes.req_int(payload, "duration_minutes", 0, C.MAX_DURATION_MINUTES)
    cost = shapes.req_int(payload, "cost_cents", 1)
    if category in C.CONTACT_CATEGORIES and minutes <= 0:
        fail("ERR_INVALID_REQUEST",
             "duration_minutes must be strictly greater than 0 for a contact category.")
    if category in C.VOUCHER_CATEGORIES and minutes != 0:
        fail("ERR_INVALID_REQUEST", "duration_minutes must be exactly 0 for a voucher category.")
    activity = create_record("support_activities", {
        "participant_id": participant["id"],
        "category": category,
        "status": "PLANNED",
        "duration_minutes": minutes,
        "cost_cents": cost,
        "delivered_by_user_id": None,
        "delivered_at": None,
        "voided_reason": None,
    })
    return created(dump(activity))


@bp.route("/support-activities/<support_activity_id>", methods=["GET"])
def read_support_activity(support_activity_id):
    require(SUPPORT_READ_ROLES)
    return ok(dump(must_get("support_activities", support_activity_id)))


@bp.route("/support-activities", methods=["GET"])
def list_support_activities():
    require(SUPPORT_READ_ROLES)
    participant = must_exist_filter("participants", shapes.query_id("participant_id"))
    status = shapes.query_enum("status", C.SUPPORT_STATUSES)
    category = shapes.query_enum("category", C.SUPPORT_CATEGORIES)
    limit, offset = read_pagination(request.args)
    rows = all_records("support_activities")
    if participant is not None:
        rows = [row for row in rows if row["participant_id"] == participant["id"]]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    if category is not None:
        rows = [row for row in rows if row["category"] == category]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/support-activities/<support_activity_id>/deliver", methods=["POST"])
def deliver_support_activity(support_activity_id):
    user_id, _role = require(("JobCoach",))
    activity = must_get("support_activities", support_activity_id)
    shapes.body()
    participant = derive.participant_of(activity)
    if (activity["status"] != "PLANNED"
            or participant["status"] not in C.SUPPORT_DELIVERABLE_PARTICIPANT_STATUSES):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a PLANNED activity for a participant in transitional employment, "
             "readiness or placement may be delivered.")
    period = derive.select_open_period(participant["business_line_id"], store.now)
    if period is None:
        fail("ERR_NO_OPEN_SUBSIDY_PERIOD",
             "No OPEN subsidy period of the participant's line covers the current instant.")
    set_fields(activity,
               status="DELIVERED",
               delivered_at=store.now,
               delivered_by_user_id=user_id)
    category = "COACHING" if activity["category"] in C.CONTACT_CATEGORIES else "SUPPORT_SERVICE"
    derive.post_cost_entry(period, category, "MISSION", activity["cost_cents"], activity["id"])
    derive.recompute_participant_metrics(participant)
    return ok(dump(activity))


@bp.route("/support-activities/<support_activity_id>/void", methods=["POST"])
def void_support_activity(support_activity_id):
    require(("ProgramDirector",))
    activity = must_get("support_activities", support_activity_id)
    payload = shapes.body()
    reason = shapes.req_string(payload, "voided_reason", 1)
    if activity["status"] not in ("PLANNED", "DELIVERED"):
        fail("ERR_INVALID_STATE_TRANSITION", "The support activity is already VOIDED.")
    entry = None
    if activity["status"] == "DELIVERED":
        entry = _posted_entry_for(activity["id"])
        if entry is not None:
            period = store.subsidy_periods[entry["subsidy_period_id"]]
            if period["status"] != "OPEN":
                fail("ERR_PERIOD_CLOSED",
                     "The cost entry of this activity belongs to a CLOSED period.")
    set_fields(activity, status="VOIDED", voided_reason=reason)
    if entry is not None:
        derive.void_cost_entry(entry)
    derive.recompute_participant_metrics(derive.participant_of(activity))
    return ok(dump(activity))


def _posted_entry_for(activity_id):
    for entry in all_records("cost_entries"):
        if entry["source_activity_id"] == activity_id and entry["status"] == "POSTED":
            return entry
    return None
