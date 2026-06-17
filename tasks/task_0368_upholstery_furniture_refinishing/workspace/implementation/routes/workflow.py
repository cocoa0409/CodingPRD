"""Work order lifecycle: approve / decline / request-revision (Customer),
finish-production / complete / cancel (ShopManager), payments listing."""
from flask import Blueprint

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles, require_owner
from helpers import (base_record, get_body, require_int, get_work_order_or_404,
                     parse_pagination, paginate, touch, serialize, serialize_list)
from response import ok_object, ok_array
import calculations as calc
from services import (order_line_items, order_material_orders,
                      reconcile_balance_due, reconcile_materials_committed,
                      recompute_shop_day_status)

bp = Blueprint("workflow", __name__)


def _record_payment(wo_id, kind, amount_cents, refund_destination="ORIGINAL"):
    rec = base_record(common=True)
    rec.update({
        "work_order_id": wo_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "refund_destination": refund_destination,
        "status": "RECORDED",
    })
    db.payments[rec["id"]] = rec
    return rec


def _active_estimate(wid):
    for e in db.estimates.values():
        if e["work_order_id"] == wid and e["status"] == "ACTIVE":
            return e
    return None


def _approved_estimate(wid):
    for e in db.estimates.values():
        if e["work_order_id"] == wid and e["status"] == "APPROVED":
            return e
    return None


