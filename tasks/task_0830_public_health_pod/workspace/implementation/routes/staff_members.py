from flask import Blueprint, request

from db import db
from errors import ApiError
from helpers import (
    fetch_or_404, get_json_body, new_common_fields, paginate,
    parse_pagination, require_fields, require_enum, require_type,
    sorted_by_created, strip_internal, touch,
)
from middleware import require_role
from response import success_array, success_object
from services import pod_set_operational_status, pod_adjust_committed_hours
from timeutil import current_clock, parse_iso8601

bp = Blueprint("staff_members", __name__)

PRIMARY_ROLES = {"CLINICAL_LEAD", "SCREENER", "VACCINATOR", "RUNNER", "TRAFFIC_CONTROL", "GREETER"}
CREDENTIAL_TYPES = {"RN_LICENSE", "MD_LICENSE", "EMT_CERT", "NIMS_IS100_700", "BACKGROUND_CHECK", "PODS_TRAINING"}
LIST_ROLES = ["PublicHealthAdmin", "LogisticsCoordinator", "ClinicalLead", "Volunteer"]


@bp.route("/staff-members", methods=["POST"])
@require_role("PublicHealthAdmin")
def create_staff_member():
    body = get_json_body()
    require_fields(body, ["full_name", "email", "primary_role", "mrc_unit", "credential_type", "credential_expires_at"])
    require_type(body["full_name"], str, "full_name")
    require_type(body["email"], str, "email")
    require_type(body["primary_role"], str, "primary_role")
    require_enum(body["primary_role"], PRIMARY_ROLES, "primary_role")
    require_type(body["mrc_unit"], str, "mrc_unit")
    require_type(body["credential_type"], str, "credential_type")
    require_enum(body["credential_type"], CREDENTIAL_TYPES, "credential_type")
    require_type(body["credential_expires_at"], str, "credential_expires_at")
    try:
        parse_iso8601(body["credential_expires_at"])
    except ValueError:
        raise ApiError("ERR_VALIDATION", "credential_expires_at must be a valid ISO8601 timestamp.", 400)
    if any(s["email"] == body["email"] for s in db.staff_members.values()):
        raise ApiError("ERR_VALIDATION", "email must be unique across StaffMember.", 400)

    row = new_common_fields()
    row.update({
        "full_name": body["full_name"],
        "email": body["email"],
        "primary_role": body["primary_role"],
        "mrc_unit": body["mrc_unit"],
        "credential_type": body["credential_type"],
        "credential_expires_at": body["credential_expires_at"],
        "credential_status": "PENDING",
    })
    db.staff_members[row["id"]] = row
    return success_object(strip_internal(row), 201)


@bp.route("/staff-members", methods=["GET"])
@require_role(*LIST_ROLES)
def list_staff_members():
    limit, offset = parse_pagination(request.args)
    mrc_unit = request.args.get("mrc_unit")
    primary_role = request.args.get("primary_role")
    credential_status = request.args.get("credential_status")
    rows = list(db.staff_members.values())
    if mrc_unit:
        rows = [r for r in rows if r["mrc_unit"] == mrc_unit]
    if primary_role:
        rows = [r for r in rows if r["primary_role"] == primary_role]
    if credential_status:
        rows = [r for r in rows if r["credential_status"] == credential_status]
    rows = sorted_by_created(rows)
    items, total = paginate(rows, limit, offset)
    return success_array(items, limit, offset, total)


@bp.route("/staff-members/<staff_id>/verify-credential", methods=["POST"])
@require_role("PublicHealthAdmin")
def verify_credential(staff_id):
    staff = fetch_or_404(db.staff_members, staff_id, "StaffMember")
    if staff["credential_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "StaffMember credential must be PENDING to verify.", 409)
    staff["credential_status"] = "VERIFIED"
    touch(staff)
    return success_object(strip_internal(staff))


@bp.route("/staff-members/<staff_id>/revoke-credential", methods=["POST"])
@require_role("PublicHealthAdmin")
def revoke_credential(staff_id):
    staff = fetch_or_404(db.staff_members, staff_id, "StaffMember")
    if staff["credential_status"] not in ("PENDING", "VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", "StaffMember credential must be PENDING or VERIFIED to revoke.", 409)
    staff["credential_status"] = "REVOKED"
    touch(staff)

    # Cascade B hop 1: auto-cancel every PENDING/CONFIRMED ShiftAssignment for this staff member.
    affected = [s for s in db.shift_assignments.values()
                if s["staff_member_id"] == staff_id and s["status"] in ("PENDING", "CONFIRMED")]
    for shift in affected:
        was_confirmed = shift["status"] == "CONFIRMED"
        shift["status"] = "CANCELLED"
        touch(shift)
        pod = db.pods.get(shift["pod_id"])
        if pod is None:
            continue
        if was_confirmed:
            hours = _shift_hours(shift)
            pod_adjust_committed_hours(pod, -hours)
        # Cascade B hop 2: if confirmed coverage for this role at this POD drops below 1
        # and the POD was OPERATIONAL, auto-restrict it.
        remaining_coverage = sum(
            1 for s in db.shift_assignments.values()
            if s["pod_id"] == pod["id"]
            and s["assigned_role"] == shift["assigned_role"]
            and s["status"] in ("CONFIRMED", "CHECKED_IN")
        )
        if remaining_coverage < 1 and pod["operational_status"] == "OPERATIONAL":
            pod_set_operational_status(pod, "RESTRICTED")

    return success_object(strip_internal(staff))


def _shift_hours(shift):
    from services import shift_duration_hours
    return shift_duration_hours(shift)
