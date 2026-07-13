"""988 Crisis Line & Mobile Crisis Dispatch API — Flask implementation.

Every behavioural rule traces to PRD.md (sections cited inline). Storage is
purely in-memory and starts empty on every boot; nothing is seeded.
"""

import os
import uuid
import secrets
from decimal import Decimal
from datetime import datetime, timezone

from flask import Flask, request, jsonify

import store
from store import (
    get_now, set_now, next_seq, new_id, parse_dt, iso, add_minutes, delta_ms,
    round_half_up, mutate, serialize,
)

app = Flask(__name__)

# ===========================================================================
# Constants
# ===========================================================================
ROLES = {"CrisisCounselor", "CrisisDispatcher", "ClinicalSupervisor"}
CC = "CrisisCounselor"
CD = "CrisisDispatcher"
CS = "ClinicalSupervisor"

CHANNELS = {"PHONE", "CHAT", "TEXT"}
SCREENING_TYPES = {"PROVISIONAL", "COMPREHENSIVE"}
ACUITIES = {"LOW", "MODERATE", "HIGH", "IMMINENT"}
CONTACT_STATUSES = {"INTAKE", "SCREENED", "DE_ESCALATION", "DISPATCH_PENDING",
                    "REFERRAL_PENDING", "EMERGENCY_911", "RESOLVED", "CLOSED"}
TEAM_STATUSES = {"ON_SHIFT", "OFF_SHIFT"}
DISPATCH_STATUSES = {"REQUESTED", "EN_ROUTE", "ON_SCENE", "COMPLETED", "CANCELLED"}
CENTER_STATUSES = {"ONLINE", "DIVERTED"}
REFERRAL_STATUSES = {"HELD", "ADMITTED", "DISCHARGED", "VOIDED"}
SAFETY_STATUSES = {"DRAFT", "ACTIVE", "ARCHIVED"}
OUTCOMES = {"REACHED", "NO_ANSWER"}

# Risk-screening score (PRD 3.2)
IDEATION_WEIGHT = 3
PLAN_WEIGHT = 4
MEANS_POINTS = 5
PRIOR_WEIGHT = 2
PRIOR_CAP = 3
PROTECTIVE_WEIGHT = 2
PROTECTIVE_CAP = 3
IMMINENT_THRESHOLD = 20
HIGH_THRESHOLD = 12
MODERATE_THRESHOLD = 6

# Dispatch priority score (PRD 3.5)
BAND_WEIGHT = {"IMMINENT": 100, "HIGH": 60, "MODERATE": 30, "LOW": 10}
WAIT_STEP_MINUTES = 10
WAIT_STEP_POINTS = 4
WAIT_STEP_CAP = 5
REPEAT_BONUS = 15

REPEAT_FLAG_THRESHOLD = 3
FOLLOWUP_DELAY_MINUTES = 1440
TEAM_TURNAROUND_MINUTES = 15
MAX_ATTEMPTS_DEFAULT = 3

MIN_DT = datetime(1, 1, 1, tzinfo=timezone.utc)


# ===========================================================================
# Error handling & response envelope (PRD 2.2)
# ===========================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    meta = _meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Unknown route"}}
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(err):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}
    return jsonify(body), 405


# ===========================================================================
# Auth (PRD 2.1)
# ===========================================================================
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


# ===========================================================================
# Body / validation helpers (PRD 2.8)
# ===========================================================================
def get_body():
    j = request.get_json(silent=True)
    return j if isinstance(j, dict) else {}


def require(body, key):
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", 422, "Missing required field: " + key)
    return body[key]


def require_str(body, key):
    v = require(body, key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, "Field must be a non-empty string: " + key)
    return v


def require_int(body, key):
    v = require(body, key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, "Field must be an integer: " + key)
    return v


def require_bool(body, key):
    v = require(body, key)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 422, "Field must be a boolean: " + key)
    return v


def require_list(body, key):
    v = require(body, key)
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 422, "Field must be a list: " + key)
    return v


def require_dt(body, key):
    v = require(body, key)
    try:
        return parse_dt(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Field must be a datetime: " + key)


def opt_dt(body, key):
    if key not in body or body[key] is None:
        return None
    try:
        return parse_dt(body[key])
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "Field must be a datetime: " + key)


def check_enum(value, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, "Value not in allowed set: " + str(value))
    return value


def check_window(start, end):
    if end <= start:
        raise ApiError("ERR_WINDOW_INVALID", 422, "window_end must be strictly after window_start")


def check_fk(body, key, table, err_id):
    """Existence check for a body FK. Absent -> defer (returns None)."""
    if key not in body or body[key] is None:
        return None
    val = body[key]
    if not isinstance(val, str) or val not in table:
        raise ApiError(err_id, 404, key + " not found")
    return table[val]


def path_lookup(table, ident, err_id):
    row = table.get(ident)
    if row is None:
        raise ApiError(err_id, 404, "resource not found")
    return row


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            offset = 0
    if offset < 0:
        offset = 0
    return limit, offset


def matches(row, spec):
    for key, val in spec.items():
        if val is None:
            continue
        rv = row.get(key)
        if key == "high_risk_flag":
            want = str(val).lower() == "true"
            if bool(rv) != want:
                return False
        else:
            if str(rv) != str(val):
                return False
    return True


