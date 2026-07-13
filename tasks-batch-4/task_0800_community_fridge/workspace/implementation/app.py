"""
Community Fridge & Food-Sharing Network API.

Single-file Flask implementation. All state is held in-memory (Python dicts keyed
by id) and is wiped on every process start. Nothing is seeded at startup — every
entity is built by the test suite through the declared API surface.

Every behaviour here traces to a sentence in PRD.md.
"""

import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD §2.6, §2.7, §3.3, §2.11)
# ---------------------------------------------------------------------------
ROLES = {"NetworkAdmin", "Steward", "DonorAgent", "SponsorAgent", "Member"}

WARN_TEMP_C = Decimal("8.0")            # §2.7 posture RESTRICTED threshold
CLEAN_INTERVAL_SECONDS = 604800         # §2.7 seven days
MAX_SAFE_TEMP_C = Decimal("5.0")        # §3.5 cold-chain intake ceiling
KG_PER_MEAL = Decimal("1.2")            # §2.11 / §3.9 meal conversion
BUFFER = timedelta(minutes=30)          # §3.3 steward travel buffer

BASE_STIPEND_CENTS = {"COVERAGE": 1500, "CLEANING": 2000}
RATE_LOW = Decimal(50)
RATE_MID = Decimal(30)
RATE_HIGH = Decimal(20)
COLD_CHAIN_BONUS_CENTS = Decimal(500)
HAZARD_MULT = Decimal("1.25")

CLOCK_START = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

FOOD_CATEGORIES = {"PRODUCE", "BAKERY", "DAIRY", "PREPARED", "PACKAGED"}
ALLERGEN_REQUIRED_CATEGORIES = {"BAKERY", "DAIRY", "PREPARED"}
STORAGE_TYPES = {"COLD_CHAIN", "AMBIENT"}
DONOR_TYPES = {"RESTAURANT", "GROCER", "INDIVIDUAL"}
SHIFT_KINDS = {"COVERAGE", "CLEANING"}

STOCK_STATUSES = {"STOCKED", "HELD", "RECALLED"}          # occupy slots §2.8
TERMINAL_BATCH_STATUSES = {"EXPIRED", "DISCARDED", "CLAIMED_OUT"}

# ---------------------------------------------------------------------------
# In-memory store — wiped every process start. No seeding.
# ---------------------------------------------------------------------------
fridges = {}
stewards = {}
donors = {}
grants = {}
shifts = {}
offers = {}
batches = {}
claims = {}
needs = {}

STATE = {"clock": CLOCK_START, "seq": 0}


def now_logical():
    return STATE["clock"]


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers (§2.4 timestamps ISO 8601 UTC, 3 fractional digits)
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid timestamp")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def rhu(value, places=0):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return d.quantize(quant, rounding=ROUND_HALF_UP)


def meals_from_kg(kg):
    return int(rhu(Decimal(kg) / KG_PER_MEAL, 0))


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _request_meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def respond(data, status=200, response_type="object", pagination=None):
    meta = _request_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = _request_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    meta = _request_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    meta = _request_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


# ---------------------------------------------------------------------------
# Common entity helpers
# ---------------------------------------------------------------------------
def base_entity(extra):
    now = now_logical()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(extra)
    return e


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_logical()


def common_out(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


# ---------------------------------------------------------------------------
# Body field validation helpers (ERR_VALIDATION 400)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "body must be a JSON object")
    return body


def req_present(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 400, f"missing field {name}")
    return body[name]


def req_str(body, name):
    v = req_present(body, name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"invalid string {name}")
    return v


def req_enum(body, name, choices):
    v = req_present(body, name)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", 400, f"invalid enum {name}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int_min(body, name, minimum):
    v = req_present(body, name)
    if not _is_int(v) or v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"invalid integer {name}")
    return v


def req_num_pos(body, name):
    v = req_present(body, name)
    if not _is_num(v) or Decimal(str(v)) <= 0:
        raise ApiError("ERR_VALIDATION", 400, f"invalid number {name}")
    return Decimal(str(v))


def req_num(body, name):
    v = req_present(body, name)
    if not _is_num(v):
        raise ApiError("ERR_VALIDATION", 400, f"invalid number {name}")
    return Decimal(str(v))


def opt_num_nonneg(body, name, default):
    if name not in body or body[name] is None:
        return Decimal(str(default))
    v = body[name]
    if not _is_num(v) or Decimal(str(v)) < 0:
        raise ApiError("ERR_VALIDATION", 400, f"invalid number {name}")
    return Decimal(str(v))


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"invalid boolean {name}")
    return v


