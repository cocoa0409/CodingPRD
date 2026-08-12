from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body
from response import success, paged
from services import (get_or_404, shipping_fee, check_no_active_recall,
                      check_recall_hold, order_allocations, cs_append,
                      quarantine_shipment, send_cooler_to_conditioning,
                      QUARANTINABLE_TRANSIT)
from util import (new_resource, touch, req, as_str, as_num, as_enum,
                  as_datetime_str, parse_datetime)

bp = Blueprint("ship", __name__)

SHIP_READ = ("Owner", "Pharmacist", "PharmacyTech", "ComplianceOfficer",
             "PharmacyAdmin")
SERVICE_LEVELS = {"STANDARD", "EXPRESS", "OVERNIGHT"}
ZONES = {"Z1", "Z2", "Z3"}


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


@bp.route("/compound-orders/<rid>/shipments", methods=["POST"])
def create_shipment(rid):
    auth("Pharmacist")
    order = get_or_404(db.compound_orders, rid, "compound order")
    d = body()
    cooler = None
    cooler_id = d.get("cooler_asset_id")
    if cooler_id is not None:
        cooler = get_or_404(db.cooler_assets, cooler_id, "cooler asset")
    carrier = as_str(req(d, "carrier"), "carrier")
    service_level = as_enum(req(d, "service_level"), "service_level", SERVICE_LEVELS)
    zone = as_enum(req(d, "destination_zone"), "destination_zone", ZONES)
    check_recall_hold(order, "shipments")
    if order["status"] != "READY_TO_DISPATCH":
        raise ApiError("ERR_INVALID_STATE", "order is not READY_TO_DISPATCH", 409)
    check_no_active_recall(order)
    rx = db.prescriptions[order["prescription_id"]]
    formula = db.formulas[rx["formula_id"]]
    drug = db.drug_catalog_items[formula["drug_catalog_item_id"]]
    requires_cold = drug["requires_cold_chain"]
    if requires_cold and cooler is None:
        raise ApiError("ERR_COLD_CHAIN_COOLER_REQUIRED",
                       "cold-chain drug requires a cooler_asset_id", 422)
    if not requires_cold and cooler is not None:
        raise ApiError("ERR_COLD_CHAIN_COOLER_REQUIRED",
                       "ambient drug forbids a cooler_asset_id", 422)
    if cooler is not None:
        attachable = cooler["status"] == "AVAILABLE"
        if cooler["status"] == "CONDITIONING" and cooler.get(
                "conditioning_available_at"):
            avail = parse_datetime(cooler["conditioning_available_at"])
            if avail is not None and db.clock() >= avail:
                attachable = True
        if not attachable:
            raise ApiError("ERR_COOLER_CONDITIONING",
                           "cooler is inside its mandatory reconditioning window", 409)
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_PAYMENT_REQUIRED", "order must be PAID before shipment",
                       402)
    sh = new_resource({
        "compound_order_id": order["id"],
        "cooler_asset_id": cooler["id"] if cooler else None,
        "carrier": carrier, "service_level": service_level,
        "destination_zone": zone,
        "transit_status": "LABEL_CREATED",
        "cold_chain_status": "COMPLIANT" if requires_cold else "NOT_REQUIRED",
        "required_temp_min_celsius": drug["cold_chain_min_celsius"],
        "required_temp_max_celsius": drug["cold_chain_max_celsius"],
        "excursion_minutes_accumulated": 0,
        "shipping_fee_cents": shipping_fee(service_level, zone, requires_cold),
        "last_reading_at": None,
    })
    db.shipments[sh["id"]] = sh
    if cooler is not None:
        cooler["status"] = "ASSIGNED"
        cooler["conditioning_available_at"] = None
        touch(cooler)
    return success(sh, 201)


@bp.route("/shipments/<rid>", methods=["GET"])
def get_shipment(rid):
    auth(*SHIP_READ)
    return success(get_or_404(db.shipments, rid, "shipment"))


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    auth(*SHIP_READ)
    return paged(_filter(list(db.shipments.values()),
                         ["compound_order_id", "cooler_asset_id", "transit_status"]))


# ---- temperature readings ----

def _readings_of(shipment_id):
    rs = [r for r in db.temperature_readings.values()
          if r["shipment_id"] == shipment_id]
    rs.sort(key=lambda r: (parse_datetime(r["recorded_at"]), r["_seq"]))
    return rs


