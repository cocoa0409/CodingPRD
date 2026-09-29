"""Member, LiabilityWaiver and ParticipationRecord endpoints (PRD 3.6 / 3.7)."""
from flask import Blueprint, g

import calc
import cascades
from core import (ApiError, ROLE_CLIENT_SPONSOR, ROLE_FITNESS_STAFF, ROLE_MEMBER,
                 ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER, bad_request, body, created, find,
                 get_or_404, new_record, now, ok, opt_bool, opt_str, req_bool, req_date,
                 req_enum, req_int, req_str, require, scope_contract, scope_member, today,
                 to_date, upd, view, where)
from guards import invalid_transition, terminal

bp = Blueprint("members", __name__)

MEMBER_CLASSES = ("EMPLOYEE", "DEPENDENT", "RETIREE")


# --------------------------------------------------------------------------
# Waiver helpers
# --------------------------------------------------------------------------
def live_waiver(member):
    """A SIGNED waiver whose expires_on is at or after today."""
    for waiver in where("waiver", member_id=member["id"]):
        if waiver["status"] != "SIGNED":
            continue
        expires = to_date(waiver["expires_on"])
        if expires is not None and expires >= today():
            return waiver
    return None


def _sponsor_ok(member):
    if member["member_class"] != "DEPENDENT":
        return True
    sponsor = find("member", member.get("sponsor_member_id"))
    if sponsor is None:
        return False
    return sponsor["member_class"] == "EMPLOYEE" and sponsor["eligibility_status"] == "ELIGIBLE"


def _dependents_of(member):
    rows = where("member", sponsor_member_id=member["id"])
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


# --------------------------------------------------------------------------
# Enrolment
# --------------------------------------------------------------------------
@bp.post("/members")
def enrol_member():
    require(ROLE_CLIENT_SPONSOR, ROLE_OPERATOR_ADMIN)
    data = body()
    contract_id = req_str(data, "contract_id")
    scope_contract(contract_id)
    member_class = req_enum(data, "member_class", MEMBER_CLASSES)
    full_name = req_str(data, "full_name", 1, 200)
    employee_number = opt_str(data, "employee_number", 1, 80)
    sponsor_member_id = opt_str(data, "sponsor_member_id", 1)
    health_data_consent = opt_bool(data, "health_data_consent", default=False)
    if member_class == "EMPLOYEE":
        if employee_number is None:
            raise bad_request("employee_number is required for an EMPLOYEE")
    elif employee_number is not None:
        raise bad_request("employee_number must be null for this member_class")
    get_or_404("contract", contract_id)
    if member_class == "DEPENDENT":
        if sponsor_member_id is None:
            raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", 422)
        sponsor = find("member", sponsor_member_id)
        if sponsor is None or sponsor["member_class"] != "EMPLOYEE" or \
                sponsor["eligibility_status"] != "ELIGIBLE":
            raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", 422)
    elif sponsor_member_id is not None:
        raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", 422)
    member = new_record("member", {
        "contract_id": contract_id,
        "sponsor_member_id": sponsor_member_id,
        "member_class": member_class,
        "full_name": full_name,
        "employee_number": employee_number,
        "eligibility_status": "PENDING_VERIFICATION",
        "access_status": "NO_BADGE",
        "health_data_consent": health_data_consent,
        "incentive_points_balance": 0,
        "current_waiver_id": None,
        "last_check_in_utc": None,
    })
    return created(view(member))


# --------------------------------------------------------------------------
# Eligibility decisions
# --------------------------------------------------------------------------
def _lapse(member):
    cascades.set_eligibility(member, "LAPSED")
    cascades.revoke_badge(member)
    if member["member_class"] == "EMPLOYEE":
        for dependent in _dependents_of(member):
            if dependent["eligibility_status"] == "ELIGIBLE":
                cascades.set_eligibility(dependent, "LAPSED")
                cascades.revoke_badge(dependent)


