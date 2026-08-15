"""Shipment / cold-chain endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db, mint_allocation_sequence
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ORDER_INVALID_STATE,
    ERR_SHIPMENT_INVALID_STATE,
    ERR_COLD_CHAIN_CARRIER_REQUIRED,
    ERR_TEMPERATURE_LOG_NOT_APPLICABLE,
)
from middleware import authorized
from response import success_object, success_list
from services.calculations import recompute_credit_used, order_lines
from services.core import (
    get_body, require_fields, require_string, require_bool, parse_dt_field,
    public, get_or_404, paginate,
)
from util import new_id, now_ts, touch, fmt_datetime

bp = Blueprint("shipments", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "SupplyChainPlanner", "ComplianceOfficer"]
TEMP_MIN_C = 2.0
TEMP_MAX_C = 8.0


def _serialize(shipment):
    out = public(shipment)
    out["temperature_log"] = [
        {"recorded_at": r["recorded_at"], "temperature_celsius": r["temperature_celsius"]}
        for r in shipment["temperature_log"]
    ]
    return out


def _order_requires_cold_chain(order_id):
    for line in order_lines(order_id):
        product = db["products"].get(line["product_id"])
        if product is not None and product.get("requires_cold_chain"):
            return True
    return False


@bp.route("/vet/shipments", methods=["POST"])
def create_shipment():
    authorized(["SupplyChainPlanner"])
    body = get_body()
    require_fields(body, ["order_id", "carrier_name"])
    order = get_or_404("orders", body["order_id"])
    carrier_name = require_string(body, "carrier_name")
    certified = require_bool(body, "carrier_cold_chain_certified", default=False)

    # Cross-entity state gate: order must be APPROVED.
    if order["status"] != "APPROVED":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"shipment requires an APPROVED order (is {order['status']})")

    requires_cold_chain = _order_requires_cold_chain(order["id"])
    if requires_cold_chain and not certified:
        raise_error(ERR_COLD_CHAIN_CARRIER_REQUIRED,
                    "shipment carries cold-chain lines but carrier is not certified")

    shipment = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "order_id": order["id"],
        "carrier_name": carrier_name,
        "carrier_cold_chain_certified": certified,
        "requires_cold_chain": requires_cold_chain,
        "temperature_log": [],
        "has_unresolved_excursion": False,
        "status": "PREPARING",
    }
    db["shipments"][shipment["id"]] = shipment
    return success_object(_serialize(shipment), status=201)


@bp.route("/vet/shipments", methods=["GET"])
def list_shipments():
    authorized(READ_ROLES)
    items = list(db["shipments"].values())
    for param in ("order_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if str(s.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([_serialize(s) for s in page], total, limit, offset)


@bp.route("/vet/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    authorized(READ_ROLES)
    shipment = get_or_404("shipments", sid)
    return success_object(_serialize(shipment))


@bp.route("/vet/shipments/<sid>/dispatch", methods=["POST"])
def dispatch_shipment(sid):
    authorized(["SupplyChainPlanner"])
    shipment = get_or_404("shipments", sid)
    if shipment["status"] != "PREPARING":
        raise_error(ERR_SHIPMENT_INVALID_STATE,
                    f"shipment must be PREPARING (is {shipment['status']})")
    order = get_or_404("orders", shipment["order_id"])
    # Every ALLOCATED line -> SHIPPED; lot qty_on_hand and qty_allocated debited.
    for line in order_lines(order["id"]):
        if line["status"] != "ALLOCATED":
            continue
        lot = db["inventory_lots"].get(line["lot_id"]) if line["lot_id"] else None
        if lot is not None:
            lot["qty_on_hand"] -= line["qty_requested"]
            lot["qty_allocated"] -= line["qty_requested"]
            lot["qty_available"] = lot["qty_on_hand"] - lot["qty_allocated"]
            touch(lot)
        line["status"] = "SHIPPED"
        touch(line)
    order["status"] = "SHIPPED"
    touch(order)
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    recompute_credit_used(order["clinic_id"])
    return success_object(_serialize(shipment))


@bp.route("/vet/shipments/<sid>/deliver", methods=["POST"])
def deliver_shipment(sid):
    authorized(["SupplyChainPlanner"])
    shipment = get_or_404("shipments", sid)
    if shipment["status"] != "IN_TRANSIT":
        raise_error(ERR_SHIPMENT_INVALID_STATE,
                    f"shipment must be IN_TRANSIT (is {shipment['status']})")
    order = get_or_404("orders", shipment["order_id"])
    for line in order_lines(order["id"]):
        if line["status"] == "SHIPPED":
            line["status"] = "DELIVERED"
            touch(line)
    order["status"] = "DELIVERED"
    touch(order)
    shipment["status"] = "DELIVERED"
    touch(shipment)
    recompute_credit_used(order["clinic_id"])
    return success_object(_serialize(shipment))


@bp.route("/vet/shipments/<sid>/temperature-readings", methods=["POST"])
def add_temperature_reading(sid):
    authorized(["SupplyChainPlanner"])
    shipment = get_or_404("shipments", sid)
    body = get_body()
    require_fields(body, ["recorded_at", "temperature_celsius"])
    recorded_at = parse_dt_field(body, "recorded_at")
    temp = body["temperature_celsius"]
    if isinstance(temp, bool) or not isinstance(temp, (int, float)):
        raise_error(ERR_INVALID_REQUEST, "temperature_celsius must be a number")

    # Applicability first: only cold-chain shipments accept readings.
    if not shipment["requires_cold_chain"]:
        raise_error(ERR_TEMPERATURE_LOG_NOT_APPLICABLE,
                    "temperature readings require a cold-chain shipment")
    if shipment["status"] != "IN_TRANSIT":
        raise_error(ERR_SHIPMENT_INVALID_STATE,
                    f"shipment must be IN_TRANSIT (is {shipment['status']})")

    shipment["temperature_log"].append({
        "recorded_at": fmt_datetime(recorded_at),
        "temperature_celsius": temp,
    })
    # Excursion: strictly outside [2.0, 8.0] inclusive band -> QUARANTINED.
    if temp < TEMP_MIN_C or temp > TEMP_MAX_C:
        shipment["has_unresolved_excursion"] = True
        shipment["status"] = "QUARANTINED"
    touch(shipment)
    return success_object(_serialize(shipment), status=201)


@bp.route("/vet/shipments/<sid>/resolve-quarantine", methods=["POST"])
def resolve_quarantine(sid):
    authorized(["ComplianceOfficer"])
    shipment = get_or_404("shipments", sid)
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("RELEASED", "DESTROYED"):
        raise_error(ERR_INVALID_REQUEST, "outcome must be RELEASED or DESTROYED")
    if shipment["status"] != "QUARANTINED":
        raise_error(ERR_SHIPMENT_INVALID_STATE,
                    f"shipment must be QUARANTINED (is {shipment['status']})")

    order = get_or_404("orders", shipment["order_id"])
    if outcome == "RELEASED":
        shipment["has_unresolved_excursion"] = False
        shipment["status"] = "IN_TRANSIT"
        touch(shipment)
        return success_object(_serialize(shipment))

    # DESTROYED: goods not returned to stock; each SHIPPED line -> BACKORDERED
    # with a fresh backorder; order SHIPPED -> BACKORDERED; credit recomputed.
    for line in order_lines(order["id"]):
        if line["status"] != "SHIPPED":
            continue
        line["qty_allocated"] = 0
        line["lot_id"] = None
        line["status"] = "BACKORDERED"
        touch(line)
        from services.calculations import mint_backorder
        mint_backorder(line)
    if order["status"] == "SHIPPED":
        order["status"] = "BACKORDERED"
        touch(order)
    shipment["status"] = "DESTROYED"
    touch(shipment)
    recompute_credit_used(order["clinic_id"])
    return success_object(_serialize(shipment))