def req_dt(body, name):
    return parse_dt(req_present(body, name))


# ---------------------------------------------------------------------------
# Lookups (ERR_NOT_FOUND 404)
# ---------------------------------------------------------------------------
def find(store, ident):
    e = store.get(ident)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return e


def batches_for_fridge(fid):
    return [b for b in batches.values() if b["fridge_id"] == fid]


def needs_for_fridge(fid):
    return [n for n in needs.values() if n["fridge_id"] == fid]


def claims_for_batch(bid):
    return [c for c in claims.values() if c["donation_batch_id"] == bid]


# ---------------------------------------------------------------------------
# Fridge derived quantities (PRD §2.7, §2.8, §2.9, §3.9)
# ---------------------------------------------------------------------------
def active_recall_count(fid):
    return sum(1 for b in batches_for_fridge(fid) if b["status"] == "RECALLED")


def stock_slots_used(fid):
    return sum(b["slot_footprint"] for b in batches_for_fridge(fid)
               if b["status"] in STOCK_STATUSES)


def compute_posture(f):
    if active_recall_count(f["id"]) >= 1:
        return "QUARANTINED"
    stale = (now_logical() - f["last_cleaned_at"]).total_seconds() > CLEAN_INTERVAL_SECONDS
    if f["current_temp_c"] > WARN_TEMP_C or stale:
        return "RESTRICTED"
    return "OPERATIONAL"


def budget_granted_cents(fid):
    return sum(g["amount_cents"] for g in grants.values()
               if g["fridge_id"] == fid and g["status"] == "ACTIVE")


def budget_committed_cents(fid):
    return sum(s["reimbursement_amount_cents"] for s in shifts.values()
               if s["fridge_id"] == fid and s["status"] == "COMPLETED")


def total_meals_provided(fid):
    # §3.9 / §2.11 — round per batch first, THEN sum.
    return sum(meals_from_kg(b["realized_quantity_kg"])
               for b in batches_for_fridge(fid)
               if b["status"] in TERMINAL_BATCH_STATUSES)


def available_quantity(b):
    claimed = sum((c["quantity_kg"] for c in claims_for_batch(b["id"])
                   if c["status"] != "VOIDED"), Decimal(0))
    return b["declared_quantity_kg"] - claimed


def freeze_realized(b):
    total = sum((c["quantity_kg"] for c in claims_for_batch(b["id"])
                 if c["status"] != "VOIDED"), Decimal(0))
    b["realized_quantity_kg"] = total
    b["realized_meals"] = meals_from_kg(total)


# ---------------------------------------------------------------------------
# Cascade reconciliation (PRD §2.7)
# ---------------------------------------------------------------------------
def reconcile_cascade(f):
    posture = compute_posture(f)
    if posture == "QUARANTINED":
        for b in batches_for_fridge(f["id"]):
            if b["status"] == "STOCKED":
                b["status"] = "HELD"
                touch(b)
        for n in needs_for_fridge(f["id"]):
            if n["status"] == "OPEN":
                n["status"] = "SUSPENDED"
                touch(n)
    else:
        for b in batches_for_fridge(f["id"]):
            if b["status"] == "HELD":
                b["status"] = "STOCKED"
                touch(b)
        for n in needs_for_fridge(f["id"]):
            if n["status"] == "SUSPENDED":
                n["status"] = "OPEN"
                touch(n)


# ---------------------------------------------------------------------------
# Reliability (PRD §3.3) & reimbursement (PRD §3.3)
# ---------------------------------------------------------------------------
def steward_completed_count(sid):
    return sum(1 for s in shifts.values()
               if s["steward_id"] == sid and s["status"] == "COMPLETED")


def steward_reliability(sid):
    completed = steward_completed_count(sid)
    missed = sum(1 for s in shifts.values()
                 if s["steward_id"] == sid and s["status"] == "MISSED")
    upcoming = sum(1 for s in shifts.values()
                   if s["steward_id"] == sid and s["status"] == "SCHEDULED"
                   and s["end_at"] > now_logical())
    if (completed + missed) > 0:
        actual = rhu(Decimal(completed) / Decimal(completed + missed), 2)
    else:
        actual = Decimal("1.00")
    denom_p = completed + missed + upcoming
    if denom_p > 0:
        projected = rhu(Decimal(completed + upcoming) / Decimal(denom_p), 2)
    else:
        projected = Decimal("1.00")
    return float(actual), float(projected)


