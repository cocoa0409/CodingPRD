"""Shared state-transition machinery and multi-link cascades (PRD 2.8)."""
from datetime import timedelta

import calc
from core import (find, now, offering_of_session, touch, upd, where)

LOCK_WINDOW_HOURS = 24


# --------------------------------------------------------------------------
# Recomputation helpers
# --------------------------------------------------------------------------
def refresh_readiness(staff, force_zero=False):
    if force_zero:
        upd(staff, readiness_index=0)
        return
    if staff["duty_status"] == "SUSPENDED_FROM_DUTY":
        upd(staff, readiness_index=0)
        return
    upd(staff, readiness_index=calc.readiness_index(staff))


def refresh_asset_readiness(asset):
    upd(asset, readiness_status=calc.aed_readiness_status(asset))


def refresh_contract_aed_readiness(contract_id):
    for asset in where("asset", contract_id=contract_id):
        refresh_asset_readiness(asset)


def refresh_attainment(offering, provisional=True, final=True):
    if offering is None:
        return
    parts = calc.compute_attainment(offering)
    fields = {}
    if provisional:
        fields["provisional_attainment_pct"] = parts["provisional_attainment_pct"]
    if final:
        fields["final_attainment_pct"] = parts["final_attainment_pct"]
    upd(offering, **fields)


def refresh_penalty(contract):
    upd(contract, pending_penalty_cents=calc.coverage_penalty_cents(contract))


def bump_coverage_gap(offering):
    if offering is None:
        return
    upd(offering, coverage_gap_count=(offering.get("coverage_gap_count") or 0) + 1)


# --------------------------------------------------------------------------
# Assignment links
# --------------------------------------------------------------------------
def _decrement_committed(assignment):
    staff = find("staff", assignment["staff_member_id"])
    if staff is None:
        return
    committed = (staff.get("committed_minutes_current_period") or 0) - (
        assignment.get("paid_minutes") or 0)
    if committed < 0:
        committed = 0
    upd(staff, committed_minutes_current_period=committed)
    refresh_readiness(staff)


def has_live_lead(session):
    for assignment in where("assignment", session_id=session["id"]):
        if assignment["role_on_session"] == "LEAD" and \
                assignment["status"] in ("ASSIGNED", "CONFIRMED"):
            return True
    return False


def drop_session_to_at_risk(session):
    """A session loses its LEAD: SCHEDULED/STAFFED -> STAFFING_AT_RISK."""
    if session["status"] not in ("SCHEDULED", "STAFFED"):
        return False
    if has_live_lead(session):
        return False
    upd(session, status="STAFFING_AT_RISK")
    bump_coverage_gap(offering_of_session(session))
    return True


def release_assignment(assignment, cascade=True):
    prior = assignment["status"]
    if prior in ("ASSIGNED", "CONFIRMED"):
        _decrement_committed(assignment)
    upd(assignment, status="RELEASED")
    if cascade and prior in ("ASSIGNED", "CONFIRMED") and \
            assignment["role_on_session"] == "LEAD":
        session = find("session", assignment["session_id"])
        if session is not None:
            drop_session_to_at_risk(session)
    return prior


def vacate_assignment(assignment):
    if assignment["status"] in ("ASSIGNED", "CONFIRMED"):
        _decrement_committed(assignment)
    upd(assignment, status="VACANT_NEEDS_COVER")


# --------------------------------------------------------------------------
# Session cancellation
# --------------------------------------------------------------------------
CANCEL_BRANCH = {
    "NO_COVER": "CANCELLED_NO_COVER",
    "CLIENT_REQUEST": "CANCELLED_CLIENT",
    "FACILITY": "CANCELLED_FACILITY",
}


def cancel_session(session, reason):
    status = CANCEL_BRANCH[reason]
    upd(session, status=status, cancel_reason=reason)
    releasable = ("ASSIGNED", "CONFIRMED")
    if reason == "NO_COVER":
        releasable = ("ASSIGNED", "CONFIRMED", "VACANT_NEEDS_COVER")
    for assignment in where("assignment", session_id=session["id"]):
        if assignment["status"] in releasable:
            release_assignment(assignment, cascade=False)
    offering = offering_of_session(session)
    if reason == "NO_COVER" and offering is not None:
        contract = find("contract", offering["contract_id"])
        if contract is not None:
            upd(contract, uncovered_session_count=(
                contract.get("uncovered_session_count") or 0) + 1)
            refresh_penalty(contract)
    refresh_attainment(offering, provisional=True, final=False)


def open_sessions_of_offering(offering):
    rows = [s for s in where("session", offering_id=offering["id"])
            if s["status"] in calc.OPEN_SESSION_STATUSES]
    rows.sort(key=lambda r: (r["scheduled_start_utc"], r["created_at"], r["_seq"]))
    return rows


def in_lock_window(session):
    return session["scheduled_start_utc"] <= now() + timedelta(hours=LOCK_WINDOW_HOURS)


def sessions_of_room_in_lock_window(room):
    rows = []
    for offering in where("offering", contract_id=room["contract_id"]):
        for session in where("session", offering_id=offering["id"]):
            if session["room_id"] != room["id"]:
                continue
            if session["status"] not in calc.OPEN_SESSION_STATUSES:
                continue
            if in_lock_window(session):
                rows.append(session)
    rows.sort(key=lambda r: (r["scheduled_start_utc"], r["created_at"], r["_seq"]))
    return rows


def cancel_room_lock_window_sessions(room, reason="FACILITY"):
    count = 0
    for session in sessions_of_room_in_lock_window(room):
        cancel_session(session, reason)
        count += 1
    return count


