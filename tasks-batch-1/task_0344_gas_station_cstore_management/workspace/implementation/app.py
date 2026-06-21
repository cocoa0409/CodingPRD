"""Gas Station & C-Store Management API — Flask entry point.

In-memory only. No seeding. Storage lives in db.py module-level dicts that
start empty on every boot. Tests construct all entities via the API surface.
"""
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, request

from db import db, new_id, now_iso, EPOCH_BASELINE
from errors import ApiError, fail
import errors as E
from response import object_response, array_response, error_response
from helpers import (
    get_auth,
    require_role,
    get_body,
    require_fields,
    require_string,
    require_int,
    require_number,
    require_enum,
    optional_int,
    must_exist,
    stamp_new,
    bump,
    check_occ,
    parse_pagination,
    paginate,
    public,
    public_list,
    round_half_up,
    round_half_up_2dp,
    g3,
)
import services as S

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Error handling — every ApiError becomes the standard error envelope (§2.2).
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", str(err), 422)


# --------------------------------------------------------------------------- #
# Clock helpers (§2.5)
# --------------------------------------------------------------------------- #
def parse_iso(value):
    """Parse an ISO 8601 instant (with optional trailing Z) to aware datetime."""
    if not isinstance(value, str):
        fail(E.ERR_INVALID_REQUEST, "Timestamp must be a string")
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        fail(E.ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp")


def iso_str(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days_iso(iso_value, days):
    dt = parse_iso(iso_value)
    return iso_str(dt + timedelta(days=days))


# --------------------------------------------------------------------------- #
# STATION
# --------------------------------------------------------------------------- #
@app.route("/stations", methods=["POST"])
def create_station():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["name", "brand"])
    name = require_string(body, "name")
    brand = require_string(body, "brand")
    tax_rate_bp = optional_int(body, "tax_rate_bp")
    if tax_rate_bp is None:
        tax_rate_bp = 825
    tol = optional_int(body, "cash_variance_tolerance_cents")
    if tol is None:
        tol = 200
    rec = {
        "id": new_id(),
        "name": name,
        "brand": brand,
        "tax_rate_bp": tax_rate_bp,
        "cash_variance_tolerance_cents": tol,
        "current_utc": EPOCH_BASELINE,
    }
    stamp_new(rec, rec)  # station is its own clock (§2.5); created_at = epoch baseline
    db.stations[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/stations/<station_id>", methods=["GET"])
def get_station(station_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant", "LoyaltyMember"})
    rec = must_exist(db.stations, station_id)
    return object_response(public(rec), 200)


@app.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["station_id", "to_iso8601"])
    station = must_exist(db.stations, body["station_id"])
    target = parse_iso(body["to_iso8601"])
    station["current_utc"] = iso_str(target)
    bump(station)
    return object_response(public(station), 200)


# --------------------------------------------------------------------------- #
# FUEL GRADE
# --------------------------------------------------------------------------- #
FUEL_GRADE_CODES = {"REGULAR", "MIDGRADE", "PREMIUM", "DIESEL"}


@app.route("/fuel-grades", methods=["POST"])
def create_fuel_grade():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["station_id", "code", "octane"])
    station = must_exist(db.stations, body["station_id"])  # FK existence (§2.6)
    code = require_enum(body, "code", FUEL_GRADE_CODES)
    octane = require_int(body, "octane")
    # Per-station uniqueness on code (§2.9, priority 16).
    for g in db.fuel_grades.values():
        if g["station_id"] == station["id"] and g["code"] == code:
            fail(E.ERR_DUPLICATE_GRADE, "Fuel grade code already exists for station")
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "code": code,
        "octane": octane,
        "current_price_cents": 0,
        "prior_price_cents": 0,
        "weighted_avg_cost_cents": 0,
    }
    stamp_new(rec, station)
    db.fuel_grades[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/fuel-grades", methods=["GET"])
def list_fuel_grades():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    items = [g for g in db.fuel_grades.values()
             if station_id is None or g["station_id"] == station_id]
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/fuel-grades/<grade_id>", methods=["GET"])
def get_fuel_grade(grade_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.fuel_grades, grade_id)
    return object_response(public(rec), 200)


@app.route("/fuel-grades/<grade_id>/reprice", methods=["POST"])
def reprice_fuel_grade(grade_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    rec = must_exist(db.fuel_grades, grade_id)
    body = get_body()
    require_fields(body, ["new_price_cents"])
    new_price = require_int(body, "new_price_cents")
    rec["prior_price_cents"] = rec["current_price_cents"]
    rec["current_price_cents"] = new_price
    bump(rec)
    return object_response(public(rec), 200)


# --------------------------------------------------------------------------- #
# TANK
# --------------------------------------------------------------------------- #
@app.route("/tanks", methods=["POST"])
def create_tank():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["station_id", "fuel_grade_id", "label",
                          "capacity_gallons", "reorder_point_gallons"])
    station = must_exist(db.stations, body["station_id"])
    grade = must_exist(db.fuel_grades, body["fuel_grade_id"])
    label = require_string(body, "label")
    capacity = require_number(body, "capacity_gallons")
    reorder = require_number(body, "reorder_point_gallons")
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "fuel_grade_id": grade["id"],
        "label": label,
        "capacity_gallons": g3(capacity),
        "reorder_point_gallons": g3(reorder),
        "volume_gallons": 0,
        "low_stock": False,
        "status": "ACTIVE",
    }
    S.recompute_low_stock(rec)  # low_stock = (0 <= reorder_point) per scaffold/§3.2
    stamp_new(rec, station)
    db.tanks[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/tanks", methods=["GET"])
def list_tanks():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    fuel_grade_id = request.args.get("fuel_grade_id")
    items = []
    for t in db.tanks.values():
        if station_id is not None and t["station_id"] != station_id:
            continue
        if fuel_grade_id is not None and t["fuel_grade_id"] != fuel_grade_id:
            continue
        items.append(t)
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/tanks/<tank_id>", methods=["GET"])
def get_tank(tank_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.tanks, tank_id)
    return object_response(public(rec), 200)


@app.route("/tanks/<tank_id>/take-down", methods=["POST"])
def take_down_tank(tank_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    tank = must_exist(db.tanks, tank_id)
    if tank["status"] != "ACTIVE":
        fail(E.ERR_INVALID_STATE, "Tank is not ACTIVE")
    tank["status"] = "DOWN"
    bump(tank)
    # Cascade: pumps on this tank not already OUT_OF_SERVICE -> OUT_OF_SERVICE (§3.2)
    for p in db.pumps.values():
        if p["tank_id"] == tank_id and p["status"] != "OUT_OF_SERVICE":
            p["status"] = "OUT_OF_SERVICE"
            bump(p)
    return object_response(public(tank), 200)


@app.route("/tanks/<tank_id>/restore", methods=["POST"])
def restore_tank(tank_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    tank = must_exist(db.tanks, tank_id)
    if tank["status"] != "DOWN":
        fail(E.ERR_INVALID_STATE, "Tank is not DOWN")
    tank["status"] = "ACTIVE"
    bump(tank)
    # Cascade: pumps currently OUT_OF_SERVICE on this tank -> IDLE (§3.2)
    for p in db.pumps.values():
        if p["tank_id"] == tank_id and p["status"] == "OUT_OF_SERVICE":
            p["status"] = "IDLE"
            bump(p)
    return object_response(public(tank), 200)


# --------------------------------------------------------------------------- #
# PUMP
# --------------------------------------------------------------------------- #
@app.route("/pumps", methods=["POST"])
def create_pump():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["station_id", "tank_id", "number"])
    station = must_exist(db.stations, body["station_id"])
    tank = must_exist(db.tanks, body["tank_id"])
    number = require_int(body, "number")
    # Per-station uniqueness on number (§2.9).
    for p in db.pumps.values():
        if p["station_id"] == station["id"] and p["number"] == number:
            fail(E.ERR_DUPLICATE_PUMP, "Pump number already exists for station")
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "tank_id": tank["id"],
        "number": number,
        "status": "IDLE",
    }
    stamp_new(rec, station)
    db.pumps[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/pumps", methods=["GET"])
def list_pumps():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    tank_id = request.args.get("tank_id")
    items = []
    for p in db.pumps.values():
        if station_id is not None and p["station_id"] != station_id:
            continue
        if tank_id is not None and p["tank_id"] != tank_id:
            continue
        items.append(p)
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/pumps/<pump_id>", methods=["GET"])
def get_pump(pump_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.pumps, pump_id)
    return object_response(public(rec), 200)


# --------------------------------------------------------------------------- #
# DELIVERY
# --------------------------------------------------------------------------- #
@app.route("/deliveries", methods=["POST"])
def create_delivery():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["station_id", "tank_id", "vendor_name",
                          "net_gallons", "unit_cost_cents"])
    station = must_exist(db.stations, body["station_id"])
    tank = must_exist(db.tanks, body["tank_id"])
    paid_cash = body.get("paid_cash", False)
    if not isinstance(paid_cash, bool):
        fail(E.ERR_INVALID_REQUEST, "paid_cash must be a boolean")
    shift_id = body.get("shift_id")
    # FK existence for shift_id when provided (left-to-right, §2.6).
    if shift_id is not None:
        must_exist(db.shifts, shift_id)
    vendor_name = require_string(body, "vendor_name")
    net_gallons = require_number(body, "net_gallons")
    unit_cost = require_int(body, "unit_cost_cents")
    invoice_total = round_half_up(g3(net_gallons) * unit_cost)
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "tank_id": tank["id"],
        "vendor_name": vendor_name,
        "net_gallons": g3(net_gallons),
        "unit_cost_cents": unit_cost,
        "invoice_total_cents": invoice_total,
        "paid_cash": paid_cash,
        "shift_id": shift_id,
        "status": "DRAFT",
    }
    stamp_new(rec, station)
    db.deliveries[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/deliveries", methods=["GET"])
def list_deliveries():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    tank_id = request.args.get("tank_id")
    shift_id = request.args.get("shift_id")
    items = []
    for d in db.deliveries.values():
        if station_id is not None and d["station_id"] != station_id:
            continue
        if tank_id is not None and d["tank_id"] != tank_id:
            continue
        if shift_id is not None and d["shift_id"] != shift_id:
            continue
        items.append(d)
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/deliveries/<delivery_id>", methods=["GET"])
def get_delivery(delivery_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.deliveries, delivery_id)
    return object_response(public(rec), 200)


@app.route("/deliveries/<delivery_id>/post", methods=["POST"])
def post_delivery(delivery_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    delivery = must_exist(db.deliveries, delivery_id)
    body = get_body()
    require_fields(body, ["expected_tank_version"])
    require_int(body, "expected_tank_version")
    tank = db.tanks[delivery["tank_id"]]
    # Validation ordering (§2.8): state -> shift open -> tank down -> capacity
    # -> OCC.
    if delivery["status"] != "DRAFT":
        fail(E.ERR_INVALID_STATE, "Delivery is not DRAFT")
    # If paid_cash: referenced shift must be OPEN (§3.3, priority 7).
    if delivery["paid_cash"] and delivery["shift_id"] is not None:
        shift = db.shifts[delivery["shift_id"]]
        if shift["lifecycle_status"] != "OPEN":
            fail(E.ERR_SHIFT_NOT_OPEN, "Charged shift is not OPEN")
    if tank["status"] != "ACTIVE":
        fail(E.ERR_TANK_DOWN, "Delivery target tank is DOWN")
    if g3(tank["volume_gallons"] + delivery["net_gallons"]) > tank["capacity_gallons"]:
        fail(E.ERR_TANK_CAPACITY_EXCEEDED, "Posting would exceed tank capacity")
    # OCC on tank version (§2.10, priority 15).
    check_occ(body, "expected_tank_version", tank["version"])
    # Apply.
    delivery["status"] = "POSTED"
    bump(delivery)
    S.add_tank_volume(tank, delivery["net_gallons"])
    bump(tank)
    grade = db.fuel_grades[tank["fuel_grade_id"]]
    S.recompute_wac(grade)
    if delivery["paid_cash"] and delivery["shift_id"] is not None:
        shift = db.shifts[delivery["shift_id"]]
        shift["cash_payouts_cents"] += delivery["invoice_total_cents"]
        S.recompute_expected_drawer(shift)
        bump(shift)
    return object_response(public(delivery), 200)


@app.route("/deliveries/<delivery_id>/reject", methods=["POST"])
def reject_delivery(delivery_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    delivery = must_exist(db.deliveries, delivery_id)
    if delivery["status"] != "DRAFT":
        fail(E.ERR_INVALID_STATE, "Delivery is not DRAFT")
    delivery["status"] = "REJECTED"
    bump(delivery)
    return object_response(public(delivery), 200)


@app.route("/deliveries/<delivery_id>/void", methods=["POST"])
def void_delivery(delivery_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    delivery = must_exist(db.deliveries, delivery_id)
    tank = db.tanks[delivery["tank_id"]]
    if delivery["status"] != "POSTED":
        fail(E.ERR_INVALID_STATE, "Delivery is not POSTED")
    if delivery["paid_cash"] and delivery["shift_id"] is not None:
        shift = db.shifts[delivery["shift_id"]]
        if shift["lifecycle_status"] != "OPEN":
            fail(E.ERR_SHIFT_NOT_OPEN, "Charged shift is not OPEN")
    if g3(tank["volume_gallons"] - delivery["net_gallons"]) < 0:
        fail(E.ERR_NEGATIVE_VOLUME, "Voiding would drive tank volume negative")
    delivery["status"] = "VOIDED"
    bump(delivery)
    S.add_tank_volume(tank, -delivery["net_gallons"])
    bump(tank)
    grade = db.fuel_grades[tank["fuel_grade_id"]]
    S.recompute_wac(grade)
    if delivery["paid_cash"] and delivery["shift_id"] is not None:
        shift = db.shifts[delivery["shift_id"]]
        shift["cash_payouts_cents"] -= delivery["invoice_total_cents"]
        S.recompute_expected_drawer(shift)
        bump(shift)
    return object_response(public(delivery), 200)


# --------------------------------------------------------------------------- #
# SHIFT
# --------------------------------------------------------------------------- #
@app.route("/shifts", methods=["POST"])
def create_shift():
    user_id, role = get_auth()
    require_role(role, {"CashierAttendant"})
    body = get_body()
    require_fields(body, ["station_id", "opening_float_cents"])
    station = must_exist(db.stations, body["station_id"])
    opening_float = require_int(body, "opening_float_cents")
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "cashier_user_id": user_id,
        "opening_float_cents": opening_float,
        "cash_sales_cents": 0,
        "cash_payouts_cents": 0,
        "cash_drops_cents": 0,
        "expected_drawer_cents": opening_float,
        "counted_drawer_cents": None,
        "variance_cents": None,
        "lifecycle_status": "OPEN",
        "reconcile_status": "PENDING",
    }
    stamp_new(rec, station)
    db.shifts[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/shifts", methods=["GET"])
def list_shifts():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    items = [s for s in db.shifts.values()
             if station_id is None or s["station_id"] == station_id]
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.shifts, shift_id)
    return object_response(public(rec), 200)


@app.route("/shifts/<shift_id>/drops", methods=["POST"])
def shift_drop(shift_id):
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    shift = must_exist(db.shifts, shift_id)
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount = require_int(body, "amount_cents")
    shift["cash_drops_cents"] += amount
    S.recompute_expected_drawer(shift)
    bump(shift)
    return object_response(public(shift), 200)


@app.route("/shifts/<shift_id>/begin-count", methods=["POST"])
def shift_begin_count(shift_id):
    user_id, role = get_auth()
    require_role(role, {"CashierAttendant"})
    shift = must_exist(db.shifts, shift_id)
    # Owner-only check (priority 5: ERR_NOT_SHIFT_OWNER) precedes state (§2.8).
    if user_id != shift["cashier_user_id"]:
        fail(E.ERR_NOT_SHIFT_OWNER, "Acting cashier is not the shift owner")
    if shift["lifecycle_status"] != "OPEN":
        fail(E.ERR_INVALID_STATE, "Shift is not OPEN")
    shift["lifecycle_status"] = "COUNTING"
    bump(shift)
    return object_response(public(shift), 200)


@app.route("/shifts/<shift_id>/close", methods=["POST"])
def shift_close(shift_id):
    user_id, role = get_auth()
    require_role(role, {"CashierAttendant"})
    shift = must_exist(db.shifts, shift_id)
    body = get_body()
    # Body well-formedness (priority 4) before owner/state per §2.8 ordering:
    # counted_drawer_cents provided and >= 0, expected_shift_version present.
    require_fields(body, ["counted_drawer_cents", "expected_shift_version"])
    counted = require_int(body, "counted_drawer_cents")  # >= 0 enforced
    require_int(body, "expected_shift_version")
    # Owner-only (priority 5).
    if user_id != shift["cashier_user_id"]:
        fail(E.ERR_NOT_SHIFT_OWNER, "Acting cashier is not the shift owner")
    # State (priority 6).
    if shift["lifecycle_status"] != "COUNTING":
        fail(E.ERR_INVALID_STATE, "Shift is not COUNTING")
    # OCC (priority 15).
    check_occ(body, "expected_shift_version", shift["version"])
    station = db.stations[shift["station_id"]]
    tol = station["cash_variance_tolerance_cents"]
    variance = counted - shift["expected_drawer_cents"]
    shift["counted_drawer_cents"] = counted
    shift["variance_cents"] = variance
    shift["lifecycle_status"] = "CLOSED"
    if abs(variance) <= tol:
        shift["reconcile_status"] = "BALANCED"
    elif variance > tol:
        shift["reconcile_status"] = "OVER"
    else:
        shift["reconcile_status"] = "SHORT"
    bump(shift)
    return object_response(public(shift), 200)


# --------------------------------------------------------------------------- #
# FUEL TRANSACTION
# --------------------------------------------------------------------------- #
@app.route("/fuel-transactions", methods=["POST"])
def create_fuel_transaction():
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    body = get_body()
    require_fields(body, ["station_id", "pump_id", "shift_id", "gallons", "tender"])
    station = must_exist(db.stations, body["station_id"])
    pump = must_exist(db.pumps, body["pump_id"])
    shift = must_exist(db.shifts, body["shift_id"])
    loyalty_id = body.get("loyalty_account_id")
    loyalty = None
    if loyalty_id is not None:
        loyalty = must_exist(db.loyalty_accounts, loyalty_id)
    gallons = require_number(body, "gallons")
    tender = require_enum(body, "tender", {"CASH", "CARD"})
    # Pump/tank availability (priority 10: ERR_PUMP_UNAVAILABLE, §3.6).
    tank = db.tanks[pump["tank_id"]]
    if pump["status"] == "OUT_OF_SERVICE" or tank["status"] != "ACTIVE":
        fail(E.ERR_PUMP_UNAVAILABLE, "Pump or its tank is unavailable")
    grade = db.fuel_grades[tank["fuel_grade_id"]]
    base_price = grade["current_price_cents"]
    tier = loyalty["tier"] if loyalty is not None else "BRONZE"
    discount = S.fuel_discount_per_gal(tier) if loyalty is not None else 0
    net_price = base_price - discount
    total = round_half_up(g3(gallons) * net_price)
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "pump_id": pump["id"],
        "shift_id": shift["id"],
        "loyalty_account_id": loyalty_id,
        "gallons": g3(gallons),
        "tender": tender,
        "base_price_cents": base_price,
        "discount_cents_per_gal": discount,
        "net_price_cents_per_gal": net_price,
        "total_cents": total,
        "cogs_cents": None,
        "payment_status": "AUTHORIZED",
        "settlement_status": "UNSETTLED",
        "_accrued_points": 0,
    }
    stamp_new(rec, station)
    db.fuel_transactions[rec["id"]] = rec
    # Pump -> DISPENSING (§3.6).
    pump["status"] = "DISPENSING"
    bump(pump)
    return object_response(public(rec), 201)


@app.route("/fuel-transactions", methods=["GET"])
def list_fuel_transactions():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    pump_id = request.args.get("pump_id")
    shift_id = request.args.get("shift_id")
    loyalty_id = request.args.get("loyalty_account_id")
    items = []
    for t in db.fuel_transactions.values():
        if station_id is not None and t["station_id"] != station_id:
            continue
        if pump_id is not None and t["pump_id"] != pump_id:
            continue
        if shift_id is not None and t["shift_id"] != shift_id:
            continue
        if loyalty_id is not None and t["loyalty_account_id"] != loyalty_id:
            continue
        items.append(t)
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/fuel-transactions/<txn_id>", methods=["GET"])
def get_fuel_transaction(txn_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.fuel_transactions, txn_id)
    return object_response(public(rec), 200)


@app.route("/fuel-transactions/<txn_id>/capture", methods=["POST"])
def capture_fuel_transaction(txn_id):
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    txn = must_exist(db.fuel_transactions, txn_id)
    if txn["payment_status"] != "AUTHORIZED":
        fail(E.ERR_INVALID_STATE, "Payment is not AUTHORIZED")
    txn["payment_status"] = "CAPTURED"
    bump(txn)
    pump = db.pumps[txn["pump_id"]]
    pump["status"] = "IDLE"
    bump(pump)
    return object_response(public(txn), 200)


@app.route("/fuel-transactions/<txn_id>/settle", methods=["POST"])
def settle_fuel_transaction(txn_id):
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    txn = must_exist(db.fuel_transactions, txn_id)
    body = get_body()
    require_fields(body, ["expected_shift_version"])
    require_int(body, "expected_shift_version")
    shift = db.shifts[txn["shift_id"]]
    # Ordering (§2.8): payment captured (8) -> shift open (7) -> state (6) ...
    # PRD §3.6 lists: payment CAPTURED, settlement UNSETTLED, shift OPEN.
    # Priority table: ERR_INVALID_STATE(6) < ERR_SHIFT_NOT_OPEN(7) <
    # ERR_PAYMENT_NOT_CAPTURED(8). Evaluate in that priority order.
    if txn["settlement_status"] != "UNSETTLED":
        fail(E.ERR_INVALID_STATE, "Settlement is not UNSETTLED")
    if shift["lifecycle_status"] != "OPEN":
        fail(E.ERR_SHIFT_NOT_OPEN, "Referenced shift is not OPEN")
    if txn["payment_status"] != "CAPTURED":
        fail(E.ERR_PAYMENT_NOT_CAPTURED, "Payment is not CAPTURED")
    # OCC on shift version (priority 15).
    check_occ(body, "expected_shift_version", shift["version"])
    tank = db.tanks[db.pumps[txn["pump_id"]]["tank_id"]]
    grade = db.fuel_grades[tank["fuel_grade_id"]]
    # cogs captured at settlement (§3.6).
    txn["cogs_cents"] = round_half_up(g3(txn["gallons"]) * grade["weighted_avg_cost_cents"])
    # Dispense recorded at settlement (§3.4/§3.6).
    S.add_tank_volume(tank, -txn["gallons"])
    bump(tank)
    txn["settlement_status"] = "SETTLED"
    if txn["tender"] == "CASH":
        shift["cash_sales_cents"] += txn["total_cents"]
        S.recompute_expected_drawer(shift)
    if txn["loyalty_account_id"] is not None:
        acct = db.loyalty_accounts[txn["loyalty_account_id"]]
        awarded = S.accrue_points(acct, gallons=txn["gallons"])
        txn["_accrued_points"] = awarded
    # Shift version is incremented by 1 (§3.6).
    bump(shift)
    bump(txn)
    return object_response(public(txn), 200)


@app.route("/fuel-transactions/<txn_id>/reverse", methods=["POST"])
def reverse_fuel_transaction(txn_id):
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    txn = must_exist(db.fuel_transactions, txn_id)
    shift = db.shifts[txn["shift_id"]]
    if txn["settlement_status"] != "SETTLED":
        fail(E.ERR_INVALID_STATE, "Settlement is not SETTLED")
    if shift["lifecycle_status"] != "OPEN":
        fail(E.ERR_SHIFT_NOT_OPEN, "Referenced shift is not OPEN")
    tank = db.tanks[db.pumps[txn["pump_id"]]["tank_id"]]
    S.add_tank_volume(tank, txn["gallons"])
    bump(tank)
    if txn["tender"] == "CASH":
        shift["cash_sales_cents"] -= txn["total_cents"]
        S.recompute_expected_drawer(shift)
        bump(shift)
    if txn["loyalty_account_id"] is not None:
        acct = db.loyalty_accounts[txn["loyalty_account_id"]]
        S.reverse_points(acct, txn.get("_accrued_points", 0))
    txn["settlement_status"] = "REVERSED"
    txn["payment_status"] = "REFUNDED"
    bump(txn)
    return object_response(public(txn), 200)


# --------------------------------------------------------------------------- #
# STORE TRANSACTION
# --------------------------------------------------------------------------- #
@app.route("/store-transactions", methods=["POST"])
def create_store_transaction():
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    body = get_body()
    require_fields(body, ["station_id", "shift_id", "line_items", "tender"])
    station = must_exist(db.stations, body["station_id"])
    shift = must_exist(db.shifts, body["shift_id"])
    loyalty_id = body.get("loyalty_account_id")
    loyalty = None
    if loyalty_id is not None:
        loyalty = must_exist(db.loyalty_accounts, loyalty_id)
    tender = require_enum(body, "tender", {"CASH", "CARD"})
    line_items = body.get("line_items")
    if not isinstance(line_items, list) or len(line_items) == 0:
        fail(E.ERR_INVALID_REQUEST, "line_items must be a non-empty array")
    subtotal = 0
    taxable_subtotal = 0
    max_min_age = 0
    norm_items = []
    for li in line_items:
        if not isinstance(li, dict):
            fail(E.ERR_INVALID_REQUEST, "Each line item must be an object")
        for f in ["sku", "name", "category", "unit_price_cents", "qty",
                  "taxable", "min_age"]:
            if f not in li or li[f] is None:
                fail(E.ERR_INVALID_REQUEST, "Line item missing field: %s" % f)
        unit_price = li["unit_price_cents"]
        qty = li["qty"]
        taxable = li["taxable"]
        min_age = li["min_age"]
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 0:
            fail(E.ERR_INVALID_REQUEST, "unit_price_cents must be a non-negative integer")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            fail(E.ERR_INVALID_REQUEST, "qty must be a non-negative integer")
        if not isinstance(taxable, bool):
            fail(E.ERR_INVALID_REQUEST, "taxable must be a boolean")
        if isinstance(min_age, bool) or not isinstance(min_age, int) or min_age < 0:
            fail(E.ERR_INVALID_REQUEST, "min_age must be a non-negative integer")
        line_total = unit_price * qty
        subtotal += line_total
        if taxable:
            taxable_subtotal += line_total
        if min_age > 0 and min_age > max_min_age:
            max_min_age = min_age
        norm_items.append(li)
    # Age compliance (priority 9: ERR_AGE_VERIFICATION_FAILED, §3.8).
    verified_age = body.get("verified_buyer_age")
    if max_min_age > 0:
        if verified_age is None or isinstance(verified_age, bool) \
                or not isinstance(verified_age, int) or verified_age < max_min_age:
            fail(E.ERR_AGE_VERIFICATION_FAILED,
                 "Age verification missing or below required minimum")
    # Tax (§3.8): single product on taxable subtotal, rounded once.
    tax = round_half_up(taxable_subtotal * station["tax_rate_bp"] / 10000)
    total = subtotal + tax
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "shift_id": shift["id"],
        "loyalty_account_id": loyalty_id,
        "tender": tender,
        "line_items": norm_items,
        "verified_buyer_age": verified_age,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "settlement_status": "SETTLED",
        "_accrued_points": 0,
    }
    stamp_new(rec, station)
    db.store_transactions[rec["id"]] = rec
    # Settles immediately (§3.8).
    if tender == "CASH":
        shift["cash_sales_cents"] += total
        S.recompute_expected_drawer(shift)
        bump(shift)
    if loyalty is not None:
        awarded = S.accrue_points(loyalty, store_subtotal_cents=subtotal)
        rec["_accrued_points"] = awarded
    return object_response(public(rec), 201)


@app.route("/store-transactions", methods=["GET"])
def list_store_transactions():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    shift_id = request.args.get("shift_id")
    loyalty_id = request.args.get("loyalty_account_id")
    items = []
    for t in db.store_transactions.values():
        if station_id is not None and t["station_id"] != station_id:
            continue
        if shift_id is not None and t["shift_id"] != shift_id:
            continue
        if loyalty_id is not None and t["loyalty_account_id"] != loyalty_id:
            continue
        items.append(t)
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/store-transactions/<store_txn_id>", methods=["GET"])
def get_store_transaction(store_txn_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.store_transactions, store_txn_id)
    return object_response(public(rec), 200)


@app.route("/store-transactions/<store_txn_id>/reverse", methods=["POST"])
def reverse_store_transaction(store_txn_id):
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    txn = must_exist(db.store_transactions, store_txn_id)
    if txn["settlement_status"] != "SETTLED":
        fail(E.ERR_INVALID_STATE, "Store transaction is not SETTLED")
    shift = db.shifts[txn["shift_id"]]
    if txn["tender"] == "CASH":
        shift["cash_sales_cents"] -= txn["total_cents"]
        S.recompute_expected_drawer(shift)
        bump(shift)
    if txn["loyalty_account_id"] is not None:
        acct = db.loyalty_accounts[txn["loyalty_account_id"]]
        S.reverse_points(acct, txn.get("_accrued_points", 0))
    txn["settlement_status"] = "REVERSED"
    bump(txn)
    return object_response(public(txn), 200)


# --------------------------------------------------------------------------- #
# LOYALTY ACCOUNT
# --------------------------------------------------------------------------- #
@app.route("/loyalty-accounts", methods=["POST"])
def create_loyalty_account():
    _, role = get_auth()
    require_role(role, {"CashierAttendant", "LoyaltyMember"})
    body = get_body()
    require_fields(body, ["station_id", "phone", "name"])
    station = must_exist(db.stations, body["station_id"])
    phone = require_string(body, "phone")
    name = require_string(body, "name")
    # Per-station uniqueness on phone (§2.9).
    for a in db.loyalty_accounts.values():
        if a["station_id"] == station["id"] and a["phone"] == phone:
            fail(E.ERR_DUPLICATE_PHONE, "Phone already enrolled at station")
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "phone": phone,
        "name": name,
        "point_balance": 0,
        "lifetime_points": 0,
        "tier": "BRONZE",
    }
    stamp_new(rec, station)
    db.loyalty_accounts[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/loyalty-accounts", methods=["GET"])
def list_loyalty_accounts():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    items = [a for a in db.loyalty_accounts.values()
             if station_id is None or a["station_id"] == station_id]
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/loyalty-accounts/<loyalty_id>", methods=["GET"])
def get_loyalty_account(loyalty_id):
    user_id, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant", "LoyaltyMember"})
    rec = must_exist(db.loyalty_accounts, loyalty_id)
    # LoyaltyMember reads only own account (§2.1 ownership binding).
    if role == "LoyaltyMember" and user_id != rec["id"]:
        fail(E.ERR_FORBIDDEN, "Member may only read their own account")
    return object_response(public(rec), 200)


@app.route("/loyalty-accounts/<loyalty_id>/redeem", methods=["POST"])
def redeem_loyalty_points(loyalty_id):
    user_id, role = get_auth()
    require_role(role, {"LoyaltyMember", "CashierAttendant"})
    rec = must_exist(db.loyalty_accounts, loyalty_id)
    if role == "LoyaltyMember" and user_id != rec["id"]:
        fail(E.ERR_FORBIDDEN, "Member may only redeem their own points")
    body = get_body()
    require_fields(body, ["points"])
    points = require_int(body, "points")
    # Sufficient points (priority 14: ERR_INSUFFICIENT_POINTS, §3.7).
    if points > rec["point_balance"]:
        fail(E.ERR_INSUFFICIENT_POINTS, "Redemption exceeds point balance")
    rec["point_balance"] -= points
    # lifetime_points unchanged (§3.7).
    bump(rec)
    return object_response(public(rec), 200)


# --------------------------------------------------------------------------- #
# CAR WASH CODE
# --------------------------------------------------------------------------- #
@app.route("/car-wash-codes", methods=["POST"])
def create_car_wash_code():
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    body = get_body()
    require_fields(body, ["station_id", "package"])
    station = must_exist(db.stations, body["station_id"])
    fuel_txn_id = body.get("fuel_transaction_id")
    if fuel_txn_id is not None:
        must_exist(db.fuel_transactions, fuel_txn_id)
    loyalty_id = body.get("loyalty_account_id")
    loyalty = None
    if loyalty_id is not None:
        loyalty = must_exist(db.loyalty_accounts, loyalty_id)
    package = require_enum(body, "package", {"BASIC", "DELUXE", "SUPREME"})
    # Earned code (fuel_transaction_id set) is free; otherwise priced (§3.9).
    if fuel_txn_id is not None:
        price = 0
    else:
        tier = loyalty["tier"] if loyalty is not None else "BRONZE"
        price = S.car_wash_price(package, tier if loyalty is not None else "BRONZE")
    expires_at = add_days_iso(station["current_utc"], S.CODE_TTL_DAYS)
    rec = {
        "id": new_id(),
        "station_id": station["id"],
        "fuel_transaction_id": fuel_txn_id,
        "package": package,
        "price_cents": price,
        "code_value": "wash_" + new_id().replace("-", "")[:16],
        "expires_at": expires_at,
        "status": "ISSUED",
    }
    stamp_new(rec, station)
    db.car_wash_codes[rec["id"]] = rec
    return object_response(public(rec), 201)


@app.route("/car-wash-codes", methods=["GET"])
def list_car_wash_codes():
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    fuel_txn_id = request.args.get("fuel_transaction_id")
    items = []
    for c in db.car_wash_codes.values():
        if station_id is not None and c["station_id"] != station_id:
            continue
        if fuel_txn_id is not None and c["fuel_transaction_id"] != fuel_txn_id:
            continue
        items.append(c)
    window, total = paginate(items, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@app.route("/car-wash-codes/<code_id>", methods=["GET"])
def get_car_wash_code(code_id):
    _, role = get_auth()
    require_role(role, {"StationManager", "CashierAttendant"})
    rec = must_exist(db.car_wash_codes, code_id)
    return object_response(public(rec), 200)


@app.route("/car-wash-codes/<code_id>/redeem", methods=["POST"])
def redeem_car_wash_code(code_id):
    _, role = get_auth()
    require_role(role, {"CashierAttendant"})
    rec = must_exist(db.car_wash_codes, code_id)
    if rec["status"] != "ISSUED":
        fail(E.ERR_INVALID_STATE, "Code is not ISSUED")
    station = db.stations[rec["station_id"]]
    now_dt = parse_iso(station["current_utc"])
    expires_dt = parse_iso(rec["expires_at"])
    # Strictly before expires_at to redeem; else lazily flip to EXPIRED (§3.9).
    if now_dt >= expires_dt:
        rec["status"] = "EXPIRED"
        bump(rec)
        fail(E.ERR_CODE_EXPIRED, "Car-wash code has expired")
    rec["status"] = "REDEEMED"
    bump(rec)
    return object_response(public(rec), 200)


@app.route("/car-wash-codes/<code_id>/reissue", methods=["POST"])
def reissue_car_wash_code(code_id):
    _, role = get_auth()
    require_role(role, {"StationManager"})
    rec = must_exist(db.car_wash_codes, code_id)
    if rec["status"] != "EXPIRED":
        fail(E.ERR_INVALID_STATE, "Code is not EXPIRED")
    station = db.stations[rec["station_id"]]
    rec["expires_at"] = add_days_iso(station["current_utc"], S.CODE_TTL_DAYS)
    rec["status"] = "ISSUED"
    bump(rec)
    return object_response(public(rec), 200)


# --------------------------------------------------------------------------- #
# MARGIN REPORT (§3.10) — ephemeral computed snapshot, returns 201
# --------------------------------------------------------------------------- #
@app.route("/margin-reports", methods=["POST"])
def margin_report():
    _, role = get_auth()
    require_role(role, {"StationManager"})
    body = get_body()
    require_fields(body, ["station_id", "window_start", "window_end"])
    station = must_exist(db.stations, body["station_id"])
    window_start = parse_iso(body["window_start"])
    window_end = parse_iso(body["window_end"])
    cost_basis = body.get("cost_basis", "WAC")
    if cost_basis not in {"WAC", "REPLACEMENT"}:
        fail(E.ERR_INVALID_REQUEST, "cost_basis must be WAC or REPLACEMENT")

    # Select SETTLED fuel transactions whose created_at in [start, end) (§3.10).
    selected = []
    for t in db.fuel_transactions.values():
        if t["station_id"] != station["id"]:
            continue
        if t["settlement_status"] != "SETTLED":
            continue
        created = parse_iso(t["created_at"])
        if created >= window_start and created < window_end:
            selected.append(t)

    gallons_sold = g3(sum(t["gallons"] for t in selected)) if selected else 0
    revenue_cents = sum(t["total_cents"] for t in selected)

    # Group by grade via pump -> tank -> fuel_grade.
    grade_gallons = {}
    for t in selected:
        tank = db.tanks[db.pumps[t["pump_id"]]["tank_id"]]
        grade_id = tank["fuel_grade_id"]
        grade_gallons[grade_id] = g3(grade_gallons.get(grade_id, 0) + t["gallons"])

    cogs_cents = 0
    for grade_id, gal in grade_gallons.items():
        grade = db.fuel_grades[grade_id]
        if cost_basis == "WAC":
            cost_per_gal = grade["weighted_avg_cost_cents"]
        else:
            cost_per_gal = _replacement_cost_per_gal(grade_id)
        cogs_cents += round_half_up(gal * cost_per_gal)

    margin_cents = revenue_cents - cogs_cents
    if revenue_cents == 0:
        margin_pct = 0
    else:
        margin_pct = round_half_up_2dp(margin_cents / revenue_cents * 100)

    report = {
        "id": new_id(),
        "station_id": station["id"],
        "window_start": iso_str(window_start),
        "window_end": iso_str(window_end),
        "cost_basis": cost_basis,
        "gallons_sold": gallons_sold,
        "revenue_cents": revenue_cents,
        "cogs_cents": cogs_cents,
        "margin_cents": margin_cents,
        "margin_pct": margin_pct,
        "created_at": now_iso(),
    }
    return object_response(report, 201)


def _replacement_cost_per_gal(grade_id):
    """Most recent POSTED delivery unit cost to a tank of this grade (§3.10):
    latest by effective time, created_at ascending as tie-break. With no
    distinct effective field, created_at is the effective time."""
    tank_ids = {t["id"] for t in db.tanks.values()
                if t["fuel_grade_id"] == grade_id}
    posted = [d for d in db.deliveries.values()
              if d["status"] == "POSTED" and d["tank_id"] in tank_ids]
    if not posted:
        return 0
    # Latest by created_at; _seq breaks exact-timestamp ties (later seq = later).
    latest = max(posted, key=lambda d: (d["created_at"], d["_seq"]))
    return latest["unit_cost_cents"]


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