def compute_reimbursement(shift, fridge):
    base = Decimal(BASE_STIPEND_CENTS[shift["kind"]])
    m = shift["miles_traveled"]
    if m <= 5:
        mileage = rhu(m * RATE_LOW, 0)
    elif m <= 20:
        mileage = rhu(Decimal(5) * RATE_LOW + (m - 5) * RATE_MID, 0)
    else:
        mileage = rhu(Decimal(5) * RATE_LOW + Decimal(15) * RATE_MID
                      + (m - 20) * RATE_HIGH, 0)
    bonus = COLD_CHAIN_BONUS_CENTS if shift["handled_cold_chain"] else Decimal(0)
    factor = HAZARD_MULT if compute_posture(fridge) == "RESTRICTED" else Decimal("1.0")
    total = rhu((base + mileage + bonus) * factor, 0)
    return int(total)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_fridge(f):
    ssu = stock_slots_used(f["id"])
    granted = budget_granted_cents(f["id"])
    committed = budget_committed_cents(f["id"])
    out = common_out(f)
    out.update({
        "name": f["name"],
        "location_label": f["location_label"],
        "capacity_slots": f["capacity_slots"],
        "current_temp_c": float(f["current_temp_c"]),
        "last_cleaned_at": fmt_dt(f["last_cleaned_at"]),
        "ops_run_index": f["ops_run_index"],
        "active_recall_count": active_recall_count(f["id"]),
        "stock_slots_used": ssu,
        "free_slots": f["capacity_slots"] - ssu,
        "safety_posture": compute_posture(f),
        "budget_granted_cents": granted,
        "budget_committed_cents": committed,
        "budget_available_cents": granted - committed,
        "total_meals_provided": total_meals_provided(f["id"]),
    })
    return out


def ser_steward(s):
    actual, projected = steward_reliability(s["id"])
    out = common_out(s)
    out.update({
        "name": s["name"],
        "email": s["email"],
        "status": s["status"],
        "missed_count": s["missed_count"],
        "completed_count": steward_completed_count(s["id"]),
        "reliability_actual": actual,
        "reliability_projected": projected,
    })
    return out


def ser_donor(d):
    out = common_out(d)
    out.update({
        "name": d["name"],
        "donor_type": d["donor_type"],
        "contact": d["contact"],
    })
    return out


def ser_grant(g):
    out = common_out(g)
    out.update({
        "fridge_id": g["fridge_id"],
        "sponsor_name": g["sponsor_name"],
        "amount_cents": g["amount_cents"],
        "status": g["status"],
    })
    return out


def ser_shift(s):
    out = common_out(s)
    out.update({
        "fridge_id": s["fridge_id"],
        "steward_id": s["steward_id"],
        "kind": s["kind"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "status": s["status"],
        "miles_traveled": float(s["miles_traveled"]),
        "handled_cold_chain": s["handled_cold_chain"],
        "reimbursement_amount_cents": s["reimbursement_amount_cents"],
        "completed_at": fmt_dt(s["completed_at"]) if s["completed_at"] else None,
    })
    return out


def ser_offer(o):
    out = common_out(o)
    out.update({
        "donor_id": o["donor_id"],
        "fridge_id": o["fridge_id"],
        "description": o["description"],
        "estimated_quantity_kg": float(o["estimated_quantity_kg"]),
        "pickup_by": fmt_dt(o["pickup_by"]),
        "status": o["status"],
    })
    return out


def ser_batch(b):
    out = common_out(b)
    out.update({
        "fridge_id": b["fridge_id"],
        "steward_id": b["steward_id"],
        "surplus_offer_id": b["surplus_offer_id"],
        "food_category": b["food_category"],
        "storage_type": b["storage_type"],
        "declared_quantity_kg": float(b["declared_quantity_kg"]),
        "slot_footprint": b["slot_footprint"],
        "intake_temp_c": float(b["intake_temp_c"]),
        "use_by": fmt_dt(b["use_by"]),
        "allergens": list(b["allergens"]),
        "status": b["status"],
        "available_quantity_kg": float(available_quantity(b)),
        "realized_quantity_kg": float(b["realized_quantity_kg"]),
        "provisional_meals": b["provisional_meals"],
        "realized_meals": b["realized_meals"],
    })
    return out


def ser_claim(c):
    out = common_out(c)
    out.update({
        "donation_batch_id": c["donation_batch_id"],
        "fridge_id": c["fridge_id"],
        "quantity_kg": float(c["quantity_kg"]),
        "recipient_label": c["recipient_label"],
        "status": c["status"],
    })
    return out


def ser_need(n):
    out = common_out(n)
    out.update({
        "fridge_id": n["fridge_id"],
        "item_description": n["item_description"],
        "quantity_needed": n["quantity_needed"],
        "needed_by": fmt_dt(n["needed_by"]),
        "status": n["status"],
    })
    return out


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, f"invalid {name}")


