"""Staff member and staff assignment endpoints."""

from flask import Blueprint

import calc
import cascades
import derive
import serializers
from auth import (ALL_DMC_ROLES, ROLE_OPS_COORDINATOR, ROLE_PROGRAM_DIRECTOR,
                  current_user_id, endpoint)
from common import (apply_filters, element_or_404, program_or_404, respond_list,
                    segment_or_404, staff_assignment_or_404, staff_member_or_404)
from envelope import created, ok
from errors import fail
from store import clock_now, db, new_row, plus_minutes, touch
from validation import (body, opt_enum, opt_int, opt_str, query_filter, ref_id, req_dt,
                        req_enum, req_int, req_str, strictly_after)

bp = Blueprint("staff", __name__)

ROLE_TYPES = ("COORDINATOR", "GREETER", "ACTIVITY_LEAD")
MEMBER_STATUSES = ("ACTIVE", "INACTIVE")
CREDENTIAL_STATUSES = ("VALID", "EXPIRING", "EXPIRED")
TARGET_TYPES = ("ELEMENT", "SEGMENT")
ASSIGNMENT_STATUSES = ("PROPOSED", "CONFIRMED", "CHECKED_IN", "COMPLETED",
                       "RELEASED", "NO_SHOW")


# --------------------------------------------------------------------------
# staff members
# --------------------------------------------------------------------------

@bp.post("/dmc/staff-members")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def create_staff_member():
    data = body()
    min_rest = opt_int(data, "min_rest_minutes", default=600, minimum=0)
    if min_rest is None:
        min_rest = 600
    max_daily = opt_int(data, "max_daily_minutes", default=720, minimum=0)
    if max_daily is None:
        max_daily = 720
    row = new_row(
        full_name=req_str(data, "full_name", min_len=1),
        role_type=req_enum(data, "role_type", ROLE_TYPES),
        badge_expires_on=req_dt(data, "badge_expires_on"),
        first_aid_expires_on=req_dt(data, "first_aid_expires_on"),
        pay_rate_cents_per_hour=req_int(data, "pay_rate_cents_per_hour", minimum=0),
        min_rest_minutes=min_rest,
        max_daily_minutes=max_daily,
        status=opt_enum(data, "status", MEMBER_STATUSES, default="ACTIVE"),
    )
    db.staff_members[row["id"]] = row
    return created(serializers.staff_member(row))


@bp.patch("/dmc/staff-members/<staff_member_id>")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def patch_staff_member(staff_member_id):
    member = staff_member_or_404(staff_member_id)
    data = body()
    if "badge_expires_on" in data:
        member["badge_expires_on"] = req_dt(data, "badge_expires_on")
    if "first_aid_expires_on" in data:
        member["first_aid_expires_on"] = req_dt(data, "first_aid_expires_on")
    if "pay_rate_cents_per_hour" in data:
        member["pay_rate_cents_per_hour"] = req_int(data, "pay_rate_cents_per_hour",
                                                    minimum=0)
    if "min_rest_minutes" in data:
        member["min_rest_minutes"] = req_int(data, "min_rest_minutes", minimum=0)
    if "max_daily_minutes" in data:
        member["max_daily_minutes"] = req_int(data, "max_daily_minutes", minimum=0)
    if "status" in data:
        member["status"] = req_enum(data, "status", MEMBER_STATUSES)
    touch(member)
    return ok(serializers.staff_member(member))


@bp.get("/dmc/staff-members/<staff_member_id>")
@endpoint(ALL_DMC_ROLES)
def read_staff_member(staff_member_id):
    return ok(serializers.staff_member(staff_member_or_404(staff_member_id)))


@bp.get("/dmc/staff-members")
@endpoint(ALL_DMC_ROLES)
def list_staff_members():
    rows = apply_filters(list(db.staff_members.values()), [
        ("role_type", "role_type", ROLE_TYPES),
        ("status", "status", MEMBER_STATUSES),
    ])
    wanted_credential = query_filter("credential_status", CREDENTIAL_STATUSES)
    if wanted_credential is not None:
        rows = [r for r in rows if derive.staff_credential_status(r) == wanted_credential]
    return respond_list(rows, serializers.staff_member)


