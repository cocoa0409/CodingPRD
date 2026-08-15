"""Equipment order endpoints: manual change-order creation (budget-checked),
procurement lifecycle (mark-ordered, receive, cancel)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    pagination_args,
    paginate,
    req_int,
    req_str,
    require_role,
)
from response import success
from serializers import ser_equipment_order
from services.core import (
    CHANGE_ORDER_FLOOR_CENTS,
    children_of,
    next_order_seq,
    recompute_work_order,
)

bp = Blueprint("equipment_orders", __name__)


def _get_order(equipmentOrderId):
    o = db.equipment_orders.get(equipmentOrderId)
    if o is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Equipment order not found")
    return o


@bp.post("/avionics/equipment-orders")
def create_equipment_order():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    work_order_id = req_str(b, "work_order_id")
    part_number = req_str(b, "part_number")
    description = req_str(b, "description")
    quantity = req_int(b, "quantity")
    if quantity < 1:
        errors.raise_err(errors.ERR_VALIDATION, "quantity must be at least 1")
    unit_price_cents = req_int(b, "unit_price_cents")
    if unit_price_cents <= 0:
        errors.raise_err(errors.ERR_VALIDATION, "unit_price_cents must be greater than 0")
    lead_time_days = req_int(b, "lead_time_days")
    if lead_time_days < 0:
        errors.raise_err(errors.ERR_VALIDATION, "lead_time_days must be zero or more")

    # existence (priority 4)
    wo = db.work_orders.get(work_order_id)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")

    # lineage (priority 8): manual change orders only once approved
    if wo.status not in ("APPROVED", "PARTS_PENDING"):
        errors.raise_err(
            errors.ERR_WORK_ORDER_NOT_APPROVED,
            "Work order must be APPROVED or PARTS_PENDING for manual equipment orders",
        )

    # budget (priority 10): committed spend must stay within
    # max(110% of the approved design's equipment subtotal, 250000 cents)
    approved = [
        d for d in children_of(db.panel_designs, wo.id) if d.status == "APPROVED"
    ]
    approved_subtotal = (
        sum(
            line["quantity"] * line["unit_price_cents"] for line in approved[0].equipment_list
        )
        if approved
        else 0
    )
    bound = max(Decimal(approved_subtotal) * Decimal("1.1"), Decimal(CHANGE_ORDER_FLOOR_CENTS))
    committed = sum(
        o.quantity * o.unit_price_cents
        for o in children_of(db.equipment_orders, wo.id)
        if o.status != "CANCELLED"
    ) + quantity * unit_price_cents
    if Decimal(committed) > bound:
        errors.raise_err(
            errors.ERR_BUDGET_EXCEEDED,
            "Committed parts spend would exceed the change-order budget",
        )

    o = db.new_entity(
        work_order_id=wo.id,
        seq=next_order_seq(wo.id),
        source="MANUAL",
        source_design_revision=None,
        part_number=part_number,
        description=description,
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        lead_time_days=lead_time_days,
        ordered_at=None,
        promised_date=None,
        received_at=None,
        status="PLANNED",
    )
    db.equipment_orders[o.id] = o
    # cascade: APPROVED -> PARTS_PENDING when a manual line is added
    if wo.status == "APPROVED":
        wo.status = "PARTS_PENDING"
        touch(wo)
    recompute_work_order(wo)
    return success(ser_equipment_order(o), 201)


@bp.get("/avionics/equipment-orders/<equipmentOrderId>")
def get_equipment_order(equipmentOrderId):
    authenticate()
    return success(ser_equipment_order(_get_order(equipmentOrderId)), 200)


@bp.get("/avionics/equipment-orders")
def list_equipment_orders():
    authenticate()
    limit, offset = pagination_args()
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    items = sorted(db.equipment_orders.values(), key=lambda o: (o._seq, o.seq))
    if work_order_id is not None:
        items = [o for o in items if o.work_order_id == work_order_id]
    if status is not None:
        items = [o for o in items if o.status == status]
    page, meta = paginate([ser_equipment_order(o) for o in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/equipment-orders/<equipmentOrderId>/mark-ordered")
def mark_ordered(equipmentOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    o = _get_order(equipmentOrderId)
    if o.status != "PLANNED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a PLANNED order can be marked ordered")
    o.ordered_at = clock.now()
    o.promised_date = o.ordered_at + timedelta(days=o.lead_time_days)
    o.status = "ORDERED"
    touch(o)
    return success(ser_equipment_order(o), 200)


@bp.post("/avionics/equipment-orders/<equipmentOrderId>/receive")
def receive(equipmentOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    o = _get_order(equipmentOrderId)
    if o.status != "ORDERED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only an ORDERED order can be received")
    o.received_at = clock.now()
    o.status = "RECEIVED"
    touch(o)
    recompute_work_order(db.work_orders[o.work_order_id])
    return success(ser_equipment_order(o), 200)


@bp.post("/avionics/equipment-orders/<equipmentOrderId>/cancel")
def cancel_order(equipmentOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    o = _get_order(equipmentOrderId)
    if o.status not in ("PLANNED", "ORDERED"):
        errors.raise_err(
            errors.ERR_INVALID_STATE, "Only a PLANNED or ORDERED order can be cancelled"
        )
    o.status = "CANCELLED"
    touch(o)
    recompute_work_order(db.work_orders[o.work_order_id])
    return success(ser_equipment_order(o), 200)