def list_response(items, serializer):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    limit = _parse_int_param("limit", 10)
    offset = _parse_int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return respond([serializer(e) for e in page], 200, "array", pagination)


# ===========================================================================
# ENDPOINTS
# ===========================================================================

# ---- Fridge -------------------------------------------------------------
@app.route("/fridges", methods=["POST"])
def create_fridge():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    body = get_body()
    name = req_str(body, "name")
    location_label = req_str(body, "location_label")
    capacity_slots = req_int_min(body, "capacity_slots", 1)
    now = now_logical()
    f = base_entity({
        "name": name,
        "location_label": location_label,
        "capacity_slots": capacity_slots,
        "current_temp_c": Decimal("4.0"),
        "last_cleaned_at": now,
        "ops_run_index": 0,
    })
    fridges[f["id"]] = f
    return respond(ser_fridge(f), 201, "object")


@app.route("/fridges/<fridge_id>", methods=["GET"])
def get_fridge(fridge_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "DonorAgent", "SponsorAgent", "Member"})
    f = find(fridges, fridge_id)
    return respond(ser_fridge(f), 200, "object")


@app.route("/fridges/<fridge_id>/temperature", methods=["POST"])
def record_temperature(fridge_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward"})
    f = find(fridges, fridge_id)
    body = get_body()
    reading = req_num(body, "reading_c")
    f["current_temp_c"] = reading
    touch(f)
    return respond(ser_fridge(f), 200, "object")


@app.route("/fridges/<fridge_id>/run-ops", methods=["POST"])
def run_ops(fridge_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    f = find(fridges, fridge_id)
    now = now_logical()
    f["ops_run_index"] += 1

    # STOCKED / HELD batches past use_by -> EXPIRED (frees slots, freezes realized)
    for b in batches_for_fridge(fridge_id):
        if b["status"] in ("STOCKED", "HELD") and now >= b["use_by"]:
            b["status"] = "EXPIRED"
            freeze_realized(b)
            for c in claims_for_batch(b["id"]):
                if c["status"] == "OPEN":
                    c["status"] = "EXPIRED"
                    touch(c)
            touch(b)

    # OFFERED / ACCEPTED offers past pickup_by -> EXPIRED (offers targeting this fridge)
    for o in offers.values():
        if o["fridge_id"] == fridge_id and o["status"] in ("OFFERED", "ACCEPTED") \
                and now >= o["pickup_by"]:
            o["status"] = "EXPIRED"
            touch(o)

    # OPEN / SUSPENDED needs past needed_by -> EXPIRED
    for n in needs_for_fridge(fridge_id):
        if n["status"] in ("OPEN", "SUSPENDED") and now >= n["needed_by"]:
            n["status"] = "EXPIRED"
            touch(n)

    # SCHEDULED shifts past end_at -> MISSED (steward.missed_count += 1)
    for s in shifts.values():
        if s["fridge_id"] == fridge_id and s["status"] == "SCHEDULED" \
                and now >= s["end_at"]:
            s["status"] = "MISSED"
            touch(s)
            st = stewards.get(s["steward_id"])
            if st is not None:
                st["missed_count"] += 1
                touch(st)

    touch(f)
    return respond(ser_fridge(f), 200, "object")


# ---- Steward ------------------------------------------------------------
@app.route("/stewards", methods=["POST"])
def create_steward():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    s = base_entity({
        "name": name,
        "email": email,
        "status": "ACTIVE",
        "missed_count": 0,
    })
    stewards[s["id"]] = s
    return respond(ser_steward(s), 201, "object")


@app.route("/stewards/<steward_id>", methods=["GET"])
def get_steward(steward_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member", "DonorAgent", "SponsorAgent"})
    s = find(stewards, steward_id)
    return respond(ser_steward(s), 200, "object")


@app.route("/stewards/<steward_id>/suspend", methods=["POST"])
def suspend_steward(steward_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    s = find(stewards, steward_id)
    s["status"] = "SUSPENDED"
    touch(s)
    return respond(ser_steward(s), 200, "object")


# ---- Donor --------------------------------------------------------------
@app.route("/donors", methods=["POST"])
def create_donor():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    body = get_body()
    name = req_str(body, "name")
    donor_type = req_enum(body, "donor_type", DONOR_TYPES)
    contact = req_str(body, "contact")
    d = base_entity({"name": name, "donor_type": donor_type, "contact": contact})
    donors[d["id"]] = d
    return respond(ser_donor(d), 201, "object")


@app.route("/donors/<donor_id>", methods=["GET"])
def get_donor(donor_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "DonorAgent", "Steward"})
    d = find(donors, donor_id)
    return respond(ser_donor(d), 200, "object")


# ---- SponsorGrant -------------------------------------------------------
@app.route("/fridges/<fridge_id>/grants", methods=["POST"])
def create_grant(fridge_id):
    _uid, role = get_auth()
    require_role(role, {"SponsorAgent", "NetworkAdmin"})
    f = find(fridges, fridge_id)
    body = get_body()
    sponsor_name = req_str(body, "sponsor_name")
    amount_cents = req_int_min(body, "amount_cents", 1)
    g = base_entity({
        "fridge_id": f["id"],
        "sponsor_name": sponsor_name,
        "amount_cents": amount_cents,
        "status": "ACTIVE",
    })
    grants[g["id"]] = g
    touch(f)  # budget_granted / budget_available changed (§2.4)
    return respond(ser_grant(g), 201, "object")


@app.route("/grants/<grant_id>", methods=["GET"])
def get_grant(grant_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "SponsorAgent", "Steward"})
    g = find(grants, grant_id)
    return respond(ser_grant(g), 200, "object")


@app.route("/grants", methods=["GET"])
def list_grants():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "SponsorAgent", "Steward"})
    items = list(grants.values())
    fid = request.args.get("fridge_id")
    if fid is not None:
        items = [g for g in items if g["fridge_id"] == fid]
    return list_response(items, ser_grant)


