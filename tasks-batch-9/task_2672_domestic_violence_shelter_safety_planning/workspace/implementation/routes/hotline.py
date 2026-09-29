"""HotlineCall, RiskAssessment and call-disposition endpoints."""

from flask import Blueprint

from db import clock_iso, db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_SHELTER_MANAGER,
                        acting_staff_id, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_call, get_client, get_shelter, insert,
                           list_page)
from services import calc, cascade, derive
from validation import (bad, date_out, get_body, opt_bool, q_enum, q_str, req_bool,
                        req_date, req_enum, req_int, req_str)

bp = Blueprint("hotline", __name__)

CALLER_TYPES = ("SURVIVOR", "FAMILY_MEMBER", "PROFESSIONAL_REFERRAL")
CALL_STATUSES = ("RECEIVED", "RISK_ASSESSED", "SCREENING_REFERRED", "SAFETY_PLAN_ONLY",
                 "RESOURCE_REFERRED")
DISPOSED_STATUSES = ("SCREENING_REFERRED", "SAFETY_PLAN_ONLY", "RESOURCE_REFERRED")
READ_ROLES = (ROLE_HOTLINE_ADVOCATE, ROLE_SHELTER_MANAGER, ROLE_AGENCY_ADMIN)


@bp.post("/hotline-calls")
def create_call():
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    body = get_body()
    client_id = req_str(body, "client_id")
    caller_type = req_enum(body, "caller_type", CALLER_TYPES)
    presenting_concerns = req_str(body, "presenting_concerns", 1, 2000)
    client = get_client(client_id)

    call = insert("hotline_calls", {
        "client_id": client["id"],
        "taken_by_staff_id": acting_staff_id(user_id, role),
        "caller_type": caller_type,
        "presenting_concerns": presenting_concerns,
        "received_at_utc": clock_iso(),
        "status": "RECEIVED",
        "disposed_at": None,
    })
    return created(public(call))


@bp.get("/hotline-calls/<call_id>")
def read_call(call_id):
    auth(READ_ROLES)
    return ok(public(get_call(call_id)))


@bp.get("/hotline-calls")
def list_calls():
    auth(READ_ROLES)
    filters = {
        "client_id": q_str("client_id"),
        "taken_by_staff_id": q_str("taken_by_staff_id"),
        "status": q_enum("status", CALL_STATUSES),
    }
    return list_page(by_created(filtered("hotline_calls", filters)))


# --------------------------------------------------------------------------
# risk assessments
# --------------------------------------------------------------------------

def _corroborating_fact_count(client_id, call_id):
    count = 0
    if any(c["status"] in ("FILED", "GRANTED")
           for c in derive.where("protective_order_cases", client_id=client_id)):
        count += 1
    if any(a["occupancy_status"] in ("CHECKED_IN", "EXITED")
           for a in derive.where("shelter_admissions", client_id=client_id)):
        count += 1
    others = [c for c in derive.where("hotline_calls", client_id=client_id)
              if c["id"] != call_id and c["status"] in DISPOSED_STATUSES]
    if len(others) >= 2:
        count += 1
    return count


@bp.post("/hotline-calls/<call_id>/risk-assessments")
def create_assessment(call_id):
    auth((ROLE_HOTLINE_ADVOCATE,))
    body = get_body()
    weapon_access = req_bool(body, "weapon_access")
    strangulation_history = req_bool(body, "strangulation_history")
    separation_recent = req_bool(body, "separation_recent")
    threats_to_kill = req_bool(body, "threats_to_kill")
    stalking = req_int(body, "stalking_frequency_per_week", 0, 40)
    corroborate = opt_bool(body, "corroborate_with_history", False)
    call = get_call(call_id)

    if call["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a risk assessment is only accepted for a RECEIVED call")

    client = get_client(call["client_id"])
    facts = _corroborating_fact_count(client["id"], call["id"]) if corroborate else 0
    variant, fact_count, base_subtotal, multiplier, score, band = calc.lethality_danger_score(
        weapon_access, strangulation_history, separation_recent, threats_to_kill,
        stalking, corroborate, facts)

    assessment = insert("risk_assessments", {
        "hotline_call_id": call["id"],
        "weapon_access": weapon_access,
        "strangulation_history": strangulation_history,
        "separation_recent": separation_recent,
        "threats_to_kill": threats_to_kill,
        "stalking_frequency_per_week": stalking,
        "corroborate_with_history": corroborate,
        "variant_applied": variant,
        "corroborating_fact_count": fact_count,
        "base_subtotal": base_subtotal,
        "escalation_multiplier": multiplier,
        "danger_score": score,
        "risk_band": band,
    }, audited=False)

    call["status"] = "RISK_ASSESSED"
    touch(call)
    touch(client)
    derive.refresh_client_risk(client)
    return created(public(assessment))


@bp.get("/hotline-calls/<call_id>/risk-assessments")
def list_assessments(call_id):
    auth(READ_ROLES)
    call = get_call(call_id)
    rows = by_created(filtered("risk_assessments", {"hotline_call_id": call["id"]}))
    return list_page(rows)


# --------------------------------------------------------------------------
# disposition
# --------------------------------------------------------------------------

@bp.post("/hotline-calls/<call_id>/dispose")
def dispose_call(call_id):
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    body = get_body()
    disposition = req_enum(body, "disposition", DISPOSED_STATUSES)
    shelter_id = None
    entry_date = None
    if disposition == "SCREENING_REFERRED":
        shelter_id = req_str(body, "requested_shelter_id")
        entry_date = req_date(body, "requested_entry_date")

    call = get_call(call_id)
    shelter = get_shelter(shelter_id) if shelter_id is not None else None

    if call["status"] != "RISK_ASSESSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a RISK_ASSESSED call may be disposed")

    client = get_client(call["client_id"])
    if disposition == "RESOURCE_REFERRED" and client["current_risk_band"] == "IMMINENT":
        raise ApiError("ERR_IMMINENT_RISK_REFERRAL_FORBIDDEN")

    call["status"] = disposition
    call["disposed_at"] = clock_iso()
    touch(call)

    if client["status"] == "INTAKE":
        client["status"] = "ACTIVE"
    touch(client)

    if disposition == "SCREENING_REFERRED":
        insert("screening_requests", {
            "client_id": client["id"],
            "hotline_call_id": call["id"],
            "requested_shelter_id": shelter["id"],
            "created_by_staff_id": acting_staff_id(user_id, role),
            "assigned_advocate_id": None,
            "offered_shelter_unit_id": None,
            "household_size": client["household_size"],
            "minor_children_count": client["minor_children_count"],
            "accessibility_required": client["accessibility_required"],
            "requested_entry_date": date_out(entry_date),
            "status": "PENDING",
            "waitlist_position": None,
            "promoted_from_waitlist": False,
            "denial_reason": None,
            "decided_at": None,
        })
    elif disposition == "SAFETY_PLAN_ONLY":
        latest = derive.newest(derive.where("risk_assessments", hotline_call_id=call["id"]))
        plan = insert("safety_plans", {
            "client_id": client["id"],
            "based_on_risk_assessment_id": latest["id"] if latest else None,
            "authored_by_staff_id": acting_staff_id(user_id, role),
            "superseded_by_plan_id": None,
            "status": "DRAFT",
            "coverage_score": 0.0,
            "revision_count": 0,
            "archived_at": None,
        })
        if cascade.archive_live_plans(client, plan):
            cascade.reject_open_referrals(client)
    else:
        derive.refresh_resource_referral_count(client)

    return ok(public(call))