def paged_list(rows, spec):
    items = [r for r in rows if matches(r, spec)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return ok_list([serialize(x) for x in page], limit, offset, total)


# ===========================================================================
# Ledger recomputation (PRD 2.9) — always derived from underlying rows
# ===========================================================================
def recompute_center(center):
    cid = center["id"]
    held = sum(1 for r in store.referrals.values()
               if r["crisis_center_id"] == cid and r["status"] == "HELD")
    occ = sum(1 for r in store.referrals.values()
              if r["crisis_center_id"] == cid and r["status"] == "ADMITTED")
    mutate(center, held_beds=held, occupied_beds=occ,
           available_beds=center["bed_capacity"] - held - occ)


def recompute_team(team):
    tid = team["id"]
    active = sum(1 for d in store.dispatches.values()
                 if d["team_id"] == tid and d["status"] in ("REQUESTED", "EN_ROUTE", "ON_SCENE"))
    mutate(team, active_dispatch_count=active)


def recompute_repeat_caller(caller_key):
    rc = store.repeat_callers.get(caller_key)
    if rc is None:
        return
    cs = [c for c in store.contacts.values() if c["caller_key"] == caller_key]
    count = len(cs)
    screened = [c for c in cs if c.get("risk_band") is not None]
    last = None
    if screened:
        best = max(screened, key=lambda c: (c["created_at"],
                                            c["disposition_at"] or MIN_DT,
                                            c["id"]))
        last = best["risk_band"]
    flag = (count >= REPEAT_FLAG_THRESHOLD) or (last == "IMMINENT")
    mutate(rc, contact_count=count, last_risk_band=last, high_risk_flag=flag)


# ===========================================================================
# Calculations
# ===========================================================================
def compute_risk_score(screening_type, ideation, plan, means, prior, protective):
    raw = (min(ideation, 3) * IDEATION_WEIGHT
           + min(plan, 3) * PLAN_WEIGHT
           + (MEANS_POINTS if means else 0)
           + min(prior, PRIOR_CAP) * PRIOR_WEIGHT)
    if screening_type == "COMPREHENSIVE":
        raw -= min(protective, PROTECTIVE_CAP) * PROTECTIVE_WEIGHT
    score = max(raw, 0)
    if score >= IMMINENT_THRESHOLD:
        band = "IMMINENT"
    elif score >= HIGH_THRESHOLD:
        band = "HIGH"
    elif score >= MODERATE_THRESHOLD:
        band = "MODERATE"
    else:
        band = "LOW"
    return score, band


def dispatch_priority(band, ref_now, contact):
    band_weight = BAND_WEIGHT[band]
    wait_minutes = delta_ms(ref_now, contact["created_at"]) // 60000
    steps = wait_minutes // WAIT_STEP_MINUTES
    if steps > WAIT_STEP_CAP:
        steps = WAIT_STEP_CAP
    if steps < 0:
        steps = 0
    wait_penalty = steps * WAIT_STEP_POINTS
    rc = store.repeat_callers.get(contact["caller_key"])
    repeat_bonus = REPEAT_BONUS if (rc and rc["high_risk_flag"]) else 0
    return band_weight + wait_penalty + repeat_bonus


# ===========================================================================
# Shared side-effect helpers
# ===========================================================================
def create_followup(contact):
    now = get_now()
    fid = new_id()
    task = {
        "id": fid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "contact_id": contact["id"],
        "scheduled_at": add_minutes(now, FOLLOWUP_DELAY_MINUTES),
        "channel": contact["channel"],
        "outcome": None,
        "attempt_count": 0,
        "max_attempts": MAX_ATTEMPTS_DEFAULT,
        "status": "SCHEDULED",
    }
    store.followups[fid] = task
    return task


def resolve_contact(contact):
    mutate(contact, status="RESOLVED")
    create_followup(contact)


def create_emergency(contact, role):
    eid = new_id()
    now = get_now()
    rec = {
        "id": eid, "created_at": now, "_seq": next_seq(),
        "contact_id": contact["id"],
        "psap_reference": "psap_" + uuid.uuid4().hex[:16],
        "risk_band_at_escalation": contact["risk_band"],
        "initiated_by_role": role,
    }
    store.emergencies[eid] = rec
    return rec


def void_referral(referral, allow_contact_revert=True):
    mutate(referral, status="VOIDED")
    center = store.centers.get(referral["crisis_center_id"])
    if center:
        recompute_center(center)
    if allow_contact_revert:
        c = store.contacts.get(referral["contact_id"])
        if c and c["status"] == "REFERRAL_PENDING":
            mutate(c, status="DISPATCH_PENDING")


def cancel_dispatch(dispatch, allow_referral_revert=True):
    mutate(dispatch, status="CANCELLED")
    team = store.teams.get(dispatch["team_id"])
    if team:
        recompute_team(team)
    for r in list(store.referrals.values()):
        if r["mobile_dispatch_id"] == dispatch["id"] and r["status"] == "HELD":
            void_referral(r, allow_contact_revert=allow_referral_revert)


def escalate_contact(contact, role):
    """Cancel active dispatch (cascade), set emergency, create coordination.
    Used from DISPATCH_PENDING / REFERRAL_PENDING / DE_ESCALATION (PRD 3.7)."""
    if contact["status"] in ("DISPATCH_PENDING", "REFERRAL_PENDING"):
        for d in list(store.dispatches.values()):
            if d["contact_id"] == contact["id"] and d["status"] in ("REQUESTED", "EN_ROUTE", "ON_SCENE"):
                # suppress revert: the contact is being escalated in the same request
                cancel_dispatch(d, allow_referral_revert=False)
    mutate(contact, status="EMERGENCY_911", emergency_status="INITIATED")
    create_emergency(contact, role)


# ===========================================================================
# Contact endpoints
# ===========================================================================
CONTACT_STATE_COARSE = {
    "DE_ESCALATION": {CC, CS},
    "DISPATCH_PENDING": {CD, CS},
    "EMERGENCY_911": {CC, CD, CS},
    "RESOLVED": {CC, CD, CS},
    "CLOSED": {CS},
    # states with no manual transition: allow through so the state check fires
    "INTAKE": ROLES, "SCREENED": ROLES, "REFERRAL_PENDING": ROLES,
}

CONTACT_TRANSITION_ROLES = {
    ("SCREENED", "DE_ESCALATION"): {CC, CS},
    ("SCREENED", "DISPATCH_PENDING"): {CD, CS},
    ("SCREENED", "EMERGENCY_911"): {CD, CS},
    ("DE_ESCALATION", "RESOLVED"): {CC, CS},
    ("DE_ESCALATION", "EMERGENCY_911"): {CC, CS},
    ("DISPATCH_PENDING", "EMERGENCY_911"): {CD, CS},
    ("REFERRAL_PENDING", "EMERGENCY_911"): {CD, CS},
    ("EMERGENCY_911", "RESOLVED"): {CD, CS},
    ("RESOLVED", "CLOSED"): {CS},
}


@app.route("/contacts", methods=["POST"])
def create_contact():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    body = get_body()
    channel = require(body, "channel")
    caller_key = require_str(body, "caller_key")
    check_enum(channel, CHANNELS)
    for f in ("caller_phone", "caller_name", "presenting_concern"):
        if f in body and body[f] is not None and not isinstance(body[f], str):
            raise ApiError("ERR_VALIDATION", 422, "Field must be a string: " + f)

    now = get_now()
    cid = new_id()
    contact = {
        "id": cid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "channel": channel,
        "caller_key": caller_key,
        "caller_phone": body.get("caller_phone"),
        "caller_name": body.get("caller_name"),
        "presenting_concern": body.get("presenting_concern"),
        "status": "INTAKE",
        "risk_score": None,
        "risk_band": None,
        "latest_screening_id": None,
        "disposition": None,
        "disposition_at": None,
        "has_active_safety_plan": False,
        "emergency_status": "NONE",
        "repeat_caller_flag": False,
    }
    store.contacts[cid] = contact

    # Upsert repeat-caller registry (PRD 3.1)
    rc = store.repeat_callers.get(caller_key)
    if rc is None:
        rc = {
            "id": new_id(), "created_at": now, "updated_at": now, "version": 1,
            "_seq": next_seq(),
            "caller_key": caller_key,
            "contact_count": 0,
            "last_risk_band": None,
            "high_risk_flag": False,
            "registry_status": "ACTIVE",
        }
        store.repeat_callers[caller_key] = rc
    recompute_repeat_caller(caller_key)
    # Snapshot the freshly recomputed flag onto the contact (frozen at intake)
    contact["repeat_caller_flag"] = rc["high_risk_flag"]

    return ok_object(serialize(contact), 201)


@app.route("/contacts/<contact_id>", methods=["GET"])
def get_contact(contact_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    contact = path_lookup(store.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
    return ok_object(serialize(contact))


@app.route("/contacts", methods=["GET"])
def list_contacts():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "status": request.args.get("status"),
        "channel": request.args.get("channel"),
        "caller_key": request.args.get("caller_key"),
    }
    return paged_list(store.contacts.values(), spec)


@app.route("/contacts/<contact_id>/state", methods=["POST"])
def contact_state(contact_id):
    _, role = authenticate()
    body = get_body()
    # Coarse role gating by requested to_status (PRD 2.8 step 2)
    to_status = body.get("to_status")
    coarse = CONTACT_STATE_COARSE.get(to_status)
    if coarse is not None:
        authorize(role, coarse)
    # Existence (step 3)
    contact = path_lookup(store.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
    # Body validity (step 4)
    to_status = require(body, "to_status")
    check_enum(to_status, CONTACT_STATUSES)
    current = contact["status"]
    key = (current, to_status)
    # From-state (step 5)
    if key not in CONTACT_TRANSITION_ROLES:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal contact transition")
    # Fine-grained role for the resolved transition (role precedes safety gate)
    authorize(role, CONTACT_TRANSITION_ROLES[key])
    now = get_now()

    if key == ("SCREENED", "DE_ESCALATION"):
        if contact["risk_band"] not in ("LOW", "MODERATE"):
            raise ApiError("ERR_DISPOSITION_NOT_ALLOWED", 409, "risk_band not eligible for DE_ESCALATION")
        mutate(contact, status="DE_ESCALATION", disposition="DE_ESCALATION", disposition_at=now)

    elif key == ("SCREENED", "DISPATCH_PENDING"):
        if contact["risk_band"] != "HIGH":
            raise ApiError("ERR_DISPOSITION_NOT_ALLOWED", 409, "risk_band not eligible for DISPATCH_PENDING")
        mutate(contact, status="DISPATCH_PENDING", disposition="MOBILE_DISPATCH", disposition_at=now)

    elif key == ("SCREENED", "EMERGENCY_911"):
        if contact["risk_band"] != "IMMINENT":
            raise ApiError("ERR_DISPOSITION_NOT_ALLOWED", 409, "risk_band not eligible for EMERGENCY_911")
        mutate(contact, status="EMERGENCY_911", disposition="EMERGENCY",
               disposition_at=now, emergency_status="INITIATED")
        create_emergency(contact, role)

    elif key == ("DE_ESCALATION", "RESOLVED"):
        if not contact["has_active_safety_plan"]:
            raise ApiError("ERR_NO_ACTIVE_SAFETY_PLAN", 409, "No ACTIVE safety plan for contact")
        resolve_contact(contact)

    elif key == ("DE_ESCALATION", "EMERGENCY_911"):
        escalate_contact(contact, role)

    elif key == ("DISPATCH_PENDING", "EMERGENCY_911"):
        escalate_contact(contact, role)

    elif key == ("REFERRAL_PENDING", "EMERGENCY_911"):
        escalate_contact(contact, role)

    elif key == ("EMERGENCY_911", "RESOLVED"):
        resolve_contact(contact)

    elif key == ("RESOLVED", "CLOSED"):
        mutate(contact, status="CLOSED")

    return ok_object(serialize(contact))


# ===========================================================================
# RiskScreening endpoints
# ===========================================================================
@app.route("/risk-screenings", methods=["POST"])
def create_screening():
    _, role = authenticate()
    authorize(role, {CC, CS})
    body = get_body()
    # Existence (step 3): body FK contact_id
    contact = check_fk(body, "contact_id", store.contacts, "ERR_CONTACT_NOT_FOUND")
    # Body validity (step 4)
    require(body, "contact_id")
    screening_type = require(body, "screening_type")
    ideation = require_int(body, "suicidal_ideation")
    plan = require_int(body, "plan_specificity")
    means = require_bool(body, "means_access")
    prior = require_int(body, "prior_attempts")
    protective = 0
    if "protective_factors" in body and body["protective_factors"] is not None:
        protective = require_int(body, "protective_factors")
    check_enum(screening_type, SCREENING_TYPES)

    score, band = compute_risk_score(screening_type, ideation, plan, means, prior, protective)

    now = get_now()
    sid = new_id()
    screening = {
        "id": sid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "contact_id": contact["id"],
        "screening_type": screening_type,
        "suicidal_ideation": ideation,
        "plan_specificity": plan,
        "means_access": means,
        "prior_attempts": prior,
        "protective_factors": protective,
        "risk_score": score,
        "risk_band": band,
    }
    store.screenings[sid] = screening

    # latest_screening_id = greatest (created_at, id) among this contact's screenings
    contact_screenings = [s for s in store.screenings.values() if s["contact_id"] == contact["id"]]
    latest = max(contact_screenings, key=lambda s: (s["created_at"], s["id"]))

    changes = {
        "risk_score": score,
        "risk_band": band,
        "latest_screening_id": latest["id"],
    }
    if contact["status"] == "INTAKE":
        changes["status"] = "SCREENED"
    mutate(contact, **changes)

    recompute_repeat_caller(contact["caller_key"])

    return ok_object(serialize(screening), 201)


@app.route("/risk-screenings/<screening_id>", methods=["GET"])
def get_screening(screening_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    s = path_lookup(store.screenings, screening_id, "ERR_SCREENING_NOT_FOUND")
    return ok_object(serialize(s))


@app.route("/risk-screenings", methods=["GET"])
def list_screenings():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "contact_id": request.args.get("contact_id"),
        "screening_type": request.args.get("screening_type"),
    }
    return paged_list(store.screenings.values(), spec)


# ===========================================================================
# SafetyPlan endpoints
# ===========================================================================
@app.route("/safety-plans", methods=["POST"])
def create_safety_plan():
    _, role = authenticate()
    authorize(role, {CC, CS})
    body = get_body()
    contact = check_fk(body, "contact_id", store.contacts, "ERR_CONTACT_NOT_FOUND")
    require(body, "contact_id")
    coping = require_list(body, "coping_strategies")
    warning = require_list(body, "warning_signs")
    support = body.get("support_contacts")
    if support is not None and not isinstance(support, list):
        raise ApiError("ERR_VALIDATION", 422, "support_contacts must be a list")
    lmc = body.get("lethal_means_counseling", False)
    if not isinstance(lmc, bool):
        raise ApiError("ERR_VALIDATION", 422, "lethal_means_counseling must be a boolean")

    now = get_now()
    pid = new_id()
    plan = {
        "id": pid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "contact_id": contact["id"],
        "coping_strategies": coping,
        "warning_signs": warning,
        "support_contacts": support if support is not None else [],
        "lethal_means_counseling": lmc,
        "status": "DRAFT",
    }
    store.safety_plans[pid] = plan
    return ok_object(serialize(plan), 201)


@app.route("/safety-plans/<plan_id>", methods=["GET"])
def get_safety_plan(plan_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    p = path_lookup(store.safety_plans, plan_id, "ERR_SAFETY_PLAN_NOT_FOUND")
    return ok_object(serialize(p))


@app.route("/safety-plans", methods=["GET"])
def list_safety_plans():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "contact_id": request.args.get("contact_id"),
        "status": request.args.get("status"),
    }
    return paged_list(store.safety_plans.values(), spec)


@app.route("/safety-plans/<plan_id>/state", methods=["POST"])
def safety_plan_state(plan_id):
    _, role = authenticate()
    authorize(role, {CC, CS})
    plan = path_lookup(store.safety_plans, plan_id, "ERR_SAFETY_PLAN_NOT_FOUND")
    body = get_body()
    to_status = require(body, "to_status")
    check_enum(to_status, SAFETY_STATUSES)
    current = plan["status"]
    contact = store.contacts.get(plan["contact_id"])

    if current == "DRAFT" and to_status == "ACTIVE":
        # supersede any other ACTIVE plan for the same contact
        for other in store.safety_plans.values():
            if (other["id"] != plan["id"] and other["contact_id"] == plan["contact_id"]
                    and other["status"] == "ACTIVE"):
                mutate(other, status="ARCHIVED")
        mutate(plan, status="ACTIVE")
        if contact:
            mutate(contact, has_active_safety_plan=True)

    elif current == "ACTIVE" and to_status == "ARCHIVED":
        mutate(plan, status="ARCHIVED")
        remaining = any(p["contact_id"] == plan["contact_id"] and p["status"] == "ACTIVE"
                        for p in store.safety_plans.values())
        if contact and not remaining:
            mutate(contact, has_active_safety_plan=False)

    elif current == "DRAFT" and to_status == "ARCHIVED":
        mutate(plan, status="ARCHIVED")

    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal safety-plan transition")

    return ok_object(serialize(plan))


# ===========================================================================
# MobileCrisisTeam endpoints
# ===========================================================================
@app.route("/mobile-crisis-teams", methods=["POST"])
def create_team():
    _, role = authenticate()
    authorize(role, {CS})
    body = get_body()
    name = require_str(body, "name")
    coverage_zone = require_str(body, "coverage_zone")
    capacity = 1
    if "capacity" in body and body["capacity"] is not None:
        capacity = require_int(body, "capacity")
        if capacity < 1:
            raise ApiError("ERR_VALIDATION", 422, "capacity must be >= 1")
    shift_start = require_dt(body, "shift_start")
    shift_end = require_dt(body, "shift_end")
    status = body.get("status", "ON_SHIFT")
    if status is None:
        status = "ON_SHIFT"
    check_enum(status, TEAM_STATUSES)
    if shift_end <= shift_start:
        raise ApiError("ERR_WINDOW_INVALID", 422, "shift_end must be strictly after shift_start")

    now = get_now()
    tid = new_id()
    team = {
        "id": tid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "name": name,
        "coverage_zone": coverage_zone,
        "capacity": capacity,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "status": status,
        "active_dispatch_count": 0,
    }
    store.teams[tid] = team
    return ok_object(serialize(team), 201)


@app.route("/mobile-crisis-teams/<team_id>", methods=["GET"])
def get_team(team_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    t = path_lookup(store.teams, team_id, "ERR_TEAM_NOT_FOUND")
    return ok_object(serialize(t))


# ===========================================================================
# MobileDispatch endpoints
# ===========================================================================
@app.route("/mobile-dispatches", methods=["POST"])
def create_dispatch():
    _, role = authenticate()
    authorize(role, {CD, CS})
    body = get_body()
    # Existence (step 3): contact_id then team_id, left to right
    contact = check_fk(body, "contact_id", store.contacts, "ERR_CONTACT_NOT_FOUND")
    team = check_fk(body, "team_id", store.teams, "ERR_TEAM_NOT_FOUND")
    # Body validity (step 4)
    require(body, "contact_id")
    require(body, "team_id")
    window_start = require_dt(body, "window_start")
    window_end = require_dt(body, "window_end")
    requested_acuity = require(body, "requested_acuity")
    expected_team_version = require_int(body, "expected_team_version")
    check_enum(requested_acuity, ACUITIES)
    check_window(window_start, window_end)
    # OCC (step 6)
    if expected_team_version != team["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_team_version does not match current team version")
    # Cross-entity referential (step 8)
    if contact["status"] != "DISPATCH_PENDING":
        raise ApiError("ERR_CONTACT_NOT_DISPATCH_PENDING", 409, "Contact must be DISPATCH_PENDING")
    # Temporal overlap (step 9): team buffer-separated single-capacity
    buffer_ms = TEAM_TURNAROUND_MINUTES * 60000
    for d in store.dispatches.values():
        if d["team_id"] != team["id"]:
            continue
        if d["status"] not in ("REQUESTED", "EN_ROUTE", "ON_SCENE", "COMPLETED"):
            continue
        o_start = d["window_start"]
        o_end = d["window_end"]
        if (delta_ms(window_start, o_end) < buffer_ms) and (delta_ms(o_start, window_end) < buffer_ms):
            # window_start < o_end + buffer AND o_start < window_end + buffer
            raise ApiError("ERR_TEAM_WINDOW_CONFLICT", 409, "Dispatch window conflicts within turnaround buffer")
    # Team availability (step 10): off-shift/containment then capacity
    if team["status"] != "ON_SHIFT" or not (window_start >= team["shift_start"] and window_end <= team["shift_end"]):
        raise ApiError("ERR_TEAM_OFF_SHIFT", 409, "Team OFF_SHIFT or window outside shift")
    if team["active_dispatch_count"] >= team["capacity"]:
        raise ApiError("ERR_TEAM_AT_CAPACITY", 409, "Team already at capacity")

    now = get_now()
    did = new_id()
    est = dispatch_priority(contact["risk_band"], now, contact)
    dispatch = {
        "id": did, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "contact_id": contact["id"],
        "team_id": team["id"],
        "window_start": window_start,
        "window_end": window_end,
        "requested_acuity": requested_acuity,
        "status": "REQUESTED",
        "on_scene_acuity": None,
        "priority_score_estimated": est,
        "priority_score_reassessed": None,
    }
    store.dispatches[did] = dispatch
    recompute_team(team)  # active count changed -> team version bumps
    return ok_object(serialize(dispatch), 201)


@app.route("/mobile-dispatches/<dispatch_id>", methods=["GET"])
def get_dispatch(dispatch_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    d = path_lookup(store.dispatches, dispatch_id, "ERR_DISPATCH_NOT_FOUND")
    return ok_object(serialize(d))


@app.route("/mobile-dispatches", methods=["GET"])
def list_dispatches():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "contact_id": request.args.get("contact_id"),
        "team_id": request.args.get("team_id"),
        "status": request.args.get("status"),
    }
    return paged_list(store.dispatches.values(), spec)


@app.route("/mobile-dispatches/<dispatch_id>/state", methods=["POST"])
def dispatch_state(dispatch_id):
    _, role = authenticate()
    authorize(role, {CD, CS})
    dispatch = path_lookup(store.dispatches, dispatch_id, "ERR_DISPATCH_NOT_FOUND")
    body = get_body()
    to_status = require(body, "to_status")
    check_enum(to_status, DISPATCH_STATUSES)
    on_scene_acuity = None
    if to_status == "ON_SCENE":
        on_scene_acuity = require(body, "on_scene_acuity")
        check_enum(on_scene_acuity, ACUITIES)
    current = dispatch["status"]

    if current == "REQUESTED" and to_status == "EN_ROUTE":
        mutate(dispatch, status="EN_ROUTE")

    elif current == "EN_ROUTE" and to_status == "ON_SCENE":
        contact = store.contacts.get(dispatch["contact_id"])
        reassessed = dispatch_priority(on_scene_acuity, get_now(), contact) if contact else None
        mutate(dispatch, status="ON_SCENE", on_scene_acuity=on_scene_acuity,
               priority_score_reassessed=reassessed)

    elif current == "ON_SCENE" and to_status == "COMPLETED":
        mutate(dispatch, status="COMPLETED")
        team = store.teams.get(dispatch["team_id"])
        if team:
            recompute_team(team)
        contact = store.contacts.get(dispatch["contact_id"])
        if contact and contact["status"] == "DISPATCH_PENDING":
            resolve_contact(contact)

    elif to_status == "CANCELLED" and current in ("REQUESTED", "EN_ROUTE", "ON_SCENE"):
        cancel_dispatch(dispatch, allow_referral_revert=True)

    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal dispatch transition")

    return ok_object(serialize(dispatch))


# ===========================================================================
# CrisisCenter endpoints
# ===========================================================================
@app.route("/crisis-centers", methods=["POST"])
def create_center():
    _, role = authenticate()
    authorize(role, {CS})
    body = get_body()
    name = require_str(body, "name")
    bed_capacity = require_int(body, "bed_capacity")
    if bed_capacity < 1:
        raise ApiError("ERR_VALIDATION", 422, "bed_capacity must be >= 1")
    accepted = require_list(body, "accepted_acuities")
    for a in accepted:
        check_enum(a, ACUITIES)

    now = get_now()
    cid = new_id()
    center = {
        "id": cid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "name": name,
        "bed_capacity": bed_capacity,
        "accepted_acuities": accepted,
        "status": "ONLINE",
        "held_beds": 0,
        "occupied_beds": 0,
        "available_beds": bed_capacity,
    }
    store.centers[cid] = center
    return ok_object(serialize(center), 201)


@app.route("/crisis-centers/<center_id>", methods=["GET"])
def get_center(center_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    c = path_lookup(store.centers, center_id, "ERR_CENTER_NOT_FOUND")
    return ok_object(serialize(c))


@app.route("/crisis-centers/<center_id>/state", methods=["POST"])
def center_state(center_id):
    _, role = authenticate()
    authorize(role, {CD, CS})
    center = path_lookup(store.centers, center_id, "ERR_CENTER_NOT_FOUND")
    body = get_body()
    to_status = require(body, "to_status")
    check_enum(to_status, CENTER_STATUSES)
    current = center["status"]

    if current == "ONLINE" and to_status == "DIVERTED":
        for r in list(store.referrals.values()):
            if r["crisis_center_id"] == center["id"] and r["status"] == "HELD":
                void_referral(r, allow_contact_revert=True)
        mutate(center, status="DIVERTED")

    elif current == "DIVERTED" and to_status == "ONLINE":
        mutate(center, status="ONLINE")

    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal center transition")

    return ok_object(serialize(center))


# ===========================================================================
# BedReferral endpoints
# ===========================================================================
@app.route("/bed-referrals", methods=["POST"])
def create_referral():
    _, role = authenticate()
    authorize(role, {CD, CS})
    body = get_body()
    # Existence (step 3): contact_id, crisis_center_id, mobile_dispatch_id (left to right)
    contact = check_fk(body, "contact_id", store.contacts, "ERR_CONTACT_NOT_FOUND")
    center = check_fk(body, "crisis_center_id", store.centers, "ERR_CENTER_NOT_FOUND")
    dispatch = check_fk(body, "mobile_dispatch_id", store.dispatches, "ERR_DISPATCH_NOT_FOUND")
    # Body validity (step 4)
    require(body, "contact_id")
    require(body, "crisis_center_id")
    acuity = require(body, "acuity")
    window_start = require_dt(body, "window_start")
    window_end = require_dt(body, "window_end")
    expected_center_version = require_int(body, "expected_crisis_center_version")
    check_enum(acuity, ACUITIES)
    check_window(window_start, window_end)
    # OCC (step 6)
    if expected_center_version != center["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_crisis_center_version does not match current center version")
    # Cross-entity referential (step 8): contact pending -> center online -> acuity accepted
    if contact["status"] != "DISPATCH_PENDING":
        raise ApiError("ERR_CONTACT_NOT_DISPATCH_PENDING", 409, "Contact must be DISPATCH_PENDING")
    if center["status"] != "ONLINE":
        raise ApiError("ERR_CENTER_OFFLINE", 409, "Center is not ONLINE")
    if acuity not in center["accepted_acuities"]:
        raise ApiError("ERR_ACUITY_NOT_ACCEPTED", 409, "Center does not accept this acuity")
    # Temporal overlap (step 9): aggregate-capacity, half-open, no buffer
    overlapping = 0
    for r in store.referrals.values():
        if r["crisis_center_id"] != center["id"]:
            continue
        if r["status"] not in ("HELD", "ADMITTED"):
            continue
        if window_start < r["window_end"] and r["window_start"] < window_end:
            overlapping += 1
    if overlapping >= center["bed_capacity"]:
        raise ApiError("ERR_BED_WINDOW_CONFLICT", 409, "Bed capacity exhausted for the requested window")

    now = get_now()
    rid = new_id()
    referral = {
        "id": rid, "created_at": now, "updated_at": now, "version": 1,
        "_seq": next_seq(),
        "contact_id": contact["id"],
        "crisis_center_id": center["id"],
        "mobile_dispatch_id": dispatch["id"] if dispatch else None,
        "acuity": acuity,
        "window_start": window_start,
        "window_end": window_end,
        "status": "HELD",
    }
    store.referrals[rid] = referral
    recompute_center(center)  # held_beds changed -> center version bumps
    mutate(contact, status="REFERRAL_PENDING")
    return ok_object(serialize(referral), 201)


@app.route("/bed-referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    r = path_lookup(store.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    return ok_object(serialize(r))


@app.route("/bed-referrals", methods=["GET"])
def list_referrals():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "contact_id": request.args.get("contact_id"),
        "crisis_center_id": request.args.get("crisis_center_id"),
        "mobile_dispatch_id": request.args.get("mobile_dispatch_id"),
        "status": request.args.get("status"),
    }
    return paged_list(store.referrals.values(), spec)


@app.route("/bed-referrals/<referral_id>/state", methods=["POST"])
def referral_state(referral_id):
    _, role = authenticate()
    authorize(role, {CD, CS})
    referral = path_lookup(store.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    body = get_body()
    to_status = require(body, "to_status")
    check_enum(to_status, REFERRAL_STATUSES)
    current = referral["status"]
    center = store.centers.get(referral["crisis_center_id"])

    if current == "HELD" and to_status == "ADMITTED":
        # cross-entity precondition (step 8): center must be ONLINE
        if center and center["status"] != "ONLINE":
            raise ApiError("ERR_CENTER_OFFLINE", 409, "Center is not ONLINE")
        mutate(referral, status="ADMITTED")
        if center:
            recompute_center(center)
        contact = store.contacts.get(referral["contact_id"])
        if contact and contact["status"] == "REFERRAL_PENDING":
            resolve_contact(contact)

    elif current == "ADMITTED" and to_status == "DISCHARGED":
        mutate(referral, status="DISCHARGED")
        if center:
            recompute_center(center)

    elif current == "HELD" and to_status == "VOIDED":
        void_referral(referral, allow_contact_revert=True)

    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Illegal referral transition")

    return ok_object(serialize(referral))


# ===========================================================================
# FollowUpTask endpoints
# ===========================================================================
@app.route("/follow-up-tasks/<task_id>", methods=["GET"])
def get_followup(task_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    t = path_lookup(store.followups, task_id, "ERR_FOLLOWUP_NOT_FOUND")
    return ok_object(serialize(t))


@app.route("/follow-up-tasks", methods=["GET"])
def list_followups():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "contact_id": request.args.get("contact_id"),
        "status": request.args.get("status"),
    }
    return paged_list(store.followups.values(), spec)


@app.route("/follow-up-tasks/<task_id>/attempt", methods=["POST"])
def followup_attempt(task_id):
    _, role = authenticate()
    authorize(role, {CC, CS})
    task = path_lookup(store.followups, task_id, "ERR_FOLLOWUP_NOT_FOUND")
    body = get_body()
    outcome = require(body, "outcome")
    check_enum(outcome, OUTCOMES)
    next_scheduled_at = opt_dt(body, "next_scheduled_at")
    # From-state (step 5)
    if task["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Follow-up not in an attemptable state")

    new_count = task["attempt_count"] + 1
    changes = {"attempt_count": new_count, "outcome": outcome}
    if outcome == "REACHED":
        changes["status"] = "COMPLETED"
    elif outcome == "NO_ANSWER" and new_count >= task["max_attempts"]:
        changes["status"] = "ABANDONED"
    else:
        changes["status"] = "RESCHEDULED"
        if next_scheduled_at is not None:
            changes["scheduled_at"] = next_scheduled_at
    mutate(task, **changes)
    return ok_object(serialize(task))


# ===========================================================================
# EmergencyCoordination endpoints
# ===========================================================================
@app.route("/emergency-coordinations/<coord_id>", methods=["GET"])
def get_emergency(coord_id):
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    e = path_lookup(store.emergencies, coord_id, "ERR_EMERGENCY_NOT_FOUND")
    return ok_object(serialize(e))


@app.route("/emergency-coordinations", methods=["GET"])
def list_emergencies():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {"contact_id": request.args.get("contact_id")}
    return paged_list(store.emergencies.values(), spec)


# ===========================================================================
# RepeatCaller endpoints
# ===========================================================================
@app.route("/repeat-callers", methods=["GET"])
def list_repeat_callers():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    spec = {
        "caller_key": request.args.get("caller_key"),
        "high_risk_flag": request.args.get("high_risk_flag"),
    }
    return paged_list(store.repeat_callers.values(), spec)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {CC, CD, CS})
    body = get_body()
    to_iso = require(body, "to_iso8601")
    try:
        dt = parse_dt(to_iso)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 must be a datetime")
    set_now(dt)
    return ok_object({})


# ===========================================================================
# Operations report (PRD 3.9)
# ===========================================================================
@app.route("/reports/operations", methods=["GET"])
def operations_report():
    _, role = authenticate()
    authorize(role, {CS})

    window_start = None
    window_end = None
    if request.args.get("window_start"):
        try:
            window_start = parse_dt(request.args.get("window_start"))
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "window_start must be a datetime")
    if request.args.get("window_end"):
        try:
            window_end = parse_dt(request.args.get("window_end"))
        except Exception:
            raise ApiError("ERR_VALIDATION", 422, "window_end must be a datetime")

    def in_window(dt):
        if window_start is not None and dt < window_start:
            return False
        if window_end is not None and dt >= window_end:
            return False
        return True

    population = [c for c in store.contacts.values()
                 if c["disposition_at"] is not None and in_window(c["disposition_at"])]

    total_contacts = len(population)

    by_disposition = {"DE_ESCALATION": 0, "MOBILE_DISPATCH": 0, "EMERGENCY": 0}
    for c in population:
        d = c["disposition"]
        if d in by_disposition:
            by_disposition[d] += 1
        elif d is not None:
            by_disposition[d] = by_disposition.get(d, 0) + 1

    # avg time to disposition: per-contact round FIRST, then divide, then round mean
    if not population:
        avg = 0.0
    else:
        per_contact = []
        for c in population:
            minutes = Decimal(delta_ms(c["disposition_at"], c["created_at"])) / Decimal(60000)
            per_contact.append(round_half_up(minutes, 0))
        mean = Decimal(sum(per_contact)) / Decimal(len(population))
        avg = round_half_up(mean, 1)

    # follow-up compliance: completed / total follow-up tasks (percent)
    all_followups = list(store.followups.values())
    if all_followups:
        completed = sum(1 for t in all_followups if t["status"] == "COMPLETED")
        compliance = round_half_up(Decimal(completed * 100) / Decimal(len(all_followups)), 1)
    else:
        compliance = 0.0

    bed_utilization = {}
    for center in store.centers.values():
        bed_utilization[center["id"]] = {
            "bed_capacity": center["bed_capacity"],
            "held_beds": center["held_beds"],
            "occupied_beds": center["occupied_beds"],
            "available_beds": center["available_beds"],
        }

    data = {
        "total_contacts": total_contacts,
        "contacts_by_disposition": by_disposition,
        "avg_time_to_disposition_minutes": avg,
        "followup_compliance_rate_pct": compliance,
        "bed_utilization_by_center": bed_utilization,
    }
    return ok_object(data)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
