"""Liquidation order endpoints (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_property_or_404, get_order_or_404,
    recompute_report_totals,
)

bp = Blueprint("liquidation", __name__)

EXECUTION_GRACE_DAYS = 60


def order_view(o):
    return {
        "id": o["id"],
        "property_id": o["property_id"],
        "liquidation_fee_cents": o["liquidation_fee_cents"],
        "execution_price_cents_per_share": o["execution_price_cents_per_share"],
        "executed_date": o["executed_date"].isoformat() if o["executed_date"] else None,
        "settled_date": o["settled_date"].isoformat() if o["settled_date"] else None,
        "gross_proceeds_cents": o["gross_proceeds_cents"],
        "net_proceeds_cents": o["net_proceeds_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _detail_for_property(prop_id):
    return next(
        (d for d in db.securities_details.values() if d["property_id"] == prop_id),
        None,
    )


def _accepted_report_for_property(prop_id):
    """The ACCEPTED report carrying a non-REMOVED line for this property."""
    for line in db.line_items.values():
        if line["property_id"] != prop_id or line["status"] not in ("INCLUDED", "FINAL"):
            continue
        report = db.reports.get(line["report_id"])
        if report is not None and report["status"] == "ACCEPTED":
            return report
    return None


@bp.post("/escheatment/liquidation-orders")
def create_order():
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    data = mw.body_json()
    property_id = mw.req_string(data, "property_id")
    fee = mw.req_int(data, "liquidation_fee_cents", min_value=0)
    prop = get_property_or_404(property_id)
    if prop["status"] != "REPORTED":
        raise_error(
            errors.ERR_PROPERTY_NOT_REPORTED,
            "Liquidation request requires the property to be REPORTED",
        )
    if prop["property_type"] != "BROKERAGE_SHARES":
        raise_error(
            errors.ERR_NOT_SECURITIES_PROPERTY,
            "Liquidation request requires a BROKERAGE_SHARES property",
        )
    if _detail_for_property(prop["id"]) is None:
        raise_error(
            errors.ERR_SECURITIES_DETAIL_REQUIRED,
            "The property has no securities detail",
        )
    for existing in db.liquidation_orders.values():
        if existing["property_id"] == prop["id"] and existing["status"] in ("REQUESTED", "EXECUTED"):
            raise_error(
                errors.ERR_DUPLICATE_ACTIVE_LIQUIDATION,
                "A non-terminal liquidation order already exists for this property",
            )
    order = new_entity({
        "property_id": prop["id"],
        "liquidation_fee_cents": fee,
        "execution_price_cents_per_share": None,
        "executed_date": None,
        "settled_date": None,
        "gross_proceeds_cents": None,
        "net_proceeds_cents": None,
        "status": "REQUESTED",
    })
    db.liquidation_orders[order["id"]] = order
    return resp.success(order_view(order), "object", 201)


@bp.get("/escheatment/liquidation-orders/<orderId>")
def get_order(orderId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    order = get_order_or_404(orderId)
    return resp.success(order_view(order), "object", 200)


@bp.get("/escheatment/properties/<propertyId>/liquidation-orders")
def list_orders_for_property(propertyId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    prop = get_property_or_404(propertyId)
    limit, offset = mw.pagination_params()
    items = [o for o in db.liquidation_orders.values() if o["property_id"] == prop["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([order_view(o) for o in page], "array", 200, pagination=meta)


@bp.post("/escheatment/liquidation-orders/<orderId>/execute")
def execute_order(orderId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    data = mw.body_json()
    exec_price = mw.req_int(data, "execution_price_cents_per_share", min_value=0)
    order = get_order_or_404(orderId)
    if order["status"] != "REQUESTED":
        raise_error(
            errors.ERR_LIQUIDATION_INVALID_STATE,
            "Execute requires the order to be REQUESTED",
        )
    prop = get_property_or_404(order["property_id"])
    report = _accepted_report_for_property(prop["id"])
    if report is not None:
        if clock.today() > report["due_date"] + timedelta(days=EXECUTION_GRACE_DAYS):
            raise_error(
                errors.ERR_LIQUIDATION_WINDOW_VIOLATION,
                "Execution is later than the containing report's due_date + 60 days",
            )
    detail = _detail_for_property(prop["id"])
    if detail is None:
        raise_error(errors.ERR_SECURITIES_DETAIL_REQUIRED, "The property has no securities detail")
    gross = exec_price * detail["shares_quantity"]
    if order["liquidation_fee_cents"] > gross + detail["accrued_dividends_cents"]:
        raise_error(
            errors.ERR_LIQUIDATION_FEE_EXCEEDS_GROSS,
            "liquidation_fee_cents exceeds execution gross plus accrued dividends",
        )
    order["execution_price_cents_per_share"] = exec_price
    order["executed_date"] = clock.today()
    order["gross_proceeds_cents"] = gross
    order["status"] = "EXECUTED"
    touch(order)
    detail["status"] = "EXECUTION_PENDING"
    detail["pending_execution_price_cents"] = exec_price
    touch(detail)
    return resp.success(order_view(order), "object", 200)


@bp.post("/escheatment/liquidation-orders/<orderId>/settle")
def settle_order(orderId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    mw.body_json(required=False)
    order = get_order_or_404(orderId)
    if order["status"] != "EXECUTED":
        raise_error(
            errors.ERR_LIQUIDATION_INVALID_STATE,
            "Settle requires the order to be EXECUTED",
        )
    prop = get_property_or_404(order["property_id"])
    detail = _detail_for_property(prop["id"])
    dividends = detail["accrued_dividends_cents"] if detail else 0
    net = max(0, order["gross_proceeds_cents"] - order["liquidation_fee_cents"] + dividends)
    order["net_proceeds_cents"] = net
    order["settled_date"] = clock.today()
    order["status"] = "SETTLED"
    touch(order)

    # Cascade hop 2: the INCLUDED report line for this property -> FINAL.
    for line in db.line_items.values():
        if line["property_id"] != prop["id"] or line["status"] != "INCLUDED":
            continue
        line["status"] = "FINAL"
        line["final_value_cents"] = net
        touch(line)
        # Cascade hop 3: report recomputes total_final_cents (provisional unchanged).
        report = db.reports.get(line["report_id"])
        if report is not None:
            recompute_report_totals(report, bump=True)
            # Cascade hop 4: PENDING remittances recompute variance lazily at
            # confirm; refresh the staged value for readers now.
            for rem in db.remittances.values():
                if rem["report_id"] == report["id"] and rem["status"] == "PENDING":
                    rem["variance_cents"] = rem["amount_cents"] - report["total_final_cents"]
                    touch(rem)
    # Cascade tail: detail -> LIQUIDATED, pending price cleared.
    if detail is not None:
        detail["status"] = "LIQUIDATED"
        detail["pending_execution_price_cents"] = None
        touch(detail)
    return resp.success(order_view(order), "object", 200)


@bp.post("/escheatment/liquidation-orders/<orderId>/cancel")
def cancel_order(orderId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    mw.body_json(required=False)
    order = get_order_or_404(orderId)
    if order["status"] not in ("REQUESTED", "EXECUTED"):
        raise_error(
            errors.ERR_LIQUIDATION_INVALID_STATE,
            "Cancel requires the order to be REQUESTED or EXECUTED",
        )
    was_executed = order["status"] == "EXECUTED"
    order["status"] = "CANCELLED"
    touch(order)
    if was_executed:
        # Compensation: detail EXECUTION_PENDING -> REGISTERED, pending price
        # cleared; the report line's provisional value and status are unchanged.
        detail = _detail_for_property(order["property_id"])
        if detail is not None and detail["status"] == "EXECUTION_PENDING":
            detail["status"] = "REGISTERED"
            detail["pending_execution_price_cents"] = None
            touch(detail)
    return resp.success(order_view(order), "object", 200)
