"""Music & Art Therapy Practice API — Flask reference implementation.

In-memory only. State is wiped on every fresh process boot (no seeding).
Every endpoint / field / error traces to a verbatim PRD sentence.
"""
import os
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants (from PRD §3.8 / SCAFFOLD §1.3)
# =============================================================================
INDIVIDUAL_RATE_CENTS = 12503
GROUP_RATE_CENTS = 6503
FPL_BASE_CENTS = 1560000
FPL_PER_PERSON_CENTS = 550000
MIN_FEE_CENTS = 2000
TURNAROUND_BUFFER_MINUTES = 15
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

ROLES = {"IntakeCoordinator", "Therapist", "ClinicalDirector", "BillingSpecialist"}
ALL_ROLES = list(ROLES)

# =============================================================================
# In-memory store — starts empty on every boot.
# =============================================================================
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.therapists = {}
        self.clients = {}
        self.referrals = {}
        self.plans = {}
        self.goals = {}
        self.rooms = {}
        self.materials = {}
        self.contracts = {}
        self.sessions = {}
        self.enrollments = {}
        self.notes = {}
        self.superbills = {}
        self.current_utc = DEFAULT_CLOCK
        self._seq = itertools.count(1)


db = Store()


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Helpers: time, ids, envelope
# =============================================================================
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}