@app.route("/grants/<grant_id>/cancel", methods=["POST"])
def cancel_grant(grant_id):
    _uid, role = get_auth()
    require_role(role, {"SponsorAgent", "NetworkAdmin"})
    g = find(grants, grant_id)
    if g["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "grant not ACTIVE")
    f = find(fridges, g["fridge_id"])
    available = budget_granted_cents(f["id"]) - budget_committed_cents(f["id"])
    if available < g["amount_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 402, "cannot withdraw committed funds")
    g["status"] = "CANCELLED"
    touch(g)
    touch(f)  # budget changed
    return respond(ser_grant(g), 200, "object")


# ---- StewardShift -------------------------------------------------------
@app.route("/fridges/<fridge_id>/shifts", methods=["POST"])
def create_shift(fridge_id):
    uid, role = get_auth()
    require_role(role, {"Steward", "NetworkAdmin"})
    body = get_body()
    # ownership: a Steward may only schedule their own steward_id (§2.1 / RBAC)
    if role == "Steward":
        sid_body = body.get("steward_id")
        if sid_body is not None and sid_body != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "steward may only schedule own shifts")
    f = find(fridges, fridge_id)
    steward_id = req_str(body, "steward_id")
    kind = req_enum(body, "kind", SHIFT_KINDS)
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    find(stewards, steward_id)  # existence

    if not (start_at < end_at):
        raise ApiError("ERR_PICKUP_WINDOW_INVALID", 422, "start_at must be before end_at")

    # COVERAGE overlap on same fridge (half-open interval)
    if kind == "COVERAGE":
        for s in shifts.values():
            if s["fridge_id"] == fridge_id and s["kind"] == "COVERAGE" \
                    and s["status"] in ("SCHEDULED", "COMPLETED"):
                if start_at < s["end_at"] and s["start_at"] < end_at:
                    raise ApiError("ERR_SHIFT_OVERLAP_FRIDGE", 409, "coverage overlap")

    # steward double-booking across any fridge (buffer-expanded closed interval)
    for s in shifts.values():
        if s["steward_id"] == steward_id and s["status"] in ("SCHEDULED", "COMPLETED"):
            if (s["start_at"] - BUFFER) <= end_at and start_at <= (s["end_at"] + BUFFER):
                raise ApiError("ERR_STEWARD_DOUBLE_BOOKED", 409, "steward double-booked")

    sh = base_entity({
        "fridge_id": f["id"],
        "steward_id": steward_id,
        "kind": kind,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
        "miles_traveled": Decimal("0"),
        "handled_cold_chain": False,
        "reimbursement_amount_cents": 0,
        "completed_at": None,
    })
    shifts[sh["id"]] = sh
    return respond(ser_shift(sh), 201, "object")


@app.route("/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member"})
    s = find(shifts, shift_id)
    return respond(ser_shift(s), 200, "object")


@app.route("/shifts", methods=["GET"])
def list_shifts():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member"})
    items = list(shifts.values())
    fid = request.args.get("fridge_id")
    sid = request.args.get("steward_id")
    if fid is not None:
        items = [s for s in items if s["fridge_id"] == fid]
    if sid is not None:
        items = [s for s in items if s["steward_id"] == sid]
    return list_response(items, ser_shift)


