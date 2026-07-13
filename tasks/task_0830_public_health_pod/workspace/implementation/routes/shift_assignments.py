from flask import Blueprint, g, request

from db import db
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_enum, require_type,
    sorted_by_created, strip_internal, touch,
)
from middleware import require_role
from response import success_array, success_object
from services import pod_adjust_committed_hours, shift_duration_hours
from timeutil import current_clock, parse_iso8601

bp = Blueprint("shift_assignments", __name__)

ASSIGNED_ROLES = {"CLINICAL_LEAD", "SCREENER", "VACCINATOR", "RUNNER", "TRAFFIC_CONTROL", "GREETER"}
READ_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "MutualAidPartner", "ClinicalLead", "Volunteer"]
LIST_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "ClinicalLead", "Volunteer"]


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.route("/shift-assignments", methods=["POST"])
@require_role("Volunteer", "PublicHealthAdmin", "ClinicalLead")
def create_shift_assignment():
    body = get_json_body()
    pod_id = body.get("pod_id")
    staff_member_id = body.get("staff_member_id")
    assigned_role = body.get("assigned_role")
    start_time = body.get("start_time")
    end_time = body.get("end_time")

    # priority 3: ownership -- Volunteer must propose their own assignment
    if g.user_role == "Volunteer" and staff_member_id != g.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Volunteer must propose their own assignment.", 403)

    # priority 5: body FK existence
    pod = fetch_or_404(db.pods, pod_id, "POD")
    staff = fetch_or_404(db.staff_members, staff_member_id, "StaffMember")

    # priority 8: start_time strictly before end_time
    if not isinstance(start_time, str) or not isinstance(end_time, str):
        raise ApiError("ERR_VALIDATION", "start_time and end_time are required.", 400)
    try:
        st = parse_iso8601(start_time)
        et = parse_iso8601(end_time)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "start_time/end_time must be valid ISO8601 timestamps.", 400)
    if not st < et:
        raise ApiError("ERR_INVALID_TIME_RANGE", "start_time must be strictly before end_time.", 400)

    # priority 23: general validation
    require_type(assigned_role, str, "assigned_role")
    require_enum(assigned_role, ASSIGNED_ROLES, "assigned_role")

    row = new_common_fields()
    row.update({
        "pod_id": pod_id,
        "staff_member_id": staff_member_id,
        "assigned_role": assigned_role,
        "start_time": start_time,
        "end_time": end_time,
        "status": "PENDING",
    })
    db.shift_assignments[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/shift-assignments/<shift_id>", methods=["GET"])
@require_role(*READ_ROLES)
def get_shift_assignment(shift_id):
    row = fetch_or_404(db.shift_assignments, shift_id, "ShiftAssignment")
    return success_object(strip_internal(row))


@bp.route("/shift-assignments", methods=["GET"])
@require_role(*LIST_ROLES)
def list_shift_assignments():
    limit, offset = parse_pagination(request.args)
    pod_id = request.args.get("pod_id")
    staff_member_id = request.args.get("staff_member_id")
    status = request.args.get("status")
    rows = list(db.shift_assignments.values())
    if pod_id:
        rows = [r for r in rows if r["pod_id"] == pod_id]
    if staff_member_id:
        rows = [r for r in rows if r["staff_member_id"] == staff_member_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/shift-assignments/<shift_id>/confirm", methods=["POST"])
@require_role("ClinicalLead", "PublicHealthAdmin")
def confirm_shift_assignment(shift_id):
    shift = fetch_or_404(db.shift_assignments, shift_id, "ShiftAssignment")
    if shift["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "ShiftAssignment must be PENDING to confirm.", 409)

    staff = fetch_or_404(db.staff_members, shift["staff_member_id"], "StaffMember")
    if staff["credential_status"] != "VERIFIED":
        raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED", "StaffMember credential is not VERIFIED.", 422)
    if not parse_iso8601(staff["credential_expires_at"]) > current_clock():
        raise ApiError("ERR_CREDENTIAL_EXPIRED", "StaffMember credential has expired.", 422)

    st = parse_iso8601(shift["start_time"])
    et = parse_iso8601(shift["end_time"])

    for other in db.shift_assignments.values():
        if other["id"] == shift_id:
            continue
        if other["staff_member_id"] != shift["staff_member_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        os_ = parse_iso8601(other["start_time"])
        oe_ = parse_iso8601(other["end_time"])
        if _intervals_overlap(st, et, os_, oe_):
            raise ApiError("ERR_SHIFT_OVERLAP", "Overlaps another CONFIRMED/CHECKED_IN shift for this staff member.", 409)

    pod = fetch_or_404(db.pods, shift["pod_id"], "POD")
    overlapping_count = 1  # this shift, hypothetically confirmed
    for other in db.shift_assignments.values():
        if other["id"] == shift_id:
            continue
        if other["pod_id"] != shift["pod_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        os_ = parse_iso8601(other["start_time"])
        oe_ = parse_iso8601(other["end_time"])
        if _intervals_overlap(st, et, os_, oe_):
            overlapping_count += 1
    if overlapping_count > pod["staffing_capacity_lanes"]:
        raise ApiError("ERR_POD_CAPACITY_EXCEEDED", "Confirming would exceed the POD's staffing_capacity_lanes.", 409)

    shift["status"] = "CONFIRMED"
    touch(shift)
    hours = shift_duration_hours(shift)
    pod_adjust_committed_hours(pod, hours)
    return success_object(strip_internal(shift))


@bp.route("/shift-assignments/<shift_id>/check_in", methods=["POST"])
@require_role("Volunteer", "ClinicalLead")
def check_in_shift_assignment(shift_id):
    shift = fetch_or_404(db.shift_assignments, shift_id, "ShiftAssignment")
    if g.user_role == "Volunteer" and g.user_id != shift["staff_member_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Volunteer may only check into their own assignment.", 403)
    if shift["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "ShiftAssignment must be CONFIRMED to check in.", 409)
    pod = fetch_or_404(db.pods, shift["pod_id"], "POD")
    if pod["operational_status"] not in ("STAGING", "OPERATIONAL", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE", "POD is not in a state that allows check-in.", 409)
    shift["status"] = "CHECKED_IN"
    touch(shift)
    return success_object(strip_internal(shift))


@bp.route("/shift-assignments/<shift_id>/check_out", methods=["POST"])
@require_role("ClinicalLead")
def check_out_shift_assignment(shift_id):
    shift = fetch_or_404(db.shift_assignments, shift_id, "ShiftAssignment")
    if shift["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "ShiftAssignment must be CHECKED_IN to check out.", 409)
    shift["status"] = "COMPLETED"
    touch(shift)
    return success_object(strip_internal(shift))


@bp.route("/shift-assignments/<shift_id>/cancel", methods=["POST"])
@require_role("Volunteer", "PublicHealthAdmin", "ClinicalLead")
def cancel_shift_assignment(shift_id):
    shift = fetch_or_404(db.shift_assignments, shift_id, "ShiftAssignment")
    if g.user_role == "Volunteer" and g.user_id != shift["staff_member_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Volunteer may only cancel their own assignment.", 403)
    if shift["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "ShiftAssignment must be PENDING or CONFIRMED to cancel.", 409)
    was_confirmed = shift["status"] == "CONFIRMED"
    shift["status"] = "CANCELLED"
    touch(shift)
    if was_confirmed:
        pod = db.pods.get(shift["pod_id"])
        if pod is not None:
            hours = shift_duration_hours(shift)
            pod_adjust_committed_hours(pod, -hours)
    return success_object(strip_internal(shift))
