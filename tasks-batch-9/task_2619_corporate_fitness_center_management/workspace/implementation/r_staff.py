"""StaffMember and StaffCredential endpoints (PRD 3.2)."""
from flask import Blueprint, g

import calc
import cascades
from core import (ApiError, ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, body, created,
                 credentials_of_staff, get_or_404, new_record, now, ok, opt_str, req_date,
                 req_enum, req_int, req_str, require, today, to_date, upd, view)

bp = Blueprint("staff", __name__)

ROLE_TYPES = ("SITE_MANAGER", "GROUP_EX_INSTRUCTOR", "PERSONAL_TRAINER", "WELLNESS_COORDINATOR")
EMPLOYMENT_TYPES = ("OPERATOR_EMPLOYED", "CLIENT_EMPLOYED")
CREDENTIAL_TYPES = ("CPR_AED", "FIRST_AID", "GROUP_EX_CERT", "PT_CERT")


@bp.post("/staff-members")
def hire_staff():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    data = body()
    contract_id = req_str(data, "contract_id")
    full_name = req_str(data, "full_name", 1, 200)
    role_type = req_enum(data, "role_type", ROLE_TYPES)
    employment_type = req_enum(data, "employment_type", EMPLOYMENT_TYPES)
    hourly_cost_cents = req_int(data, "hourly_cost_cents", minimum=1)
    get_or_404("contract", contract_id)
    staff = new_record("staff", {
        "contract_id": contract_id,
        "full_name": full_name,
        "role_type": role_type,
        "employment_type": employment_type,
        "hourly_cost_cents": hourly_cost_cents,
        "duty_status": "ACTIVE_DUTY",
        "readiness_index": 0,
        "last_drill_on": None,
        "committed_minutes_current_period": 0,
        "required_credential_types": list(calc.REQUIRED_CREDENTIALS[role_type]),
    })
    staff["readiness_index"] = calc.readiness_index(staff)
    return created(view(staff))


@bp.post("/staff-members/<sid>/drills")
def record_drill(sid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    staff = get_or_404("staff", sid)
    data = body()
    drill_on = req_date(data, "drill_on")
    opt_str(data, "drill_type", 1, 60)
    if staff["duty_status"] == "OFFBOARDED":
        raise ApiError("ERR_TERMINAL_STATE", 409)
    upd(staff, last_drill_on=drill_on)
    cascades.refresh_readiness(staff)
    # PRD 4: recording a drill brings no new record into existence -- it updates
    # the staff member, so the updated record is returned with 200.
    return ok(view(staff))


@bp.post("/staff-members/<sid>/duty-reinstate")
def duty_reinstate(sid):
    require(ROLE_OPERATOR_ADMIN)
    staff = get_or_404("staff", sid)
    body()
    if staff["duty_status"] == "OFFBOARDED":
        raise ApiError("ERR_TERMINAL_STATE", 409)
    if staff["duty_status"] != "SUSPENDED_FROM_DUTY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    for credential_type in staff.get("required_credential_types") or []:
        if not calc.holds_live_credential(staff["id"], credential_type):
            raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED", 422)
    upd(staff, duty_status="ACTIVE_DUTY")
    cascades.refresh_readiness(staff)
    return ok(view(staff))


@bp.post("/staff-credentials")
def file_credential():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    data = body()
    staff_member_id = req_str(data, "staff_member_id")
    credential_type = req_enum(data, "credential_type", CREDENTIAL_TYPES)
    issuer = req_str(data, "issuer", 1, 200)
    credential_number = req_str(data, "credential_number", 1, 120)
    expires_on = req_date(data, "expires_on")
    staff = get_or_404("staff", staff_member_id)
    credential = new_record("credential", {
        "staff_member_id": staff_member_id,
        "credential_type": credential_type,
        "issuer": issuer,
        "credential_number": credential_number,
        "expires_on": expires_on,
        "status": "PENDING_VERIFICATION",
        "verified_at": None,
        "verified_by_user_id": None,
        "rejection_reason": None,
        "renewal_count": 0,
    })
    cascades.refresh_readiness(staff)
    return created(view(credential))


@bp.post("/staff-credentials/<cid>/verify")
def verify_credential(cid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    credential = get_or_404("credential", cid)
    if g.user_id == credential["staff_member_id"]:
        raise ApiError("ERR_SELF_VERIFICATION_FORBIDDEN", 403)
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    rejection_reason = data.get("rejection_reason")
    if credential["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_CREDENTIAL_NOT_PENDING", 409)
    staff = get_or_404("staff", credential["staff_member_id"])
    if decision == "ACCEPT":
        if to_date(credential["expires_on"]) <= today():
            raise ApiError("ERR_CREDENTIAL_EXPIRED_ON_FILE", 422)
        upd(credential, status="VERIFIED", verified_at=now(),
            verified_by_user_id=g.user_id, rejection_reason=None)
        if staff["duty_status"] == "SUSPENDED_FROM_DUTY":
            all_live = True
            for credential_type in staff.get("required_credential_types") or []:
                if not calc.holds_live_credential(staff["id"], credential_type):
                    all_live = False
                    break
            if all_live:
                upd(staff, duty_status="ACTIVE_DUTY")
        cascades.refresh_readiness(staff)
    else:
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            raise ApiError("ERR_REJECTION_REASON_REQUIRED", 422)
        upd(credential, status="REJECTED", rejection_reason=rejection_reason)
        required = staff.get("required_credential_types") or []
        if credential["credential_type"] in required and staff["duty_status"] == "ACTIVE_DUTY":
            # PRD 3.2: the holder is suspended and the index collapses to 0; the
            # assignment/session consequences are applied by the nightly sweep.
            upd(staff, duty_status="SUSPENDED_FROM_DUTY", readiness_index=0)
        else:
            cascades.refresh_readiness(staff)
    return ok(view(credential))


@bp.post("/staff-credentials/<cid>/renew")
def renew_credential(cid):
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    credential = get_or_404("credential", cid)
    data = body()
    credential_number = req_str(data, "credential_number", 1, 120)
    expires_on = req_date(data, "expires_on")
    if credential["status"] not in ("EXPIRED", "REJECTED"):
        raise ApiError("ERR_CREDENTIAL_NOT_RENEWABLE", 409)
    if to_date(expires_on) <= today():
        raise ApiError("ERR_RENEWAL_DATE_INVALID", 422)
    upd(credential, status="PENDING_VERIFICATION", credential_number=credential_number,
        expires_on=expires_on, verified_at=None, verified_by_user_id=None,
        rejection_reason=None,
        renewal_count=(credential.get("renewal_count") or 0) + 1)
    staff = get_or_404("staff", credential["staff_member_id"])
    cascades.refresh_readiness(staff)
    return ok(view(credential))