def success(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# =============================================================================
# Auth
# =============================================================================
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


# =============================================================================
# Body / field validation helpers
# =============================================================================
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return data


def verr(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def v_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            verr(f"Missing required field: {name}")
        return None
    val = body[name]
    if not isinstance(val, str):
        verr(f"Field {name} must be a string")
    return val


def v_enum(body, name, choices, required=True):
    if name not in body or body[name] is None:
        if required:
            verr(f"Missing required field: {name}")
        return None
    val = body[name]
    if val not in choices:
        verr(f"Field {name} must be one of {sorted(choices)}")
    return val


def v_int(body, name, required=True, minv=None, maxv=None, default=None):
    if name not in body or body[name] is None:
        if required:
            verr(f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        verr(f"Field {name} must be an integer")
    if minv is not None and val < minv:
        verr(f"Field {name} must be >= {minv}")
    if maxv is not None and val > maxv:
        verr(f"Field {name} must be <= {maxv}")
    return val


def v_num(body, name, required=True, minv=None, maxv=None, default=None):
    if name not in body or body[name] is None:
        if required:
            verr(f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        verr(f"Field {name} must be a number")
    if minv is not None and val < minv:
        verr(f"Field {name} must be >= {minv}")
    if maxv is not None and val > maxv:
        verr(f"Field {name} must be <= {maxv}")
    return val


def parse_dt(s, field="datetime"):
    if not isinstance(s, str):
        verr(f"Field {field} must be an ISO8601 datetime string")
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
    except Exception:
        verr(f"Field {field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# Precision helpers
# =============================================================================
def rhu_cents(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_2dp(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# =============================================================================
# Common-field / mutation helpers
# =============================================================================
def new_common():
    ts = now_iso()
    return {"id": gen_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next(db._seq)}


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def serialize(entity, extra=None):
    d = {k: v for k, v in entity.items() if not k.startswith("_")}
    if extra:
        d.update(extra)
    return d


def ser_client(c):
    remaining = c["insurance_visits_authorized"] - c["insurance_visits_used"]
    return serialize(c, {"insurance_visits_remaining": remaining})


def ser_material(m):
    available = m["on_hand_quantity"] - m["reserved_quantity"]
    return serialize(m, {"available_quantity": available})


# =============================================================================
# Lookup helpers (existence)
# =============================================================================
def get_or_404(coll, key, error_id):
    ent = coll.get(key)
    if ent is None:
        raise ApiError(error_id, 404, f"{error_id}: {key}")
    return ent


# =============================================================================
# Pagination / listing
# =============================================================================
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    ordered = sorted(items, key=lambda e: e["_seq"])
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def filter_by(items, mapping):
    """mapping: {query_param: entity_field}. Exact-match filtering."""
    result = list(items)
    for param, field in mapping.items():
        val = request.args.get(param)
        if val is not None:
            result = [e for e in result if str(e.get(field)) == val]
    return result


# =============================================================================
# Clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(ALL_ROLES)
    body = body_json()
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        verr("Missing required field: to_iso8601")
    parse_dt(to_iso, "to_iso8601")  # validate
    db.current_utc = to_iso
    return success({}, "object", 200)


def current_dt():
    return parse_dt(db.current_utc, "current_utc")


# =============================================================================
# Therapist
# =============================================================================
@app.route("/therapists", methods=["POST"])
def create_therapist():
    authenticate(["IntakeCoordinator"])
    body = body_json()
    full_name = v_str(body, "full_name")
    discipline = v_enum(body, "discipline", {"MUSIC", "ART"})
    credential = v_str(body, "credential")
    t = new_common()
    t.update({"full_name": full_name, "discipline": discipline, "credential": credential})
    db.therapists[t["id"]] = t
    return success(serialize(t), "object", 201)


# =============================================================================
# Client
# =============================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    authenticate(["IntakeCoordinator"])
    body = body_json()
    full_name = v_str(body, "full_name")
    dob = v_str(body, "dob")
    payer_type = v_enum(body, "payer_type", {"INSURANCE", "SELF_PAY"})

    household_income_cents = None
    household_size = v_int(body, "household_size", required=False, minv=1, default=1)
    insurance_payer_name = None
    insurance_coinsurance_pct = v_num(body, "insurance_coinsurance_pct", required=False, minv=0.0, maxv=1.0, default=0.20)
    insurance_contracted_rate_cents = v_int(body, "insurance_contracted_rate_cents", required=False, minv=0, default=0)
    insurance_visits_authorized = v_int(body, "insurance_visits_authorized", required=False, minv=0, default=0)

    if payer_type == "SELF_PAY":
        household_income_cents = v_int(body, "household_income_cents", required=True, minv=0)
    else:
        household_income_cents = v_int(body, "household_income_cents", required=False, minv=0, default=0)
        insurance_payer_name = v_str(body, "insurance_payer_name", required=False)

    c = new_common()
    c.update({
        "full_name": full_name,
        "dob": dob,
        "payer_type": payer_type,
        "household_income_cents": household_income_cents,
        "household_size": household_size,
        "insurance_payer_name": insurance_payer_name,
        "insurance_coinsurance_pct": insurance_coinsurance_pct,
        "insurance_contracted_rate_cents": insurance_contracted_rate_cents,
        "insurance_visits_authorized": insurance_visits_authorized,
        "insurance_visits_used": 0,
        "status": "INTAKE",
        "discharge_reason": None,
    })
    db.clients[c["id"]] = c
    return success(ser_client(c), "object", 201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    authenticate(ALL_ROLES)
    c = get_or_404(db.clients, cid, "ERR_CLIENT_NOT_FOUND")
    return success(ser_client(c), "object", 200)


@app.route("/clients/<cid>/discharge", methods=["POST"])
def discharge_client(cid):
    authenticate(["ClinicalDirector"])
    c = get_or_404(db.clients, cid, "ERR_CLIENT_NOT_FOUND")
    body = body_json()
    discharge_reason = v_str(body, "discharge_reason", required=False)
    # State: non-ACTIVE discharge rejected with plan-level guard (PRD §3.9).
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Client is not ACTIVE")

    c["status"] = "DISCHARGED"
    if discharge_reason is not None:
        c["discharge_reason"] = discharge_reason
    touch(c)

    # CASCADE L1: client's ACTIVE/UNDER_REVISION plans -> DISCHARGED
    for plan in db.plans.values():
        if plan["client_id"] == cid and plan["status"] in ("ACTIVE", "UNDER_REVISION"):
            plan["status"] = "DISCHARGED"
            touch(plan)
            # CASCADE L2: OPEN goals of this plan -> DISCONTINUED
            for goal in db.goals.values():
                if goal["plan_id"] == plan["id"] and goal["status"] == "OPEN":
                    goal["status"] = "DISCONTINUED"
                    touch(goal)
                    # CASCADE L3: SCHEDULED sessions on this goal -> CANCELLED
                    for sess in db.sessions.values():
                        if sess["goal_id"] == goal["id"] and sess["scheduling_status"] == "SCHEDULED":
                            _cancel_session(sess)
    return success(ser_client(c), "object", 200)


# =============================================================================
# Referral
# =============================================================================
@app.route("/referrals", methods=["POST"])
def create_referral():
    authenticate(["IntakeCoordinator"])
    body = body_json()
    client_id = v_str(body, "client_id")  # presence
    # existence must precede field validation of other fields; but client_id
    # presence already checked above. Validate existence:
    get_or_404(db.clients, client_id, "ERR_CLIENT_NOT_FOUND")
    referral_source = v_str(body, "referral_source")
    reason = v_str(body, "reason")
    referred_discipline = v_enum(body, "referred_discipline", {"MUSIC", "ART"})
    r = new_common()
    r.update({
        "client_id": client_id,
        "referral_source": referral_source,
        "reason": reason,
        "referred_discipline": referred_discipline,
        "assessed_by_therapist_id": None,
        "recommendation": None,
        "baseline_score": None,
        "status": "RECEIVED",
    })
    db.referrals[r["id"]] = r
    return success(serialize(r), "object", 201)


@app.route("/referrals", methods=["GET"])
def list_referrals():
    authenticate(ALL_ROLES)
    items = filter_by(db.referrals.values(), {
        "client_id": "client_id",
        "assessed_by_therapist_id": "assessed_by_therapist_id",
        "status": "status",
    })
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


@app.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    authenticate(ALL_ROLES)
    r = get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    return success(serialize(r), "object", 200)


@app.route("/referrals/<rid>/assess", methods=["POST"])
def assess_referral(rid):
    uid, role = authenticate(["Therapist"])
    r = get_or_404(db.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    body = body_json()
    recommendation = v_enum(body, "recommendation", {"THERAPY_RECOMMENDED", "NOT_APPROPRIATE"})
    baseline_score = v_int(body, "baseline_score", required=True, minv=0, maxv=100)
    if r["status"] != "RECEIVED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "Referral not in RECEIVED state")
    r["assessed_by_therapist_id"] = uid
    r["recommendation"] = recommendation
    r["baseline_score"] = baseline_score
    r["status"] = "ASSESSED" if recommendation == "THERAPY_RECOMMENDED" else "DECLINED"
    touch(r)
    return success(serialize(r), "object", 200)


# =============================================================================
# TreatmentPlan
# =============================================================================
@app.route("/clients/<cid>/treatment-plans", methods=["POST"])
def create_plan(cid):
    authenticate(["ClinicalDirector"])
    c = get_or_404(db.clients, cid, "ERR_CLIENT_NOT_FOUND")
    body = body_json()
    referral_id = v_str(body, "referral_id")
    referral = get_or_404(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND")
    discipline = v_enum(body, "discipline", {"MUSIC", "ART"})
    weekly_frequency = v_int(body, "weekly_frequency", required=True, minv=1)
    expected_client_version = v_int(body, "expected_client_version", required=True)
    # OCC (priority 6)
    if expected_client_version != c["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION", 412, "expected_client_version does not match current client version")

    # Supersede prior DRAFT/ACTIVE plans of this client
    for plan in db.plans.values():
        if plan["client_id"] == cid and plan["status"] in ("DRAFT", "ACTIVE"):
            plan["status"] = "SUPERSEDED"
            touch(plan)

    p = new_common()
    p.update({
        "client_id": cid,
        "referral_id": referral_id,
        "discipline": discipline,
        "weekly_frequency": weekly_frequency,
        "revision_count": 0,
        "revision_note": None,
        "status": "DRAFT",
    })
    db.plans[p["id"]] = p

    # Convert referral if ASSESSED + recommended
    if referral["status"] == "ASSESSED" and referral["recommendation"] == "THERAPY_RECOMMENDED":
        referral["status"] = "CONVERTED"
        touch(referral)

    # Advance client version by 1
    touch(c)
    return success(serialize(p), "object", 201)


@app.route("/treatment-plans", methods=["GET"])
def list_plans():
    authenticate(ALL_ROLES)
    items = filter_by(db.plans.values(), {
        "client_id": "client_id",
        "referral_id": "referral_id",
        "status": "status",
    })
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


@app.route("/treatment-plans/<pid>", methods=["GET"])
def get_plan(pid):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, pid, "ERR_PLAN_NOT_FOUND")
    return success(serialize(p), "object", 200)


@app.route("/treatment-plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    authenticate(["ClinicalDirector"])
    p = get_or_404(db.plans, pid, "ERR_PLAN_NOT_FOUND")
    if p["status"] not in ("DRAFT", "UNDER_REVISION"):
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Plan not in DRAFT or UNDER_REVISION")
    p["status"] = "ACTIVE"
    touch(p)
    # Bubble up: owning client INTAKE -> ACTIVE
    c = db.clients.get(p["client_id"])
    if c is not None and c["status"] == "INTAKE":
        c["status"] = "ACTIVE"
        touch(c)
    return success(serialize(p), "object", 200)


@app.route("/treatment-plans/<pid>/revise", methods=["POST"])
def revise_plan(pid):
    authenticate(["ClinicalDirector"])
    p = get_or_404(db.plans, pid, "ERR_PLAN_NOT_FOUND")
    body = body_json()
    revision_note = v_str(body, "revision_note", required=False)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_INVALID_STATE", 409, "Plan not in ACTIVE state")
    p["status"] = "UNDER_REVISION"
    p["revision_count"] += 1
    if revision_note is not None:
        p["revision_note"] = revision_note
    touch(p)
    return success(serialize(p), "object", 200)


# =============================================================================
# Goal
# =============================================================================
@app.route("/treatment-plans/<pid>/goals", methods=["POST"])
def create_goal(pid):
    authenticate(["ClinicalDirector"])
    p = get_or_404(db.plans, pid, "ERR_PLAN_NOT_FOUND")
    body = body_json()
    description = v_str(body, "description")
    target_sessions = v_int(body, "target_sessions", required=True, minv=1)
    weight = v_num(body, "weight", required=True)
    if not (0.0 < weight <= 1.0):
        verr("Field weight must satisfy 0.0 < weight <= 1.0")
    goal = new_common()
    goal.update({
        "plan_id": pid,
        "description": description,
        "target_sessions": target_sessions,
        "weight": weight,
        "progress_attendance": 0.0,
        "progress_rubric": 0.0,
        "status": "OPEN",
    })
    db.goals[goal["id"]] = goal
    return success(serialize(goal), "object", 201)


@app.route("/treatment-plans/<pid>/goals", methods=["GET"])
def list_goals(pid):
    authenticate(ALL_ROLES)
    get_or_404(db.plans, pid, "ERR_PLAN_NOT_FOUND")
    items = [g_ for g_ in db.goals.values() if g_["plan_id"] == pid]
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


# =============================================================================
# Room
# =============================================================================
@app.route("/rooms", methods=["POST"])
def create_room():
    authenticate(["IntakeCoordinator"])
    body = body_json()
    name = v_str(body, "name")
    capacity = v_int(body, "capacity", required=True, minv=1)
    r = new_common()
    r.update({"name": name, "capacity": capacity})
    db.rooms[r["id"]] = r
    return success(serialize(r), "object", 201)


# =============================================================================
# MaterialItem
# =============================================================================
@app.route("/materials", methods=["POST"])
def create_material():
    authenticate(["IntakeCoordinator"])
    body = body_json()
    name = v_str(body, "name")
    category = v_enum(body, "category", {"INSTRUMENT", "ART_SUPPLY"})
    on_hand_quantity = v_int(body, "on_hand_quantity", required=True, minv=0)
    unit_charge_cents = v_int(body, "unit_charge_cents", required=True, minv=0)
    m = new_common()
    m.update({
        "name": name,
        "category": category,
        "on_hand_quantity": on_hand_quantity,
        "reserved_quantity": 0,
        "unit_charge_cents": unit_charge_cents,
    })
    db.materials[m["id"]] = m
    return success(ser_material(m), "object", 201)


@app.route("/materials/<mid>", methods=["GET"])
def get_material(mid):
    authenticate(ALL_ROLES)
    m = get_or_404(db.materials, mid, "ERR_MATERIAL_NOT_FOUND")
    return success(ser_material(m), "object", 200)


# =============================================================================
# Contract
# =============================================================================
@app.route("/contracts", methods=["POST"])
def create_contract():
    authenticate(["IntakeCoordinator"])
    body = body_json()
    party_name = v_str(body, "party_name")
    contract_type = v_enum(body, "contract_type", {"FACILITY", "SCHOOL"})
    budget_cents = v_int(body, "budget_cents", required=True, minv=0)
    rate_cents_per_session = v_int(body, "rate_cents_per_session", required=True, minv=0)
    ct = new_common()
    ct.update({
        "party_name": party_name,
        "contract_type": contract_type,
        "budget_cents": budget_cents,
        "rate_cents_per_session": rate_cents_per_session,
        "spent_cents": 0,
    })
    db.contracts[ct["id"]] = ct
    return success(serialize(ct), "object", 201)


# =============================================================================
# Session
# =============================================================================
def _interval(sess):
    return parse_dt(sess["start_utc"], "start_utc"), parse_dt(sess["end_utc"], "end_utc")


@app.route("/sessions", methods=["POST"])
def create_session():
    uid, role = authenticate(["Therapist"])
    body = body_json()

    # ---- Existence (priority 3): path-none; body FKs, provided only ----
    therapist_id = body.get("therapist_id")
    if therapist_id is not None:
        get_or_404(db.therapists, therapist_id, "ERR_THERAPIST_NOT_FOUND")
    room_id = body.get("room_id")
    if room_id is not None:
        get_or_404(db.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    plan_id = body.get("plan_id")
    if plan_id is not None:
        get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    goal_id = body.get("goal_id")
    if goal_id is not None:
        get_or_404(db.goals, goal_id, "ERR_GOAL_NOT_FOUND")
    material_item_id = body.get("material_item_id")
    if material_item_id is not None:
        get_or_404(db.materials, material_item_id, "ERR_MATERIAL_NOT_FOUND")
    contract_id = body.get("contract_id")
    if contract_id is not None:
        get_or_404(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")

    # ---- Ownership (priority 4) ----
    if therapist_id is not None and therapist_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting therapist is not the session therapist")

    # ---- Field validation (priority 5) ----
    therapist_id = v_str(body, "therapist_id")
    room_id = v_str(body, "room_id")
    plan_id = v_str(body, "plan_id")
    goal_id = v_str(body, "goal_id")
    modality = v_enum(body, "modality", {"INDIVIDUAL", "GROUP"})
    start_raw = v_str(body, "start_utc")
    end_raw = v_str(body, "end_utc")
    start_dt = parse_dt(start_raw, "start_utc")
    end_dt = parse_dt(end_raw, "end_utc")
    if end_dt <= start_dt:
        verr("end_utc must be strictly after start_utc")
    capacity = v_int(body, "capacity", required=False, minv=1, default=1)
    material_qty = v_int(body, "material_qty", required=False, minv=0, default=0)

    plan = db.plans[plan_id]
    goal = db.goals[goal_id]
    material = db.materials[material_item_id] if material_item_id is not None else None
    contract = db.contracts[contract_id] if contract_id is not None else None

    # ---- Plan-active gate (priority 8) ----
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Referenced plan is not ACTIVE")

    # ---- Referential coherence (priority 9): goal belongs to plan ----
    if goal["plan_id"] != plan_id:
        raise ApiError("ERR_GOAL_PLAN_MISMATCH", 409, "goal_id does not belong to plan_id")

    # ---- Therapist calendar (priority 10): half-open overlap ----
    for other in db.sessions.values():
        if other["therapist_id"] == therapist_id and other["scheduling_status"] != "CANCELLED":
            os_, oe_ = _interval(other)
            if start_dt < oe_ and os_ < end_dt:
                raise ApiError("ERR_THERAPIST_UNAVAILABLE", 409, "Therapist has an overlapping session")

    # ---- Room calendar (priority 11): buffer-expanded overlap ----
    buf = timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    for other in db.sessions.values():
        if other["room_id"] == room_id and other["scheduling_status"] != "CANCELLED":
            os_, oe_ = _interval(other)
            if start_dt < (oe_ + buf) and (os_ - buf) < end_dt:
                raise ApiError("ERR_ROOM_UNAVAILABLE", 409, "Room unavailable within turnaround buffer")

    # ---- Material availability (priority 13) ----
    if material is not None:
        available = material["on_hand_quantity"] - material["reserved_quantity"]
        if material_qty > available:
            raise ApiError("ERR_INSUFFICIENT_MATERIAL", 409, "material_qty exceeds available quantity")

    # ---- Contract budget (priority 14) ----
    if contract is not None:
        projected = contract["spent_cents"] + contract["rate_cents_per_session"]
        if projected > contract["budget_cents"]:
            raise ApiError("ERR_CONTRACT_BUDGET_EXCEEDED", 402, "Contract budget exceeded")

    # ---- Commit ----
    sess = new_common()
    sess.update({
        "therapist_id": therapist_id,
        "room_id": room_id,
        "plan_id": plan_id,
        "goal_id": goal_id,
        "contract_id": contract_id,
        "material_item_id": material_item_id,
        "material_qty": material_qty,
        "modality": modality,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "capacity": capacity,
        "attended_count": 0,
        "scheduling_status": "SCHEDULED",
        "billing_status": "UNBILLED",
    })
    db.sessions[sess["id"]] = sess

    if material is not None and material_qty:
        material["reserved_quantity"] += material_qty
        touch(material)
    if contract is not None:
        contract["spent_cents"] += contract["rate_cents_per_session"]
        touch(contract)

    return success(serialize(sess), "object", 201)


@app.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    authenticate(ALL_ROLES)
    s = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    return success(serialize(s), "object", 200)


@app.route("/sessions", methods=["GET"])
def list_sessions():
    authenticate(ALL_ROLES)
    items = filter_by(db.sessions.values(), {
        "therapist_id": "therapist_id",
        "room_id": "room_id",
        "plan_id": "plan_id",
        "goal_id": "goal_id",
        "material_item_id": "material_item_id",
        "contract_id": "contract_id",
        "status": "scheduling_status",
    })
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


def _release_material(sess):
    if sess["material_item_id"] is not None and sess["material_qty"]:
        m = db.materials.get(sess["material_item_id"])
        if m is not None:
            m["reserved_quantity"] -= sess["material_qty"]
            if m["reserved_quantity"] < 0:
                m["reserved_quantity"] = 0
            touch(m)


def _cancel_session(sess):
    """Cancel a SCHEDULED session with full release cascade (manual or discharge)."""
    sess["scheduling_status"] = "CANCELLED"
    touch(sess)
    for e in db.enrollments.values():
        if e["session_id"] == sess["id"] and e["status"] == "ENROLLED":
            e["status"] = "CANCELLED"
            touch(e)
    _release_material(sess)
    if sess["contract_id"] is not None:
        ct = db.contracts.get(sess["contract_id"])
        if ct is not None:
            ct["spent_cents"] -= ct["rate_cents_per_session"]
            touch(ct)


def _recompute_attendance(goal):
    plan = db.plans.get(goal["plan_id"])
    client_id = plan["client_id"] if plan else None
    target = goal["target_sessions"]
    count = 0
    for s in db.sessions.values():
        if s["goal_id"] == goal["id"] and s["scheduling_status"] == "COMPLETED":
            for e in db.enrollments.values():
                if e["session_id"] == s["id"] and e["client_id"] == client_id and e["status"] == "ATTENDED":
                    count += 1
                    break
    val = Decimal(count) / Decimal(target)
    if val > 1:
        val = Decimal(1)
    goal["progress_attendance"] = float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if goal["progress_attendance"] >= 1.0 and goal["status"] == "OPEN":
        goal["status"] = "MET"


def _recompute_rubric(goal):
    scores = []
    for n in db.notes.values():
        if n["status"] != "SIGNED":
            continue
        e = db.enrollments.get(n["enrollment_id"])
        if e is None:
            continue
        s = db.sessions.get(e["session_id"])
        if s is not None and s["goal_id"] == goal["id"]:
            scores.append(n["rubric_score"])
    if not scores:
        goal["progress_rubric"] = 0.0
    else:
        mean = Decimal(sum(scores)) / Decimal(len(scores))
        goal["progress_rubric"] = float((mean / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@app.route("/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    uid, role = authenticate(["Therapist"])
    sess = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    # Ownership
    if sess["therapist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting therapist is not the session therapist")
    body = body_json()
    attended = body.get("attended_client_ids", [])
    if attended is None:
        attended = []
    if not isinstance(attended, list):
        verr("attended_client_ids must be an array")

    # State (priority 7)
    if sess["scheduling_status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session not in SCHEDULED state")
    if current_dt() < parse_dt(sess["start_utc"], "start_utc"):
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session cannot be completed before its start")

    attended_set = list(dict.fromkeys(attended))  # de-dup, keep order
    # Every attended id must be an ENROLLED enrollee of this session.
    session_enrollments = [e for e in db.enrollments.values() if e["session_id"] == sid]
    enrolled_ids = {e["client_id"] for e in session_enrollments if e["status"] == "ENROLLED"}
    for cid in attended_set:
        if cid not in enrolled_ids:
            raise ApiError("ERR_SESSION_INVALID_STATE", 409, "attended_client_ids must be ENROLLED enrollees")

    if attended_set:
        # -> COMPLETED
        for e in session_enrollments:
            if e["status"] == "ENROLLED":
                e["status"] = "ATTENDED" if e["client_id"] in attended_set else "NO_SHOW"
                touch(e)
        sess["attended_count"] = len(attended_set)
        sess["scheduling_status"] = "COMPLETED"
        touch(sess)
        _release_material(sess)
        goal = db.goals.get(sess["goal_id"])
        if goal is not None:
            _recompute_attendance(goal)
            touch(goal)
    else:
        # -> NO_SHOW
        for e in session_enrollments:
            if e["status"] == "ENROLLED":
                e["status"] = "NO_SHOW"
                touch(e)
        sess["attended_count"] = 0
        sess["scheduling_status"] = "NO_SHOW"
        touch(sess)
        _release_material(sess)

    return success(serialize(sess), "object", 200)


@app.route("/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    uid, role = authenticate(["Therapist"])
    sess = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    if sess["therapist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting therapist is not the session therapist")
    body = body_json()
    v_str(body, "cancel_reason", required=False)
    if sess["scheduling_status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session not in SCHEDULED state")
    _cancel_session(sess)
    return success(serialize(sess), "object", 200)


@app.route("/sessions/<sid>/enrollments", methods=["POST"])
def enroll(sid):
    uid, role = authenticate(["Therapist"])
    sess = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    body = body_json()
    client_id = body.get("client_id")
    if client_id is not None:
        get_or_404(db.clients, client_id, "ERR_CLIENT_NOT_FOUND")
    # Ownership
    if sess["therapist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting therapist is not the session therapist")
    client_id = v_str(body, "client_id")

    # Referential coherence (priority 9): not already enrolled (non-cancelled)
    non_cancelled = [e for e in db.enrollments.values()
                     if e["session_id"] == sid and e["status"] != "CANCELLED"]
    for e in non_cancelled:
        if e["client_id"] == client_id:
            raise ApiError("ERR_CLIENT_ALREADY_ENROLLED", 409, "Client already enrolled in session")

    # Group capacity (priority 12)
    if len(non_cancelled) >= sess["capacity"]:
        raise ApiError("ERR_SESSION_FULL", 409, "Session is full")

    en = new_common()
    en.update({"session_id": sid, "client_id": client_id, "status": "ENROLLED"})
    db.enrollments[en["id"]] = en
    return success(serialize(en), "object", 201)


# =============================================================================
# Enrollment
# =============================================================================
@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    authenticate(ALL_ROLES)
    items = filter_by(db.enrollments.values(), {
        "client_id": "client_id",
        "session_id": "session_id",
        "status": "status",
    })
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    authenticate(ALL_ROLES)
    e = get_or_404(db.enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    return success(serialize(e), "object", 200)


# =============================================================================
# ProgressNote
# =============================================================================
@app.route("/enrollments/<eid>/progress-notes", methods=["POST"])
def create_note(eid):
    uid, role = authenticate(["Therapist"])
    e = get_or_404(db.enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    # Ownership: session owner
    sess = db.sessions.get(e["session_id"])
    if sess is not None and sess["therapist_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting therapist is not the session therapist")
    body = body_json()
    narrative = v_str(body, "narrative")
    rubric_score = v_int(body, "rubric_score", required=True, minv=0, maxv=100)
    outcome_rating = v_enum(body, "outcome_rating", {"IMPROVED", "MAINTAINED", "DECLINED"})
    n = new_common()
    n.update({
        "enrollment_id": eid,
        "narrative": narrative,
        "rubric_score": rubric_score,
        "outcome_rating": outcome_rating,
        "status": "DRAFT",
    })
    db.notes[n["id"]] = n
    return success(serialize(n), "object", 201)


@app.route("/enrollments/<eid>/progress-notes", methods=["GET"])
def list_notes(eid):
    authenticate(ALL_ROLES)
    get_or_404(db.enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    items = [n for n in db.notes.values() if n["enrollment_id"] == eid]
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


@app.route("/progress-notes/<nid>/sign", methods=["POST"])
def sign_note(nid):
    authenticate(["Therapist"])
    n = db.notes.get(nid)
    if n is None:
        raise ApiError("ERR_PROGRESS_NOTE_NOT_FOUND", 404, "Progress note not found")
    if n["status"] != "DRAFT":
        # DRAFT -> SIGNED is the only transition; signing a non-DRAFT note is invalid.
        raise ApiError("ERR_VALIDATION", 422, "Progress note is not in DRAFT state")
    n["status"] = "SIGNED"
    touch(n)
    # Recompute rubric for the goal the note ultimately belongs to
    e = db.enrollments.get(n["enrollment_id"])
    if e is not None:
        s = db.sessions.get(e["session_id"])
        if s is not None:
            goal = db.goals.get(s["goal_id"])
            if goal is not None:
                _recompute_rubric(goal)
                touch(goal)
    return success(serialize(n), "object", 200)


# =============================================================================
# Superbill
# =============================================================================
def _estimated_insurance(sb, client):
    therapy_charge = sb["therapy_charge_cents"]
    materials_charge = sb["materials_charge_cents"]
    coins = client["insurance_coinsurance_pct"]
    contracted = client["insurance_contracted_rate_cents"]
    therapy_allowed = min(therapy_charge, contracted)
    materials_allowed = materials_charge
    allowed = therapy_allowed + materials_allowed
    pr = rhu_cents(Decimal(therapy_allowed) * Decimal(str(coins))) + \
        rhu_cents(Decimal(materials_allowed) * Decimal(str(coins)))
    sb["coinsurance_pct"] = coins
    sb["allowed_amount_cents"] = allowed
    sb["patient_responsibility_cents"] = pr
    sb["plan_paid_cents"] = allowed - pr
    sb["adjustment_cents"] = 0


def _sliding_scale(sb, client, session):
    modality = session["modality"]
    hh_size = client["household_size"]
    income = client["household_income_cents"]
    fpl = FPL_BASE_CENTS + FPL_PER_PERSON_CENTS * (hh_size - 1)
    ratio = Decimal(income) / Decimal(fpl)
    if ratio <= Decimal("1.50"):
        discount = Decimal("0.75")
    elif ratio <= Decimal("2.50"):
        discount = Decimal("0.50")
    elif ratio <= Decimal("4.00"):
        discount = Decimal("0.25")
    else:
        discount = Decimal("0.00")
    base = INDIVIDUAL_RATE_CENTS if modality == "INDIVIDUAL" else GROUP_RATE_CENTS
    fee = rhu_cents(Decimal(base) * (Decimal(1) - discount))
    fee = max(MIN_FEE_CENTS, min(fee, base))
    sb["coinsurance_pct"] = None
    sb["allowed_amount_cents"] = None
    sb["patient_responsibility_cents"] = fee
    sb["plan_paid_cents"] = 0
    sb["adjustment_cents"] = sb["billed_amount_cents"] - fee


@app.route("/superbills", methods=["POST"])
def create_superbill():
    authenticate(["BillingSpecialist"])
    body = body_json()
    session_id = body.get("session_id")
    if session_id is not None:
        get_or_404(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    client_id = body.get("client_id")
    if client_id is not None:
        get_or_404(db.clients, client_id, "ERR_CLIENT_NOT_FOUND")
    session_id = v_str(body, "session_id")
    client_id = v_str(body, "client_id")

    sess = db.sessions[session_id]
    client = db.clients[client_id]

    # State (priority 7)
    if sess["scheduling_status"] != "COMPLETED":
        raise ApiError("ERR_SESSION_NOT_COMPLETED", 409, "Session is not COMPLETED")
    if sess["billing_status"] != "UNBILLED":
        raise ApiError("ERR_SESSION_INVALID_STATE", 409, "Session billing status is not UNBILLED")

    # client must be an ATTENDED enrollee of the session
    attended = any(
        e["session_id"] == session_id and e["client_id"] == client_id and e["status"] == "ATTENDED"
        for e in db.enrollments.values()
    )
    if not attended:
        verr("client_id must be an ATTENDED enrollee of the session")

    # Insurance authorization (priority 15)
    if client["payer_type"] == "INSURANCE":
        remaining = client["insurance_visits_authorized"] - client["insurance_visits_used"]
        if remaining < 1:
            raise ApiError("ERR_AUTH_VISITS_EXHAUSTED", 402, "Insurance visits exhausted")

    # Charges
    therapy_charge = INDIVIDUAL_RATE_CENTS if sess["modality"] == "INDIVIDUAL" else GROUP_RATE_CENTS
    materials_charge = 0
    if sess["material_item_id"] is not None:
        mat = db.materials.get(sess["material_item_id"])
        if mat is not None:
            materials_charge = sess["material_qty"] * mat["unit_charge_cents"]
    billed = therapy_charge + materials_charge

    sb = new_common()
    sb.update({
        "session_id": session_id,
        "client_id": client_id,
        "payer_type": client["payer_type"],
        "coinsurance_pct": None,
        "therapy_charge_cents": therapy_charge,
        "materials_charge_cents": materials_charge,
        "billed_amount_cents": billed,
        "allowed_amount_cents": None,
        "patient_responsibility_cents": 0,
        "plan_paid_cents": 0,
        "adjustment_cents": 0,
        "status": "SUBMITTED",
    })

    if client["payer_type"] == "INSURANCE":
        _estimated_insurance(sb, client)
    else:
        _sliding_scale(sb, client, sess)

    db.superbills[sb["id"]] = sb

    # Session billing axis -> BILLED
    sess["billing_status"] = "BILLED"
    touch(sess)
    # Insurance: consume a visit
    if client["payer_type"] == "INSURANCE":
        client["insurance_visits_used"] += 1
        touch(client)

    return success(serialize(sb), "object", 201)


@app.route("/superbills", methods=["GET"])
def list_superbills():
    authenticate(ALL_ROLES)
    items = filter_by(db.superbills.values(), {
        "client_id": "client_id",
        "session_id": "session_id",
        "status": "status",
    })
    page, pg = paginate(items)
    return success([serialize(e) for e in page], "array", 200, pg)


@app.route("/superbills/<sbid>", methods=["GET"])
def get_superbill(sbid):
    authenticate(ALL_ROLES)
    sb = get_or_404(db.superbills, sbid, "ERR_SUPERBILL_NOT_FOUND")
    return success(serialize(sb), "object", 200)


@app.route("/superbills/<sbid>/adjudicate", methods=["POST"])
def adjudicate_superbill(sbid):
    authenticate(["BillingSpecialist"])
    sb = get_or_404(db.superbills, sbid, "ERR_SUPERBILL_NOT_FOUND")
    body = body_json()
    allowed_amount = v_int(body, "allowed_amount_cents", required=True, minv=0)
    if sb["status"] != "SUBMITTED":
        raise ApiError("ERR_SUPERBILL_INVALID_STATE", 409, "Superbill not in SUBMITTED state")

    billed = sb["billed_amount_cents"]
    sb["allowed_amount_cents"] = allowed_amount
    sb["adjustment_cents"] = billed - allowed_amount

    if sb["payer_type"] == "INSURANCE":
        coins = sb["coinsurance_pct"]
        therapy_charge = sb["therapy_charge_cents"]
        materials_charge = sb["materials_charge_cents"]
        therapy_share = Decimal(allowed_amount) * Decimal(therapy_charge) / Decimal(billed)
        materials_share = Decimal(allowed_amount) * Decimal(materials_charge) / Decimal(billed)
        pr = rhu_cents(therapy_share * Decimal(str(coins))) + \
            rhu_cents(materials_share * Decimal(str(coins)))
        sb["patient_responsibility_cents"] = pr
        sb["plan_paid_cents"] = allowed_amount - pr
    else:
        # SELF_PAY: responsibility remains the sliding-scale figure; no plan payment.
        sb["plan_paid_cents"] = 0

    sb["status"] = "ADJUDICATED"
    touch(sb)

    sess = db.sessions.get(sb["session_id"])
    if sess is not None:
        sess["billing_status"] = "ADJUDICATED"
        touch(sess)

    return success(serialize(sb), "object", 200)


@app.route("/superbills/<sbid>/void", methods=["POST"])
def void_superbill(sbid):
    authenticate(["BillingSpecialist"])
    sb = get_or_404(db.superbills, sbid, "ERR_SUPERBILL_NOT_FOUND")
    if sb["status"] not in ("SUBMITTED", "ADJUDICATED"):
        raise ApiError("ERR_SUPERBILL_INVALID_STATE", 409, "Superbill not in a voidable state")

    sb["status"] = "VOIDED"
    touch(sb)

    sess = db.sessions.get(sb["session_id"])
    if sess is not None:
        sess["billing_status"] = "UNBILLED"
        touch(sess)

    client = db.clients.get(sb["client_id"])
    if client is not None and client["payer_type"] == "INSURANCE":
        client["insurance_visits_used"] -= 1
        if client["insurance_visits_used"] < 0:
            client["insurance_visits_used"] = 0
        touch(client)

    return success(serialize(sb), "object", 200)


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