def _terminate(member):
    cascades.terminate_member(member)
    for dependent in _dependents_of(member):
        if dependent["eligibility_status"] != "TERMINATED":
            _terminate(dependent)


@bp.post("/members/<mid>/eligibility-decisions")
def eligibility_decision(mid):
    require(ROLE_CLIENT_SPONSOR, ROLE_OPERATOR_ADMIN)
    member = get_or_404("member", mid)
    scope_contract(member["contract_id"])
    data = body()
    action = req_enum(data, "action", ("VERIFY", "LAPSE", "REINSTATE", "TERMINATE"))
    opt_str(data, "reason", 1, 500)
    terminal(member["eligibility_status"] == "TERMINATED")
    contract = find("contract", member["contract_id"])
    status = member["eligibility_status"]
    if action == "VERIFY":
        if status != "PENDING_VERIFICATION":
            invalid_transition()
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
        if not _sponsor_ok(member):
            raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", 422)
        cascades.set_eligibility(member, "ELIGIBLE")
    elif action == "LAPSE":
        if status != "ELIGIBLE":
            invalid_transition()
        _lapse(member)
    elif action == "REINSTATE":
        if status != "LAPSED":
            invalid_transition()
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
        if not _sponsor_ok(member):
            raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", 422)
        cascades.set_eligibility(member, "ELIGIBLE")
    else:
        if status not in ("PENDING_VERIFICATION", "ELIGIBLE", "LAPSED"):
            invalid_transition()
        _terminate(member)
    return ok(view(member))


# --------------------------------------------------------------------------
# Badge access
# --------------------------------------------------------------------------
@bp.post("/members/<mid>/badge-access")
def badge_access(mid):
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    member = get_or_404("member", mid)
    scope_contract(member["contract_id"])
    data = body()
    action = req_enum(data, "action", ("GRANT", "REVOKE"))
    opt_str(data, "badge_number", 1, 80)
    if action == "GRANT":
        if member["access_status"] not in ("NO_BADGE", "REVOKED"):
            invalid_transition()
        if live_waiver(member) is None:
            raise ApiError("ERR_WAIVER_REQUIRED", 422)
        if member["eligibility_status"] != "ELIGIBLE":
            raise ApiError("ERR_ELIGIBILITY_NOT_VERIFIED", 422)
        upd(member, access_status="ACTIVE")
    else:
        if member["access_status"] != "ACTIVE":
            invalid_transition()
        upd(member, access_status="REVOKED")
    return ok(view(member))


