"""Transportation Management System (TMS) API — Flask entry point.

All routes are mounted under /tms (PRD §2). Storage is in-memory (db.py); the
process starts empty and is never seeded.
"""
import os

from flask import Flask, request

import db
import calculations as calc
import serializers as ser
from errors import ApiError
from helpers import (
    auth,
    get_json_body,
    as_int,
    as_number,
    as_str,
    as_enum,
    paginate,
    clean_all,
)
from response import success, success_list, error

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = ["ShipperOps", "CarrierOps", "DockOps", "FreightAuditor"]
MODES = {"TL", "LTL", "PARCEL", "INTERMODAL"}
CLAIM_TYPES = {"OSD_SHORTAGE", "OSD_OVERAGE", "DAMAGE", "LOSS"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route — generic invalid request shape would be misleading; surface
    # a 404 envelope. (Tests target declared routes; this is a safety net.)
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error(exc.error_id, exc.message, exc.http_status)
    return error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)


# ---------------------------------------------------------------------------
# Lookup helpers (existence checks, PRD §2.6)
# ---------------------------------------------------------------------------
from errors import err


def find_or_404(store, entity_id, not_found_id):
    rec = store.get(entity_id)
    if rec is None:
        raise err(not_found_id, "%s not found" % entity_id)
    return rec


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
@app.route("/tms/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ALL_ROLES)
    body = get_json_body()
    to_iso = as_str(body, "to_iso8601")
    db.clock_iso = to_iso
    return success({}, 200)


# ---------------------------------------------------------------------------
# Carrier (PRD §3.1)
# ---------------------------------------------------------------------------
@app.route("/tms/carriers", methods=["POST"])
def create_carrier():
    auth(["CarrierOps"])
    body = get_json_body()
    name = as_str(body, "name")
    scac = as_str(body, "scac")
    mode = as_enum(body, "mode", MODES)
    # Business: scac unique across carriers (priority 6).
    for c in db.carriers.values():
        if c["scac"] == scac:
            raise err("ERR_DUPLICATE_SCAC", "scac %s already exists" % scac)
    carrier = {
        "name": name,
        "scac": scac,
        "mode": mode,
        "status": "ACTIVE",
        "delivered_count": 0,
        "on_time_count": 0,
        "claim_count": 0,
    }
    db.stamp_create(carrier)
    db.carriers[carrier["id"]] = carrier
    return success(ser.carrier_view(carrier), 201)


@app.route("/tms/carriers", methods=["GET"])
def list_carriers():
    auth(ALL_ROLES)
    records = list(db.carriers.values())
    scac = request.args.get("scac")
    if scac is not None:
        records = [c for c in records if c["scac"] == scac]
    page, meta = paginate(records)
    return success_list([ser.carrier_view(c) for c in page], meta)


@app.route("/tms/carriers/<carrier_id>", methods=["GET"])
def get_carrier(carrier_id):
    auth(ALL_ROLES)
    carrier = find_or_404(db.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    return success(ser.carrier_view(carrier), 200)


@app.route("/tms/carriers/<carrier_id>/suspend", methods=["POST"])
def suspend_carrier(carrier_id):
    auth(["CarrierOps"])
    carrier = find_or_404(db.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    if carrier["status"] != "ACTIVE":
        raise err("ERR_CARRIER_NOT_ACTIVE", "Carrier is not ACTIVE")
    carrier["status"] = "SUSPENDED"
    db.touch(carrier)
    return success(ser.carrier_view(carrier), 200)


@app.route("/tms/carriers/<carrier_id>/reinstate", methods=["POST"])
def reinstate_carrier(carrier_id):
    auth(["CarrierOps"])
    carrier = find_or_404(db.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    if carrier["status"] != "SUSPENDED":
        raise err("ERR_CARRIER_NOT_SUSPENDED", "Carrier is not SUSPENDED")
    carrier["status"] = "ACTIVE"
    db.touch(carrier)
    return success(ser.carrier_view(carrier), 200)


# ---------------------------------------------------------------------------
# ContractRate (PRD §3.2)
# ---------------------------------------------------------------------------
@app.route("/tms/contract-rates", methods=["POST"])
def create_contract_rate():
    auth(["CarrierOps"])
    body = get_json_body()
    # priority 4: FK existence (carrier_id) before structural validation.
    carrier_id = as_str(body, "carrier_id")
    carrier = find_or_404(db.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    # priority 5: structural validity.
    mode = as_enum(body, "mode", MODES)
    origin_zone = as_str(body, "origin_zone")
    dest_zone = as_str(body, "dest_zone")
    base_rate = as_int(body, "base_rate_per_mile_cents")
    min_charge = as_int(body, "min_charge_cents")
    fuel_pct = as_number(body, "fuel_surcharge_pct", required=False, default=0)
    eff_start = as_int(body, "effective_start_minute")
    eff_end = as_int(body, "effective_end_minute")
    if eff_start < 0:
        raise err("ERR_INVALID_REQUEST", "effective_start_minute must be >= 0")
    if eff_end < eff_start:
        raise err("ERR_INVALID_REQUEST", "effective_end_minute must be >= effective_start_minute")
    # priority 7: mode must equal the carrier's mode.
    if mode != carrier["mode"]:
        raise err("ERR_MODE_MISMATCH", "ContractRate.mode must equal Carrier.mode")
    # priority 16: closed-window overlap on the same lane among ACTIVE rates.
    for r in db.contract_rates.values():
        if r["status"] != "ACTIVE":
            continue
        if (r["carrier_id"] == carrier_id and r["mode"] == mode
                and r["origin_zone"] == origin_zone and r["dest_zone"] == dest_zone):
            # Closed intervals overlap iff start <= other_end AND other_start <= end.
            if eff_start <= r["effective_end_minute"] and r["effective_start_minute"] <= eff_end:
                raise err("ERR_RATE_WINDOW_OVERLAP", "Effective window overlaps an existing ACTIVE rate on this lane")
    rate = {
        "carrier_id": carrier_id,
        "mode": mode,
        "origin_zone": origin_zone,
        "dest_zone": dest_zone,
        "base_rate_per_mile_cents": base_rate,
        "min_charge_cents": min_charge,
        "fuel_surcharge_pct": fuel_pct,
        "effective_start_minute": eff_start,
        "effective_end_minute": eff_end,
        "status": "ACTIVE",
    }
    db.stamp_create(rate)
    db.contract_rates[rate["id"]] = rate
    return success(ser.rate_view(rate), 201)


@app.route("/tms/contract-rates", methods=["GET"])
def list_contract_rates():
    auth(ALL_ROLES)
    records = list(db.contract_rates.values())
    carrier_id = request.args.get("carrier_id")
    if carrier_id is not None:
        records = [r for r in records if r["carrier_id"] == carrier_id]
    page, meta = paginate(records)
    return success_list([ser.rate_view(r) for r in page], meta)


@app.route("/tms/contract-rates/<rate_id>", methods=["GET"])
def get_contract_rate(rate_id):
    auth(ALL_ROLES)
    rate = find_or_404(db.contract_rates, rate_id, "ERR_RATE_NOT_FOUND")
    return success(ser.rate_view(rate), 200)


@app.route("/tms/contract-rates/<rate_id>/retire", methods=["POST"])
def retire_contract_rate(rate_id):
    auth(["CarrierOps"])
    rate = find_or_404(db.contract_rates, rate_id, "ERR_RATE_NOT_FOUND")
    if rate["status"] != "ACTIVE":
        raise err("ERR_RATE_NOT_ACTIVE", "Rate is not ACTIVE")
    rate["status"] = "RETIRED"
    db.touch(rate)
    return success(ser.rate_view(rate), 200)


# ---------------------------------------------------------------------------
# Order (PRD §3.3)
# ---------------------------------------------------------------------------
@app.route("/tms/orders", methods=["POST"])
def create_order():
    auth(["ShipperOps"])
    body = get_json_body()
    customer_ref = as_str(body, "customer_ref")
    origin_zone = as_str(body, "origin_zone")
    dest_zone = as_str(body, "dest_zone")
    weight_lbs = as_int(body, "weight_lbs")
    declared_value = as_int(body, "declared_value_cents")
    if weight_lbs <= 0:
        raise err("ERR_INVALID_REQUEST", "weight_lbs must be > 0")
    if declared_value <= 0:
        raise err("ERR_INVALID_REQUEST", "declared_value_cents must be > 0")
    order = {
        "customer_ref": customer_ref,
        "origin_zone": origin_zone,
        "dest_zone": dest_zone,
        "weight_lbs": weight_lbs,
        "declared_value_cents": declared_value,
        "status": "OPEN",
    }
    db.stamp_create(order)
    db.orders[order["id"]] = order
    return success(ser.order_view(order), 201)


@app.route("/tms/orders", methods=["GET"])
def list_orders():
    auth(ALL_ROLES)
    records = list(db.orders.values())
    status = request.args.get("status")
    if status is not None:
        records = [o for o in records if o["status"] == status]
    page, meta = paginate(records)
    return success_list([ser.order_view(o) for o in page], meta)


@app.route("/tms/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    auth(ALL_ROLES)
    order = find_or_404(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    return success(ser.order_view(order), 200)


@app.route("/tms/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    auth(["ShipperOps"])
    order = find_or_404(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "OPEN":
        raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not OPEN")
    order["status"] = "CANCELLED"
    db.touch(order)
    return success(ser.order_view(order), 200)


# ---------------------------------------------------------------------------
# Shipment (PRD §3.3, §3.8, §3.9)
# ---------------------------------------------------------------------------
@app.route("/tms/shipments", methods=["POST"])
def create_shipment():
    auth(["ShipperOps"])
    body = get_json_body()
    # priority 4: FK existence (order_id).
    order_id = as_str(body, "order_id")
    order = find_or_404(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    # priority 5: structural validity.
    mode = as_enum(body, "mode", MODES)
    distance_miles = as_int(body, "distance_miles")
    weight_lbs = as_int(body, "weight_lbs")
    promised_eta = as_int(body, "promised_eta_minute")
    if distance_miles <= 0:
        raise err("ERR_INVALID_REQUEST", "distance_miles must be > 0")
    if weight_lbs <= 0:
        raise err("ERR_INVALID_REQUEST", "weight_lbs must be > 0")
    # priority 7: shipment weight must not exceed the order's weight (ERR_MODE_MISMATCH).
    if weight_lbs > order["weight_lbs"]:
        raise err("ERR_MODE_MISMATCH", "Shipment weight exceeds order weight")
    shipment = {
        "order_id": order_id,
        "mode": mode,
        "distance_miles": distance_miles,
        "weight_lbs": weight_lbs,
        "load_id": None,
        "assigned_carrier_id": None,
        "contract_rate_id": None,
        "quoted_cost_cents": None,
        "audited_cost_cents": None,
        "promised_eta_minute": promised_eta,
        "actual_delivery_minute": None,
        "tender_status": "UNTENDERED",
        "execution_status": "PENDING",
    }
    db.stamp_create(shipment)
    db.shipments[shipment["id"]] = shipment
    # Bubble-up: Order OPEN -> PLANNED the instant its first shipment exists.
    if order["status"] == "OPEN":
        order["status"] = "PLANNED"
        db.touch(order)
    return success(ser.shipment_view(shipment), 201)


@app.route("/tms/shipments", methods=["GET"])
def list_shipments():
    auth(ALL_ROLES)
    records = list(db.shipments.values())
    for field in ("order_id", "load_id", "assigned_carrier_id", "contract_rate_id"):
        val = request.args.get(field)
        if val is not None:
            records = [s for s in records if s.get(field) == val]
    page, meta = paginate(records)
    return success_list([ser.shipment_view(s) for s in page], meta)


@app.route("/tms/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    auth(ALL_ROLES)
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    return success(ser.shipment_view(shipment), 200)


@app.route("/tms/shipments/<shipment_id>/depart", methods=["POST"])
def depart_shipment(shipment_id):
    auth(["CarrierOps"])
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    # State preconditions then cross-entity guard (PRD §2.8 / §3.8).
    if shipment["tender_status"] != "BOOKED":
        raise err("ERR_SHIPMENT_NOT_BOOKED", "Shipment is not BOOKED")
    if shipment["execution_status"] != "PENDING":
        raise err("ERR_SHIPMENT_NOT_PENDING", "Shipment is not PENDING")
    load_id = shipment.get("load_id")
    load = db.loads.get(load_id) if load_id else None
    if load is None or load["status"] != "DISPATCHED":
        raise err("ERR_LOAD_NOT_DISPATCHED", "Consolidating load is not DISPATCHED")
    shipment["execution_status"] = "IN_TRANSIT"
    db.touch(shipment)
    return success(ser.shipment_view(shipment), 200)


@app.route("/tms/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(shipment_id):
    auth(["CarrierOps"])
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body = get_json_body()
    delivered_minute = as_int(body, "delivered_minute")
    if shipment["execution_status"] != "IN_TRANSIT":
        raise err("ERR_SHIPMENT_NOT_IN_TRANSIT", "Shipment is not IN_TRANSIT")
    shipment["execution_status"] = "DELIVERED"
    shipment["actual_delivery_minute"] = delivered_minute
    db.touch(shipment)
    # Carrier scorecard update.
    carrier = db.carriers.get(shipment["assigned_carrier_id"])
    if carrier is not None:
        carrier["delivered_count"] += 1
        if delivered_minute <= shipment["promised_eta_minute"]:
            carrier["on_time_count"] += 1
        db.touch(carrier)
    # Bubble-up: Order PLANNED -> CLOSED.
    order = db.orders.get(shipment["order_id"])
    if order is not None and order["status"] == "PLANNED":
        order["status"] = "CLOSED"
        db.touch(order)
    return success(ser.shipment_view(shipment), 200)


@app.route("/tms/shipments/<shipment_id>/cancel", methods=["POST"])
def cancel_shipment(shipment_id):
    auth(["ShipperOps"])
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    if shipment["execution_status"] != "PENDING":
        raise err("ERR_SHIPMENT_NOT_CANCELLABLE", "Shipment is not PENDING")
    shipment["execution_status"] = "CANCELLED"
    # Unwind cascade (PRD §3.9).
    # 1) Any OFFERED tender for this shipment -> DECLINED, which reverts
    #    tender_status TENDERED -> UNTENDERED.
    declined_offered = False
    for tender in db.tenders.values():
        if tender["shipment_id"] == shipment_id and tender["status"] == "OFFERED":
            tender["status"] = "DECLINED"
            db.touch(tender)
            declined_offered = True
            shipment["tender_status"] = "UNTENDERED"
    # 2) If already BOOKED (no OFFERED tender to decline): clear assignment fields
    #    and revert tender_status directly.
    if not declined_offered and shipment["tender_status"] == "BOOKED":
        shipment["assigned_carrier_id"] = None
        shipment["contract_rate_id"] = None
        shipment["quoted_cost_cents"] = None
        shipment["tender_status"] = "UNTENDERED"
    # 3) Detach from load if consolidated; recompute load consolidated weight.
    load_id = shipment.get("load_id")
    if load_id:
        shipment["load_id"] = None
        load = db.loads.get(load_id)
        if load is not None:
            db.touch(load)  # consolidated_weight_lbs recomputed on read
    db.touch(shipment)
    return success(ser.shipment_view(shipment), 200)


# ---------------------------------------------------------------------------
# Tender (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------
@app.route("/tms/shipments/<shipment_id>/tenders", methods=["POST"])
def create_tender(shipment_id):
    auth(["ShipperOps"])
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    body = get_json_body()
    tender_minute = as_int(body, "tender_minute")
    # State preconditions (PRD §3.4): execution PENDING, tender UNTENDERED.
    if shipment["execution_status"] != "PENDING":
        raise err("ERR_SHIPMENT_NOT_PENDING", "Shipment is not PENDING")
    if shipment["tender_status"] != "UNTENDERED":
        raise err("ERR_SHIPMENT_ALREADY_TENDERED", "Shipment is already TENDERED")
    # Rate-shop (priority 11: empty candidate set -> ERR_NO_ELIGIBLE_CARRIER).
    order = db.orders.get(shipment["order_id"])
    rate = calc.rate_shop_selection(shipment, order, tender_minute)
    if rate is None:
        raise err("ERR_NO_ELIGIBLE_CARRIER", "No eligible carrier for this shipment")
    tender = {
        "shipment_id": shipment_id,
        "carrier_id": rate["carrier_id"],
        "contract_rate_id": rate["id"],
        "offered_rate_cents": calc.offered_rate_cents(rate, shipment),
        "status": "OFFERED",
    }
    db.stamp_create(tender)
    db.tenders[tender["id"]] = tender
    # Shipment tender_status UNTENDERED -> TENDERED.
    shipment["tender_status"] = "TENDERED"
    db.touch(shipment)
    return success(ser.tender_view(tender), 201)


@app.route("/tms/shipments/<shipment_id>/tenders", methods=["GET"])
def list_shipment_tenders(shipment_id):
    auth(ALL_ROLES)
    find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    records = [t for t in db.tenders.values() if t["shipment_id"] == shipment_id]
    page, meta = paginate(records)
    return success_list([ser.tender_view(t) for t in page], meta)


@app.route("/tms/tenders", methods=["GET"])
def list_tenders():
    auth(ALL_ROLES)
    records = list(db.tenders.values())
    for field in ("carrier_id", "shipment_id", "contract_rate_id"):
        val = request.args.get(field)
        if val is not None:
            records = [t for t in records if t.get(field) == val]
    page, meta = paginate(records)
    return success_list([ser.tender_view(t) for t in page], meta)


@app.route("/tms/tenders/<tender_id>", methods=["GET"])
def get_tender(tender_id):
    auth(ALL_ROLES)
    tender = find_or_404(db.tenders, tender_id, "ERR_TENDER_NOT_FOUND")
    return success(ser.tender_view(tender), 200)


@app.route("/tms/tenders/<tender_id>/accept", methods=["POST"])
def accept_tender(tender_id):
    auth(["CarrierOps"])
    tender = find_or_404(db.tenders, tender_id, "ERR_TENDER_NOT_FOUND")
    if tender["status"] != "OFFERED":
        raise err("ERR_TENDER_NOT_OFFERED", "Tender is not OFFERED")
    shipment = db.shipments.get(tender["shipment_id"])
    if shipment is None or shipment["tender_status"] != "TENDERED":
        raise err("ERR_SHIPMENT_NOT_TENDERED", "Shipment is not TENDERED")
    tender["status"] = "ACCEPTED"
    db.touch(tender)
    # Book the shipment: write carrier/rate, lock quoted_cost_cents.
    rate = db.contract_rates.get(tender["contract_rate_id"])
    shipment["assigned_carrier_id"] = tender["carrier_id"]
    shipment["contract_rate_id"] = tender["contract_rate_id"]
    shipment["quoted_cost_cents"] = calc.freight_cost_quoted(shipment, rate)
    shipment["tender_status"] = "BOOKED"
    db.touch(shipment)
    return success(ser.tender_view(tender), 200)


@app.route("/tms/tenders/<tender_id>/decline", methods=["POST"])
def decline_tender(tender_id):
    auth(["CarrierOps"])
    tender = find_or_404(db.tenders, tender_id, "ERR_TENDER_NOT_FOUND")
    if tender["status"] != "OFFERED":
        raise err("ERR_TENDER_NOT_OFFERED", "Tender is not OFFERED")
    tender["status"] = "DECLINED"
    db.touch(tender)
    _revert_shipment_to_untendered(tender)
    return success(ser.tender_view(tender), 200)


@app.route("/tms/tenders/<tender_id>/expire", methods=["POST"])
def expire_tender(tender_id):
    auth(["ShipperOps", "CarrierOps"])
    tender = find_or_404(db.tenders, tender_id, "ERR_TENDER_NOT_FOUND")
    if tender["status"] != "OFFERED":
        raise err("ERR_TENDER_NOT_OFFERED", "Tender is not OFFERED")
    tender["status"] = "EXPIRED"
    db.touch(tender)
    _revert_shipment_to_untendered(tender)
    return success(ser.tender_view(tender), 200)


def _revert_shipment_to_untendered(tender):
    """Decline/expire side effect: shipment tender_status TENDERED -> UNTENDERED;
    assignment fields remain null (PRD §3.5)."""
    shipment = db.shipments.get(tender["shipment_id"])
    if shipment is not None and shipment["tender_status"] == "TENDERED":
        shipment["tender_status"] = "UNTENDERED"
        db.touch(shipment)


# ---------------------------------------------------------------------------
# Load (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
@app.route("/tms/loads", methods=["POST"])
def create_load():
    auth(["DockOps"])
    body = get_json_body()
    carrier_id = as_str(body, "carrier_id")
    carrier = find_or_404(db.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    planned_capacity = as_int(body, "planned_capacity_lbs")
    if planned_capacity <= 0:
        raise err("ERR_INVALID_REQUEST", "planned_capacity_lbs must be > 0")
    load = {
        "carrier_id": carrier_id,
        "planned_capacity_lbs": planned_capacity,
        "status": "BUILDING",
    }
    db.stamp_create(load)
    db.loads[load["id"]] = load
    return success(ser.load_view(load), 201)


@app.route("/tms/loads", methods=["GET"])
def list_loads():
    auth(ALL_ROLES)
    records = list(db.loads.values())
    carrier_id = request.args.get("carrier_id")
    if carrier_id is not None:
        records = [l for l in records if l["carrier_id"] == carrier_id]
    page, meta = paginate(records)
    return success_list([ser.load_view(l) for l in page], meta)


@app.route("/tms/loads/<load_id>", methods=["GET"])
def get_load(load_id):
    auth(ALL_ROLES)
    load = find_or_404(db.loads, load_id, "ERR_LOAD_NOT_FOUND")
    return success(ser.load_view(load), 200)


@app.route("/tms/loads/<load_id>/shipments", methods=["GET"])
def list_load_shipments(load_id):
    auth(ALL_ROLES)
    find_or_404(db.loads, load_id, "ERR_LOAD_NOT_FOUND")
    records = [s for s in db.shipments.values() if s.get("load_id") == load_id]
    page, meta = paginate(records)
    return success_list([ser.shipment_view(s) for s in page], meta)


@app.route("/tms/loads/<load_id>/shipments", methods=["POST"])
def add_shipment_to_load(load_id):
    auth(["DockOps"])
    load = find_or_404(db.loads, load_id, "ERR_LOAD_NOT_FOUND")
    body = get_json_body()
    # priority 4: FK existence (shipment_id).
    shipment_id = as_str(body, "shipment_id")
    expected_version = as_int(body, "expected_load_version")
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    # priority 8: load state must be BUILDING.
    if load["status"] != "BUILDING":
        raise err("ERR_LOAD_NOT_BUILDING", "Load is not BUILDING")
    # shipment must be BOOKED and not already on a load.
    if shipment["tender_status"] != "BOOKED" or shipment.get("load_id") is not None:
        raise err("ERR_SHIPMENT_NOT_ON_BUILDING_LOAD", "Shipment must be BOOKED and not already on a load")
    # priority 15: OCC on Load.version.
    if expected_version != load["version"]:
        raise err("ERR_STALE_LOAD_VERSION", "expected_load_version does not match current load version")
    # priority 13: capacity guard.
    before = calc.consolidated_weight(load)
    if before + shipment["weight_lbs"] > load["planned_capacity_lbs"]:
        raise err("ERR_LOAD_CAPACITY_EXCEEDED", "Adding shipment would exceed planned capacity")
    shipment["load_id"] = load_id
    db.touch(shipment)
    db.touch(load)  # increments Load.version; consolidated weight recomputed on read
    return success(ser.load_view(load), 200)


@app.route("/tms/loads/<load_id>/dispatch", methods=["POST"])
def dispatch_load(load_id):
    auth(["DockOps"])
    load = find_or_404(db.loads, load_id, "ERR_LOAD_NOT_FOUND")
    if load["status"] != "BUILDING":
        raise err("ERR_LOAD_NOT_BUILDING", "Load is not BUILDING")
    if calc.consolidated_weight(load) <= 0:
        raise err("ERR_EMPTY_LOAD", "Load has no consolidated shipments")
    has_appt = any(
        a["load_id"] == load_id and a["status"] in ("SCHEDULED", "CHECKED_IN")
        for a in db.dock_appointments.values()
    )
    if not has_appt:
        raise err("ERR_NO_DOCK_APPOINTMENT", "Load has no SCHEDULED/CHECKED_IN dock appointment")
    load["status"] = "DISPATCHED"
    db.touch(load)
    return success(ser.load_view(load), 200)


@app.route("/tms/loads/<load_id>/close", methods=["POST"])
def close_load(load_id):
    auth(["DockOps"])
    load = find_or_404(db.loads, load_id, "ERR_LOAD_NOT_FOUND")
    if load["status"] != "DISPATCHED":
        raise err("ERR_LOAD_NOT_DISPATCHED", "Load is not DISPATCHED")
    for s in db.shipments.values():
        if s.get("load_id") == load_id and s["execution_status"] != "CANCELLED":
            if s["execution_status"] != "DELIVERED":
                raise err("ERR_LOAD_HAS_UNDELIVERED_SHIPMENTS", "Load has undelivered shipments")
    load["status"] = "CLOSED"
    db.touch(load)
    return success(ser.load_view(load), 200)


# ---------------------------------------------------------------------------
# DockAppointment (PRD §3.7)
# ---------------------------------------------------------------------------
@app.route("/tms/dock-appointments", methods=["POST"])
def create_dock_appointment():
    auth(["DockOps"])
    body = get_json_body()
    load_id = as_str(body, "load_id")
    find_or_404(db.loads, load_id, "ERR_LOAD_NOT_FOUND")
    dock_door = as_str(body, "dock_door")
    start_minute = as_int(body, "start_minute")
    end_minute = as_int(body, "end_minute")
    if start_minute < 0:
        raise err("ERR_INVALID_REQUEST", "start_minute must be >= 0")
    if end_minute <= start_minute:
        raise err("ERR_INVALID_REQUEST", "end_minute must be > start_minute")
    # priority 10: half-open overlap on the same door among SCHEDULED/CHECKED_IN.
    for a in db.dock_appointments.values():
        if a["dock_door"] != dock_door:
            continue
        if a["status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        # Half-open [s, e) overlap iff start < other_end AND other_start < end.
        if start_minute < a["end_minute"] and a["start_minute"] < end_minute:
            raise err("ERR_DOCK_DOUBLE_BOOKED", "Appointment overlaps an existing appointment on this door")
    appt = {
        "load_id": load_id,
        "dock_door": dock_door,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "SCHEDULED",
    }
    db.stamp_create(appt)
    db.dock_appointments[appt["id"]] = appt
    return success(ser.appt_view(appt), 201)


@app.route("/tms/dock-appointments", methods=["GET"])
def list_dock_appointments():
    auth(ALL_ROLES)
    records = list(db.dock_appointments.values())
    load_id = request.args.get("load_id")
    if load_id is not None:
        records = [a for a in records if a["load_id"] == load_id]
    dock_door = request.args.get("dock_door")
    if dock_door is not None:
        records = [a for a in records if a["dock_door"] == dock_door]
    page, meta = paginate(records)
    return success_list([ser.appt_view(a) for a in page], meta)


@app.route("/tms/dock-appointments/<appt_id>", methods=["GET"])
def get_dock_appointment(appt_id):
    auth(ALL_ROLES)
    appt = find_or_404(db.dock_appointments, appt_id, "ERR_APPT_NOT_FOUND")
    return success(ser.appt_view(appt), 200)


@app.route("/tms/dock-appointments/<appt_id>/check-in", methods=["POST"])
def checkin_dock_appointment(appt_id):
    auth(["DockOps"])
    appt = find_or_404(db.dock_appointments, appt_id, "ERR_APPT_NOT_FOUND")
    if appt["status"] != "SCHEDULED":
        raise err("ERR_APPT_NOT_SCHEDULED", "Appointment is not SCHEDULED")
    appt["status"] = "CHECKED_IN"
    db.touch(appt)
    return success(ser.appt_view(appt), 200)


@app.route("/tms/dock-appointments/<appt_id>/release", methods=["POST"])
def release_dock_appointment(appt_id):
    auth(["DockOps"])
    appt = find_or_404(db.dock_appointments, appt_id, "ERR_APPT_NOT_FOUND")
    if appt["status"] != "CHECKED_IN":
        raise err("ERR_APPT_NOT_CHECKED_IN", "Appointment is not CHECKED_IN")
    appt["status"] = "RELEASED"
    db.touch(appt)
    return success(ser.appt_view(appt), 200)


@app.route("/tms/dock-appointments/<appt_id>/cancel", methods=["POST"])
def cancel_dock_appointment(appt_id):
    auth(["DockOps"])
    appt = find_or_404(db.dock_appointments, appt_id, "ERR_APPT_NOT_FOUND")
    if appt["status"] != "SCHEDULED":
        raise err("ERR_APPT_NOT_SCHEDULED", "Appointment is not SCHEDULED")
    appt["status"] = "CANCELLED"
    db.touch(appt)
    return success(ser.appt_view(appt), 200)


# ---------------------------------------------------------------------------
# FreightInvoice (PRD §3.10, §3.11)
# ---------------------------------------------------------------------------
@app.route("/tms/freight-invoices", methods=["POST"])
def create_freight_invoice():
    auth(["FreightAuditor"])
    body = get_json_body()
    shipment_id = as_str(body, "shipment_id")
    find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    invoiced_linehaul = as_int(body, "invoiced_linehaul_cents")
    codes = body.get("invoiced_accessorial_codes")
    if codes is None:
        codes = []
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise err("ERR_INVALID_REQUEST", "invoiced_accessorial_codes must be a list of strings")
    invoice = {
        "shipment_id": shipment_id,
        "invoiced_linehaul_cents": invoiced_linehaul,
        "invoiced_accessorial_codes": codes,
        "variance_cents": None,
        "status": "RECEIVED",
    }
    db.stamp_create(invoice)
    db.freight_invoices[invoice["id"]] = invoice
    return success(ser.invoice_view(invoice), 201)


@app.route("/tms/freight-invoices", methods=["GET"])
def list_freight_invoices():
    auth(ALL_ROLES)
    records = list(db.freight_invoices.values())
    shipment_id = request.args.get("shipment_id")
    if shipment_id is not None:
        records = [i for i in records if i["shipment_id"] == shipment_id]
    page, meta = paginate(records)
    return success_list([ser.invoice_view(i) for i in page], meta)


@app.route("/tms/freight-invoices/<invoice_id>", methods=["GET"])
def get_freight_invoice(invoice_id):
    auth(ALL_ROLES)
    invoice = find_or_404(db.freight_invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    return success(ser.invoice_view(invoice), 200)


@app.route("/tms/freight-invoices/<invoice_id>/audit", methods=["POST"])
def audit_freight_invoice(invoice_id):
    auth(["FreightAuditor"])
    invoice = find_or_404(db.freight_invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["status"] != "RECEIVED":
        raise err("ERR_INVOICE_NOT_RECEIVED", "Invoice is not RECEIVED")
    shipment = db.shipments.get(invoice["shipment_id"])
    if shipment is None or shipment["execution_status"] != "DELIVERED":
        raise err("ERR_SHIPMENT_NOT_DELIVERED", "Shipment is not DELIVERED")
    # priority 12: every accessorial code must be known.
    for code in invoice["invoiced_accessorial_codes"]:
        if code not in calc.KNOWN_ACCESSORIALS:
            raise err("ERR_UNKNOWN_ACCESSORIAL", "Unknown accessorial code: %s" % code)
    rate = db.contract_rates.get(shipment["contract_rate_id"])
    audited, variance = calc.freight_cost_audited(shipment, rate, invoice)
    shipment["audited_cost_cents"] = audited
    db.touch(shipment)
    invoice["variance_cents"] = variance
    invoice["status"] = "AUDITED"
    db.touch(invoice)
    return success(ser.invoice_view(invoice), 200)


@app.route("/tms/freight-invoices/<invoice_id>/approve", methods=["POST"])
def approve_freight_invoice(invoice_id):
    auth(["FreightAuditor"])
    invoice = find_or_404(db.freight_invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["status"] != "AUDITED":
        raise err("ERR_INVOICE_NOT_AUDITED", "Invoice is not AUDITED")
    if abs(invoice["variance_cents"]) > calc.TOLERANCE_CENTS:
        raise err("ERR_VARIANCE_EXCEEDS_TOLERANCE", "Variance exceeds tolerance")
    invoice["status"] = "APPROVED"
    db.touch(invoice)
    return success(ser.invoice_view(invoice), 200)


@app.route("/tms/freight-invoices/<invoice_id>/dispute", methods=["POST"])
def dispute_freight_invoice(invoice_id):
    auth(["FreightAuditor"])
    invoice = find_or_404(db.freight_invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["status"] != "AUDITED":
        raise err("ERR_INVOICE_NOT_AUDITED", "Invoice is not AUDITED")
    invoice["status"] = "DISPUTED"
    db.touch(invoice)
    return success(ser.invoice_view(invoice), 200)


# ---------------------------------------------------------------------------
# Claim (PRD §3.12)
# ---------------------------------------------------------------------------
@app.route("/tms/claims", methods=["POST"])
def create_claim():
    auth(["ShipperOps"])
    body = get_json_body()
    shipment_id = as_str(body, "shipment_id")
    shipment = find_or_404(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    claim_type = as_enum(body, "claim_type", CLAIM_TYPES)
    claimed_amount = as_int(body, "claimed_amount_cents")
    if claimed_amount <= 0:
        raise err("ERR_INVALID_REQUEST", "claimed_amount_cents must be > 0")
    claim = {
        "shipment_id": shipment_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount,
        "approved_amount_cents": None,
        "status": "OPEN",
    }
    db.stamp_create(claim)
    db.claims[claim["id"]] = claim
    # Increment claim_count on the carrier assigned to the shipment.
    carrier = db.carriers.get(shipment.get("assigned_carrier_id"))
    if carrier is not None:
        carrier["claim_count"] += 1
        db.touch(carrier)
    return success(ser.claim_view(claim), 201)


@app.route("/tms/claims", methods=["GET"])
def list_claims():
    auth(ALL_ROLES)
    records = list(db.claims.values())
    shipment_id = request.args.get("shipment_id")
    if shipment_id is not None:
        records = [c for c in records if c["shipment_id"] == shipment_id]
    page, meta = paginate(records)
    return success_list([ser.claim_view(c) for c in page], meta)


@app.route("/tms/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    auth(ALL_ROLES)
    claim = find_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    return success(ser.claim_view(claim), 200)


@app.route("/tms/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    auth(["FreightAuditor"])
    claim = find_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "OPEN":
        raise err("ERR_CLAIM_NOT_OPEN", "Claim is not OPEN")
    shipment = db.shipments.get(claim["shipment_id"])
    if shipment is None or shipment["execution_status"] != "DELIVERED":
        raise err("ERR_SHIPMENT_NOT_DELIVERED", "Shipment is not DELIVERED")
    order = db.orders.get(shipment["order_id"])
    claim["approved_amount_cents"] = calc.claim_settlement(claim, order)
    claim["status"] = "APPROVED"
    db.touch(claim)
    return success(ser.claim_view(claim), 200)


@app.route("/tms/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    auth(["FreightAuditor"])
    claim = find_or_404(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "OPEN":
        raise err("ERR_CLAIM_NOT_OPEN", "Claim is not OPEN")
    claim["approved_amount_cents"] = 0
    claim["status"] = "DENIED"
    db.touch(claim)
    return success(ser.claim_view(claim), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
