"""Shipments: packing, hazmat certification, dispatch and delivery."""
from datetime import timedelta

from flask import Blueprint

import calc
from common import (
    ApiError, DB, D, authenticate, ceil_int, f_datetime, f_enum, f_int, f_str,
    get_body, must, new_row, now_date, now_ts, ok, page, parse_date, parse_dt,
    public, qp, sort_rows, touch,
)

bp = Blueprint("shipments", __name__, url_prefix="/distribution")

SHIP_READERS = ["PlatformAdmin", "SalesRep", "WarehouseOperator", "HazmatCertifier", "ComplianceOfficer"]
LIVE_STATUSES = ("PACKED", "CERTIFIED", "DISPATCHED")


@bp.post("/shipments")
def pack_shipment():
    user_id, role = authenticate(["WarehouseOperator"])
    body = get_body()
    order_id = f_str(body, "order_id")
    carrier_id = f_str(body, "carrier_id")
    raw_start = f_datetime(body, "pickup_window_start")
    raw_end = f_datetime(body, "pickup_window_end")
    expected_version = f_int(body, "expected_order_version")
    start = parse_dt(raw_start)
    end = parse_dt(raw_end)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "pickup_window_end must be later than pickup_window_start")

    order = must("orders", order_id)
    carrier = must("carriers", carrier_id)

    if expected_version != int(order["version"]):
        raise ApiError("ERR_STALE_VERSION", "expected_order_version does not match the order")
    if order["fulfillment_status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "order is not ALLOCATED")

    lines = calc.order_lines(order_id)
    class_code = calc.order_class_code(lines)
    weight = calc.lines_weight_kg(lines)
    lead = calc.lines_lead_kg(lines)
    package_count = ceil_int(D(weight) / calc.HAZMAT_MAX_PACKAGE_KG)

    if class_code not in carrier["accepts_hazmat_classes"]:
        raise ApiError("ERR_CARRIER_HAZMAT_REFUSED", "carrier does not tender %s" % class_code)
    if class_code == "UN3480_SECTION_IA" and not carrier["ground_only"]:
        raise ApiError("ERR_AIR_MODE_PROHIBITED", "class UN3480_SECTION_IA may not move by air")
    for line in lines:
        model = DB.battery_models[line["battery_model_id"]]
        if model["chemistry"] == "LITHIUM_IRON_PHOSPHATE" and \
                D(model["watt_hour_rating"]) > D(carrier["max_lithium_watt_hours_per_package"]):
            raise ApiError("ERR_LITHIUM_WH_LIMIT_EXCEEDED", "lithium watt-hour ceiling exceeded")

    for other in DB.shipments.values():
        if other["carrier_id"] != carrier_id or other["status"] not in LIVE_STATUSES:
            continue
        other_start = parse_dt(other["pickup_window_start"])
        other_end = parse_dt(other["pickup_window_end"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_CARRIER_WINDOW_CONFLICT", "carrier pickup window conflict")

    warehouse = DB.warehouses[order["warehouse_id"]]
    aggregate = D(weight)
    for other in DB.shipments.values():
        if other["status"] not in LIVE_STATUSES:
            continue
        other_order = DB.orders[other["order_id"]]
        if other_order["warehouse_id"] != order["warehouse_id"]:
            continue
        other_start = parse_dt(other["pickup_window_start"])
        other_end = parse_dt(other["pickup_window_end"])
        if start <= other_end and other_start <= end:
            aggregate += D(other["total_weight_kg"])
    if aggregate > D(warehouse["dock_capacity_kg_per_window"]):
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED", "dock capacity exceeded for this window")

    for other in DB.shipments.values():
        if other["order_id"] == order_id and other["status"] in ("PACKED", "CERTIFIED", "DISPATCHED", "DELIVERED"):
            raise ApiError("ERR_SHIPMENT_ALREADY_OPEN", "order already carries a live shipment")

    row = new_row({
        "order_id": order_id,
        "carrier_id": carrier_id,
        "pickup_window_start": raw_start,
        "pickup_window_end": raw_end,
        "packed_by_user_id": user_id,
        "certified_by_user_id": None,
        "status": "PACKED",
        "hazmat_class_code": class_code,
        "total_weight_kg": float(weight),
        "total_lead_kg": float(lead),
        "package_count": package_count,
        "hazmat_surcharge_cents": 0,
        "rejection_reason": None,
        "dispatched_at": None,
        "delivered_at": None,
    })
    DB.shipments[row["id"]] = row
    touch(order)
    return ok(public(row), 201)


@bp.get("/shipments/<shipment_id>")
def read_shipment(shipment_id):
    authenticate(SHIP_READERS)
    return ok(public(must("shipments", shipment_id)))


@bp.get("/shipments")
def list_shipments():
    authenticate(SHIP_READERS)
    rows = list(DB.shipments.values())
    for name in ("order_id", "carrier_id", "status"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, public)


@bp.post("/shipments/<shipment_id>/certify")
def certify_shipment(shipment_id):
    user_id, role = authenticate(["HazmatCertifier"])
    shipment = must("shipments", shipment_id)
    body = get_body()
    decision = f_enum(body, "certification_decision", ("APPROVE", "REJECT"))
    rejection_reason = f_str(body, "rejection_reason", required=False, default=None)

    if user_id == shipment["packed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "the packer may not certify the shipment")
    if shipment["status"] != "PACKED":
        raise ApiError("ERR_INVALID_STATE", "shipment is not PACKED")

    order = DB.orders[shipment["order_id"]]
    warehouse = DB.warehouses[order["warehouse_id"]]
    account = DB.accounts[order["account_id"]]

    if decision == "APPROVE":
        if shipment["hazmat_class_code"] != "NON_REGULATED" and not warehouse["hazmat_endorsement"]:
            raise ApiError("ERR_WAREHOUSE_NOT_HAZMAT_ENDORSED", "warehouse is not hazmat endorsed")
        lines = calc.order_lines(order["id"])
        surcharge = calc.hazmat_surcharge(
            shipment["hazmat_class_code"], calc.lines_weight_kg(lines), warehouse,
            int(shipment["package_count"]))
        shipment["certified_by_user_id"] = user_id
        shipment["hazmat_surcharge_cents"] = surcharge
        shipment["status"] = "CERTIFIED"
        touch(shipment)
        if not order["hazmat_fee_waived"]:
            previous_total = int(order["total_cents"])
            order["hazmat_fee_cents"] = surcharge
            order["total_cents"] = calc.assemble_total(order)
            touch(order)
            calc.adjust_receivable(account, int(order["total_cents"]) - previous_total)
    else:
        shipment["certified_by_user_id"] = user_id
        shipment["rejection_reason"] = rejection_reason
        shipment["status"] = "HAZMAT_REJECTED"
        touch(shipment)
        order["hazmat_hold"] = True
        rejected = list(order["rejected_carrier_ids"])
        rejected.append(shipment["carrier_id"])
        order["rejected_carrier_ids"] = rejected
        touch(order)
    return ok(public(shipment))


@bp.post("/shipments/<shipment_id>/dispatch")
def dispatch_shipment(shipment_id):
    authenticate(["WarehouseOperator"])
    shipment = must("shipments", shipment_id)
    get_body()
    if shipment["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE", "shipment is not CERTIFIED")
    order = DB.orders[shipment["order_id"]]
    start = parse_dt(shipment["pickup_window_start"])
    end = parse_dt(shipment["pickup_window_end"])
    if not (start <= DB.clock < end):
        raise ApiError("ERR_DISPATCH_WINDOW_NOT_OPEN", "the logical clock is outside the pickup window")
    if shipment["carrier_id"] in order["rejected_carrier_ids"]:
        raise ApiError("ERR_CARRIER_PREVIOUSLY_REJECTED", "carrier was previously rejected for this order")

    shipment["dispatched_at"] = now_ts()
    shipment["status"] = "DISPATCHED"
    touch(shipment)
    if order["fulfillment_status"] == "ALLOCATED":
        order["fulfillment_status"] = "SHIPPED"
        touch(order)
    return ok(public(shipment))


@bp.post("/shipments/<shipment_id>/deliver")
def deliver_shipment(shipment_id):
    authenticate(["WarehouseOperator"])
    shipment = must("shipments", shipment_id)
    get_body()
    if shipment["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "shipment is not DISPATCHED")

    order = DB.orders[shipment["order_id"]]
    account = DB.accounts[order["account_id"]]

    shipment["delivered_at"] = now_ts()
    shipment["status"] = "DELIVERED"
    touch(shipment)

    if order["fulfillment_status"] == "SHIPPED":
        lines = calc.order_lines(order["id"])
        due_by = (parse_dt(shipment["delivered_at"]).date()
                  + timedelta(days=calc.CORE_RETURN_WINDOW_DAYS)).isoformat()
        for line in lines:
            line["core_due_by"] = due_by
            if line["allocated_lot_id"]:
                lot = DB.inventory_lots[line["allocated_lot_id"]]
                lot["quantity_reserved"] = max(0, int(lot["quantity_reserved"]) - int(line["allocated_quantity"]))
                lot["quantity_on_hand"] = max(0, int(lot["quantity_on_hand"]) - int(line["allocated_quantity"]))
                calc.lot_view(lot)
                touch(lot)
            touch(line)

        order["fulfillment_status"] = "DELIVERED"
        order["credit_status"] = "CLOSED"
        touch(order)

        for contract in sort_rows(list(DB.service_contracts.values())):
            if contract.get("order_id") == order["id"] and contract["status"] == "ATTACHED":
                contract["status"] = "ACTIVE"
                touch(contract)

        liability = 0
        for line in lines:
            model = DB.battery_models[line["battery_model_id"]]
            liability += int(line["core_expected_count"]) * int(model["core_deposit_cents"])
        if liability:
            account["core_deposit_balance_cents"] = int(account["core_deposit_balance_cents"]) + liability
            touch(account)
        calc.apply_credit_hold(account)
    return ok(public(shipment))