@app.route("/shifts/<shift_id>/complete", methods=["POST"])
def complete_shift(shift_id):
    uid, role = get_auth()
    require_role(role, {"Steward", "NetworkAdmin"})
    s = find(shifts, shift_id)
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "shift not SCHEDULED")
    steward = find(stewards, s["steward_id"])
    # ordered gating per §3.3
    if steward["status"] != "ACTIVE":
        raise ApiError("ERR_STEWARD_SUSPENDED", 409, "steward is suspended")
    if now_logical() < s["start_at"]:
        raise ApiError("ERR_INVALID_STATE", 409, "shift has not started")
    if role == "Steward" and uid != s["steward_id"]:
        raise ApiError("ERR_STEWARD_NOT_ASSIGNED", 409, "not the assigned steward")

    body = get_body()
    miles = opt_num_nonneg(body, "miles_traveled", 0)
    cold = opt_bool(body, "handled_cold_chain", False)
    s["miles_traveled"] = miles
    s["handled_cold_chain"] = cold

    f = find(fridges, s["fridge_id"])
    # reimbursement reads posture BEFORE the cleaning update lifts RESTRICTED (§3.3)
    reimb = compute_reimbursement(s, f)
    s["reimbursement_amount_cents"] = reimb
    s["status"] = "COMPLETED"
    s["completed_at"] = now_logical()
    touch(s)

    if s["kind"] == "CLEANING":
        s["_prev_last_cleaned"] = f["last_cleaned_at"]
        f["last_cleaned_at"] = now_logical()
    touch(f)  # budget_committed changed (+ possibly last_cleaned / posture)
    return respond(ser_shift(s), 200, "object")


