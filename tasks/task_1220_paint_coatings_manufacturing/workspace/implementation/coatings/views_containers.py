"""Container endpoints: reweigh, ship (VOC gate), freeze exposure, customer return."""
from decimal import Decimal

from flask import Blueprint, request

from .domain import (
    order_line_gallons,
    reconcile_filled_net,
    ser_container,
    shipped_volume_gal,
    weigh_passes,
)
from .errors import bad_request, invalid_state, not_found, unprocessable
from .store import now, store
from .util import D, auth, body, list_response, round2, success, touch, v_str

bp = Blueprint("containers", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


@bp.get("/coatings/containers/<cid>")
def get_container(cid):
    auth(ALL)
    rec = store.containers.get(cid)
    if rec is None:
        raise not_found()
    return success(ser_container(rec), 200)


@bp.get("/coatings/containers")
def list_containers():
    auth(ALL)
    recs = list(store.containers.values())
    for param in ("batch_id", "order_id", "disposal_request_id", "status"):
        v = request.args.get(param)
        if v is not None:
            recs = [c for c in recs if c.get(param) == v]
    return list_response(recs, ser_container)


@bp.post("/coatings/containers/<cid>/reweigh")
def reweigh_container(cid):
    auth(("QCInspector",))
    b = body()
    actual_fill_g = b.get("actual_fill_g")
    if isinstance(actual_fill_g, bool) or not isinstance(actual_fill_g, int):
        if isinstance(actual_fill_g, float) and actual_fill_g.is_integer():
            actual_fill_g = int(actual_fill_g)
        else:
            raise bad_request("actual_fill_g must be an integer")
    mark_rejected = b.get("mark_rejected", False)
    if mark_rejected is not None and not isinstance(mark_rejected, bool):
        raise bad_request("mark_rejected must be a boolean")
    rec = store.containers.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] != "QUARANTINED":
        raise invalid_state("Container is not QUARANTINED")
    if mark_rejected:
        rec["status"] = "REJECTED"
    else:
        rec["actual_fill_g"] = actual_fill_g
        rec["fill_variance_g"] = actual_fill_g - rec["nominal_fill_g"]
        rec["net_weight_kg"] = round2(D(actual_fill_g) / Decimal("1000"))
        if weigh_passes(rec["nominal_fill_g"], actual_fill_g):
            rec["status"] = "IN_STOCK"
    touch(rec)
    batch = store.batches.get(rec["batch_id"])
    if batch is not None:
        reconcile_filled_net(batch)
        touch(batch)
    return success(ser_container(rec), 200)


@bp.post("/coatings/containers/<cid>/ship")
def ship_container(cid):
    auth(("ProductionOperator",))
    b = body()
    order_id = v_str(b, "order_id")
    rec = store.containers.get(cid)
    if rec is None:
        raise not_found()
    order = store.orders.get(order_id)
    if order is None:
        raise not_found()
    if rec["status"] != "IN_STOCK":
        raise invalid_state("Container is not IN_STOCK")
    if order["status"] not in ("PLACED", "SCHEDULED", "IN_PRODUCTION"):
        raise invalid_state("Order state does not permit shipment")
    # gate 7: VOC compliance for (category, destination, ship date, container size)
    batch = store.batches.get(rec["batch_id"])
    if batch is None:
        raise not_found()
    ship_date = now().date()
    eligible = []
    for rule in store.voc_rules.values():
        if rule["status"] != "ACTIVE":
            continue
        if rule["category"] != batch["product_category"]:
            continue
        if rule["state_code"] not in (order["destination_state_code"], "*"):
            continue
        if rule["_from_d"] > ship_date:
            continue
        if rule["_to_d"] is not None and ship_date >= rule["_to_d"]:
            continue
        eligible.append(rule)
    if not eligible:
        raise unprocessable("ERR_VOC_RULE_MISSING", "No ACTIVE VOC rule covers this shipment")
    size_liters = rec["size_liters"]
    filtered = [
        r
        for r in eligible
        if not (r["exempt_container_l"] is not None and size_liters <= D(r["exempt_container_l"]))
    ]
    if filtered:
        limit = min(D(r["max_voc_gpl"]) for r in filtered)
        voc = batch["voc_actual_gpl"]
        if voc is None or voc > limit:
            raise unprocessable("ERR_VOC_LIMIT_EXCEEDED", "Batch VOC exceeds the resolved limit")
    rec["status"] = "SHIPPED"
    rec["order_id"] = order_id
    rec["destination_state_code"] = order["destination_state_code"]
    rec["shipped_at"] = now()
    touch(rec)
    # fulfillment bubble-up (volume-based)
    if order["status"] in ("PLACED", "IN_PRODUCTION"):
        if shipped_volume_gal(order_id) >= order_line_gallons(order):
            order["status"] = "FULFILLED"
            touch(order)
    return success(ser_container(rec), 200)


@bp.post("/coatings/containers/<cid>/mark-freeze-exposure")
def mark_freeze_exposure(cid):
    auth(("ProductionOperator",))
    rec = store.containers.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] not in ("IN_STOCK", "SHIPPED", "RETURNED"):
        raise invalid_state("Freeze exposure cannot be recorded in this state")
    rec["freeze_exposure_count"] += 1
    touch(rec)
    return success(ser_container(rec), 200)


@bp.post("/coatings/containers/<cid>/customer-return")
def customer_return(cid):
    auth(("ProductionOperator",))
    rec = store.containers.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] != "SHIPPED":
        raise invalid_state("Container is not SHIPPED")
    rec["status"] = "RETURNED"
    touch(rec)
    return success(ser_container(rec), 200)