# --------------------------------------------------------------------------
# Liability waivers
# --------------------------------------------------------------------------
@bp.post("/members/<mid>/waivers")
def file_waiver(mid):
    require(ROLE_MEMBER, ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    member = get_or_404("member", mid)
    scope_member(member)
    data = body()
    waiver_version_code = req_str(data, "waiver_version_code", 1, 60)
    expires_on = req_date(data, "expires_on")
    acknowledged = req_bool(data, "acknowledged_health_disclosure")
    expected_member_version = req_int(data, "expected_member_version", minimum=1)
    if not acknowledged:
        raise bad_request("acknowledged_health_disclosure must be true")
    if to_date(expires_on) <= today():
        raise bad_request("expires_on must be strictly later than the signing date")
    if expected_member_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION", 412)
    waiver = new_record("waiver", {
        "member_id": member["id"],
        "waiver_version_code": waiver_version_code,
        "expires_on": expires_on,
        "acknowledged_health_disclosure": True,
        "signed_at": now(),
        "status": "SIGNED",
    })
    for prior in where("waiver", member_id=member["id"]):
        if prior["id"] != waiver["id"] and prior["status"] == "SIGNED":
            upd(prior, status="SUPERSEDED")
    upd(member, current_waiver_id=waiver["id"])
    return created(view(waiver))


# --------------------------------------------------------------------------
# Participation capture
# --------------------------------------------------------------------------
@bp.post("/participation-records")
def check_in():
    require(ROLE_FITNESS_STAFF, ROLE_SITE_MANAGER, ROLE_MEMBER)
    data = body()
    raw_member_id = data.get("member_id")
    if g.role == ROLE_MEMBER and isinstance(raw_member_id, str) and \
            raw_member_id != g.user_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    member_id = req_str(data, "member_id")
    session_id = req_str(data, "session_id")
    health_metrics_note = opt_str(data, "health_metrics_note", 1, 2000)
    if g.role == ROLE_MEMBER and member_id != g.user_id:
        raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    peek = find("member", member_id)
    if health_metrics_note is not None and peek is not None and \
            not peek.get("health_data_consent"):
        raise ApiError("ERR_HEALTH_DATA_FORBIDDEN", 403)
    member = get_or_404("member", member_id)
    session = get_or_404("session", session_id)
    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_NOT_IN_PROGRESS", 409)
    if live_waiver(member) is None:
        raise ApiError("ERR_WAIVER_REQUIRED", 422)
    offering = find("offering", session["offering_id"])
    if offering is not None and member["contract_id"] != offering["contract_id"]:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    counted = [p for p in where("participation", session_id=session["id"])
               if p["status"] == "COUNTED"]
    if offering is not None and len(counted) >= offering["max_participants_per_session"]:
        raise ApiError("ERR_SESSION_CAPACITY_EXCEEDED", 409)
    if offering is not None and member["member_class"] not in \
            (offering.get("eligible_member_classes") or []):
        raise ApiError("ERR_MEMBER_CLASS_NOT_ELIGIBLE", 422)
    if member["access_status"] != "ACTIVE" or member["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_ACCESS_NOT_ACTIVE", 422)
    for existing in counted:
        if existing["member_id"] == member["id"]:
            raise ApiError("ERR_DUPLICATE_CHECK_IN", 409)
    award = calc.incentive_award(member["id"])
    record = new_record("participation", {
        "member_id": member["id"],
        "session_id": session["id"],
        "check_in_utc": now(),
        "points_awarded": award["points_awarded"],
        "points_capped": award["points_capped"],
        "streak_bonus_applied": award["streak_bonus_applied"],
        "recorded_by_role": "MEMBER" if g.role == ROLE_MEMBER else "FITNESS_STAFF",
        "health_metrics_note": health_metrics_note,
        "status": "COUNTED",
        "void_reason": None,
    }, versioned=False)
    upd(member,
        incentive_points_balance=(member.get("incentive_points_balance") or 0)
        + award["points_awarded"],
        last_check_in_utc=now())
    upd(session, actual_attendance=(session.get("actual_attendance") or 0) + 1)
    if offering is not None:
        upd(offering, counted_participation_total=(
            offering.get("counted_participation_total") or 0) + 1)
        cascades.refresh_attainment(offering, provisional=True, final=True)
    return created(view(record))


@bp.post("/participation-records/<pid>/void")
def void_participation(pid):
    require(ROLE_SITE_MANAGER)
    record = get_or_404("participation", pid)
    data = body()
    void_reason = req_str(data, "void_reason", 1, 500)
    terminal(record["status"] == "VOIDED")
    session = find("session", record["session_id"])
    allowed = ("IN_PROGRESS", "COMPLETED", "CANCELLED_NO_COVER", "CANCELLED_CLIENT",
               "CANCELLED_FACILITY")
    if session is None or session["status"] not in allowed:
        invalid_transition()
    record["status"] = "VOIDED"
    record["void_reason"] = void_reason
    member = find("member", record["member_id"])
    if member is not None:
        balance = (member.get("incentive_points_balance") or 0) - (
            record.get("points_awarded") or 0)
        upd(member, incentive_points_balance=max(0, balance))
    upd(session, actual_attendance=max(0, (session.get("actual_attendance") or 0) - 1))
    offering = find("offering", session["offering_id"])
    if offering is not None:
        upd(offering, counted_participation_total=max(0, (
            offering.get("counted_participation_total") or 0) - 1))
        cascades.refresh_attainment(offering, provisional=True, final=True)
    return ok(view(record))