@app.route("/shifts/<shift_id>/fail-inspection", methods=["POST"])
def fail_inspection(shift_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    s = find(shifts, shift_id)
    if s["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "shift not COMPLETED")
    if s["kind"] != "CLEANING":
        raise ApiError("ERR_INVALID_STATE", 409, "only cleaning shifts can fail inspection")
    f = find(fridges, s["fridge_id"])
    s["status"] = "SCHEDULED"
    s["reimbursement_amount_cents"] = 0
    s["completed_at"] = None
    if "_prev_last_cleaned" in s:
        f["last_cleaned_at"] = s["_prev_last_cleaned"]
    touch(s)
    touch(f)  # budget + last_cleaned + posture reconciled
    return respond(ser_shift(s), 200, "object")


# ---- SurplusOffer -------------------------------------------------------
@app.route("/donors/<donor_id>/offers", methods=["POST"])
def create_offer(donor_id):
    uid, role = get_auth()
    require_role(role, {"DonorAgent", "NetworkAdmin"})
    if role == "DonorAgent" and uid != donor_id:
        raise ApiError("ERR_DONOR_MISMATCH", 403, "donor agent may only act on own donor")
    d = find(donors, donor_id)
    body = get_body()
    fridge_id = req_str(body, "fridge_id")
    description = req_str(body, "description")
    estimated_quantity_kg = req_num_pos(body, "estimated_quantity_kg")
    pickup_by = req_dt(body, "pickup_by")
    find(fridges, fridge_id)  # body FK existence
    o = base_entity({
        "donor_id": d["id"],
        "fridge_id": fridge_id,
        "description": description,
        "estimated_quantity_kg": estimated_quantity_kg,
        "pickup_by": pickup_by,
        "status": "OFFERED",
    })
    offers[o["id"]] = o
    return respond(ser_offer(o), 201, "object")


@app.route("/offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "DonorAgent", "Steward"})
    o = find(offers, offer_id)
    return respond(ser_offer(o), 200, "object")


@app.route("/offers", methods=["GET"])
def list_offers():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "DonorAgent", "Steward"})
    items = list(offers.values())
    did = request.args.get("donor_id")
    fid = request.args.get("fridge_id")
    if did is not None:
        items = [o for o in items if o["donor_id"] == did]
    if fid is not None:
        items = [o for o in items if o["fridge_id"] == fid]
    return list_response(items, ser_offer)


@app.route("/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    _uid, role = get_auth()
    require_role(role, {"Steward", "NetworkAdmin"})
    o = find(offers, offer_id)
    if o["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "offer not OFFERED")
    f = find(fridges, o["fridge_id"])
    if compute_posture(f) != "OPERATIONAL":
        raise ApiError("ERR_FRIDGE_NOT_OPERATIONAL", 409, "fridge not operational")
    if now_logical() >= o["pickup_by"]:
        raise ApiError("ERR_OFFER_EXPIRED", 409, "offer past pickup_by")
    o["status"] = "ACCEPTED"
    touch(o)
    return respond(ser_offer(o), 200, "object")


# ---- DonationBatch ------------------------------------------------------
@app.route("/fridges/<fridge_id>/donation-batches", methods=["POST"])
def create_batch(fridge_id):
    _uid, role = get_auth()
    require_role(role, {"Steward", "NetworkAdmin"})
    f = find(fridges, fridge_id)
    body = get_body()

    # required fields / body FK existence
    steward_id = req_str(body, "steward_id")
    food_category = req_enum(body, "food_category", FOOD_CATEGORIES)
    storage_type = req_enum(body, "storage_type", STORAGE_TYPES)
    declared_quantity_kg = req_num_pos(body, "declared_quantity_kg")
    slot_footprint = req_int_min(body, "slot_footprint", 1)
    intake_temp_c = req_num(body, "intake_temp_c")
    use_by = req_dt(body, "use_by")
    allergens = body.get("allergens", [])
    if allergens is None:
        allergens = []
    if not isinstance(allergens, list) or any(not isinstance(a, str) for a in allergens):
        raise ApiError("ERR_VALIDATION", 400, "invalid allergens")
    surplus_offer_id = body.get("surplus_offer_id")
    expected_version = req_present(body, "expected_fridge_version")
    if not _is_int(expected_version):
        raise ApiError("ERR_VALIDATION", 400, "invalid expected_fridge_version")

    find(stewards, steward_id)  # existence
    offer = None
    if surplus_offer_id is not None:
        offer = find(offers, surplus_offer_id)  # existence

    # gating order §3.5: OCC -> operational -> temp -> allergen -> capacity
    if expected_version != f["version"]:
        raise ApiError("ERR_FRIDGE_VERSION_CONFLICT", 412, "stale fridge version")
    if compute_posture(f) != "OPERATIONAL":
        raise ApiError("ERR_FRIDGE_NOT_OPERATIONAL", 409, "fridge not operational")
    if storage_type == "COLD_CHAIN" and intake_temp_c > MAX_SAFE_TEMP_C:
        raise ApiError("ERR_TEMP_UNSAFE", 422, "cold-chain intake temperature unsafe")
    if food_category in ALLERGEN_REQUIRED_CATEGORIES and len(allergens) == 0:
        raise ApiError("ERR_ALLERGEN_LABEL_REQUIRED", 422, "allergen labels required")
    free_slots = f["capacity_slots"] - stock_slots_used(f["id"])
    if slot_footprint > free_slots:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409, "slot footprint exceeds free slots")

    b = base_entity({
        "fridge_id": f["id"],
        "steward_id": steward_id,
        "surplus_offer_id": surplus_offer_id,
        "food_category": food_category,
        "storage_type": storage_type,
        "declared_quantity_kg": declared_quantity_kg,
        "slot_footprint": slot_footprint,
        "intake_temp_c": intake_temp_c,
        "use_by": use_by,
        "allergens": list(allergens),
        "status": "STOCKED",
        "realized_quantity_kg": Decimal("0"),
        "provisional_meals": meals_from_kg(declared_quantity_kg),
        "realized_meals": 0,
    })
    batches[b["id"]] = b
    touch(f)  # slots changed + version increment (invalidates stale OCC) §3.5

    if offer is not None and offer["status"] == "ACCEPTED":
        offer["status"] = "CONVERTED"
        touch(offer)

    return respond(ser_batch(b), 201, "object")


@app.route("/donation-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member", "DonorAgent"})
    b = find(batches, batch_id)
    return respond(ser_batch(b), 200, "object")


@app.route("/donation-batches", methods=["GET"])
def list_batches():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member", "DonorAgent"})
    items = list(batches.values())
    fid = request.args.get("fridge_id")
    sid = request.args.get("steward_id")
    oid = request.args.get("surplus_offer_id")
    if fid is not None:
        items = [b for b in items if b["fridge_id"] == fid]
    if sid is not None:
        items = [b for b in items if b["steward_id"] == sid]
    if oid is not None:
        items = [b for b in items if b["surplus_offer_id"] == oid]
    return list_response(items, ser_batch)


@app.route("/donation-batches/<batch_id>/recall", methods=["POST"])
def recall_batch(batch_id):
    _uid, role = get_auth()
    require_role(role, {"Steward", "NetworkAdmin"})
    b = find(batches, batch_id)
    if b["status"] not in ("STOCKED", "HELD"):
        raise ApiError("ERR_INVALID_STATE", 409, "batch not STOCKED/HELD")
    b["status"] = "RECALLED"
    for c in claims_for_batch(b["id"]):
        if c["status"] == "OPEN":
            c["status"] = "VOIDED"
            touch(c)
    touch(b)
    f = find(fridges, b["fridge_id"])
    touch(f)  # active_recall_count -> posture -> QUARANTINED
    reconcile_cascade(f)
    return respond(ser_batch(b), 200, "object")


@app.route("/donation-batches/<batch_id>/discard", methods=["POST"])
def discard_batch(batch_id):
    _uid, role = get_auth()
    require_role(role, {"Steward", "NetworkAdmin"})
    b = find(batches, batch_id)
    if b["status"] not in ("RECALLED", "STOCKED"):
        raise ApiError("ERR_INVALID_STATE", 409, "batch not RECALLED/STOCKED")
    b["status"] = "DISCARDED"
    freeze_realized(b)
    touch(b)
    f = find(fridges, b["fridge_id"])
    touch(f)  # slots freed + active_recall_count recomputed
    reconcile_cascade(f)
    return respond(ser_batch(b), 200, "object")


# ---- Claim --------------------------------------------------------------
@app.route("/donation-batches/<batch_id>/claims", methods=["POST"])
def create_claim(batch_id):
    _uid, role = get_auth()
    require_role(role, {"Member", "Steward", "NetworkAdmin"})
    b = find(batches, batch_id)
    body = get_body()
    quantity_kg = req_num_pos(body, "quantity_kg")
    recipient_label = body.get("recipient_label")
    if recipient_label is not None and not isinstance(recipient_label, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid recipient_label")

    if b["status"] != "STOCKED":
        raise ApiError("ERR_BATCH_RECALLED", 409, "batch not STOCKED")
    if now_logical() >= b["use_by"]:
        raise ApiError("ERR_USE_BY_PASSED", 422, "batch past use_by")
    available = available_quantity(b)
    if available <= 0 or quantity_kg > available:
        raise ApiError("ERR_NO_PORTIONS", 409, "insufficient availability")

    c = base_entity({
        "donation_batch_id": b["id"],
        "fridge_id": b["fridge_id"],
        "quantity_kg": quantity_kg,
        "recipient_label": recipient_label,
        "status": "OPEN",
    })
    claims[c["id"]] = c

    if available_quantity(b) == 0:
        b["status"] = "CLAIMED_OUT"
        freeze_realized(b)
        touch(b)
        f = find(fridges, b["fridge_id"])
        touch(f)  # slots freed
    return respond(ser_claim(c), 201, "object")


@app.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member"})
    c = find(claims, claim_id)
    return respond(ser_claim(c), 200, "object")


@app.route("/claims", methods=["GET"])
def list_claims():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member"})
    items = list(claims.values())
    bid = request.args.get("donation_batch_id")
    fid = request.args.get("fridge_id")
    if bid is not None:
        items = [c for c in items if c["donation_batch_id"] == bid]
    if fid is not None:
        items = [c for c in items if c["fridge_id"] == fid]
    return list_response(items, ser_claim)


# ---- NeedPosting --------------------------------------------------------
@app.route("/fridges/<fridge_id>/needs", methods=["POST"])
def create_need(fridge_id):
    _uid, role = get_auth()
    require_role(role, {"Member", "Steward", "NetworkAdmin"})
    f = find(fridges, fridge_id)
    body = get_body()
    item_description = req_str(body, "item_description")
    quantity_needed = req_int_min(body, "quantity_needed", 1)
    needed_by = req_dt(body, "needed_by")
    n = base_entity({
        "fridge_id": f["id"],
        "item_description": item_description,
        "quantity_needed": quantity_needed,
        "needed_by": needed_by,
        "status": "OPEN",
    })
    needs[n["id"]] = n
    return respond(ser_need(n), 201, "object")


@app.route("/needs/<need_id>", methods=["GET"])
def get_need(need_id):
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member"})
    n = find(needs, need_id)
    return respond(ser_need(n), 200, "object")


@app.route("/needs", methods=["GET"])
def list_needs():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin", "Steward", "Member"})
    items = list(needs.values())
    fid = request.args.get("fridge_id")
    if fid is not None:
        items = [n for n in items if n["fridge_id"] == fid]
    return list_response(items, ser_need)


# ---- Logical clock (test-driving) ---------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_auth()
    require_role(role, {"NetworkAdmin"})
    body = get_body()
    to_iso = parse_dt(req_present(body, "to_iso8601"))
    if to_iso < STATE["clock"]:
        raise ApiError("ERR_VALIDATION", 400, "clock cannot move backward")
    STATE["clock"] = to_iso
    return respond({}, 200, "object")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
