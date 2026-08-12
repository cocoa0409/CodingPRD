"""Mushroom Farm API - Task 1249 implementation."""
import os
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================================
# Logical clock
# =========================================================================
START_TIME = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": START_TIME}


def now():
    return _clock["now"]


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    # Format with millisecond precision
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"Invalid ISO8601 timestamp: {s}", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =========================================================================
# Decimal helpers
# =========================================================================

def D(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(x):
    """Convert Decimal to JSON-serializable number: int if whole, else float."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        # Return as float but rounded to 2 decimal places to avoid repr issues
        return float(x)
    return x


# =========================================================================
# In-memory store
# =========================================================================
db = {
    "varieties": {},
    "buyers": {},
    "buyer_commitments": {},
    "commitment_lines": {},
    "substrate_batches": {},
    "pasteurization_tunnels": {},
    "pasteurization_cycles": {},
    "growing_rooms": {},
    "room_cycles": {},
    "flush_harvests": {},
    "harvest_pieces": {},
    "workers": {},
    "contamination_events": {},
    "packaged_lots": {},
    "spent_substrate_lots": {},
}


# =========================================================================
# Errors
# =========================================================================
class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    raise ApiError(error_id, message, http_status)


# =========================================================================
# Response envelope
# =========================================================================

def make_request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def ok_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": iso(now()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": iso(now()),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": iso(now()),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "Not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_generic(e):
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


# =========================================================================
# Auth / RBAC
# =========================================================================
ROLE_FARM = "FarmManager"
ROLE_COMPOST = "CompostSupervisor"
ROLE_GRADING = "GradingInspector"
ROLE_CREW = "HarvestCrewLead"
ROLE_PAYROLL = "PayrollClerk"
ROLE_SALES = "SalesManager"
ROLE_QUALITY = "QualityInspector"
ROLE_BUYER_PORTAL = "BuyerPortal"
ROLE_ANY = "Any"

ALL_ROLES = {ROLE_FARM, ROLE_COMPOST, ROLE_GRADING, ROLE_CREW, ROLE_PAYROLL,
             ROLE_SALES, ROLE_QUALITY, ROLE_BUYER_PORTAL, ROLE_ANY}


def get_auth():
    """Return (user_id, role). Raises on missing/empty headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty", 400)
    # Identity resolution for entity-backed roles (priority 2)
    if role == ROLE_CREW:
        if uid not in db["workers"]:
            err("ERR_IDENTITY_NOT_RESOLVED", f"No Worker with id {uid}", 403)
    elif role == ROLE_BUYER_PORTAL:
        if uid not in db["buyers"]:
            err("ERR_IDENTITY_NOT_RESOLVED", f"No Buyer with id {uid}", 403)
    return uid, role


def require_role(*allowed):
    """Check role permission. Any means any authenticated role (for GETs)."""
    uid, role = get_auth()
    if ROLE_ANY in allowed:
        return uid, role
    if role not in allowed:
        err("ERR_FORBIDDEN", f"Role {role} not permitted for this operation", 403)
    return uid, role


# =========================================================================
# Pagination
# =========================================================================

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except Exception:
            err("ERR_INVALID_REQUEST", "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", "limit must be between 1 and 100", 400)
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except Exception:
            err("ERR_INVALID_REQUEST", "offset must be an integer", 400)
        if offset < 0:
            err("ERR_INVALID_REQUEST", "offset must be >= 0", 400)
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    # Sort by created_at ascending
    items = sorted(items, key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array(page, limit, offset, total)


# =========================================================================
# Body helpers
# =========================================================================

def body():
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data


def require_field(data, name):
    if name not in data or data[name] is None:
        err("ERR_INVALID_REQUEST", f"Missing required field: {name}", 400)
    return data[name]


def require_number(data, name, positive=False, integer=False):
    v = require_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", f"Field {name} must be a number", 400)
    if integer and not isinstance(v, int):
        # floats that are whole allowed? Keep strict to int.
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        else:
            err("ERR_INVALID_REQUEST", f"Field {name} must be an integer", 400)
    if positive and v <= 0:
        err("ERR_INVALID_REQUEST", f"Field {name} must be > 0", 400)
    return v


def require_enum(data, name, allowed):
    v = require_field(data, name)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}", 400)
    return v


# =========================================================================
# Resource helpers
# =========================================================================

def new_id():
    return str(uuid.uuid4())


def make_resource(fields):
    ts = iso(now())
    r = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    r.update(fields)
    return r


def touch(r):
    r["updated_at"] = iso(now())
    r["version"] = r.get("version", 1) + 1


def touch_no_version(r):
    r["updated_at"] = iso(now())


def serialize(r):
    """Convert Decimals in the resource to floats for JSON output."""
    if isinstance(r, dict):
        return {k: serialize(v) for k, v in r.items()}
    if isinstance(r, list):
        return [serialize(v) for v in r]
    if isinstance(r, Decimal):
        return float(r)
    if isinstance(r, datetime):
        return iso(r)
    return r


# =========================================================================
# Lookups
# =========================================================================

def get_variety(vid):
    if vid not in db["varieties"]:
        err("ERR_VARIETY_NOT_FOUND", f"Variety {vid} not found", 404)
    return db["varieties"][vid]


def get_buyer(bid):
    if bid not in db["buyers"]:
        err("ERR_BUYER_NOT_FOUND", f"Buyer {bid} not found", 404)
    return db["buyers"][bid]


def get_commitment(cid):
    if cid not in db["buyer_commitments"]:
        err("ERR_COMMITMENT_NOT_FOUND", f"BuyerCommitment {cid} not found", 404)
    return db["buyer_commitments"][cid]


def get_line(lid):
    if lid not in db["commitment_lines"]:
        err("ERR_LINE_NOT_FOUND", f"CommitmentLine {lid} not found", 404)
    return db["commitment_lines"][lid]


def get_batch(bid):
    if bid not in db["substrate_batches"]:
        err("ERR_BATCH_NOT_FOUND", f"SubstrateBatch {bid} not found", 404)
    return db["substrate_batches"][bid]


def get_tunnel(tid):
    if tid not in db["pasteurization_tunnels"]:
        err("ERR_TUNNEL_NOT_FOUND", f"PasteurizationTunnel {tid} not found", 404)
    return db["pasteurization_tunnels"][tid]


def get_pcycle(cid):
    if cid not in db["pasteurization_cycles"]:
        err("ERR_CYCLE_NOT_FOUND", f"PasteurizationCycle {cid} not found", 404)
    return db["pasteurization_cycles"][cid]


def get_room(rid):
    if rid not in db["growing_rooms"]:
        err("ERR_ROOM_NOT_FOUND", f"GrowingRoom {rid} not found", 404)
    return db["growing_rooms"][rid]


def get_rcycle(rid):
    if rid not in db["room_cycles"]:
        err("ERR_ROOM_CYCLE_NOT_FOUND", f"RoomCycle {rid} not found", 404)
    return db["room_cycles"][rid]


def get_flush(fid):
    if fid not in db["flush_harvests"]:
        err("ERR_FLUSH_NOT_FOUND", f"FlushHarvest {fid} not found", 404)
    return db["flush_harvests"][fid]


def get_piece(pid):
    if pid not in db["harvest_pieces"]:
        err("ERR_PIECE_NOT_FOUND", f"HarvestPiece {pid} not found", 404)
    return db["harvest_pieces"][pid]


def get_worker(wid):
    if wid not in db["workers"]:
        err("ERR_WORKER_NOT_FOUND", f"Worker {wid} not found", 404)
    return db["workers"][wid]


def get_event(eid):
    if eid not in db["contamination_events"]:
        err("ERR_EVENT_NOT_FOUND", f"ContaminationEvent {eid} not found", 404)
    return db["contamination_events"][eid]


def get_lot(lid):
    if lid not in db["packaged_lots"]:
        err("ERR_LOT_NOT_FOUND", f"PackagedLot {lid} not found", 404)
    return db["packaged_lots"][lid]


def get_spent(sid):
    if sid not in db["spent_substrate_lots"]:
        err("ERR_SPENT_LOT_NOT_FOUND", f"SpentSubstrateLot {sid} not found", 404)
    return db["spent_substrate_lots"][sid]


# =========================================================================
# Computed fields / recomputation
# =========================================================================

def recompute_batch_remaining(batch):
    total = D(batch["tonnage"])
    used = Decimal("0")
    for rc in db["room_cycles"].values():
        if rc["batch_id"] == batch["id"] and rc["status"] != "CANCELLED":
            used += D(rc["allocated_tonnage"])
    batch["remaining_tonnage"] = round2(total - used)


def recompute_variety_planned(variety_id):
    v = db["varieties"][variety_id]
    total = Decimal("0")
    for rc in db["room_cycles"].values():
        if rc["variety_id"] == variety_id and rc["status"] in ("SCHEDULED", "SPAWN_RUN", "CASING", "FRUITING"):
            total += D(rc["scheduled_projection_kg"])
    v["planned_production_kg"] = round2(total)


def recompute_variety_committed(variety_id):
    v = db["varieties"][variety_id]
    total = Decimal("0")
    for line in db["commitment_lines"].values():
        if line["variety_id"] == variety_id and line["status"] == "ACTIVE":
            total += D(line["committed_kg"])
    v["active_committed_kg"] = round2(total)


def recompute_supply_at_risk(variety_id):
    v = db["varieties"][variety_id]
    planned = D(v["planned_production_kg"])
    for line in db["commitment_lines"].values():
        if line["variety_id"] == variety_id and line["status"] == "ACTIVE":
            remainder = D(line["committed_kg"]) - D(line["delivered_kg"])
            line["supply_at_risk"] = planned < remainder


def recompute_commitment_totals(commitment):
    lines = [l for l in db["commitment_lines"].values() if l["commitment_id"] == commitment["id"]]
    commitment["total_committed_kg"] = round2(sum(D(l["committed_kg"]) for l in lines))
    commitment["total_delivered_kg"] = round2(sum(D(l["delivered_kg"]) for l in lines))
    commitment["total_shortfall_penalty_cents"] = sum(int(l["penalty_cents"]) for l in lines)


def recompute_actualized_projection(rc):
    variety = db["varieties"][rc["variety_id"]]
    total_expected = D(rc["allocated_tonnage"]) * D(1000) * D(variety["target_bioefficiency_pct"]) / D(100)
    graded = [f for f in db["flush_harvests"].values()
              if f["room_cycle_id"] == rc["id"] and f["status"] in ("GRADED", "SETTLED")]
    graded_total = sum(D(f["total_kg"]) for f in graded)
    flush_count = len(graded)
    remaining = Decimal("0")
    dist = variety["flush_yield_distribution"]
    max_flushes = variety["max_flushes"]
    for n in range(flush_count + 1, max_flushes + 1):
        frac = D(dist[n - 1])
        remaining += total_expected * frac
    rc["actualized_projection_kg"] = round2(graded_total + remaining)
    rc["flush_count"] = flush_count
    rc["harvested_kg"] = round2(graded_total)


def recompute_worker_accrual(worker):
    approved = [p for p in db["harvest_pieces"].values()
                if p["worker_id"] == worker["id"] and p["status"] == "APPROVED"]
    worker["accrued_unpaid_cents"] = sum(int(p["final_pay_cents"]) for p in approved)
    paid = [p for p in db["harvest_pieces"].values()
            if p["worker_id"] == worker["id"] and p["status"] == "PAID"]
    worker["lifetime_paid_cents"] = sum(int(p["final_pay_cents"]) for p in paid)


def recompute_room_health(room):
    open_events = [e for e in db["contamination_events"].values()
                   if e["room_id"] == room["id"] and e["status"] in ("REPORTED", "CONFIRMED", "REMEDIATING")]
    severe_open = [e for e in open_events if e["status"] in ("CONFIRMED", "REMEDIATING") and e["severity"] >= 4]
    confirmed_open = [e for e in open_events if e["status"] in ("CONFIRMED", "REMEDIATING")]
    if severe_open:
        room["health_status"] = "QUARANTINED"
    elif confirmed_open:
        room["health_status"] = "WATCH"
    else:
        room["health_status"] = "CLEAR"


def recompute_batch_money(batch):
    revenue = 0
    disposal = 0
    for lot in db["spent_substrate_lots"].values():
        if lot["batch_id"] == batch["id"]:
            if lot["status"] == "SOLD" and lot["sale_price_cents"] is not None:
                revenue += int(lot["sale_price_cents"])
            if lot["status"] == "DISPOSED" and lot["disposal_cost_cents"] is not None:
                disposal += int(lot["disposal_cost_cents"])
    batch["spent_revenue_cents"] = revenue
    batch["disposal_cost_cents"] = disposal


# =========================================================================
# Endpoint: clock
# =========================================================================

@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role(ROLE_FARM)
    data = body()
    to_iso = require_field(data, "to_iso8601")
    if not isinstance(to_iso, str):
        err("ERR_INVALID_REQUEST", "to_iso8601 must be a string", 400)
    target = parse_iso(to_iso)
    if target < _clock["now"]:
        err("ERR_CLOCK_REGRESSION", "Cannot move clock backwards", 409)
    _clock["now"] = target
    return ok_object({"current_utc": iso(_clock["now"])})


@app.route("/api/operations/run-daily-sweep", methods=["POST"])
def run_daily_sweep():
    require_role(ROLE_FARM)
    expired_count = 0
    settled_count = 0
    closed_count = 0
    ts = now()
    # Expire packaged lots
    for lot in db["packaged_lots"].values():
        if lot["status"] in ("IN_STOCK", "ALLOCATED") and parse_iso(lot["expires_at"]) <= ts:
            was_allocated = lot["status"] == "ALLOCATED"
            line_id = lot.get("allocated_line_id")
            lot["status"] = "EXPIRED"
            if was_allocated and line_id:
                line = db["commitment_lines"][line_id]
                line["allocated_kg"] = round2(D(line["allocated_kg"]) - D(lot["lot_kg"]))
                lot["allocated_line_id"] = None
            touch(lot)
            expired_count += 1
    # Settle due commitment lines
    for line in db["commitment_lines"].values():
        if line["status"] == "ACTIVE" and parse_iso(line["week_end"]) < ts:
            settle_line(line)
            settled_count += 1
            # Bubble up: if all sibling lines SETTLED or CANCELLED, close commitment
            commitment = db["buyer_commitments"][line["commitment_id"]]
            if commitment["status"] == "ACTIVE":
                siblings = [l for l in db["commitment_lines"].values()
                            if l["commitment_id"] == commitment["id"]]
                if all(l["status"] in ("SETTLED", "CANCELLED") for l in siblings):
                    commitment["status"] = "CLOSED"
                    touch(commitment)
                    closed_count += 1
    return ok_object({
        "expired_lot_count": expired_count,
        "settled_line_count": settled_count,
        "closed_commitment_count": closed_count,
    })


def settle_line(line):
    committed = D(line["committed_kg"])
    delivered = D(line["delivered_kg"])
    shortfall = committed - delivered
    if shortfall < 0:
        shortfall = Decimal("0")
    shortfall = round2(shortfall)
    line["shortfall_kg"] = shortfall
    # FULFILLED check: delivered >= committed * (1 - 0.05)
    threshold = committed * D("0.95")
    if delivered >= threshold:
        line["settlement_outcome"] = "FULFILLED"
        line["penalty_cents"] = 0
    else:
        line["settlement_outcome"] = "SHORTFALL"
        ratio = shortfall / committed if committed > 0 else Decimal("0")
        if ratio <= D("0.15"):
            rate = 120
        elif ratio <= D("0.40"):
            rate = 200
        else:
            rate = 350
        line["penalty_cents"] = round0(shortfall * rate)
    line["status"] = "SETTLED"
    touch(line)
    # Buyer rollup
    commitment = db["buyer_commitments"][line["commitment_id"]]
    buyer = db["buyers"][commitment["buyer_id"]]
    buyer["lifetime_shortfall_penalty_cents"] = int(buyer.get("lifetime_shortfall_penalty_cents", 0)) + int(line["penalty_cents"])
    touch(buyer)
    recompute_commitment_totals(commitment)
    touch(commitment)


# =========================================================================
# Varieties
# =========================================================================

@app.route("/api/varieties", methods=["POST"])
def create_variety():
    require_role(ROLE_COMPOST)
    data = body()
    variety_code = require_field(data, "variety_code")
    display_name = require_field(data, "display_name")
    substrate_recipe = require_enum(data, "substrate_recipe", {"PHASE_II_COMPOST", "STRAW_SAWDUST"})
    target_bio = require_number(data, "target_bioefficiency_pct", positive=True)
    shelf_life = require_number(data, "shelf_life_days", integer=True)
    spawn_run_days = require_number(data, "spawn_run_days", integer=True)
    casing_days = require_number(data, "casing_days", integer=True)
    max_flushes = require_number(data, "max_flushes", integer=True)
    if max_flushes < 1:
        err("ERR_INVALID_REQUEST", "max_flushes must be >= 1", 400)
    dist = require_field(data, "flush_yield_distribution")
    if not isinstance(dist, list) or len(dist) != max_flushes:
        err("ERR_INVALID_REQUEST", "flush_yield_distribution length must equal max_flushes", 400)
    # Validate fractions
    for f in dist:
        if isinstance(f, bool) or not isinstance(f, (int, float)):
            err("ERR_INVALID_REQUEST", "flush_yield_distribution entries must be numbers", 400)
    r = make_resource({
        "variety_code": variety_code,
        "display_name": display_name,
        "substrate_recipe": substrate_recipe,
        "target_bioefficiency_pct": round2(target_bio),
        "shelf_life_days": int(shelf_life),
        "spawn_run_days": int(spawn_run_days),
        "casing_days": int(casing_days),
        "max_flushes": int(max_flushes),
        "flush_yield_distribution": [round2(f) for f in dist],
        "active_committed_kg": Decimal("0.0"),
        "planned_production_kg": Decimal("0.0"),
    })
    db["varieties"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/varieties/<varietyId>", methods=["GET"])
def get_variety_endpoint(varietyId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_variety(varietyId)))


# =========================================================================
# Buyers
# =========================================================================

@app.route("/api/buyers", methods=["POST"])
def create_buyer():
    require_role(ROLE_SALES)
    data = body()
    name = require_field(data, "name")
    r = make_resource({
        "name": name,
        "status": "ACTIVE",
        "lifetime_shortfall_penalty_cents": 0,
    })
    db["buyers"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/buyers/<buyerId>", methods=["GET"])
def get_buyer_endpoint(buyerId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_buyer(buyerId)))


@app.route("/api/buyers/<buyerId>", methods=["PATCH"])
def patch_buyer(buyerId):
    require_role(ROLE_SALES)
    buyer = get_buyer(buyerId)
    data = body()
    status = require_field(data, "status")
    if status not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_REQUEST", "status must be ACTIVE or SUSPENDED", 400)
    if status == buyer["status"]:
        err("ERR_INVALID_REQUEST", f"Buyer already has status {status}", 400)
    buyer["status"] = status
    touch(buyer)
    return ok_object(serialize(buyer))


# =========================================================================
# BuyerCommitments
# =========================================================================

@app.route("/api/buyer-commitments", methods=["POST"])
def create_commitment():
    uid, role = get_auth()
    if role not in (ROLE_SALES, ROLE_BUYER_PORTAL):
        err("ERR_FORBIDDEN", f"Role {role} not permitted to create commitments", 403)
    data = body()
    buyer_id = require_field(data, "buyer_id")
    reference = require_field(data, "reference")
    if role == ROLE_BUYER_PORTAL and buyer_id != uid:
        err("ERR_BUYER_MISMATCH", "BuyerPortal may only create commitments for itself", 403)
    buyer = get_buyer(buyer_id)
    if buyer["status"] != "ACTIVE":
        err("ERR_BUYER_NOT_ACTIVE", "Buyer must be ACTIVE", 409)
    r = make_resource({
        "buyer_id": buyer_id,
        "reference": reference,
        "status": "DRAFT",
        "total_committed_kg": Decimal("0.0"),
        "total_delivered_kg": Decimal("0.0"),
        "total_shortfall_penalty_cents": 0,
    })
    db["buyer_commitments"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/buyer-commitments", methods=["GET"])
def list_commitments():
    require_role(ROLE_ANY)
    items = list(db["buyer_commitments"].values())
    buyer_id = request.args.get("buyer_id")
    status = request.args.get("status")
    if buyer_id:
        items = [i for i in items if i["buyer_id"] == buyer_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/buyer-commitments/<commitmentId>", methods=["GET"])
def get_commitment_endpoint(commitmentId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_commitment(commitmentId)))


@app.route("/api/buyer-commitments/<commitmentId>/activate", methods=["POST"])
def activate_commitment(commitmentId):
    require_role(ROLE_SALES)
    commitment = get_commitment(commitmentId)
    data = body()
    expected_version = data.get("expected_commitment_version")
    if expected_version is not None and int(expected_version) != commitment["version"]:
        err("ERR_STALE_VERSION", "Commitment version is stale", 412)
    if commitment["status"] != "DRAFT":
        err("ERR_COMMITMENT_NOT_DRAFT", "Commitment must be DRAFT", 409)
    lines = [l for l in db["commitment_lines"].values() if l["commitment_id"] == commitmentId]
    if not lines:
        err("ERR_COMMITMENT_EMPTY", "Commitment has no lines", 409)
    commitment["status"] = "ACTIVE"
    touch(commitment)
    for line in lines:
        line["status"] = "ACTIVE"
        touch(line)
        recompute_variety_committed(line["variety_id"])
        recompute_supply_at_risk(line["variety_id"])
    return ok_object(serialize(commitment))


@app.route("/api/buyer-commitments/<commitmentId>/cancel", methods=["POST"])
def cancel_commitment(commitmentId):
    require_role(ROLE_SALES)
    commitment = get_commitment(commitmentId)
    if commitment["status"] != "ACTIVE":
        err("ERR_COMMITMENT_NOT_ACTIVE", "Commitment must be ACTIVE", 409)
    lines = [l for l in db["commitment_lines"].values() if l["commitment_id"] == commitmentId]
    for line in lines:
        if D(line["delivered_kg"]) > 0:
            err("ERR_COMMITMENT_HAS_DELIVERIES", "A line has delivered_kg > 0", 409)
    # Check no ALLOCATED lots
    for lot in db["packaged_lots"].values():
        if lot["status"] == "ALLOCATED" and lot.get("allocated_line_id"):
            alloc_line = db["commitment_lines"].get(lot["allocated_line_id"])
            if alloc_line and alloc_line["commitment_id"] == commitmentId:
                err("ERR_COMMITMENT_HAS_ALLOCATIONS", "A lot is ALLOCATED to a line", 409)
    commitment["status"] = "CANCELLED"
    touch(commitment)
    affected_varieties = set()
    for line in lines:
        was_active = line["status"] == "ACTIVE"
        line["status"] = "CANCELLED"
        touch(line)
        if was_active:
            affected_varieties.add(line["variety_id"])
    for vid in affected_varieties:
        recompute_variety_committed(vid)
        recompute_supply_at_risk(vid)
    return ok_object(serialize(commitment))


@app.route("/api/buyer-commitments/<commitmentId>/lines", methods=["POST"])
def add_line(commitmentId):
    require_role(ROLE_SALES)
    commitment = get_commitment(commitmentId)
    if commitment["status"] != "DRAFT":
        err("ERR_COMMITMENT_NOT_DRAFT", "Commitment must be DRAFT", 409)
    data = body()
    variety_id = require_field(data, "variety_id")
    variety = get_variety(variety_id)
    committed_kg = require_number(data, "committed_kg", positive=True)
    week_start = require_field(data, "week_start")
    week_end = require_field(data, "week_end")
    ws = parse_iso(week_start) if isinstance(week_start, str) else None
    we = parse_iso(week_end) if isinstance(week_end, str) else None
    if ws is None or we is None:
        err("ERR_INVALID_REQUEST", "week_start and week_end must be ISO strings", 400)
    if we <= ws:
        err("ERR_INVALID_REQUEST", "week_end must be > week_start", 400)
    min_grade = data.get("min_grade", "B")
    if min_grade not in ("A", "B"):
        err("ERR_INVALID_REQUEST", "min_grade must be A or B", 400)
    r = make_resource({
        "commitment_id": commitmentId,
        "variety_id": variety_id,
        "committed_kg": round2(committed_kg),
        "week_start": iso(ws),
        "week_end": iso(we),
        "min_grade": min_grade,
        "delivered_kg": Decimal("0.0"),
        "allocated_kg": Decimal("0.0"),
        "status": "DRAFT",
        "settlement_outcome": None,
        "shortfall_kg": Decimal("0.0"),
        "penalty_cents": 0,
        "supply_at_risk": False,
    })
    db["commitment_lines"][r["id"]] = r
    recompute_commitment_totals(commitment)
    touch_no_version(commitment)  # Deliberately does NOT increment version
    return ok_object(serialize(r), 201)


# =========================================================================
# CommitmentLines
# =========================================================================

@app.route("/api/commitment-lines", methods=["GET"])
def list_lines():
    require_role(ROLE_ANY)
    items = list(db["commitment_lines"].values())
    commitment_id = request.args.get("commitment_id")
    variety_id = request.args.get("variety_id")
    status = request.args.get("status")
    if commitment_id:
        items = [i for i in items if i["commitment_id"] == commitment_id]
    if variety_id:
        items = [i for i in items if i["variety_id"] == variety_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/commitment-lines/<lineId>", methods=["GET"])
def get_line_endpoint(lineId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_line(lineId)))


@app.route("/api/commitment-lines/<lineId>/allocate", methods=["POST"])
def allocate_line(lineId):
    require_role(ROLE_SALES)
    line = get_line(lineId)
    if line["status"] != "ACTIVE":
        err("ERR_LINE_NOT_ACTIVE", "Line must be ACTIVE", 409)
    data = body()
    target_kg = require_number(data, "target_kg", positive=True)
    target = D(target_kg)
    open_kg = D(line["committed_kg"]) - D(line["delivered_kg"]) - D(line["allocated_kg"])
    if target > open_kg:
        err("ERR_ALLOCATION_EXCEEDS_OPEN_COMMITMENT", "target_kg exceeds open commitment", 422)
    ts = now()
    candidates = []
    for lot in db["packaged_lots"].values():
        if lot["status"] != "IN_STOCK":
            continue
        if lot["variety_id"] != line["variety_id"]:
            continue
        if line["min_grade"] == "A" and lot["grade"] != "A":
            continue
        if parse_iso(lot["expires_at"]) <= ts:
            continue
        candidates.append(lot)
    candidates.sort(key=lambda l: (l["expires_at"], l["created_at"]))
    allocated_ids = []
    running = Decimal("0")
    for lot in candidates:
        lot_kg = D(lot["lot_kg"])
        if running + lot_kg <= target:
            lot["status"] = "ALLOCATED"
            lot["allocated_line_id"] = lineId
            touch(lot)
            allocated_ids.append(lot["id"])
            running += lot_kg
        else:
            break  # stop at first overshoot, no skipping
    if not allocated_ids:
        err("ERR_NO_ELIGIBLE_LOTS", "No eligible IN_STOCK lots", 422)
    line["allocated_kg"] = round2(D(line["allocated_kg"]) + running)
    touch(line)
    return ok_object({
        "allocated_lot_ids": allocated_ids,
        "allocated_kg": float(round2(running)),
    })


# =========================================================================
# Substrate Batches
# =========================================================================

@app.route("/api/substrate-batches", methods=["POST"])
def create_batch():
    require_role(ROLE_COMPOST)
    data = body()
    recipe = require_enum(data, "recipe", {"PHASE_II_COMPOST", "STRAW_SAWDUST"})
    tonnage = require_number(data, "tonnage", positive=True)
    r = make_resource({
        "recipe": recipe,
        "tonnage": round2(tonnage),
        "variety_id": None,
        "spawn_kg": None,
        "remaining_tonnage": round2(tonnage),
        "status": "MIXED",
        "spent_revenue_cents": 0,
        "disposal_cost_cents": 0,
    })
    db["substrate_batches"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/substrate-batches", methods=["GET"])
def list_batches():
    require_role(ROLE_ANY)
    items = list(db["substrate_batches"].values())
    variety_id = request.args.get("variety_id")
    status = request.args.get("status")
    if variety_id:
        items = [i for i in items if i["variety_id"] == variety_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/substrate-batches/<batchId>", methods=["GET"])
def get_batch_endpoint(batchId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_batch(batchId)))


@app.route("/api/substrate-batches/<batchId>/spawn", methods=["POST"])
def spawn_batch(batchId):
    require_role(ROLE_COMPOST)
    batch = get_batch(batchId)
    data = body()
    variety_id = require_field(data, "variety_id")
    spawn_kg = require_number(data, "spawn_kg", positive=True)
    variety = get_variety(variety_id)
    if batch["status"] != "CONDITIONED":
        err("ERR_BATCH_NOT_CONDITIONED", "Batch must be CONDITIONED", 409)
    if variety["substrate_recipe"] != batch["recipe"]:
        err("ERR_RECIPE_MISMATCH", "Variety recipe does not match batch recipe", 422)
    batch["variety_id"] = variety_id
    batch["spawn_kg"] = round2(spawn_kg)
    batch["status"] = "SPAWNED"
    touch(batch)
    return ok_object(serialize(batch))


@app.route("/api/substrate-batches/<batchId>/retire", methods=["POST"])
def retire_batch(batchId):
    require_role(ROLE_COMPOST)
    batch = get_batch(batchId)
    if batch["status"] != "EXHAUSTED":
        err("ERR_BATCH_NOT_EXHAUSTED", "Batch must be EXHAUSTED", 409)
    # Check all cycles terminal
    for rc in db["room_cycles"].values():
        if rc["batch_id"] == batchId and rc["status"] not in ("CLOSED", "CANCELLED", "ABORTED"):
            err("ERR_UNRESOLVED_SPENT_LOTS", "Some room cycles are not terminal", 409)
    for lot in db["spent_substrate_lots"].values():
        if lot["batch_id"] == batchId and lot["status"] not in ("SOLD", "DISPOSED"):
            err("ERR_UNRESOLVED_SPENT_LOTS", "Some spent lots are not SOLD|DISPOSED", 409)
    batch["status"] = "RETIRED"
    touch(batch)
    return ok_object(serialize(batch))


# =========================================================================
# Pasteurization Tunnels
# =========================================================================

@app.route("/api/pasteurization-tunnels", methods=["POST"])
def create_tunnel():
    require_role(ROLE_COMPOST)
    data = body()
    tunnel_code = require_field(data, "tunnel_code")
    capacity_tonnes = require_number(data, "capacity_tonnes", positive=True)
    r = make_resource({
        "tunnel_code": tunnel_code,
        "capacity_tonnes": round2(capacity_tonnes),
        "status": "AVAILABLE",
    })
    db["pasteurization_tunnels"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/pasteurization-tunnels/<tunnelId>", methods=["GET"])
def get_tunnel_endpoint(tunnelId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_tunnel(tunnelId)))


@app.route("/api/pasteurization-tunnels/<tunnelId>/sanitize", methods=["POST"])
def sanitize_tunnel(tunnelId):
    require_role(ROLE_COMPOST)
    tunnel = get_tunnel(tunnelId)
    if tunnel["status"] != "OUT_OF_SERVICE":
        err("ERR_TUNNEL_NOT_AVAILABLE", "Tunnel must be OUT_OF_SERVICE to sanitize", 409)
    tunnel["status"] = "AVAILABLE"
    touch(tunnel)
    return ok_object(serialize(tunnel))


# =========================================================================
# Pasteurization Cycles
# =========================================================================

@app.route("/api/pasteurization-cycles", methods=["POST"])
def create_pcycle():
    require_role(ROLE_COMPOST)
    data = body()
    batch_id = require_field(data, "batch_id")
    tunnel_id = require_field(data, "tunnel_id")
    planned_start = require_field(data, "planned_start")
    planned_end = require_field(data, "planned_end")
    batch = get_batch(batch_id)
    tunnel = get_tunnel(tunnel_id)
    ps = parse_iso(planned_start) if isinstance(planned_start, str) else None
    pe = parse_iso(planned_end) if isinstance(planned_end, str) else None
    if ps is None or pe is None:
        err("ERR_INVALID_REQUEST", "planned_start/end must be ISO strings", 400)
    if pe <= ps:
        err("ERR_INVALID_REQUEST", "planned_end must be > planned_start", 400)
    if batch["status"] != "MIXED":
        err("ERR_BATCH_NOT_MIXED", "Batch must be MIXED", 409)
    if D(batch["tonnage"]) > D(tunnel["capacity_tonnes"]):
        err("ERR_TUNNEL_CAPACITY_EXCEEDED", "Batch tonnage exceeds tunnel capacity", 422)
    # Half-open [start, end) overlap with cycles in SCHEDULED or RUNNING
    for c in db["pasteurization_cycles"].values():
        if c["tunnel_id"] != tunnel_id:
            continue
        if c["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        cs = parse_iso(c["planned_start"])
        ce = parse_iso(c["planned_end"])
        if ps < ce and pe > cs:
            err("ERR_TUNNEL_WINDOW_OVERLAP", "Tunnel window overlaps existing cycle", 409)
    r = make_resource({
        "batch_id": batch_id,
        "tunnel_id": tunnel_id,
        "planned_start": iso(ps),
        "planned_end": iso(pe),
        "actual_start": None,
        "hours_at_target_temp": None,
        "status": "SCHEDULED",
    })
    db["pasteurization_cycles"][r["id"]] = r
    batch["status"] = "PASTEURIZING"
    touch(batch)
    return ok_object(serialize(r), 201)


@app.route("/api/pasteurization-cycles", methods=["GET"])
def list_pcycles():
    require_role(ROLE_ANY)
    items = list(db["pasteurization_cycles"].values())
    batch_id = request.args.get("batch_id")
    tunnel_id = request.args.get("tunnel_id")
    status = request.args.get("status")
    if batch_id:
        items = [i for i in items if i["batch_id"] == batch_id]
    if tunnel_id:
        items = [i for i in items if i["tunnel_id"] == tunnel_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/pasteurization-cycles/<cycleId>", methods=["GET"])
def get_pcycle_endpoint(cycleId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_pcycle(cycleId)))


@app.route("/api/pasteurization-cycles/<cycleId>/start", methods=["POST"])
def start_pcycle(cycleId):
    require_role(ROLE_COMPOST)
    c = get_pcycle(cycleId)
    if c["status"] != "SCHEDULED":
        err("ERR_CYCLE_INVALID_STATE", "Cycle must be SCHEDULED", 409)
    tunnel = db["pasteurization_tunnels"][c["tunnel_id"]]
    if tunnel["status"] != "AVAILABLE":
        err("ERR_TUNNEL_NOT_AVAILABLE", "Tunnel must be AVAILABLE", 409)
    ts = now()
    ps = parse_iso(c["planned_start"])
    pe = parse_iso(c["planned_end"])
    if not (ps <= ts <= pe):
        err("ERR_CYCLE_WINDOW_NOT_OPEN", "Clock not within planned window", 409)
    c["status"] = "RUNNING"
    c["actual_start"] = iso(ts)
    touch(c)
    return ok_object(serialize(c))


@app.route("/api/pasteurization-cycles/<cycleId>/complete", methods=["POST"])
def complete_pcycle(cycleId):
    require_role(ROLE_COMPOST)
    c = get_pcycle(cycleId)
    if c["status"] != "RUNNING":
        err("ERR_CYCLE_INVALID_STATE", "Cycle must be RUNNING", 409)
    data = body()
    hours = require_number(data, "hours_at_target_temp")
    if D(hours) < D("6.0"):
        err("ERR_PASTEURIZATION_INCOMPLETE", "hours_at_target_temp < 6.0", 422)
    c["hours_at_target_temp"] = round2(hours)
    c["status"] = "COMPLETED"
    touch(c)
    batch = db["substrate_batches"][c["batch_id"]]
    batch["status"] = "CONDITIONED"
    touch(batch)
    return ok_object(serialize(c))


@app.route("/api/pasteurization-cycles/<cycleId>/fail", methods=["POST"])
def fail_pcycle(cycleId):
    require_role(ROLE_COMPOST)
    c = get_pcycle(cycleId)
    if c["status"] != "RUNNING":
        err("ERR_CYCLE_INVALID_STATE", "Cycle must be RUNNING", 409)
    c["status"] = "FAILED"
    touch(c)
    batch = db["substrate_batches"][c["batch_id"]]
    batch["status"] = "MIXED"
    touch(batch)
    tunnel = db["pasteurization_tunnels"][c["tunnel_id"]]
    tunnel["status"] = "OUT_OF_SERVICE"
    touch(tunnel)
    return ok_object(serialize(c))


@app.route("/api/pasteurization-cycles/<cycleId>/abort", methods=["POST"])
def abort_pcycle(cycleId):
    require_role(ROLE_COMPOST)
    c = get_pcycle(cycleId)
    if c["status"] != "SCHEDULED":
        err("ERR_CYCLE_INVALID_STATE", "Cycle must be SCHEDULED", 409)
    c["status"] = "ABORTED"
    touch(c)
    batch = db["substrate_batches"][c["batch_id"]]
    batch["status"] = "MIXED"
    touch(batch)
    return ok_object(serialize(c))


# =========================================================================
# Growing Rooms
# =========================================================================

@app.route("/api/rooms", methods=["POST"])
def create_room():
    require_role(ROLE_FARM)
    data = body()
    room_code = require_field(data, "room_code")
    capacity_tonnes = require_number(data, "capacity_tonnes", positive=True)
    r = make_resource({
        "room_code": room_code,
        "capacity_tonnes": round2(capacity_tonnes),
        "occupancy_status": "IDLE",
        "health_status": "CLEAR",
    })
    db["growing_rooms"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/rooms", methods=["GET"])
def list_rooms():
    require_role(ROLE_ANY)
    items = list(db["growing_rooms"].values())
    return paginate([serialize(i) for i in items])


@app.route("/api/rooms/<roomId>", methods=["GET"])
def get_room_endpoint(roomId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_room(roomId)))


# =========================================================================
# Room Cycles
# =========================================================================

@app.route("/api/room-cycles", methods=["POST"])
def create_rcycle():
    require_role(ROLE_FARM)
    data = body()
    room_id = require_field(data, "room_id")
    batch_id = require_field(data, "batch_id")
    allocated_tonnage = require_number(data, "allocated_tonnage", positive=True)
    planned_start = require_field(data, "planned_start")
    planned_end = require_field(data, "planned_end")
    room = get_room(room_id)
    batch = get_batch(batch_id)
    # OCC check (priority 6) - before state preconditions
    expected_room_version = data.get("expected_room_version")
    if expected_room_version is not None and int(expected_room_version) != room["version"]:
        err("ERR_STALE_VERSION", "Room version is stale", 412)
    # State preconditions (priority 7)
    if batch["status"] != "SPAWNED":
        err("ERR_BATCH_NOT_SPAWNED", "Batch must be SPAWNED", 409)
    ps = parse_iso(planned_start) if isinstance(planned_start, str) else None
    pe = parse_iso(planned_end) if isinstance(planned_end, str) else None
    if ps is None or pe is None:
        err("ERR_INVALID_REQUEST", "planned_start/end must be ISO strings", 400)
    if pe <= ps:
        err("ERR_INVALID_REQUEST", "planned_end must be > planned_start", 400)
    # Room window overlap (priority 9) - blocking interval [start, end + 2 days)
    for rc in db["room_cycles"].values():
        if rc["room_id"] != room_id:
            continue
        if rc["status"] not in ("SCHEDULED", "SPAWN_RUN", "CASING", "FRUITING", "TURNAROUND"):
            continue
        rs = parse_iso(rc["planned_start"])
        re_ = parse_iso(rc["planned_end"]) + timedelta(days=2)
        if ps < re_ and pe > rs:
            err("ERR_ROOM_WINDOW_OVERLAP", "Room window overlaps existing cycle's blocking interval", 409)
    # Capacity / substrate checks (priority 10)
    alloc = D(allocated_tonnage)
    if alloc > D(room["capacity_tonnes"]):
        err("ERR_ROOM_CAPACITY_EXCEEDED", "allocated_tonnage exceeds room capacity", 422)
    recompute_batch_remaining(batch)
    if alloc > D(batch["remaining_tonnage"]):
        err("ERR_INSUFFICIENT_SUBSTRATE", "allocated_tonnage exceeds batch remaining_tonnage", 422)
    r = make_resource({
        "room_id": room_id,
        "batch_id": batch_id,
        "variety_id": batch["variety_id"],
        "allocated_tonnage": round2(alloc),
        "planned_start": iso(ps),
        "planned_end": iso(pe),
        "placed_at": None,
        "phase_entered_at": None,
        "status": "SCHEDULED",
        "flush_count": 0,
        "harvested_kg": Decimal("0.0"),
        "scheduled_projection_kg": Decimal("0.0"),
        "actualized_projection_kg": Decimal("0.0"),
    })
    db["room_cycles"][r["id"]] = r
    # Debit batch remaining
    recompute_batch_remaining(batch)
    # Auto-exhaust if remaining == 0 and batch SPAWNED
    if D(batch["remaining_tonnage"]) == 0 and batch["status"] == "SPAWNED":
        batch["status"] = "EXHAUSTED"
        touch(batch)
    # Bump room version (booking against the room's schedule)
    touch(room)
    # Recompute variety planned_production_kg
    recompute_variety_planned(r["variety_id"])
    recompute_supply_at_risk(r["variety_id"])
    return ok_object(serialize(r), 201)


@app.route("/api/room-cycles", methods=["GET"])
def list_rcycles():
    require_role(ROLE_ANY)
    items = list(db["room_cycles"].values())
    room_id = request.args.get("room_id")
    batch_id = request.args.get("batch_id")
    variety_id = request.args.get("variety_id")
    status = request.args.get("status")
    if room_id:
        items = [i for i in items if i["room_id"] == room_id]
    if batch_id:
        items = [i for i in items if i["batch_id"] == batch_id]
    if variety_id:
        items = [i for i in items if i["variety_id"] == variety_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/room-cycles/<roomCycleId>", methods=["GET"])
def get_rcycle_endpoint(roomCycleId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_rcycle(roomCycleId)))


@app.route("/api/room-cycles/<roomCycleId>/place", methods=["POST"])
def place_rcycle(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] != "SCHEDULED":
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be SCHEDULED", 409)
    room = db["growing_rooms"][rc["room_id"]]
    if room["occupancy_status"] != "IDLE":
        err("ERR_ROOM_NOT_IDLE", "Room must be IDLE", 409)
    if room["health_status"] == "QUARANTINED":
        err("ERR_ROOM_QUARANTINED", "Room is QUARANTINED", 409)
    ts = now()
    ps = parse_iso(rc["planned_start"])
    pe = parse_iso(rc["planned_end"])
    if not (ps <= ts <= pe):
        err("ERR_CYCLE_WINDOW_NOT_OPEN", "Clock not within planned window", 409)
    rc["status"] = "SPAWN_RUN"
    rc["placed_at"] = iso(ts)
    rc["phase_entered_at"] = iso(ts)
    # Compute projections
    variety = db["varieties"][rc["variety_id"]]
    total_expected = D(rc["allocated_tonnage"]) * D(1000) * D(variety["target_bioefficiency_pct"]) / D(100)
    rc["scheduled_projection_kg"] = round2(total_expected)
    rc["actualized_projection_kg"] = round2(total_expected)
    touch(rc)
    room["occupancy_status"] = "OCCUPIED"
    touch(room)
    recompute_variety_planned(rc["variety_id"])
    recompute_supply_at_risk(rc["variety_id"])
    return ok_object(serialize(rc))


@app.route("/api/room-cycles/<roomCycleId>/advance", methods=["POST"])
def advance_rcycle(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] not in ("SPAWN_RUN", "CASING"):
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be SPAWN_RUN or CASING", 409)
    variety = db["varieties"][rc["variety_id"]]
    ts = now()
    if rc["status"] == "SPAWN_RUN":
        placed = parse_iso(rc["placed_at"])
        min_end = placed + timedelta(days=variety["spawn_run_days"])
        if ts < min_end:
            err("ERR_COLONIZATION_INCOMPLETE", "spawn_run_days not elapsed", 409)
        rc["status"] = "CASING"
    else:
        phase_entered = parse_iso(rc["phase_entered_at"])
        min_end = phase_entered + timedelta(days=variety["casing_days"])
        if ts < min_end:
            err("ERR_COLONIZATION_INCOMPLETE", "casing_days not elapsed", 409)
        rc["status"] = "FRUITING"
    rc["phase_entered_at"] = iso(ts)
    touch(rc)
    return ok_object(serialize(rc))


def make_spent_lot(rc, disposal_only):
    tonnage = round2(D(rc["allocated_tonnage"]) * D("0.75"))
    r = make_resource({
        "room_cycle_id": rc["id"],
        "batch_id": rc["batch_id"],
        "tonnage": tonnage,
        "disposal_only": disposal_only,
        "reserved_buyer_id": None,
        "sale_price_cents": None,
        "disposal_cost_cents": None,
        "status": "AVAILABLE",
    })
    db["spent_substrate_lots"][r["id"]] = r
    return r


def end_cropping_common(rc, disposal_only=False):
    """Common FRUITING -> TURNAROUND logic."""
    make_spent_lot(rc, disposal_only)
    rc["status"] = "TURNAROUND"
    touch(rc)
    room = db["growing_rooms"][rc["room_id"]]
    room["occupancy_status"] = "TURNAROUND"
    touch(room)
    recompute_variety_planned(rc["variety_id"])
    recompute_supply_at_risk(rc["variety_id"])


@app.route("/api/room-cycles/<roomCycleId>/end-cropping", methods=["POST"])
def end_cropping(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] != "FRUITING":
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be FRUITING", 409)
    end_cropping_common(rc, disposal_only=False)
    return ok_object(serialize(rc))


@app.route("/api/room-cycles/<roomCycleId>/certify-cleanout", methods=["POST"])
def certify_cleanout(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] != "TURNAROUND":
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be TURNAROUND", 409)
    rc["status"] = "CLOSED"
    touch(rc)
    room = db["growing_rooms"][rc["room_id"]]
    room["occupancy_status"] = "IDLE"
    touch(room)
    return ok_object(serialize(rc))


@app.route("/api/room-cycles/<roomCycleId>/cancel", methods=["POST"])
def cancel_rcycle(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] != "SCHEDULED":
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be SCHEDULED", 409)
    rc["status"] = "CANCELLED"
    touch(rc)
    # Release tonnage reservation
    batch = db["substrate_batches"][rc["batch_id"]]
    recompute_batch_remaining(batch)
    recompute_variety_planned(rc["variety_id"])
    recompute_supply_at_risk(rc["variety_id"])
    return ok_object(serialize(rc))


def abort_rcycle_common(rc, disposal_only):
    """Common abort logic for SPAWN_RUN|CASING|FRUITING -> ABORTED."""
    make_spent_lot(rc, disposal_only)
    rc["status"] = "ABORTED"
    touch(rc)
    room = db["growing_rooms"][rc["room_id"]]
    room["occupancy_status"] = "TURNAROUND"
    touch(room)
    recompute_variety_planned(rc["variety_id"])
    recompute_supply_at_risk(rc["variety_id"])


@app.route("/api/room-cycles/<roomCycleId>/abort", methods=["POST"])
def abort_rcycle(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] not in ("SPAWN_RUN", "CASING", "FRUITING"):
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be SPAWN_RUN, CASING, or FRUITING", 409)
    abort_rcycle_common(rc, disposal_only=False)
    return ok_object(serialize(rc))


# =========================================================================
# Flush Harvests
# =========================================================================

@app.route("/api/room-cycles/<roomCycleId>/flushes", methods=["POST"])
def create_flush(roomCycleId):
    require_role(ROLE_FARM)
    rc = get_rcycle(roomCycleId)
    if rc["status"] != "FRUITING":
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be FRUITING", 409)
    room = db["growing_rooms"][rc["room_id"]]
    if room["health_status"] == "QUARANTINED":
        err("ERR_ROOM_QUARANTINED", "Room is QUARANTINED", 409)
    data = body()
    total_kg = require_number(data, "total_kg", positive=True)
    variety = db["varieties"][rc["variety_id"]]
    existing = [f for f in db["flush_harvests"].values() if f["room_cycle_id"] == roomCycleId]
    if len(existing) + 1 > variety["max_flushes"]:
        err("ERR_FLUSH_LIMIT_REACHED", "Exceeds max_flushes", 409)
    r = make_resource({
        "room_cycle_id": roomCycleId,
        "flush_number": len(existing) + 1,
        "recorded_at": iso(now()),
        "total_kg": round2(total_kg),
        "grade_a_kg": None,
        "grade_b_kg": None,
        "cull_kg": None,
        "graded_at": None,
        "status": "RECORDED",
    })
    db["flush_harvests"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/room-cycles/<roomCycleId>/flushes", methods=["GET"])
def list_flushes_under_cycle(roomCycleId):
    require_role(ROLE_ANY)
    rc = get_rcycle(roomCycleId)
    items = [f for f in db["flush_harvests"].values() if f["room_cycle_id"] == roomCycleId]
    return paginate([serialize(i) for i in items])


@app.route("/api/flushes", methods=["GET"])
def list_flushes():
    require_role(ROLE_ANY)
    items = list(db["flush_harvests"].values())
    rcid = request.args.get("room_cycle_id")
    status = request.args.get("status")
    if rcid:
        items = [i for i in items if i["room_cycle_id"] == rcid]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/flushes/<flushId>", methods=["GET"])
def get_flush_endpoint(flushId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_flush(flushId)))


@app.route("/api/flushes/<flushId>/grade", methods=["POST"])
def grade_flush(flushId):
    require_role(ROLE_GRADING)
    f = get_flush(flushId)
    if f["status"] != "RECORDED":
        err("ERR_FLUSH_NOT_RECORDED", "Flush must be RECORDED", 409)
    data = body()
    a = require_number(data, "grade_a_kg")
    b = require_number(data, "grade_b_kg")
    c = require_number(data, "cull_kg")
    if D(a) < 0 or D(b) < 0 or D(c) < 0:
        err("ERR_INVALID_REQUEST", "Grade values must be non-negative", 400)
    a2 = round2(a)
    b2 = round2(b)
    c2 = round2(c)
    total = D(f["total_kg"])
    if (a2 + b2 + c2) != round2(total):
        err("ERR_GRADE_SPLIT_MISMATCH", "grade_a_kg + grade_b_kg + cull_kg != total_kg", 422)
    f["grade_a_kg"] = a2
    f["grade_b_kg"] = b2
    f["cull_kg"] = c2
    f["graded_at"] = iso(now())
    f["status"] = "GRADED"
    touch(f)
    rc = db["room_cycles"][f["room_cycle_id"]]
    recompute_actualized_projection(rc)
    touch(rc)
    # Check max_flushes -> auto end-cropping
    variety = db["varieties"][rc["variety_id"]]
    if rc["flush_count"] == variety["max_flushes"] and rc["status"] == "FRUITING":
        end_cropping_common(rc, disposal_only=False)
    return ok_object(serialize(f))


@app.route("/api/flushes/<flushId>/reopen", methods=["POST"])
def reopen_flush(flushId):
    require_role(ROLE_GRADING)
    f = get_flush(flushId)
    if f["status"] != "GRADED":
        err("ERR_FLUSH_NOT_GRADED", "Flush must be GRADED", 409)
    rc = db["room_cycles"][f["room_cycle_id"]]
    if rc["status"] != "FRUITING":
        err("ERR_ROOM_CYCLE_INVALID_PHASE", "Cycle must be FRUITING", 409)
    # Check no packaged lots AND all pieces LOGGED
    lots = [l for l in db["packaged_lots"].values() if l["flush_id"] == flushId]
    if lots:
        err("ERR_FLUSH_HAS_COMMITTED_PIECES", "Packaged lots exist for flush", 409)
    pieces = [p for p in db["harvest_pieces"].values() if p["flush_id"] == flushId]
    for p in pieces:
        if p["status"] != "LOGGED":
            err("ERR_FLUSH_HAS_COMMITTED_PIECES", "Some pieces are not LOGGED", 409)
    f["grade_a_kg"] = None
    f["grade_b_kg"] = None
    f["cull_kg"] = None
    f["graded_at"] = None
    f["status"] = "RECORDED"
    touch(f)
    recompute_actualized_projection(rc)
    touch(rc)
    return ok_object(serialize(f))


# =========================================================================
# Packaged Lots
# =========================================================================

@app.route("/api/flushes/<flushId>/packaged-lots", methods=["POST"])
def create_packaged_lot(flushId):
    require_role(ROLE_FARM)
    f = get_flush(flushId)
    if f["status"] != "GRADED":
        err("ERR_FLUSH_NOT_GRADED", "Flush must be GRADED", 409)
    rc = db["room_cycles"][f["room_cycle_id"]]
    room = db["growing_rooms"][rc["room_id"]]
    if room["health_status"] == "QUARANTINED":
        err("ERR_ROOM_QUARANTINED", "Room is QUARANTINED", 409)
    data = body()
    grade = require_enum(data, "grade", {"A", "B"})
    units = require_number(data, "units", positive=True, integer=True)
    kg_per_unit = require_number(data, "kg_per_unit", positive=True)
    lot_kg = round2(D(units) * D(kg_per_unit))
    # Remaining per-grade
    if grade == "A":
        available = D(f["grade_a_kg"])
    else:
        available = D(f["grade_b_kg"])
    used = Decimal("0")
    for lot in db["packaged_lots"].values():
        if lot["flush_id"] == flushId and lot["grade"] == grade:
            used += D(lot["lot_kg"])
    remaining = available - used
    if lot_kg > remaining:
        err("ERR_INSUFFICIENT_GRADE_KG", "Insufficient remaining kg of grade", 422)
    variety = db["varieties"][rc["variety_id"]]
    ts = now()
    expires = ts + timedelta(days=variety["shelf_life_days"])
    r = make_resource({
        "flush_id": flushId,
        "variety_id": rc["variety_id"],
        "grade": grade,
        "units": int(units),
        "kg_per_unit": round2(kg_per_unit),
        "lot_kg": lot_kg,
        "packed_at": iso(ts),
        "expires_at": iso(expires),
        "allocated_line_id": None,
        "status": "IN_STOCK",
    })
    db["packaged_lots"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/packaged-lots", methods=["GET"])
def list_packaged_lots():
    require_role(ROLE_ANY)
    items = list(db["packaged_lots"].values())
    flush_id = request.args.get("flush_id")
    variety_id = request.args.get("variety_id")
    allocated_line_id = request.args.get("allocated_line_id")
    status = request.args.get("status")
    if flush_id:
        items = [i for i in items if i["flush_id"] == flush_id]
    if variety_id:
        items = [i for i in items if i["variety_id"] == variety_id]
    if allocated_line_id:
        items = [i for i in items if i.get("allocated_line_id") == allocated_line_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/packaged-lots/<lotId>", methods=["GET"])
def get_packaged_lot(lotId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_lot(lotId)))


@app.route("/api/packaged-lots/<lotId>/deallocate", methods=["POST"])
def deallocate_lot(lotId):
    require_role(ROLE_SALES)
    lot = get_lot(lotId)
    if lot["status"] != "ALLOCATED":
        err("ERR_LOT_NOT_ALLOCATED", "Lot must be ALLOCATED", 409)
    line_id = lot["allocated_line_id"]
    line = db["commitment_lines"][line_id]
    line["allocated_kg"] = round2(D(line["allocated_kg"]) - D(lot["lot_kg"]))
    touch(line)
    lot["status"] = "IN_STOCK"
    lot["allocated_line_id"] = None
    touch(lot)
    return ok_object(serialize(lot))


@app.route("/api/packaged-lots/<lotId>/ship", methods=["POST"])
def ship_lot(lotId):
    require_role(ROLE_SALES)
    lot = get_lot(lotId)
    if lot["status"] != "ALLOCATED":
        err("ERR_LOT_NOT_ALLOCATED", "Lot must be ALLOCATED", 409)
    if parse_iso(lot["expires_at"]) <= now():
        err("ERR_LOT_EXPIRED", "Lot expires_at not strictly greater than now", 409)
    line_id = lot["allocated_line_id"]
    line = db["commitment_lines"][line_id]
    line["allocated_kg"] = round2(D(line["allocated_kg"]) - D(lot["lot_kg"]))
    line["delivered_kg"] = round2(D(line["delivered_kg"]) + D(lot["lot_kg"]))
    touch(line)
    commitment = db["buyer_commitments"][line["commitment_id"]]
    recompute_commitment_totals(commitment)
    touch(commitment)
    lot["status"] = "SHIPPED"
    touch(lot)
    return ok_object(serialize(lot))


# =========================================================================
# Harvest Pieces
# =========================================================================

@app.route("/api/flushes/<flushId>/pieces", methods=["POST"])
def create_piece(flushId):
    uid, role = require_role(ROLE_CREW)
    f = get_flush(flushId)
    if f["status"] != "RECORDED":
        err("ERR_FLUSH_NOT_RECORDED", "Flush must be RECORDED", 409)
    data = body()
    worker_id = require_field(data, "worker_id")
    kg_picked = require_number(data, "kg_picked", positive=True)
    worker = get_worker(worker_id)
    if worker["status"] != "ACTIVE":
        err("ERR_WORKER_NOT_ACTIVE", "Worker must be ACTIVE", 409)
    rate = int(worker["piece_rate_cents_per_kg"])
    provisional = round0(D(kg_picked) * D(rate))
    r = make_resource({
        "flush_id": flushId,
        "worker_id": worker_id,
        "logged_by_user_id": uid,
        "kg_picked": round2(kg_picked),
        "rate_cents_per_kg": rate,
        "provisional_pay_cents": provisional,
        "final_pay_cents": None,
        "status": "LOGGED",
    })
    db["harvest_pieces"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/flushes/<flushId>/pieces", methods=["GET"])
def list_pieces_under_flush(flushId):
    require_role(ROLE_ANY)
    get_flush(flushId)  # ensure flush exists
    items = [p for p in db["harvest_pieces"].values() if p["flush_id"] == flushId]
    return paginate([serialize(i) for i in items])


@app.route("/api/pieces", methods=["GET"])
def list_pieces():
    require_role(ROLE_ANY)
    items = list(db["harvest_pieces"].values())
    worker_id = request.args.get("worker_id")
    flush_id = request.args.get("flush_id")
    status = request.args.get("status")
    if worker_id:
        items = [i for i in items if i["worker_id"] == worker_id]
    if flush_id:
        items = [i for i in items if i["flush_id"] == flush_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/pieces/<pieceId>", methods=["GET"])
def get_piece_endpoint(pieceId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_piece(pieceId)))


@app.route("/api/pieces/<pieceId>/approve", methods=["POST"])
def approve_piece(pieceId):
    uid, role = require_role(ROLE_PAYROLL)
    p = get_piece(pieceId)
    if p["status"] not in ("LOGGED", "DISPUTED"):
        err("ERR_PIECE_INVALID_STATE", "Piece must be LOGGED or DISPUTED", 409)
    f = db["flush_harvests"][p["flush_id"]]
    if f["status"] != "GRADED":
        err("ERR_FLUSH_NOT_GRADED", "Flush must be GRADED", 409)
    if uid == p["logged_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Cannot approve own piece", 403)
    # Compute final pay
    total = D(f["total_kg"])
    a_share = D(f["grade_a_kg"]) / total
    b_share = D(f["grade_b_kg"]) / total
    c_share = D(f["cull_kg"]) / total
    factor = D("1.20") * a_share + D("1.00") * b_share + D("0.0") * c_share
    final_pay = round0(D(p["kg_picked"]) * D(p["rate_cents_per_kg"]) * factor)
    p["final_pay_cents"] = final_pay
    p["status"] = "APPROVED"
    touch(p)
    worker = db["workers"][p["worker_id"]]
    recompute_worker_accrual(worker)
    touch(worker)
    return ok_object(serialize(p))


@app.route("/api/pieces/<pieceId>/dispute", methods=["POST"])
def dispute_piece(pieceId):
    uid, role = require_role(ROLE_PAYROLL)
    p = get_piece(pieceId)
    if p["status"] != "APPROVED":
        err("ERR_PIECE_INVALID_STATE", "Piece must be APPROVED", 409)
    if uid == p["logged_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Cannot dispute own piece", 403)
    p["status"] = "DISPUTED"
    touch(p)
    worker = db["workers"][p["worker_id"]]
    recompute_worker_accrual(worker)
    touch(worker)
    return ok_object(serialize(p))


# =========================================================================
# Workers
# =========================================================================

@app.route("/api/workers", methods=["POST"])
def create_worker():
    require_role(ROLE_FARM)
    data = body()
    full_name = require_field(data, "full_name")
    crew_code = require_field(data, "crew_code")
    rate = require_number(data, "piece_rate_cents_per_kg", positive=True, integer=True)
    r = make_resource({
        "full_name": full_name,
        "crew_code": crew_code,
        "piece_rate_cents_per_kg": int(rate),
        "status": "ACTIVE",
        "accrued_unpaid_cents": 0,
        "lifetime_paid_cents": 0,
    })
    db["workers"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/workers/<workerId>", methods=["GET"])
def get_worker_endpoint(workerId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_worker(workerId)))


@app.route("/api/workers/<workerId>", methods=["PATCH"])
def patch_worker(workerId):
    require_role(ROLE_FARM)
    w = get_worker(workerId)
    data = body()
    status = require_field(data, "status")
    if status not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_REQUEST", "status must be ACTIVE or SUSPENDED", 400)
    if status == w["status"]:
        err("ERR_INVALID_REQUEST", f"Worker already has status {status}", 400)
    w["status"] = status
    touch(w)
    return ok_object(serialize(w))


@app.route("/api/workers/<workerId>/payout", methods=["POST"])
def payout_worker(workerId):
    require_role(ROLE_PAYROLL)
    w = get_worker(workerId)
    approved = [p for p in db["harvest_pieces"].values()
                if p["worker_id"] == workerId and p["status"] == "APPROVED"]
    paid_count = 0
    total_paid = 0
    affected_flushes = set()
    for p in approved:
        p["status"] = "PAID"
        touch(p)
        paid_count += 1
        total_paid += int(p["final_pay_cents"])
        affected_flushes.add(p["flush_id"])
    w["accrued_unpaid_cents"] = 0
    w["lifetime_paid_cents"] = int(w["lifetime_paid_cents"]) + total_paid
    touch(w)
    # Check flush settle
    for fid in affected_flushes:
        f = db["flush_harvests"][fid]
        if f["status"] != "GRADED":
            continue
        pieces = [p for p in db["harvest_pieces"].values() if p["flush_id"] == fid]
        if pieces and all(p["status"] == "PAID" for p in pieces):
            f["status"] = "SETTLED"
            touch(f)
    return ok_object({
        "paid_piece_count": paid_count,
        "total_paid_cents": total_paid,
    })


# =========================================================================
# Contamination Events
# =========================================================================

@app.route("/api/contamination-events", methods=["POST"])
def create_event():
    require_role(ROLE_QUALITY)
    data = body()
    room_id = require_field(data, "room_id")
    room = get_room(room_id)
    room_cycle_id = data.get("room_cycle_id")
    if room_cycle_id is not None:
        if room_cycle_id not in db["room_cycles"]:
            err("ERR_ROOM_CYCLE_NOT_FOUND", f"RoomCycle {room_cycle_id} not found", 404)
        rc = db["room_cycles"][room_cycle_id]
        if rc["room_id"] != room_id:
            err("ERR_ROOM_CYCLE_NOT_FOUND", "Cycle does not belong to room", 404)
    pathogen = require_enum(data, "pathogen", {"TRICHODERMA", "COBWEB", "BACTERIAL_BLOTCH", "VIRUS"})
    severity = require_number(data, "severity", integer=True)
    if severity < 1 or severity > 5:
        err("ERR_INVALID_REQUEST", "severity must be 1-5", 400)
    affected_zone = require_number(data, "affected_zone_pct")
    if D(affected_zone) < 0 or D(affected_zone) > 100:
        err("ERR_INVALID_REQUEST", "affected_zone_pct must be 0-100", 400)
    r = make_resource({
        "room_id": room_id,
        "room_cycle_id": room_cycle_id,
        "pathogen": pathogen,
        "severity": int(severity),
        "affected_zone_pct": round2(affected_zone),
        "status": "REPORTED",
    })
    db["contamination_events"][r["id"]] = r
    return ok_object(serialize(r), 201)


@app.route("/api/contamination-events", methods=["GET"])
def list_events():
    require_role(ROLE_ANY)
    items = list(db["contamination_events"].values())
    room_id = request.args.get("room_id")
    rcid = request.args.get("room_cycle_id")
    status = request.args.get("status")
    if room_id:
        items = [i for i in items if i["room_id"] == room_id]
    if rcid:
        items = [i for i in items if i["room_cycle_id"] == rcid]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/contamination-events/<eventId>", methods=["GET"])
def get_event_endpoint(eventId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_event(eventId)))


@app.route("/api/contamination-events/<eventId>/confirm", methods=["POST"])
def confirm_event(eventId):
    require_role(ROLE_QUALITY)
    e = get_event(eventId)
    if e["status"] != "REPORTED":
        err("ERR_EVENT_INVALID_STATE", "Event must be REPORTED", 409)
    e["status"] = "CONFIRMED"
    touch(e)
    room = db["growing_rooms"][e["room_id"]]
    recompute_room_health(room)
    if room["health_status"] == "QUARANTINED" and e["severity"] >= 4:
        # Quarantine cascade: abort active cycles
        for rc in list(db["room_cycles"].values()):
            if rc["room_id"] == room["id"] and rc["status"] in ("SPAWN_RUN", "CASING", "FRUITING"):
                abort_rcycle_common(rc, disposal_only=True)
    touch(room)
    return ok_object(serialize(e))


@app.route("/api/contamination-events/<eventId>/dismiss", methods=["POST"])
def dismiss_event(eventId):
    require_role(ROLE_QUALITY)
    e = get_event(eventId)
    if e["status"] != "REPORTED":
        err("ERR_EVENT_INVALID_STATE", "Event must be REPORTED", 409)
    e["status"] = "DISMISSED"
    touch(e)
    room = db["growing_rooms"][e["room_id"]]
    recompute_room_health(room)
    touch(room)
    return ok_object(serialize(e))


@app.route("/api/contamination-events/<eventId>/remediate", methods=["POST"])
def remediate_event(eventId):
    require_role(ROLE_QUALITY)
    e = get_event(eventId)
    if e["status"] != "CONFIRMED":
        err("ERR_EVENT_INVALID_STATE", "Event must be CONFIRMED", 409)
    e["status"] = "REMEDIATING"
    touch(e)
    room = db["growing_rooms"][e["room_id"]]
    recompute_room_health(room)
    touch(room)
    return ok_object(serialize(e))


@app.route("/api/contamination-events/<eventId>/clear", methods=["POST"])
def clear_event(eventId):
    require_role(ROLE_QUALITY)
    e = get_event(eventId)
    if e["status"] != "REMEDIATING":
        err("ERR_EVENT_INVALID_STATE", "Event must be REMEDIATING", 409)
    e["status"] = "CLEARED"
    touch(e)
    room = db["growing_rooms"][e["room_id"]]
    recompute_room_health(room)
    touch(room)
    return ok_object(serialize(e))


# =========================================================================
# Spent Substrate Lots
# =========================================================================

@app.route("/api/spent-substrate-lots", methods=["GET"])
def list_spent_lots():
    require_role(ROLE_ANY)
    items = list(db["spent_substrate_lots"].values())
    rcid = request.args.get("room_cycle_id")
    batch_id = request.args.get("batch_id")
    reserved_buyer_id = request.args.get("reserved_buyer_id")
    status = request.args.get("status")
    if rcid:
        items = [i for i in items if i["room_cycle_id"] == rcid]
    if batch_id:
        items = [i for i in items if i["batch_id"] == batch_id]
    if reserved_buyer_id:
        items = [i for i in items if i.get("reserved_buyer_id") == reserved_buyer_id]
    if status:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@app.route("/api/spent-substrate-lots/<lotId>", methods=["GET"])
def get_spent_lot(lotId):
    require_role(ROLE_ANY)
    return ok_object(serialize(get_spent(lotId)))


@app.route("/api/spent-substrate-lots/<lotId>/reserve", methods=["POST"])
def reserve_spent(lotId):
    require_role(ROLE_SALES)
    lot = get_spent(lotId)
    if lot["status"] != "AVAILABLE":
        err("ERR_SPENT_LOT_INVALID_STATE", "Lot must be AVAILABLE", 409)
    if lot["disposal_only"]:
        err("ERR_SPENT_LOT_DISPOSAL_ONLY", "Lot is disposal_only", 409)
    data = body()
    buyer_id = require_field(data, "buyer_id")
    buyer = get_buyer(buyer_id)
    if buyer["status"] != "ACTIVE":
        err("ERR_BUYER_NOT_ACTIVE", "Buyer must be ACTIVE", 409)
    lot["status"] = "RESERVED"
    lot["reserved_buyer_id"] = buyer_id
    touch(lot)
    return ok_object(serialize(lot))


@app.route("/api/spent-substrate-lots/<lotId>/release", methods=["POST"])
def release_spent(lotId):
    require_role(ROLE_SALES)
    lot = get_spent(lotId)
    if lot["status"] != "RESERVED":
        err("ERR_SPENT_LOT_INVALID_STATE", "Lot must be RESERVED", 409)
    lot["status"] = "AVAILABLE"
    lot["reserved_buyer_id"] = None
    touch(lot)
    return ok_object(serialize(lot))


@app.route("/api/spent-substrate-lots/<lotId>/sell", methods=["POST"])
def sell_spent(lotId):
    require_role(ROLE_SALES)
    lot = get_spent(lotId)
    if lot["status"] != "RESERVED":
        err("ERR_SPENT_LOT_INVALID_STATE", "Lot must be RESERVED", 409)
    if lot["disposal_only"]:
        err("ERR_SPENT_LOT_DISPOSAL_ONLY", "Lot is disposal_only", 409)
    data = body()
    sale_price = require_number(data, "sale_price_cents", integer=True)
    floor = round0(D(lot["tonnage"]) * D(1500))
    if int(sale_price) < floor:
        err("ERR_PRICE_BELOW_FLOOR", "sale_price_cents below floor", 422)
    lot["sale_price_cents"] = int(sale_price)
    lot["status"] = "SOLD"
    touch(lot)
    batch = db["substrate_batches"][lot["batch_id"]]
    recompute_batch_money(batch)
    touch(batch)
    return ok_object(serialize(lot))


@app.route("/api/spent-substrate-lots/<lotId>/dispose", methods=["POST"])
def dispose_spent(lotId):
    require_role(ROLE_FARM)
    lot = get_spent(lotId)
    if lot["status"] not in ("AVAILABLE", "RESERVED"):
        err("ERR_SPENT_LOT_INVALID_STATE", "Lot must be AVAILABLE or RESERVED", 409)
    cost = round0(D(lot["tonnage"]) * D(2500))
    lot["disposal_cost_cents"] = cost
    lot["status"] = "DISPOSED"
    lot["reserved_buyer_id"] = None
    touch(lot)
    batch = db["substrate_batches"][lot["batch_id"]]
    recompute_batch_money(batch)
    touch(batch)
    return ok_object(serialize(lot))


# =========================================================================
# Health / diagnostics (not in spec, but useful)
# =========================================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =========================================================================
# Main
# =========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
