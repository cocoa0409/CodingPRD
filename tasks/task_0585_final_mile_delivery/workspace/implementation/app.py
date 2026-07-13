"""
Final-Mile Big & Bulky Delivery API — Python + Flask reference implementation.

All storage is in-memory (Python dicts keyed by id). The store starts EMPTY on
every boot; no entity is seeded, preloaded, or hardcoded. Tests build every
precondition through the declared API surface.
"""

import math
import os
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (empty on boot; keyed by id, insertion order == created_at ASC)
# ---------------------------------------------------------------------------
depots = {}
docks = {}
teams = {}
customers = {}
orders = {}
windows = {}
routes = {}
stops = {}
appointments = {}
attempts = {}

# ---------------------------------------------------------------------------
# Constants (from PRD §3 / SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
SERVICE_LEVELS = ("THRESHOLD", "ROOM_OF_CHOICE", "WHITE_GLOVE")
SERVICE_BASE_CENTS = {"THRESHOLD": 4000, "ROOM_OF_CHOICE": 7000, "WHITE_GLOVE": 12000}
PER_FLIGHT_CENTS = 800
MAX_BILLABLE_FLIGHTS = 5
ASSEMBLY_FEE_CENTS = 2500
HAUL_AWAY_FLAT_CENTS = 3000
WG_MULTIPLIER = Decimal("1.15")
DISPOSAL_UNIT_LBS = 50
DISPOSAL_PER_UNIT_CENTS = 1000
REATTEMPT_FEE_CENTS = 2000
LIABILITY_VALUE_UNIT_CENTS = 100000
DAMAGE_PENALTY = {"MINOR": 20, "MAJOR": 50, "NONE": 0}
TEAM_PAYOUT_RATE = Decimal("0.375")
MAX_REATTEMPTS = 2

ROLES = ("PlatformAdmin", "DispatchPlanner", "DockCoordinator", "DeliveryLead", "Customer")
OUTCOMES = ("DELIVERED", "REFUSED", "CUSTOMER_UNAVAILABLE", "DAMAGED")
FAILED_OUTCOMES = ("REFUSED", "CUSTOMER_UNAVAILABLE", "DAMAGED")
SEVERITIES = ("NONE", "MINOR", "MAJOR")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers: time, ids, envelope
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}


def obj_response(data, code=200):
    return jsonify({"meta": meta_base(), "response_type": "object", "data": data}), code