# --------------------------------------------------------------------------
# staff assignments
# --------------------------------------------------------------------------

@bp.post("/dmc/staff-assignments")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def create_assignment():
    data = body()

    member = None
    staff_ref = ref_id(data, "staff_id")
    if staff_ref is not None:
        member = staff_member_or_404(staff_ref)
    program_ref = ref_id(data, "program_id")
    if program_ref is not None:
        program_or_404(program_ref)
    element = None
    element_ref = ref_id(data, "element_id")
    if element_ref is not None:
        element = element_or_404(element_ref)
    segment = None
    segment_ref = ref_id(data, "segment_id")
    if segment_ref is not None:
        segment = segment_or_404(segment_ref)

    staff_id = req_str(data, "staff_id", min_len=1)
    program_id = req_str(data, "program_id", min_len=1)
    target_type = req_enum(data, "target_type", TARGET_TYPES)
    role_type = req_enum(data, "role_type", ROLE_TYPES)
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    strictly_after(ends_at, starts_at, "ends_at", "starts_at")

    if element is not None and element["program_id"] != program_id:
        fail("ERR_SEGMENT_PROGRAM_MISMATCH",
             "The named element belongs to a different programme.")
    if segment is not None and segment["program_id"] != program_id:
        fail("ERR_SEGMENT_PROGRAM_MISMATCH",
             "The named segment belongs to a different programme.")

    if role_type != member["role_type"]:
        fail("ERR_STAFF_ROLE_MISMATCH",
             "The shift's role_type must equal the staff member's role_type.")
    if target_type == "ELEMENT":
        if element_ref is None or segment_ref is not None:
            fail("ERR_STAFF_ROLE_MISMATCH",
                 "target_type ELEMENT requires element_id alone.")
    else:
        if segment_ref is None or element_ref is not None:
            fail("ERR_STAFF_ROLE_MISMATCH",
                 "target_type SEGMENT requires segment_id alone.")

    row = new_row(
        staff_id=staff_id,
        program_id=program_id,
        element_id=element_ref,
        segment_id=segment_ref,
        target_type=target_type,
        role_type=role_type,
        starts_at=starts_at,
        ends_at=ends_at,
        status="PROPOSED",
        check_in_at=None,
        completed_at=None,
        planned_labor_cost_cents=0,
        actual_labor_cost_cents=0,
    )
    db.staff_assignments[row["id"]] = row
    return created(serializers.staff_assignment(row))


@bp.get("/dmc/staff-assignments/<staff_assignment_id>")
@endpoint(ALL_DMC_ROLES)
def read_assignment(staff_assignment_id):
    return ok(serializers.staff_assignment(staff_assignment_or_404(staff_assignment_id)))


@bp.get("/dmc/staff-assignments")
@endpoint(ALL_DMC_ROLES)
def list_assignments():
    rows = apply_filters(list(db.staff_assignments.values()), [
        ("staff_id", "staff_id", None),
        ("program_id", "program_id", None),
        ("element_id", "element_id", None),
        ("segment_id", "segment_id", None),
        ("status", "status", ASSIGNMENT_STATUSES),
    ])
    return respond_list(rows, serializers.staff_assignment)


def _incumbents(assignment):
    return [a for a in derive.assignments_of_staff(assignment["staff_id"])
            if a["id"] != assignment["id"]
            and a["status"] in derive.STAFF_OCCUPYING_STATUSES]


def _overlaps(candidate, incumbent):
    return (candidate["starts_at"] <= incumbent["ends_at"]
            and incumbent["starts_at"] <= candidate["ends_at"])