@bp.route("/shipments/<rid>/temperature-readings", methods=["POST"])
def add_reading(rid):
    auth("PharmacyTech")
    sh = get_or_404(db.shipments, rid, "shipment")
    d = body()
    recorded_s = as_datetime_str(req(d, "recorded_at"), "recorded_at")
    temp = as_num(req(d, "temp_celsius"), "temp_celsius")
    if sh["cold_chain_status"] == "NOT_REQUIRED":
        raise ApiError("ERR_COLD_CHAIN_NOT_REQUIRED",
                       "shipment does not require cold chain", 422)
    prior = _readings_of(rid)
    recorded = parse_datetime(recorded_s)
    if prior and recorded < parse_datetime(prior[-1]["recorded_at"]):
        raise ApiError("ERR_COLD_CHAIN_NOT_REQUIRED",
                       "recorded_at must be monotonic non-decreasing", 422)
    reading = new_resource({
        "shipment_id": rid, "recorded_at": recorded_s, "temp_celsius": temp,
    }, versioned=False)
    db.temperature_readings[reading["id"]] = reading
    # recompute excursion state over the full reading history
    lo = sh["required_temp_min_celsius"]
    hi = sh["required_temp_max_celsius"]
    accumulated = 0
    prev = None
    for r in _readings_of(rid):
        out = r["temp_celsius"] < lo or r["temp_celsius"] > hi
        if prev is not None and out:
            delta = parse_datetime(r["recorded_at"]) - parse_datetime(
                prev["recorded_at"])
            accumulated += int(delta.total_seconds() // 60)
        prev = r
    latest_out = prev["temp_celsius"] < lo or prev["temp_celsius"] > hi
    sh["excursion_minutes_accumulated"] = accumulated
    if accumulated >= 30:
        sh["cold_chain_status"] = "EXCURSION_BREACH"
    elif accumulated > 0 or latest_out:
        sh["cold_chain_status"] = "EXCURSION_WATCH"
    else:
        sh["cold_chain_status"] = "COMPLIANT"
    sh["last_reading_at"] = prev["recorded_at"]
    if sh["cold_chain_status"] == "EXCURSION_BREACH" and \
            sh["transit_status"] in QUARANTINABLE_TRANSIT:
        quarantine_shipment(sh)
    else:
        touch(sh)
    return success(reading, 201)


@bp.route("/shipments/<rid>/temperature-readings", methods=["GET"])
def list_readings(rid):
    auth("Pharmacist", "PharmacyTech", "ComplianceOfficer", "PharmacyAdmin")
    get_or_404(db.shipments, rid, "shipment")
    return paged([r for r in db.temperature_readings.values()
                  if r["shipment_id"] == rid])


# ---- transit scans ----

def _shipment_transition(rid, from_states, to_state):
    auth("Pharmacist")
    sh = get_or_404(db.shipments, rid, "shipment")
    if sh["transit_status"] not in from_states:
        raise ApiError("ERR_INVALID_STATE",
                       "shipment is not in a permitted source state", 409)
    sh["transit_status"] = to_state
    touch(sh)
    return sh


@bp.route("/shipments/<rid>/mark-picked-up", methods=["POST"])
def mark_picked_up(rid):
    _, user_id = auth("Pharmacist")
    sh = get_or_404(db.shipments, rid, "shipment")
    if sh["transit_status"] != "LABEL_CREATED":
        raise ApiError("ERR_INVALID_STATE", "shipment is not LABEL_CREATED", 409)
    order = db.compound_orders[sh["compound_order_id"]]
    check_no_active_recall(order)
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_PAYMENT_REQUIRED", "order must be PAID before pickup", 402)
    if order["status"] != "READY_TO_DISPATCH":
        raise ApiError("ERR_INVALID_STATE",
                       "order is not READY_TO_DISPATCH", 409)
    order["status"] = "DISPENSED"
    touch(order)
    for a in order_allocations(order):
        if a["status"] == "CONSUMED":
            lot = db.lots[a["lot_id"]]
            cs_append(lot, "DISPENSE", -a["qty_consumed"], user_id,
                      order_id=order["id"])
    sh["transit_status"] = "PICKED_UP"
    touch(sh)
    return success(sh)


@bp.route("/shipments/<rid>/mark-in-transit", methods=["POST"])
def mark_in_transit(rid):
    sh = _shipment_transition(rid, ("PICKED_UP",), "IN_TRANSIT")
    return success(sh)


@bp.route("/shipments/<rid>/mark-out-for-delivery", methods=["POST"])
def mark_out_for_delivery(rid):
    sh = _shipment_transition(rid, ("IN_TRANSIT",), "OUT_FOR_DELIVERY")
    return success(sh)


@bp.route("/shipments/<rid>/mark-delivered", methods=["POST"])
def mark_delivered(rid):
    auth("Pharmacist")
    sh = get_or_404(db.shipments, rid, "shipment")
    if sh["transit_status"] != "OUT_FOR_DELIVERY":
        raise ApiError("ERR_INVALID_STATE", "shipment is not OUT_FOR_DELIVERY", 409)
    if sh["cold_chain_status"] == "EXCURSION_BREACH":
        raise ApiError("ERR_INVALID_STATE",
                       "shipment has an excursion breach", 409)
    sh["transit_status"] = "DELIVERED"
    send_cooler_to_conditioning(sh)
    touch(sh)
    return success(sh)


@bp.route("/shipments/<rid>/report-exception", methods=["POST"])
def report_exception(rid):
    body()  # reason (free text)
    sh = _shipment_transition(rid, ("IN_TRANSIT", "OUT_FOR_DELIVERY"),
                              "DELIVERY_EXCEPTION")
    return success(sh)


@bp.route("/shipments/<rid>/mark-returned", methods=["POST"])
def mark_returned(rid):
    auth("Pharmacist")
    sh = get_or_404(db.shipments, rid, "shipment")
    if sh["transit_status"] != "DELIVERY_EXCEPTION":
        raise ApiError("ERR_INVALID_STATE", "shipment is not DELIVERY_EXCEPTION", 409)
    sh["transit_status"] = "RETURNED_TO_PHARMACY"
    send_cooler_to_conditioning(sh)
    touch(sh)
    return success(sh)
