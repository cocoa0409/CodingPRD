"""Assignment: booking, reads, the staffing dimension (confirm / activate /
release / reassign), the independent review dimension, and time entries."""

from flask import Blueprint

import db
import response
import validation
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_ENGAGEMENT_STAFF,
    ROLE_FIRM_ADMIN,
    ROLE_SCHEDULING_MANAGER,
    authorize,
)
from routes import common
from services import booking, calc, derive, serialize

bp = Blueprint("assignments", __name__)

MAX_ALLOCATED_HOURS = calc.D("400.00")


def _require_staffing(assignment, allowed, detail):
    if assignment["staffing_status"] not in allowed:
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", detail)


def _require_review_owner(assignment, user_id):
    if assignment["review_owner_staff_id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Only the booking's review owner may drive its review."
        )


# =============================================================================
# booking
# =============================================================================
@bp.post("/assignments")
def create_assignment():
    authorize(ROLE_SCHEDULING_MANAGER)
    body = validation.json_body()

    # --- 5: body foreign keys in declared field order ----------------------
    phase = validation.body_fk(body, "engagement_phase_id", db.phases, "ERR_PHASE_NOT_FOUND")
    staff = validation.body_fk(
        body, "staff_member_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )
    review_owner = validation.body_fk(
        body, "review_owner_staff_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )

    # --- 6: shape ----------------------------------------------------------
    validation.req_string(body, "engagement_phase_id")
    validation.req_string(body, "staff_member_id")
    start_date = validation.req_date(body, "start_date")
    end_date = validation.req_date(body, "end_date")
    allocated_hours = validation.req_number(
        body, "allocated_hours", calc.D("0"), MAX_ALLOCATED_HOURS, exclusive_min=True
    )
    validation.opt_string(body, "review_owner_staff_id")

    # --- 8: date geometry ---------------------------------------------------
    if end_date <= start_date:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must fall after start_date.")

    # --- 11 / 12 ------------------------------------------------------------
    if phase["staffing_status"] == "COMPLETE":
        raise ApiError("ERR_PHASE_INVALID_STATE", "A COMPLETE phase accepts no new booking.")
    engagement = common.engagement_of(phase)
    common.require_unblocked(engagement)

    # --- 14 through 34 ------------------------------------------------------
    plan = booking.gauntlet(
        phase, engagement, staff, review_owner, start_date, end_date, allocated_hours
    )

    row = booking.write_assignment(
        phase, staff, start_date, end_date, allocated_hours, review_owner, plan, calc.ZERO
    )
    derive.refresh_phase_status(phase)
    db.mark(phase)
    db.commit()
    return response.object_response(serialize.assignment(row), 201)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    row = validation.path_assignment(assignment_id)
    return response.object_response(serialize.assignment(row))


@bp.get("/assignments")
def list_assignments():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    filters = {
        "engagement_phase_id": common.q("engagement_phase_id"),
        "staff_member_id": common.q("staff_member_id"),
        "review_owner_staff_id": common.q("review_owner_staff_id"),
        "review_capacity_window_id": common.q("review_capacity_window_id"),
        "superseded_by_assignment_id": common.q("superseded_by_assignment_id"),
        "staffing_status": common.q("staffing_status"),
        "review_status": common.q("review_status"),
    }
    rows = db.by_seq(list(db.assignments.values()))
    for field, wanted in filters.items():
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return common.page(rows, serialize.assignment)


@bp.get("/assignments/<assignment_id>/time-entries")
def list_assignment_time_entries(assignment_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    assignment = validation.path_assignment(assignment_id)
    entry_type = common.q("entry_type")
    rows = calc.time_entries_of_assignment(assignment["id"])
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return common.page(rows, serialize.time_entry)


# =============================================================================
# the staffing dimension
# =============================================================================
@bp.post("/assignments/<assignment_id>/confirm")
def confirm_assignment(assignment_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    assignment = validation.path_assignment(assignment_id)

    _require_staffing(
        assignment, ("PROPOSED",), "Only a PROPOSED booking may be confirmed."
    )

    phase = common.phase_of(assignment)
    engagement = common.engagement_of(phase)
    common.require_unblocked(engagement)

    staff = db.staff_members[assignment["staff_member_id"]]
    if calc.independence_conflict(
        engagement["client_id"], staff["id"], assignment["start_date"], assignment["end_date"]
    ):
        raise ApiError(
            "ERR_INDEPENDENCE_RESTRICTED",
            "An active independence restriction now covers this booking.",
        )

    if calc.turnover_risk_band(staff) == "HIGH":
        week_start = calc.iso_week_start(assignment["start_date"])
        relieved = any(
            w["week_start_date"] == week_start
            for w in derive.waivers_of(staff_id=staff["id"], status="APPROVED")
        )
        if not relieved:
            raise ApiError(
                "ERR_TURNOVER_RISK_BLOCK",
                "The staff member's turnover risk is HIGH and no approved allowance covers that week.",
            )

    assignment["staffing_status"] = "CONFIRMED"
    db.mark(assignment)
    db.commit()
    return response.object_response(serialize.assignment(assignment))


@bp.post("/assignments/<assignment_id>/activate")
def activate_assignment(assignment_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    assignment = validation.path_assignment(assignment_id)

    _require_staffing(
        assignment, ("CONFIRMED",), "Only a CONFIRMED booking may be activated."
    )

    phase = common.phase_of(assignment)
    if phase is None or phase["staffing_status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_PHASE_NOT_IN_PROGRESS", "The owning phase must be IN_PROGRESS."
        )

    assignment["staffing_status"] = "ACTIVE"
    db.mark(assignment)
    db.commit()
    return response.object_response(serialize.assignment(assignment))


@bp.post("/assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    assignment = validation.path_assignment(assignment_id)
    body = validation.json_body()
    validation.opt_string(body, "reason_note", 1, 500)

    _require_staffing(
        assignment,
        ("PROPOSED", "CONFIRMED"),
        "Only a PROPOSED or CONFIRMED booking may be released.",
    )

    derive.release_assignment(assignment)
    phase = common.phase_of(assignment)
    if phase is not None:
        derive.refresh_phase_status(phase)
        derive.bubble_engagement(common.engagement_of(phase))

    db.commit()
    return response.object_response(serialize.assignment(assignment))


@bp.post("/assignments/<assignment_id>/reassign")
def reassign_assignment(assignment_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    original = validation.path_assignment(assignment_id)
    body = validation.json_body()

    # --- 5: body foreign keys in declared field order ----------------------
    staff = validation.body_fk(
        body, "staff_member_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )
    review_owner = validation.body_fk(
        body, "review_owner_staff_id", db.staff_members, "ERR_STAFF_MEMBER_NOT_FOUND"
    )

    # --- 6: shape ----------------------------------------------------------
    expected_phase_version = validation.req_integer(body, "expected_phase_version", 1)
    validation.req_string(body, "staff_member_id")
    start_date = validation.opt_date(body, "start_date", original["start_date"])
    end_date = validation.opt_date(body, "end_date", original["end_date"])
    allocated_hours = validation.opt_number(
        body,
        "allocated_hours",
        calc.D("0"),
        MAX_ALLOCATED_HOURS,
        exclusive_min=True,
        default=calc.D(original["allocated_hours"]),
    )
    validation.opt_string(body, "review_owner_staff_id")

    # --- 8: date geometry ---------------------------------------------------
    if end_date <= start_date:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must fall after start_date.")

    # --- 11 / 12 ------------------------------------------------------------
    _require_staffing(
        original,
        ("PROPOSED", "CONFIRMED"),
        "Only a PROPOSED or CONFIRMED booking may be reassigned.",
    )
    phase = common.phase_of(original)
    engagement = common.engagement_of(phase)
    common.require_unblocked(engagement)

    # --- 14 through 34 ------------------------------------------------------
    plan = booking.gauntlet(
        phase, engagement, staff, review_owner, start_date, end_date, allocated_hours
    )

    # --- 41: optimistic concurrency on the parent phase --------------------
    if expected_phase_version != phase["version"]:
        raise ApiError(
            "ERR_STALE_PHASE_VERSION",
            "expected_phase_version %d does not match the phase version %d."
            % (expected_phase_version, phase["version"]),
        )

    replacement = booking.write_assignment(
        phase, staff, start_date, end_date, allocated_hours, review_owner, plan, calc.ZERO
    )
    original["superseded_by_assignment_id"] = replacement["id"]
    derive.release_assignment(original)

    derive.refresh_phase_status(phase)
    db.mark(phase)
    db.commit()
    return response.object_response(serialize.assignment(replacement), 201)


# =============================================================================
# the review dimension
# =============================================================================
@bp.post("/assignments/<assignment_id>/start-review")
def start_review(assignment_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    assignment = validation.path_assignment(assignment_id)

    _require_review_owner(assignment, user_id)

    opening_from = assignment["review_status"]
    if opening_from not in ("PENDING_REVIEW", "REWORK_REQUESTED"):
        raise ApiError(
            "ERR_REVIEW_INVALID_STATE",
            "The review must be PENDING_REVIEW or REWORK_REQUESTED to be opened.",
        )
    if assignment["staffing_status"] not in ("CONFIRMED", "ACTIVE"):
        raise ApiError(
            "ERR_REVIEW_INVALID_STATE",
            "The booking must be CONFIRMED or ACTIVE for its review to be opened.",
        )

    if opening_from == "PENDING_REVIEW" and user_id == assignment["staff_member_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "A staff member may not review their own work."
        )

    assignment["review_status"] = "IN_REVIEW"
    db.mark(assignment)
    db.commit()
    return response.object_response(serialize.assignment(assignment))


@bp.post("/assignments/<assignment_id>/request-rework")
def request_rework(assignment_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    assignment = validation.path_assignment(assignment_id)
    body = validation.json_body()
    validation.opt_string(body, "reason_note", 1, 500)

    _require_review_owner(assignment, user_id)

    if assignment["review_status"] != "IN_REVIEW":
        raise ApiError("ERR_REVIEW_INVALID_STATE", "Only an IN_REVIEW booking may be sent back.")

    next_cycles = assignment["rework_cycles"] + 1
    next_charge = calc.review_hours_for(calc.D(assignment["allocated_hours"]), next_cycles)

    # --- 34: the reviewer's weekly review capacity -------------------------
    window_id = assignment["review_capacity_window_id"]
    if window_id is not None and window_id in db.review_windows:
        window = db.review_windows[window_id]
        others = calc.committed_review_hours(window_id, exclude_ids=(assignment["id"],))
        if others + next_charge > calc.D(window["review_capacity_hours"]):
            raise ApiError(
                "ERR_REVIEW_CAPACITY_EXCEEDED",
                "The extra rework block would exceed the reviewer's weekly review capacity.",
            )

    # --- 35: the rework ceiling --------------------------------------------
    if assignment["rework_cycles"] >= calc.MAX_REWORK_CYCLES:
        raise ApiError(
            "ERR_REWORK_LIMIT_EXCEEDED",
            "The booking has already been through the maximum number of rework cycles.",
        )

    assignment["rework_cycles"] = next_cycles
    assignment["review_hours_charged"] = next_charge
    assignment["review_status"] = "REWORK_REQUESTED"
    db.mark(assignment)
    db.commit()
    return response.object_response(serialize.assignment(assignment))


@bp.post("/assignments/<assignment_id>/accept-review")
def accept_review(assignment_id):
    user_id, _role = authorize(ROLE_ENGAGEMENT_PARTNER)
    assignment = validation.path_assignment(assignment_id)

    _require_review_owner(assignment, user_id)

    if assignment["review_status"] != "IN_REVIEW":
        raise ApiError("ERR_REVIEW_INVALID_STATE", "Only an IN_REVIEW booking may be accepted.")

    if user_id == assignment["staff_member_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "A staff member may not accept their own work."
        )

    assignment["review_status"] = "REVIEW_ACCEPTED"
    db.mark(assignment)
    db.commit()
    return response.object_response(serialize.assignment(assignment))


# =============================================================================
# TimeEntry
# =============================================================================
@bp.post("/time-entries")
def create_time_entry():
    user_id, _role = authorize(ROLE_ENGAGEMENT_STAFF)
    body = validation.json_body()

    assignment = validation.body_fk(
        body, "assignment_id", db.assignments, "ERR_ASSIGNMENT_NOT_FOUND"
    )

    validation.req_string(body, "assignment_id")
    work_date = validation.req_date(body, "work_date")
    hours = validation.req_number(body, "hours", calc.D("0.25"), calc.D("16.00"))
    entry_type = validation.req_enum(body, "entry_type", validation.ENTRY_TYPES)

    # --- 10: only the assigned person logs their own hours -----------------
    if user_id != assignment["staff_member_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "Only the staff member booked on the assignment may log its hours.",
        )

    # --- 11: the booking must be live --------------------------------------
    _require_staffing(
        assignment,
        ("ACTIVE", "COMPLETED"),
        "Hours may only be logged against an ACTIVE or COMPLETED booking.",
    )

    # --- 13: the phase must be in progress ---------------------------------
    phase = common.phase_of(assignment)
    if phase is None or phase["staffing_status"] != "IN_PROGRESS":
        raise ApiError("ERR_PHASE_NOT_IN_PROGRESS", "The owning phase must be IN_PROGRESS.")

    # --- 36: the work date must sit inside the booking ---------------------
    if not (assignment["start_date"] <= work_date < assignment["end_date"]):
        raise ApiError(
            "ERR_TIME_ENTRY_OUT_OF_WINDOW",
            "work_date must satisfy start_date <= work_date < end_date.",
        )

    # --- 37: the allocation tolerance --------------------------------------
    logged = calc.r2(
        sum(
            (calc.D(e["hours"]) for e in calc.time_entries_of_assignment(assignment["id"])),
            calc.ZERO,
        )
    )
    ceiling = calc.r2(calc.D(assignment["allocated_hours"]) * calc.TIME_ENTRY_TOLERANCE)
    if calc.r2(logged + hours) > ceiling:
        raise ApiError(
            "ERR_TIME_ENTRY_EXCEEDS_ALLOCATION",
            "Logged hours would exceed 125 percent of the booking's allocated hours.",
        )

    row = db.new_row(versioned=False)
    row.update(
        {
            "assignment_id": assignment["id"],
            "work_date": work_date,
            "hours": calc.r2(hours),
            "entry_type": entry_type,
        }
    )
    db.time_entries[row["id"]] = row
    db.commit()
    return response.object_response(serialize.time_entry(row), 201)
