"""Transfer order endpoints: create, get, list, activate (the
contamination-controlled moment), pause, complete, cancel."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FACILITY_SUSPENDED,
    ERR_POSTURE_ELEVATED_HAZMAT, ERR_CAR_HELD, ERR_CONTAMINATION_RISK,
    ERR_CAR_NOT_SPOTTED, ERR_CAR_BUSY, ERR_EQUIPMENT_NOT_AVAILABLE,
    ERR_NOTHING_TO_COMPLETE, ERR_CREDIT_HOLD,
)
from middleware import auth_context, require_role, require_ownership, ALL_ROLES
from response import ok, paginated
from util import dec, round3
from validate import body, req_str, req_pos_num

bp = Blueprint("transfer_orders", __name__)


def _get_order_or_404(transfer_order_id):
    order = STORE.transfer_orders.get(transfer_order_id)
    if order is None:
        raise_err(ERR_NOT_FOUND, "transfer order id does not exist")
    return order


def _order_customer_id(order):
    return STORE.railcars[order["railcar_id"]]["customer_id"]


@bp.route("/transload/transfer-orders", methods=["POST"])
def create_transfer_order():
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    data = body()
    # Priority 3: body FK ids resolve.
    for field, table, label in (
        ("railcar_id", STORE.railcars, "railcar"),
        ("equipment_id", STORE.equipment, "equipment"),
    ):
        raw = data.get(field)
        if isinstance(raw, str) and raw not in table:
            raise_err(ERR_NOT_FOUND, "%s id does not exist" % label)
    railcar_id = req_str(data, "railcar_id")
    equipment_id = req_str(data, "equipment_id")
    quantity_planned_tons = round3(req_pos_num(data, "quantity_planned_tons"))
    order = new_entity(STORE.transfer_orders, {
        "railcar_id": railcar_id,
        "equipment_id": equipment_id,
        "quantity_planned_tons": quantity_planned_tons,
        "quantity_completed_tons": 0.0,
        "risk_score": 0,
        "status": "PLANNED",
    })
    return ok(public(order), status=201)


@bp.route("/transload/transfer-orders/<tid>", methods=["GET"])
def get_transfer_order(tid):
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    order = _get_order_or_404(tid)
    require_ownership(user_id, role, _order_customer_id(order))
    return ok(public(order))


@bp.route("/transload/transfer-orders", methods=["GET"])
def list_transfer_orders():
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    railcar_id = request.args.get("railcar_id")
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    items = sorted(STORE.transfer_orders.values(), key=lambda o: (o["created_at"], o["_seq"]))
    if role == "CustomerRep":
        items = [o for o in items if _order_customer_id(o) == user_id]
    if railcar_id is not None:
        items = [o for o in items if o["railcar_id"] == railcar_id]
    if equipment_id is not None:
        items = [o for o in items if o["equipment_id"] == equipment_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginated(items)
    return ok([public(o) for o in page], pagination=meta)


@bp.route("/transload/transfer-orders/<tid>/activate", methods=["POST"])
def activate_transfer_order(tid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    order = _get_order_or_404(tid)
    # Priority 5: state (PLANNED -> ACTIVE; PAUSED -> ACTIVE resume).
    if order["status"] not in ("PLANNED", "PAUSED"):
        raise_err(ERR_INVALID_STATE, "transfer order is not PLANNED or PAUSED")
    car = STORE.railcars[order["railcar_id"]]
    eq = STORE.equipment[order["equipment_id"]]
    product = STORE.products[car["product_id"]]
    # Priority 7: facility posture gates.
    if STORE.posture == "SUSPENDED":
        raise_err(ERR_FACILITY_SUSPENDED, "facility safety posture is SUSPENDED")
    if STORE.posture == "ELEVATED" and product["hazard_class"] == "HAZARDOUS":
        raise_err(ERR_POSTURE_ELEVATED_HAZMAT, "ELEVATED posture blocks HAZARDOUS transfers")
    # Priority 8: car-level safety hold.
    if car["hold_status"] != "NONE":
        raise_err(ERR_CAR_HELD, "railcar is on SAFETY_HOLD")
    # Priority 9: contamination risk.
    risk = domain.contamination_risk_score(eq, product)
    if risk >= domain.BLOCK_THRESHOLD:
        raise_err(ERR_CONTAMINATION_RISK, "contamination risk score blocks activation")
    # Priority 11: equipment/scale constraints.
    if car["placement_status"] not in ("SPOTTED", "IN_TRANSFER"):
        raise_err(ERR_CAR_NOT_SPOTTED, "railcar is not SPOTTED or IN_TRANSFER")
    if eq["status"] != "AVAILABLE":
        raise_err(ERR_EQUIPMENT_NOT_AVAILABLE, "equipment is not AVAILABLE")
    for other in STORE.transfer_orders.values():
        if other["id"] == order["id"] or other["status"] != "ACTIVE":
            continue
        if other["railcar_id"] == car["id"]:
            raise_err(ERR_CAR_BUSY, "another transfer order is ACTIVE on this railcar")
        if other["equipment_id"] == eq["id"]:
            raise_err(ERR_EQUIPMENT_NOT_AVAILABLE, "equipment is bound to another ACTIVE transfer")
    # Priority 12: credit hold.
    cust = STORE.customers[car["customer_id"]]
    if cust["credit_standing"] == "CREDIT_HOLD":
        raise_err(ERR_CREDIT_HOLD, "customer is on CREDIT_HOLD")
    order["risk_score"] = risk
    eq["status"] = "IN_USE"
    eq["last_product_id"] = car["product_id"]
    touch(eq)
    if car["placement_status"] == "SPOTTED":
        car["placement_status"] = "IN_TRANSFER"
        touch(car)
    order["status"] = "ACTIVE"
    touch(order)
    return ok(public(order))


@bp.route("/transload/transfer-orders/<tid>/pause", methods=["POST"])
def pause_transfer_order(tid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    order = _get_order_or_404(tid)
    if order["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "transfer order is not ACTIVE")
    eq = STORE.equipment[order["equipment_id"]]
    if eq["status"] == "IN_USE":
        eq["status"] = "AVAILABLE"
        touch(eq)
    car = STORE.railcars[order["railcar_id"]]
    if car["placement_status"] == "IN_TRANSFER":
        car["placement_status"] = "SPOTTED"
        touch(car)
    order["status"] = "PAUSED"
    touch(order)
    return ok(public(order))


@bp.route("/transload/transfer-orders/<tid>/complete", methods=["POST"])
def complete_transfer_order(tid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    order = _get_order_or_404(tid)
    if order["status"] not in ("ACTIVE", "PAUSED"):
        raise_err(ERR_INVALID_STATE, "transfer order is not ACTIVE or PAUSED")
    if dec(order["quantity_completed_tons"]) <= 0:
        raise_err(ERR_NOTHING_TO_COMPLETE, "nothing has been certified to complete")
    domain.complete_transfer_order(order, release_equipment=(order["status"] == "ACTIVE"))
    return ok(public(order))


@bp.route("/transload/transfer-orders/<tid>/cancel", methods=["POST"])
def cancel_transfer_order(tid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    order = _get_order_or_404(tid)
    if order["status"] not in ("PLANNED", "PAUSED"):
        raise_err(ERR_INVALID_STATE, "transfer order is not PLANNED or PAUSED")
    order["status"] = "CANCELLED"
    touch(order)
    return ok(public(order))