def paginate(items):
    def parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    limit = parse("limit", 10)
    offset = parse("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, limit, offset, total, has_more


def list_response(items, code=200):
    page, limit, offset, total, has_more = paginate(items)
    meta = meta_base()
    meta.update({"limit": limit, "offset": offset, "total_count": total, "has_more": has_more})
    return jsonify({"meta": meta, "response_type": "array", "data": page}), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(e):
    # Wrap framework-generated errors (unknown route, bad method) in the envelope.
    error_id = "ERR_NOT_FOUND" if e.code == 404 else "ERR_INVALID_REQUEST"
    body = {"meta": meta_base(), "response_type": "error",
            "data": {"error_id": error_id, "message": e.description or error_id}}
    return jsonify(body), e.code


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(store, fields, versioned=True):
    _id = str(uuid4())
    now = now_iso()
    e = {"id": _id, "created_at": now}
    if versioned:
        e["updated_at"] = now
        e["version"] = 1
    e.update(fields)
    store[_id] = e
    return e


def touch(e):
    e["version"] += 1
    e["updated_at"] = now_iso()


def fetch(store, _id, err_id):
    e = store.get(_id)
    if e is None:
        raise ApiError(err_id, 404, "Resource not found: %s" % _id)
    return e


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s not permitted for this operation" % role)


# ---------------------------------------------------------------------------
# Request body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_bool(x):
    return isinstance(x, bool)


def validation_error(msg="Invalid payload"):
    raise ApiError("ERR_VALIDATION", 422, msg)


def require_present(body, keys):
    for k in keys:
        if k not in body or body[k] is None:
            validation_error("Missing required field: %s" % k)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def weight_surcharge_cents(weight_lbs):
    if weight_lbs <= 75:
        return 0
    if weight_lbs <= 150:
        return 1500
    if weight_lbs <= 300:
        return 3500
    return 6000


def compute_quote(o):
    base = SERVICE_BASE_CENTS[o["service_level"]]
    wsur = weight_surcharge_cents(o["weight_lbs"])
    mult = WG_MULTIPLIER if o["service_level"] == "WHITE_GLOVE" else Decimal("1")
    core = round_half_up(Decimal(base + wsur) * mult)
    stair = min(o["stair_flights"], MAX_BILLABLE_FLIGHTS) * PER_FLIGHT_CENTS
    total = core + stair
    if o["assembly_required"]:
        total += ASSEMBLY_FEE_CENTS
    if o["haul_away_required"]:
        total += HAUL_AWAY_FLAT_CENTS
    return total


def compute_final(o, att):
    plevel = att["placement"] or o["service_level"]
    base = SERVICE_BASE_CENTS[plevel]
    wsur = weight_surcharge_cents(o["weight_lbs"])
    mult = WG_MULTIPLIER if plevel == "WHITE_GLOVE" else Decimal("1")
    core = round_half_up(Decimal(base + wsur) * mult)
    stair = min(o["stair_flights"], MAX_BILLABLE_FLIGHTS) * PER_FLIGHT_CENTS
    assembly = ASSEMBLY_FEE_CENTS if att["assembly_completed"] else 0
    debris = att["debris_weight_lbs"]
    disposal = (math.ceil(debris / DISPOSAL_UNIT_LBS) * DISPOSAL_PER_UNIT_CENTS) if debris > 0 else 0
    reattempt = REATTEMPT_FEE_CENTS * o["reattempt_count"]
    return core + stair + assembly + disposal + reattempt


# ---------------------------------------------------------------------------
# Reconciliation helpers (each recompute is a mutation -> bump version)
# ---------------------------------------------------------------------------
def recompute_team_estimated(team_id):
    team = teams.get(team_id)
    if team is None:
        return
    total = 0
    for w in windows.values():
        if w["team_id"] == team_id and w["status"] in ("RESERVED", "CONFIRMED"):
            o = orders.get(w["order_id"])
            if o is not None and o["service_level"] == "WHITE_GLOVE":
                total += math.ceil(o["declared_value_cents"] / LIABILITY_VALUE_UNIT_CENTS)
    team["estimated_liability_points"] = total
    touch(team)


def recompute_route_load(route):
    active = [s for s in stops.values()
              if s["route_id"] == route["id"] and s["status"] in ("PLANNED", "COMPLETED")]
    route["committed_stops"] = len(active)
    route["committed_weight_lbs"] = sum(orders[s["order_id"]]["weight_lbs"] for s in active)
    route["committed_volume_cuft"] = sum(orders[s["order_id"]]["volume_cuft"] for s in active)
    touch(route)


def set_dock_ready(route):
    appt_id = route["dock_appointment_id"]
    ready = appt_id is not None and appt_id in appointments and appointments[appt_id]["status"] == "BOOKED"
    route["dock_ready"] = ready


def release_window(win):
    win["status"] = "RELEASED"
    touch(win)
    recompute_team_estimated(win["team_id"])


# ---------------------------------------------------------------------------
# Generic filtered list helper
# ---------------------------------------------------------------------------
def filtered(store, filters):
    """filters: list of (query_param_name, entity_field_name)."""
    result = list(store.values())
    for qname, fname in filters:
        val = request.args.get(qname)
        if val is not None:
            result = [e for e in result if str(e.get(fname)) == val]
    return result


# ===========================================================================
# Health
# ===========================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ===========================================================================
# Depot
# ===========================================================================
@app.route("/depots", methods=["POST"])
def create_depot():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_present(body, ["name", "region_code"])
    if not isinstance(body["name"], str) or not isinstance(body["region_code"], str):
        validation_error("name and region_code must be strings")
    depot = new_entity(depots, {"name": body["name"], "region_code": body["region_code"]})
    return obj_response(depot, 201)


@app.route("/depots", methods=["GET"])
def list_depots():
    auth()
    return list_response(filtered(depots, []))


# ===========================================================================
# Dock
# ===========================================================================
@app.route("/docks", methods=["POST"])
def create_dock():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    if body.get("depot_id") is not None:
        fetch(depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    require_present(body, ["depot_id", "dock_code"])
    if not isinstance(body["dock_code"], str):
        validation_error("dock_code must be a string")
    slot = body.get("slot_length_min", 60)
    buf = body.get("buffer_min", 30)
    if slot is None:
        slot = 60
    if buf is None:
        buf = 30
    if not is_int(slot) or not is_int(buf):
        validation_error("slot_length_min and buffer_min must be integers")
    dock = new_entity(docks, {
        "depot_id": body["depot_id"], "dock_code": body["dock_code"],
        "slot_length_min": slot, "buffer_min": buf, "status": "OPEN",
    })
    return obj_response(dock, 201)


@app.route("/docks", methods=["GET"])
def list_docks():
    auth()
    return list_response(filtered(docks, [("depot_id", "depot_id")]))


@app.route("/docks/<dock_id>", methods=["GET"])
def get_dock(dock_id):
    auth()
    return obj_response(fetch(docks, dock_id, "ERR_DOCK_NOT_FOUND"))


@app.route("/docks/<dock_id>/close", methods=["POST"])
def close_dock(dock_id):
    uid, role = auth()
    require_role(role, {"DockCoordinator"})
    dock = fetch(docks, dock_id, "ERR_DOCK_NOT_FOUND")
    if dock["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Dock is not OPEN")
    dock["status"] = "CLOSED"
    touch(dock)
    # cascade hop1: release BOOKED appointments on this dock; hop2: clear route link
    for appt in appointments.values():
        if appt["dock_id"] == dock_id and appt["status"] == "BOOKED":
            appt["status"] = "RELEASED"
            touch(appt)
            route = routes.get(appt["route_id"])
            if route is not None:
                route["dock_appointment_id"] = None
                set_dock_ready(route)
                touch(route)
    return obj_response(dock)


# ===========================================================================
# DeliveryTeam
# ===========================================================================
@app.route("/delivery-teams", methods=["POST"])
def create_team():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    if body.get("depot_id") is not None:
        fetch(depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    require_present(body, ["depot_id", "team_name", "lead_name", "member2_name", "region_code",
                           "max_daily_stops", "max_daily_weight_lbs", "max_daily_volume_cuft"])
    for k in ("team_name", "lead_name", "member2_name", "region_code"):
        if not isinstance(body[k], str):
            validation_error("%s must be a string" % k)
    for k in ("max_daily_stops", "max_daily_weight_lbs", "max_daily_volume_cuft"):
        if not is_int(body[k]):
            validation_error("%s must be an integer" % k)
    wg = body.get("white_glove_certified", False)
    asm = body.get("assembly_certified", False)
    if wg is None:
        wg = False
    if asm is None:
        asm = False
    if not is_bool(wg) or not is_bool(asm):
        validation_error("certification flags must be booleans")
    status = body.get("status", "ACTIVE")
    if status is None:
        status = "ACTIVE"
    if status not in ("ACTIVE", "OUT_OF_SERVICE"):
        validation_error("status must be ACTIVE or OUT_OF_SERVICE")
    team = new_entity(teams, {
        "depot_id": body["depot_id"], "team_name": body["team_name"],
        "lead_name": body["lead_name"], "member2_name": body["member2_name"],
        "region_code": body["region_code"], "max_daily_stops": body["max_daily_stops"],
        "max_daily_weight_lbs": body["max_daily_weight_lbs"],
        "max_daily_volume_cuft": body["max_daily_volume_cuft"],
        "white_glove_certified": wg, "assembly_certified": asm, "status": status,
        "estimated_liability_points": 0, "settled_liability_points": 0,
    })
    return obj_response(team, 201)


@app.route("/delivery-teams", methods=["GET"])
def list_teams():
    auth()
    return list_response(filtered(teams, [("depot_id", "depot_id")]))


@app.route("/delivery-teams/<team_id>", methods=["GET"])
def get_team(team_id):
    auth()
    return obj_response(fetch(teams, team_id, "ERR_TEAM_NOT_FOUND"))


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    uid, role = auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_present(body, ["full_name", "address_line", "region_code", "geo_lat", "geo_lng"])
    for k in ("full_name", "address_line", "region_code"):
        if not isinstance(body[k], str):
            validation_error("%s must be a string" % k)
    for k in ("geo_lat", "geo_lng"):
        if not is_number(body[k]):
            validation_error("%s must be a number" % k)
    cust = new_entity(customers, {
        "full_name": body["full_name"], "address_line": body["address_line"],
        "region_code": body["region_code"], "geo_lat": body["geo_lat"], "geo_lng": body["geo_lng"],
        "outstanding_balance_cents": 0,
    })
    return obj_response(cust, 201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    auth()
    return obj_response(fetch(customers, customer_id, "ERR_CUSTOMER_NOT_FOUND"))


# ===========================================================================
# DeliveryOrder
# ===========================================================================
@app.route("/delivery-orders", methods=["POST"])
def create_order():
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    body = get_body()
    if body.get("customer_id") is not None:
        fetch(customers, body["customer_id"], "ERR_CUSTOMER_NOT_FOUND")
    require_present(body, ["customer_id", "item_description", "weight_lbs", "volume_cuft",
                           "declared_value_cents", "service_level"])
    if not isinstance(body["item_description"], str):
        validation_error("item_description must be a string")
    if not is_number(body["weight_lbs"]) or body["weight_lbs"] <= 0:
        validation_error("weight_lbs must be a number > 0")
    if not is_number(body["volume_cuft"]) or body["volume_cuft"] <= 0:
        validation_error("volume_cuft must be a number > 0")
    if not is_int(body["declared_value_cents"]) or body["declared_value_cents"] < 0:
        validation_error("declared_value_cents must be an integer >= 0")
    if body["service_level"] not in SERVICE_LEVELS:
        validation_error("invalid service_level")
    assembly = body.get("assembly_required", False)
    haul = body.get("haul_away_required", False)
    stair = body.get("stair_flights", 0)
    if assembly is None:
        assembly = False
    if haul is None:
        haul = False
    if stair is None:
        stair = 0
    if not is_bool(assembly) or not is_bool(haul):
        validation_error("assembly_required and haul_away_required must be booleans")
    if not is_int(stair) or stair < 0:
        validation_error("stair_flights must be an integer >= 0")

    order = new_entity(orders, {
        "customer_id": body["customer_id"], "item_description": body["item_description"],
        "weight_lbs": body["weight_lbs"], "volume_cuft": body["volume_cuft"],
        "declared_value_cents": body["declared_value_cents"], "service_level": body["service_level"],
        "assembly_required": assembly, "haul_away_required": haul, "stair_flights": stair,
        "status": "CREATED", "reattempt_count": 0,
        "active_window_id": None, "active_stop_id": None, "actual_placement_level": None,
        "quoted_fee_cents": 0, "final_fee_cents": None,
    })
    order["quoted_fee_cents"] = compute_quote(order)
    return obj_response(order, 201)


@app.route("/delivery-orders", methods=["GET"])
def list_orders():
    auth()
    return list_response(filtered(orders, [("customer_id", "customer_id"), ("status", "status")]))


@app.route("/delivery-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    auth()
    return obj_response(fetch(orders, order_id, "ERR_ORDER_NOT_FOUND"))


@app.route("/delivery-orders/<order_id>/windows", methods=["POST"])
def reserve_window(order_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    order = fetch(orders, order_id, "ERR_ORDER_NOT_FOUND")
    body = get_body()
    # existence of body FK (team_id) when provided (left-to-right after path)
    team = None
    if body.get("team_id") is not None:
        team = fetch(teams, body["team_id"], "ERR_TEAM_NOT_FOUND")
    # payload validity
    require_present(body, ["team_id", "service_date", "window_start_min",
                           "window_end_min", "expected_order_version"])
    if not isinstance(body["service_date"], str):
        validation_error("service_date must be a string")
    ws, we = body["window_start_min"], body["window_end_min"]
    if not is_int(ws) or not is_int(we):
        validation_error("window bounds must be integers")
    if not is_int(body["expected_order_version"]):
        validation_error("expected_order_version must be an integer")
    if we <= ws:
        raise ApiError("ERR_INVALID_WINDOW", 422, "window_end_min must be > window_start_min")
    # optimistic concurrency
    if body["expected_order_version"] != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_order_version does not match")
    # state legality
    st = order["status"]
    if st not in ("CREATED", "SCHEDULED", "REFUSED_RETRY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order not in a schedulable state")
    if st == "SCHEDULED" and order["active_stop_id"] is not None:
        raise ApiError("ERR_INVALID_STATE", 409, "Order already routed")
    # referential (8): region match
    customer = customers[order["customer_id"]]
    if team["region_code"] != customer["region_code"]:
        raise ApiError("ERR_REGION_MISMATCH", 409, "Team region does not match customer region")
    # safety (9): team in service
    if team["status"] != "ACTIVE":
        raise ApiError("ERR_TEAM_OUT_OF_SERVICE", 409, "Team is out of service")
    # safety (9): certification
    if order["service_level"] == "WHITE_GLOVE" and not team["white_glove_certified"]:
        raise ApiError("ERR_TEAM_NOT_CERTIFIED", 409, "Team not white-glove certified")
    if order["assembly_required"] and not team["assembly_certified"]:
        raise ApiError("ERR_TEAM_NOT_CERTIFIED", 409, "Team not assembly certified")
    # temporal (10): team calendar overlap (exclude order's own current active window)
    for w in windows.values():
        if (w["team_id"] == team["id"] and w["status"] in ("RESERVED", "CONFIRMED")
                and w["service_date"] == body["service_date"] and w["id"] != order["active_window_id"]):
            if ws < w["window_end_min"] and w["window_start_min"] < we:
                raise ApiError("ERR_TEAM_WINDOW_CONFLICT", 409, "Overlapping team window")
    # limit (11): reattempt ceiling on reschedule
    if st == "REFUSED_RETRY" and order["reattempt_count"] >= MAX_REATTEMPTS:
        raise ApiError("ERR_MAX_REATTEMPTS", 409, "Reattempt ceiling reached")

    # side effects
    old_team_id = None
    if order["active_window_id"]:
        ow = windows.get(order["active_window_id"])
        if ow is not None and ow["status"] in ("RESERVED", "CONFIRMED"):
            old_team_id = ow["team_id"]
            ow["status"] = "RELEASED"
            touch(ow)
    win = new_entity(windows, {
        "order_id": order_id, "team_id": team["id"], "service_date": body["service_date"],
        "window_start_min": ws, "window_end_min": we, "status": "RESERVED",
    })
    order["active_window_id"] = win["id"]
    order["status"] = "SCHEDULED"
    touch(order)  # increments DeliveryOrder.version by 1
    recompute_team_estimated(team["id"])
    if old_team_id is not None and old_team_id != team["id"]:
        recompute_team_estimated(old_team_id)
    return obj_response(win, 201)


@app.route("/delivery-orders/<order_id>/attempts", methods=["GET"])
def list_order_attempts(order_id):
    auth()
    fetch(orders, order_id, "ERR_ORDER_NOT_FOUND")
    items = [a for a in attempts.values() if a["order_id"] == order_id]
    return list_response(items)


@app.route("/delivery-orders/<order_id>/attempts", methods=["POST"])
def record_attempt(order_id):
    uid, role = auth()
    require_role(role, {"DeliveryLead"})
    order = fetch(orders, order_id, "ERR_ORDER_NOT_FOUND")
    body = get_body()
    # payload validity
    require_present(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in OUTCOMES:
        validation_error("invalid outcome")
    severity = body.get("damage_severity", "NONE")
    if severity is None:
        severity = "NONE"
    if severity not in SEVERITIES:
        validation_error("invalid damage_severity")
    placement = body.get("placement")
    if placement is not None and placement not in SERVICE_LEVELS:
        validation_error("invalid placement")
    signature = body.get("signature_captured", False)
    if signature is None:
        signature = False
    if not is_bool(signature):
        validation_error("signature_captured must be a boolean")
    photo_count = body.get("photo_count", 0)
    if photo_count is None:
        photo_count = 0
    if not is_int(photo_count) or photo_count < 0:
        validation_error("photo_count must be an integer >= 0")
    assembly_completed = body.get("assembly_completed", False)
    if assembly_completed is None:
        assembly_completed = False
    if not is_bool(assembly_completed):
        validation_error("assembly_completed must be a boolean")
    debris = body.get("debris_weight_lbs", 0)
    if debris is None:
        debris = 0
    if not is_number(debris) or debris < 0:
        validation_error("debris_weight_lbs must be a number >= 0")
    refusal_reason = body.get("refusal_reason")
    if refusal_reason is not None and not isinstance(refusal_reason, str):
        validation_error("refusal_reason must be a string")

    # state legality
    if order["status"] != "OUT_FOR_DELIVERY":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not out for delivery")
    # referential (8): acting crew == route team of order's active stop
    stop = stops.get(order["active_stop_id"])
    route = routes.get(stop["route_id"]) if stop else None
    if route is None or route["team_id"] != uid:
        raise ApiError("ERR_STOP_ORDER_MISMATCH", 409, "Acting crew is not the route team")
    team = teams.get(route["team_id"])

    if outcome == "DELIVERED":
        eff_placement = placement or order["service_level"]
        # safety (9): certification re-checked at the door
        if eff_placement == "WHITE_GLOVE" and (team is None or not team["white_glove_certified"]):
            raise ApiError("ERR_TEAM_NOT_CERTIFIED", 409, "Team not white-glove certified")
        if assembly_completed and (team is None or not team["assembly_certified"]):
            raise ApiError("ERR_TEAM_NOT_CERTIFIED", 409, "Team not assembly certified")
        # safety (9): proof of delivery
        if not (signature is True and photo_count >= 1):
            raise ApiError("ERR_POD_REQUIRED", 422, "Signature and at least one photo required")

        att = new_entity(attempts, {
            "order_id": order_id, "stop_id": stop["id"],
            "attempt_number": order["reattempt_count"] + 1, "outcome": outcome,
            "refusal_reason": refusal_reason, "damage_severity": severity,
            "placement": eff_placement, "signature_captured": signature,
            "photo_count": photo_count, "assembly_completed": assembly_completed,
            "debris_weight_lbs": debris, "fee_delta_cents": 0,
        }, versioned=False)
        # stop -> COMPLETED (still occupies route capacity: no route recompute)
        stop["status"] = "COMPLETED"
        touch(stop)
        order["actual_placement_level"] = eff_placement
        order["final_fee_cents"] = compute_final(order, att)
        disposal = (math.ceil(debris / DISPOSAL_UNIT_LBS) * DISPOSAL_PER_UNIT_CENTS) if debris > 0 else 0
        att["fee_delta_cents"] = disposal + REATTEMPT_FEE_CENTS * order["reattempt_count"]
        # window -> COMPLETED
        win = windows.get(order["active_window_id"])
        if win is not None:
            win["status"] = "COMPLETED"
            touch(win)
            recompute_team_estimated(win["team_id"])
        order["status"] = "DELIVERED"
        order["active_window_id"] = None
        order["active_stop_id"] = None
        touch(order)
        return obj_response(att, 201)

    # FAILED outcome (three-hop cascade)
    att = new_entity(attempts, {
        "order_id": order_id, "stop_id": stop["id"],
        "attempt_number": order["reattempt_count"] + 1, "outcome": outcome,
        "refusal_reason": refusal_reason, "damage_severity": severity,
        "placement": placement, "signature_captured": signature,
        "photo_count": photo_count, "assembly_completed": assembly_completed,
        "debris_weight_lbs": debris, "fee_delta_cents": REATTEMPT_FEE_CENTS,
    }, versioned=False)
    order["reattempt_count"] += 1
    stop["status"] = "SKIPPED"
    touch(stop)
    recompute_route_load(route)  # capacity released
    win = windows.get(order["active_window_id"])
    if win is not None and win["status"] in ("RESERVED", "CONFIRMED"):
        release_window(win)
    if outcome == "DAMAGED" and team is not None:
        team["settled_liability_points"] += DAMAGE_PENALTY[severity]
        touch(team)
    order["status"] = "REFUSED_RETRY"
    order["active_window_id"] = None
    order["active_stop_id"] = None
    touch(order)
    return obj_response(att, 201)


@app.route("/delivery-orders/<order_id>/settle", methods=["POST"])
def settle_order(order_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    order = fetch(orders, order_id, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not delivered")
    order["status"] = "SETTLED"
    touch(order)
    cust = customers.get(order["customer_id"])
    if cust is not None:
        cust["outstanding_balance_cents"] += order["final_fee_cents"]
        touch(cust)
    return obj_response(order)


@app.route("/delivery-orders/<order_id>/void-delivery", methods=["POST"])
def void_delivery(order_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    order = fetch(orders, order_id, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "SETTLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not settled")
    order["status"] = "RETURNED"
    touch(order)
    cust = customers.get(order["customer_id"])
    if cust is not None:
        cust["outstanding_balance_cents"] -= order["final_fee_cents"]
        touch(cust)
    return obj_response(order)


@app.route("/delivery-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    order = fetch(orders, order_id, "ERR_ORDER_NOT_FOUND")
    if order["status"] not in ("CREATED", "SCHEDULED", "REFUSED_RETRY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled")
    if order["active_window_id"]:
        w = windows.get(order["active_window_id"])
        if w is not None and w["status"] in ("RESERVED", "CONFIRMED"):
            release_window(w)
        order["active_window_id"] = None
    order["status"] = "CANCELLED"
    touch(order)
    return obj_response(order)


# ===========================================================================
# DeliveryWindow
# ===========================================================================
@app.route("/delivery-windows", methods=["GET"])
def list_windows():
    auth()
    return list_response(filtered(windows, [("order_id", "order_id"), ("team_id", "team_id")]))


@app.route("/delivery-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    auth()
    return obj_response(fetch(windows, window_id, "ERR_WINDOW_NOT_FOUND"))


@app.route("/delivery-windows/<window_id>/confirm", methods=["POST"])
def confirm_window(window_id):
    uid, role = auth()
    require_role(role, {"Customer"})
    win = fetch(windows, window_id, "ERR_WINDOW_NOT_FOUND")
    order = orders.get(win["order_id"])
    # resource ownership: acting customer owns the window's order
    if order is None or order["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Window does not belong to this customer")
    # state legality
    if win["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not reserved")
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not scheduled")
    win["status"] = "CONFIRMED"
    touch(win)
    return obj_response(win)


# ===========================================================================
# Route
# ===========================================================================
@app.route("/routes", methods=["POST"])
def create_route():
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    body = get_body()
    if body.get("depot_id") is not None:
        fetch(depots, body["depot_id"], "ERR_DEPOT_NOT_FOUND")
    if body.get("team_id") is not None:
        fetch(teams, body["team_id"], "ERR_TEAM_NOT_FOUND")
    require_present(body, ["depot_id", "team_id", "service_date"])
    if not isinstance(body["service_date"], str):
        validation_error("service_date must be a string")
    route = new_entity(routes, {
        "depot_id": body["depot_id"], "team_id": body["team_id"], "service_date": body["service_date"],
        "status": "PLANNING", "dock_appointment_id": None, "dock_ready": False,
        "committed_stops": 0, "committed_weight_lbs": 0, "committed_volume_cuft": 0,
        "route_settlement_cents": None,
    })
    return obj_response(route, 201)


@app.route("/routes", methods=["GET"])
def list_routes():
    auth()
    return list_response(filtered(routes, [("depot_id", "depot_id"), ("team_id", "team_id")]))


@app.route("/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    auth()
    return obj_response(fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND"))


@app.route("/routes/<route_id>/stops", methods=["POST"])
def add_stop(route_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    route = fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND")
    body = get_body()
    order = None
    win = None
    if body.get("order_id") is not None:
        order = fetch(orders, body["order_id"], "ERR_ORDER_NOT_FOUND")
    if body.get("window_id") is not None:
        win = fetch(windows, body["window_id"], "ERR_WINDOW_NOT_FOUND")
    require_present(body, ["order_id", "window_id"])
    sequence = body.get("sequence", 0)
    if sequence is None:
        sequence = 0
    if not is_int(sequence):
        validation_error("sequence must be an integer")
    # state legality: a second stop for an already-routed order is rejected
    # with ERR_ORDER_ALREADY_ROUTED (this specific case takes precedence over
    # the generic SCHEDULED-state check, otherwise the error is unreachable).
    if order["active_stop_id"] is not None:
        raise ApiError("ERR_ORDER_ALREADY_ROUTED", 409, "Order already has an active stop")
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not scheduled")
    if route["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Route not in planning")
    # referential (8)
    if win["id"] != order["active_window_id"] or win["team_id"] != route["team_id"]:
        raise ApiError("ERR_ROUTE_TEAM_MISMATCH", 409, "Window/route team mismatch")
    if win["service_date"] != route["service_date"]:
        raise ApiError("ERR_WINDOW_ROUTE_DATE_MISMATCH", 409, "Window/route date mismatch")
    # fiscal (12): capacity
    team = teams.get(route["team_id"])
    if route["committed_stops"] + 1 > team["max_daily_stops"]:
        raise ApiError("ERR_ROUTE_STOPS_EXCEEDED", 409, "Route stop capacity exceeded")
    if route["committed_weight_lbs"] + order["weight_lbs"] > team["max_daily_weight_lbs"]:
        raise ApiError("ERR_ROUTE_WEIGHT_EXCEEDED", 409, "Route weight capacity exceeded")
    if route["committed_volume_cuft"] + order["volume_cuft"] > team["max_daily_volume_cuft"]:
        raise ApiError("ERR_ROUTE_VOLUME_EXCEEDED", 409, "Route volume capacity exceeded")

    stop = new_entity(stops, {
        "route_id": route_id, "order_id": order["id"], "window_id": win["id"],
        "sequence": sequence, "status": "PLANNED",
    })
    order["active_stop_id"] = stop["id"]
    order["status"] = "ROUTED"
    touch(order)
    recompute_route_load(route)
    return obj_response(stop, 201)


@app.route("/routes/<route_id>/stops", methods=["GET"])
def list_route_stops(route_id):
    auth()
    fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND")
    items = [s for s in stops.values() if s["route_id"] == route_id]
    return list_response(items)


@app.route("/routes/<route_id>/stops/<stop_id>/remove", methods=["POST"])
def remove_stop(route_id, stop_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    route = fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND")
    stop = fetch(stops, stop_id, "ERR_STOP_NOT_FOUND")
    if stop["route_id"] != route_id:
        raise ApiError("ERR_STOP_NOT_FOUND", 404, "Stop not on this route")
    if route["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Route not in planning")
    if stop["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Stop not planned")
    stop["status"] = "SKIPPED"
    touch(stop)
    order = orders.get(stop["order_id"])
    if order is not None:
        order["status"] = "SCHEDULED"
        order["active_stop_id"] = None
        touch(order)
    recompute_route_load(route)
    return obj_response(stop)


@app.route("/routes/<route_id>/dispatch", methods=["POST"])
def dispatch_route(route_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    route = fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Route not in planning")
    if route["committed_stops"] < 1:
        raise ApiError("ERR_INVALID_STATE", 409, "Route has no committed stops")
    if not route["dock_ready"]:
        raise ApiError("ERR_DOCK_APPOINTMENT_MISSING", 409, "No booked dock appointment")
    for s in stops.values():
        if s["route_id"] == route_id and s["status"] == "PLANNED":
            o = orders.get(s["order_id"])
            if o is not None and o["status"] == "ROUTED":
                o["status"] = "OUT_FOR_DELIVERY"
                touch(o)
    route["status"] = "DISPATCHED"
    touch(route)
    return obj_response(route)


@app.route("/routes/<route_id>/close", methods=["POST"])
def close_route(route_id):
    uid, role = auth()
    require_role(role, {"DispatchPlanner"})
    route = fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND")
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Route not dispatched")
    route_stops = [s for s in stops.values() if s["route_id"] == route_id]
    for s in route_stops:
        if s["status"] not in ("COMPLETED", "SKIPPED"):
            raise ApiError("ERR_ROUTE_NOT_READY_TO_CLOSE", 409, "Route has non-terminal stops")
    completed = [s for s in route_stops if s["status"] == "COMPLETED"]
    settlement = 0
    for s in completed:
        o = orders[s["order_id"]]
        settlement += round_half_up(Decimal(o["final_fee_cents"]) * TEAM_PAYOUT_RATE)
    route["route_settlement_cents"] = settlement
    route["status"] = "CLOSED"
    appt_id = route["dock_appointment_id"]
    if appt_id is not None and appt_id in appointments and appointments[appt_id]["status"] == "BOOKED":
        appointments[appt_id]["status"] = "COMPLETED"
        touch(appointments[appt_id])
    set_dock_ready(route)
    touch(route)
    return obj_response(route)


# ===========================================================================
# RouteStop (top-level access)
# ===========================================================================
@app.route("/route-stops/<stop_id>", methods=["GET"])
def get_route_stop(stop_id):
    auth()
    return obj_response(fetch(stops, stop_id, "ERR_STOP_NOT_FOUND"))


@app.route("/route-stops", methods=["GET"])
def list_route_stops_top():
    auth()
    return list_response(filtered(stops, [("route_id", "route_id"),
                                          ("order_id", "order_id"), ("window_id", "window_id")]))


# ===========================================================================
# DockAppointment
# ===========================================================================
@app.route("/routes/<route_id>/dock-appointments", methods=["POST"])
def book_dock_appointment(route_id):
    uid, role = auth()
    require_role(role, {"DockCoordinator"})
    route = fetch(routes, route_id, "ERR_ROUTE_NOT_FOUND")
    body = get_body()
    dock = None
    if body.get("dock_id") is not None:
        dock = fetch(docks, body["dock_id"], "ERR_DOCK_NOT_FOUND")
    require_present(body, ["dock_id", "appt_date", "appt_start_min", "appt_end_min"])
    if not isinstance(body["appt_date"], str):
        validation_error("appt_date must be a string")
    a_start, a_end = body["appt_start_min"], body["appt_end_min"]
    if not is_int(a_start) or not is_int(a_end):
        validation_error("appointment bounds must be integers")
    if a_end <= a_start:
        validation_error("appt_end_min must be > appt_start_min")
    # temporal (10): dock buffer conflict against BOOKED appts on same dock/date
    buffer_min = dock["buffer_min"]
    for appt in appointments.values():
        if appt["dock_id"] == dock["id"] and appt["status"] == "BOOKED" and appt["appt_date"] == body["appt_date"]:
            es, ee = appt["appt_start_min"], appt["appt_end_min"]
            if a_start >= ee:
                gap = a_start - ee
            elif es >= a_end:
                gap = es - a_end
            else:
                gap = -1  # overlapping
            if gap < buffer_min:
                raise ApiError("ERR_DOCK_SLOT_CONFLICT", 409, "Dock buffer conflict")
    appt = new_entity(appointments, {
        "dock_id": dock["id"], "route_id": route_id, "appt_date": body["appt_date"],
        "appt_start_min": a_start, "appt_end_min": a_end, "status": "BOOKED",
    })
    route["dock_appointment_id"] = appt["id"]
    set_dock_ready(route)
    touch(route)
    return obj_response(appt, 201)


@app.route("/dock-appointments/<appt_id>", methods=["GET"])
def get_dock_appointment(appt_id):
    auth()
    return obj_response(fetch(appointments, appt_id, "ERR_APPOINTMENT_NOT_FOUND"))


@app.route("/dock-appointments", methods=["GET"])
def list_dock_appointments():
    auth()
    return list_response(filtered(appointments, [("dock_id", "dock_id"), ("route_id", "route_id")]))


# ===========================================================================
# DeliveryAttempt (top-level access)
# ===========================================================================
@app.route("/delivery-attempts/<attempt_id>", methods=["GET"])
def get_attempt(attempt_id):
    auth()
    return obj_response(fetch(attempts, attempt_id, "ERR_ATTEMPT_NOT_FOUND"))


@app.route("/delivery-attempts", methods=["GET"])
def list_attempts():
    auth()
    return list_response(filtered(attempts, [("order_id", "order_id"), ("stop_id", "stop_id")]))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