# --------------------------------------------------------------------------
# Credential-driven staffing cascade (links 1-4)
# --------------------------------------------------------------------------
def bump(tally, key, amount=1):
    if tally is not None:
        tally[key] = tally.get(key, 0) + amount


def credential_suspension_cascade(staff, tally=None):
    """Link 1: suspend the holder; links 2-4: vacate, at-risk, lock-window cancel."""
    if staff["duty_status"] != "ACTIVE_DUTY":
        return
    upd(staff, duty_status="SUSPENDED_FROM_DUTY", readiness_index=0)
    bump(tally, "staff_suspended")
    rows = where("assignment", staff_member_id=staff["id"])
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    lead_sessions = []
    for assignment in rows:
        session = find("session", assignment["session_id"])
        if session is None or session["status"] not in calc.OPEN_SESSION_STATUSES:
            continue
        if assignment["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        was_lead = assignment["role_on_session"] == "LEAD"
        vacate_assignment(assignment)
        bump(tally, "assignments_vacated")
        if was_lead:
            lead_sessions.append(session)
    lead_sessions.sort(key=lambda r: (r["scheduled_start_utc"], r["created_at"], r["_seq"]))
    at_risk = []
    for session in lead_sessions:
        if drop_session_to_at_risk(session):
            bump(tally, "sessions_at_risk")
            at_risk.append(session)
    for session in at_risk:
        if session["status"] == "STAFFING_AT_RISK" and in_lock_window(session):
            cancel_session(session, "NO_COVER")
            bump(tally, "sessions_cancelled_no_cover")


# --------------------------------------------------------------------------
# Offering pause / resume
# --------------------------------------------------------------------------
def pause_offering(offering):
    upd(offering, status="PAUSED")
    for session in open_sessions_of_offering(offering):
        cancel_session(session, "CLIENT_REQUEST")
    refresh_attainment(offering, provisional=True, final=False)


# --------------------------------------------------------------------------
# Member eligibility / staff offboarding
# --------------------------------------------------------------------------
def set_eligibility(member, new_status):
    prior = member["eligibility_status"]
    if prior == new_status:
        return
    contract = find("contract", member["contract_id"])
    upd(member, eligibility_status=new_status)
    if contract is None:
        return
    count = contract.get("eligible_member_count") or 0
    if new_status == "ELIGIBLE" and prior != "ELIGIBLE":
        upd(contract, eligible_member_count=count + 1)
    elif prior == "ELIGIBLE" and new_status != "ELIGIBLE":
        upd(contract, eligible_member_count=max(0, count - 1))


def revoke_badge(member):
    if member["access_status"] == "ACTIVE":
        upd(member, access_status="REVOKED")
        return True
    return False


def revoke_waivers(member):
    changed = False
    for waiver in where("waiver", member_id=member["id"]):
        if waiver["status"] == "SIGNED":
            upd(waiver, status="REVOKED")
            changed = True
    if member.get("current_waiver_id") is not None:
        upd(member, current_waiver_id=None)
    return changed


def terminate_member(member):
    set_eligibility(member, "TERMINATED")
    revoke_badge(member)
    revoke_waivers(member)


def offboard_staff(staff):
    for assignment in where("assignment", staff_member_id=staff["id"]):
        if assignment["status"] in ("ASSIGNED", "CONFIRMED"):
            release_assignment(assignment, cascade=False)
    upd(staff, duty_status="OFFBOARDED", committed_minutes_current_period=0)
    upd(staff, readiness_index=calc.readiness_index(staff))


# --------------------------------------------------------------------------
# Contract-level cascades
# --------------------------------------------------------------------------
def active_offerings_ordered(contract_id):
    rows = [o for o in where("offering", contract_id=contract_id) if o["status"] == "ACTIVE"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def contract_stand_down(contract):
    """Links 1-3 of the suspension cascade plus the room lockdown (link 4)."""
    for offering in active_offerings_ordered(contract["id"]):
        pause_offering(offering)
    for room in where("room", contract_id=contract["id"]):
        upd(room, room_state="CLOSED")


def contract_resume(contract):
    rows = [o for o in where("offering", contract_id=contract["id"]) if o["status"] == "PAUSED"]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for offering in rows:
        upd(offering, status="ACTIVE")
        refresh_attainment(offering)
    for room in where("room", contract_id=contract["id"]):
        if room["room_state"] != "CLOSED":
            continue
        if (room.get("open_deficiency_count") or 0) == 0:
            upd(room, room_state="OPEN")
        else:
            upd(room, room_state="RESTRICTED")


def contract_open_rooms_on_approval(contract):
    for room in where("room", contract_id=contract["id"]):
        if room["room_state"] == "CLOSED" and (room.get("open_deficiency_count") or 0) == 0:
            upd(room, room_state="OPEN")


def contract_terminate_people(contract):
    for member in where("member", contract_id=contract["id"]):
        terminate_member(member)
    for staff in where("staff", contract_id=contract["id"]):
        offboard_staff(staff)


def has_open_invoices(contract_id):
    for invoice in where("invoice", contract_id=contract_id):
        if invoice["status"] in ("DRAFT", "DISPUTED"):
            return True
    return False


# --------------------------------------------------------------------------
# Incident equipment cascade
# --------------------------------------------------------------------------
def incident_equipment_cascade(incident):
    asset = find("asset", incident.get("asset_id"))
    if asset is None:
        return
    upd(asset, status="OUT_OF_SERVICE", out_of_service_since=now())
    refresh_asset_readiness(asset)
    room = find("room", asset.get("room_id"))
    if room is None:
        return
    if room["room_state"] == "OPEN":
        upd(room, room_state="RESTRICTED",
            open_deficiency_count=(room.get("open_deficiency_count") or 0) + 1)
    cancel_room_lock_window_sessions(room, "FACILITY")