def _rest_gap_minutes(candidate, incumbent):
    first = abs((candidate["starts_at"] - incumbent["ends_at"]).total_seconds())
    second = abs((incumbent["starts_at"] - candidate["ends_at"]).total_seconds())
    return int(min(first, second) // 60)


@bp.post("/dmc/staff-assignments/<staff_assignment_id>/confirm")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def confirm_assignment(staff_assignment_id):
    assignment = staff_assignment_or_404(staff_assignment_id)
    if assignment["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "confirm requires status PROPOSED.")
    program = db.programs.get(assignment["program_id"])
    if program is None or program["execution_status"] not in ("DESIGN_LOCKED",
                                                             "CONFIRMED",
                                                             "IN_EXECUTION"):
        fail("ERR_PROGRAM_NOT_CONFIRMED",
             "The programme must be DESIGN_LOCKED, CONFIRMED or IN_EXECUTION.")
    member = db.staff_members.get(assignment["staff_id"])
    if member is None or derive.staff_credential_status(member) != "VALID":
        fail("ERR_CREDENTIAL_EXPIRED",
             "The staff member's credentials are not VALID.")
    if member["status"] != "ACTIVE":
        fail("ERR_STAFF_INACTIVE", "The staff member is not ACTIVE.")

    incumbents = _incumbents(assignment)
    for incumbent in incumbents:
        if _overlaps(assignment, incumbent):
            fail("ERR_STAFF_ASSIGNMENT_OVERLAP",
                 "The shift collides with another confirmed shift.")
    for incumbent in incumbents:
        if _rest_gap_minutes(assignment, incumbent) < int(member["min_rest_minutes"]):
            fail("ERR_STAFF_REST_GAP_VIOLATION",
                 "The shift does not leave the required rest gap.")
    candidate_minutes = calc.planned_minutes(assignment)
    day = assignment["starts_at"].date()
    same_day_minutes = sum(calc.planned_minutes(a) for a in incumbents
                           if a["starts_at"].date() == day)
    if same_day_minutes + candidate_minutes > int(member["max_daily_minutes"]):
        fail("ERR_STAFF_DAILY_LIMIT_EXCEEDED",
             "The shift would exceed the member's daily minute ceiling.")

    if assignment["role_type"] != member["role_type"]:
        fail("ERR_STAFF_ROLE_MISMATCH",
             "The shift's role_type must equal the staff member's role_type.")

    assignment["status"] = "CONFIRMED"
    assignment["planned_labor_cost_cents"] = calc.staff_labor_cost(
        candidate_minutes, member["pay_rate_cents_per_hour"])
    touch(assignment)
    return ok(serializers.staff_assignment(assignment))


@bp.post("/dmc/staff-assignments/<staff_assignment_id>/check-in")
@endpoint((ROLE_OPS_COORDINATOR,))
def check_in_assignment(staff_assignment_id):
    assignment = staff_assignment_or_404(staff_assignment_id)
    if current_user_id() != assignment["staff_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the assigned staff member may check in.")
    if assignment["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE_TRANSITION", "check-in requires status CONFIRMED.")
    program = db.programs.get(assignment["program_id"])
    if program is None or program["execution_status"] != "IN_EXECUTION":
        fail("ERR_PROGRAM_NOT_IN_EXECUTION", "The programme is not IN_EXECUTION.")
    now = clock_now()
    opens = plus_minutes(assignment["starts_at"], -calc.STAFF_CHECKIN_LEAD_MINUTES)
    if now < opens or now > assignment["ends_at"]:
        fail("ERR_CHECKIN_WINDOW_NOT_OPEN",
             "The on-site check-in window is not open.")

    assignment["status"] = "CHECKED_IN"
    assignment["check_in_at"] = now
    touch(assignment)
    return ok(serializers.staff_assignment(assignment))


@bp.post("/dmc/staff-assignments/<staff_assignment_id>/release")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def release_assignment(staff_assignment_id):
    assignment = staff_assignment_or_404(staff_assignment_id)
    data = body()
    opt_str(data, "release_reason")
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "release requires status PROPOSED or CONFIRMED.")
    program = db.programs.get(assignment["program_id"])
    cascades.release_assignment(assignment, program)
    return ok(serializers.staff_assignment(assignment))