# --------------------------------------------------------------------------
# Customer: request-revision
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/request-revision")
def request_revision(wid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    wo = get_work_order_or_404(wid)
    require_owner(user_id, wo)
    if wo["status"] != "AWAITING_APPROVAL":
        raise err(errors.ERR_INVALID_STATE,
                  "Revision can be requested only while AWAITING_APPROVAL")
    wo["status"] = "REVISION_REQUESTED"
    touch(wo)
    return ok_object(serialize(wo), 200)


# --------------------------------------------------------------------------
# Customer: approve (deposit gate + turnaround)
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/approve")
def approve(wid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    wo = get_work_order_or_404(wid)
    require_owner(user_id, wo)
    body = get_body()
    expected_version = require_int(body, "expected_work_order_version")
    deposit = require_int(body, "deposit_amount_cents")

    if wo["status"] != "AWAITING_APPROVAL":
        raise err(errors.ERR_INVALID_STATE, "Approval requires AWAITING_APPROVAL")
    if expected_version != wo["version"]:
        raise err(errors.ERR_STALE_WORK_ORDER_VERSION,
                  "expected_work_order_version does not match")
    required = calc.required_deposit(wo["estimate_total_cents"])
    if deposit < required:
        raise err(errors.ERR_DEPOSIT_TOO_LOW,
                  "Deposit below the required minimum")

    active = _active_estimate(wid)
    if active is not None:
        active["status"] = "APPROVED"
        touch(active)

    line_items = order_line_items(wid)
    wo["promised_turnaround_days"] = calc.turnaround_days(
        line_items, wo["rush_requested"])

    _record_payment(wid, "DEPOSIT", deposit)
    wo["amount_paid_cents"] = wo["amount_paid_cents"] + deposit
    reconcile_balance_due(wo)
    wo["status"] = "APPROVED"
    touch(wo)  # increments version by 1
    return ok_object(serialize(wo), 200)


# --------------------------------------------------------------------------
# Customer: decline
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/decline")
def decline(wid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    wo = get_work_order_or_404(wid)
    require_owner(user_id, wo)
    if wo["status"] != "AWAITING_APPROVAL":
        raise err(errors.ERR_INVALID_STATE, "Decline requires AWAITING_APPROVAL")
    active = _active_estimate(wid)
    if active is not None:
        active["status"] = "DECLINED"
        touch(active)
    wo["status"] = "DECLINED"
    touch(wo)
    return ok_object(serialize(wo), 200)


# --------------------------------------------------------------------------
# ShopManager: finish-production (compute final invoice)
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/finish-production")
def finish_production(wid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    wo = get_work_order_or_404(wid)
    if wo["status"] != "IN_PRODUCTION":
        raise err(errors.ERR_INVALID_STATE, "finish-production requires IN_PRODUCTION")
    # The PRODUCTION fulfillment leg must be COMPLETED (priority 23).
    prod_legs = [fl for fl in db.fulfillment_legs.values()
                 if fl["work_order_id"] == wid and fl["kind"] == "PRODUCTION"
                 and fl["status"] != "CANCELLED"]
    if not any(fl["status"] == "COMPLETED" for fl in prod_legs):
        raise err(errors.ERR_PRODUCTION_NOT_COMPLETE,
                  "PRODUCTION fulfillment leg is not COMPLETED")

    line_items = order_line_items(wid)
    received = [mo for mo in order_material_orders(wid) if mo["status"] == "RECEIVED"]
    approved = _approved_estimate(wid)
    rush_surcharge = approved["rush_surcharge_cents"] if approved else 0
    wo["final_invoice_cents"] = calc.final_invoice(line_items, received, rush_surcharge)
    reconcile_balance_due(wo)
    wo["status"] = "READY_FOR_FULFILLMENT"
    touch(wo)
    return ok_object(serialize(wo), 200)


# --------------------------------------------------------------------------
# ShopManager: complete (settlement)
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/complete")
def complete(wid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    wo = get_work_order_or_404(wid)
    body = get_body()
    settlement = require_int(body, "settlement_amount_cents")

    if wo["status"] != "READY_FOR_FULFILLMENT":
        raise err(errors.ERR_INVALID_STATE, "complete requires READY_FOR_FULFILLMENT")
    # A PICKUP or DELIVERY leg must be COMPLETED.
    has_logistics = any(
        fl["work_order_id"] == wid and fl["kind"] in ("PICKUP", "DELIVERY")
        and fl["status"] == "COMPLETED"
        for fl in db.fulfillment_legs.values()
    )
    if not has_logistics:
        raise err(errors.ERR_INVALID_STATE,
                  "A COMPLETED PICKUP or DELIVERY leg is required")
    # Settlement must exactly equal current balance_due (priority 51).
    if settlement != wo["balance_due_cents"]:
        raise err(errors.ERR_SETTLEMENT_MISMATCH,
                  "settlement_amount_cents must equal balance_due_cents")

    _record_payment(wid, "SETTLEMENT", settlement)
    wo["amount_paid_cents"] = wo["amount_paid_cents"] + settlement
    reconcile_balance_due(wo)
    from db import server_clock_iso
    wo["completed_at"] = server_clock_iso()
    wo["status"] = "COMPLETED"
    touch(wo)
    return ok_object(serialize(wo), 200)


# --------------------------------------------------------------------------
# ShopManager: cancel (compensation chain)
# --------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/cancel")
def cancel(wid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    wo = get_work_order_or_404(wid)
    body = get_body()
    expected_version = require_int(body, "expected_work_order_version")
    refund_destination = body.get("refund_destination", "ORIGINAL")
    if refund_destination is None:
        refund_destination = "ORIGINAL"
    if refund_destination not in ("ORIGINAL", "WALLET"):
        raise err(errors.ERR_INVALID_REQUEST, "refund_destination invalid")

    if wo["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise err(errors.ERR_INVALID_STATE,
                  "Cancel requires APPROVED or IN_PRODUCTION")
    if expected_version != wo["version"]:
        raise err(errors.ERR_STALE_WORK_ORDER_VERSION,
                  "expected_work_order_version does not match")

    # Cancel every still-ORDERED material order; return reserved fabric yards.
    for mo in order_material_orders(wid):
        if mo["status"] == "ORDERED":
            _release_material_order(mo)
            mo["status"] = "CANCELLED"
            touch(mo)
    reconcile_materials_committed(wo)  # lands at 0 for the remaining committed set

    # Cancel every PLANNED PRODUCTION leg; release booked capacity.
    for fl in db.fulfillment_legs.values():
        if (fl["work_order_id"] == wid and fl["kind"] == "PRODUCTION"
                and fl["status"] == "PLANNED"):
            _release_production_leg(fl)
            fl["status"] = "CANCELLED"
            touch(fl)

    # Refund every paid cent.
    refunded = wo["amount_paid_cents"]
    if refunded > 0:
        _record_payment(wid, "REFUND", refunded, refund_destination)
        if refund_destination == "WALLET":
            cust = db.customers.get(wo["customer_id"])
            if cust is not None:
                cust["store_credit_cents"] = cust["store_credit_cents"] + refunded
                touch(cust)
    wo["amount_paid_cents"] = 0
    reconcile_balance_due(wo)
    wo["status"] = "CANCELLED"
    touch(wo)  # increments version by 1
    return ok_object(serialize(wo), 200)


def _release_material_order(mo):
    """Return reserved fabric yards to stock (yard-conservation invariant)."""
    reserved = mo.get("_reserved_yards", 0)
    if reserved and mo.get("fabric_sku_id"):
        sku = db.fabric_skus.get(mo["fabric_sku_id"])
        if sku is not None:
            sku["in_stock_yards"] = sku["in_stock_yards"] + reserved
            touch(sku)
    mo["_reserved_yards"] = 0


def _release_production_leg(fl):
    """Decrement booked ShopDay hours; FULL->OPEN if applicable."""
    day = db.shop_days.get(fl.get("shop_day_id"))
    if day is None:
        return
    day["booked_hours"] = day["booked_hours"] - fl.get("_booked_hours", 0)
    touch(day)
    recompute_shop_day_status(day)
    fl["_booked_hours"] = 0


# --------------------------------------------------------------------------
# Payments listing
# --------------------------------------------------------------------------
@bp.get("/work-orders/<wid>/payments")
def list_payments(wid):
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator", "Customer"})
    limit, offset = parse_pagination()
    get_work_order_or_404(wid)
    matches = [p for p in db.payments.values() if p["work_order_id"] == wid]
    page, total = paginate(matches, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
