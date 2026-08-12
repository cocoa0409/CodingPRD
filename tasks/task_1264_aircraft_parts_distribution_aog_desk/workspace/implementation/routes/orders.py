"""SalesOrder and OrderLine endpoints."""

from flask import Blueprint, request

from auth import require_roles, ALL_BUSINESS
from calc import TRACE_RANK
from db import store
from errors import (ApiError, ERR_INVALID_STATE, ERR_ORDER_NOT_FOUND,
                    ERR_ORDER_LINE_NOT_FOUND, ERR_UNIT_NOT_FOUND,
                    ERR_UNIT_NOT_AVAILABLE, ERR_LINE_ALREADY_ALLOCATED,
                    ERR_CONDITION_NOT_ACCEPTABLE, ERR_TRACE_DOC_INSUFFICIENT)
from helpers import (touch, get_or_404, bump_unit_status, ser_order,
                     ser_order_line, sort_asc, order_lines_of)
from util import (success, get_body, page_params, paged, as_enum, bad,
                  req_present)

bp = Blueprint("orders", __name__)

DECISIONS = {"CLEARED", "EXPORT_HELD", "BLOCKED"}


def _order_customer(order):
    return order["customer_id"]


def _line_customer(line):
    order = store["orders"].get(line["order_id"])
    return order["customer_id"] if order else None


@bp.get("/aog/orders")
def list_orders():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["orders"].values())
    if role == "CustomerContact":
        recs = [o for o in recs if o["customer_id"] == uid]
    q = request.args
    if q.get("quote_id") is not None:
        recs = [o for o in recs if o["quote_id"] == q.get("quote_id")]
    if q.get("customer_id") is not None:
        recs = [o for o in recs if o["customer_id"] == q.get("customer_id")]
    if q.get("fulfillment_status") is not None:
        recs = [o for o in recs
                if o["fulfillment_status"] == q.get("fulfillment_status")]
    return paged([ser_order(o) for o in sort_asc(recs)], limit, offset)


@bp.get("/aog/orders/<oid>")
def get_order(oid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("orders", oid, ERR_ORDER_NOT_FOUND, "SalesOrder")
    return success(ser_order(rec))


@bp.post("/aog/orders/<oid>/compliance-decision")
def compliance_decision(oid):
    require_roles("ComplianceOfficer")
    order = get_or_404("orders", oid, ERR_ORDER_NOT_FOUND, "SalesOrder")
    body = get_body()
    decision = as_enum(req_present(body, "decision"), "decision", DECISIONS)
    current = order["compliance_status"]
    allowed = {
        "PENDING_SCREENING": {"CLEARED", "EXPORT_HELD"},
        "EXPORT_HELD": {"CLEARED", "BLOCKED"},
    }
    if decision not in allowed.get(current, set()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"compliance decision {decision} not permitted from "
                       f"{current}")
    if decision == "BLOCKED":
        # release every allocated line; revert fulfillment
        for line in order_lines_of(order["id"]):
            if line["allocation_status"] == "ALLOCATED":
                unit = store["units"].get(line["allocated_unit_id"])
                if unit is not None and unit["status"] == "ALLOCATED":
                    bump_unit_status(unit, "AVAILABLE")
                line["allocation_status"] = "PENDING"
                line["allocated_unit_id"] = None
                touch(line)
        if order["fulfillment_status"] == "ALLOCATED":
            order["fulfillment_status"] = "PENDING_ALLOCATION"
    order["compliance_status"] = decision
    touch(order)
    return success(ser_order(order))


@bp.get("/aog/order-lines")
def list_order_lines():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["order_lines"].values())
    if role == "CustomerContact":
        recs = [l for l in recs if _line_customer(l) == uid]
    q = request.args
    if q.get("order_id") is not None:
        recs = [l for l in recs if l["order_id"] == q.get("order_id")]
    if q.get("part_id") is not None:
        recs = [l for l in recs if l["part_id"] == q.get("part_id")]
    if q.get("allocated_unit_id") is not None:
        recs = [l for l in recs
                if l["allocated_unit_id"] == q.get("allocated_unit_id")]
    if q.get("allocation_status") is not None:
        recs = [l for l in recs
                if l["allocation_status"] == q.get("allocation_status")]
    return paged([ser_order_line(l) for l in sort_asc(recs)], limit, offset)


@bp.get("/aog/order-lines/<lid>")
def get_order_line(lid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("order_lines", lid, ERR_ORDER_LINE_NOT_FOUND,
                     "OrderLine")
    return success(ser_order_line(rec))


def _request_of_line(line):
    order = store["orders"].get(line["order_id"])
    if order is None:
        return None
    quote = store["quotes"].get(order["quote_id"])
    if quote is None:
        return None
    return store["requests"].get(quote["aog_request_id"])


@bp.post("/aog/order-lines/<lid>/allocate")
def allocate_line(lid):
    require_roles("WarehouseOperator")
    line = get_or_404("order_lines", lid, ERR_ORDER_LINE_NOT_FOUND,
                      "OrderLine")
    body = get_body()
    unit_id = body.get("unit_id")
    if unit_id is not None and not isinstance(unit_id, str):
        bad("unit_id must be a string")
    order = store["orders"][line["order_id"]]
    if order["fulfillment_status"] not in ("PENDING_ALLOCATION", "ALLOCATED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Order fulfillment status does not permit allocation")
    aog = _request_of_line(line)
    if unit_id is not None:
        unit = get_or_404("units", unit_id, ERR_UNIT_NOT_FOUND,
                          "InventoryUnit")
    else:
        pin = aog["reserved_unit_id"] if aog else None
        if not pin:
            raise ApiError(ERR_UNIT_NOT_AVAILABLE, 409,
                           "No reserving unit is pinned for this request")
        unit = store["units"].get(pin)
        if unit is None:
            raise ApiError(ERR_UNIT_NOT_AVAILABLE, 409,
                           "Pinned unit not found")
    # merchandise checks (priority 7)
    if unit["condition"] != line["condition_required"]:
        raise ApiError(ERR_CONDITION_NOT_ACCEPTABLE, 422,
                       "Unit condition does not equal condition_required")
    if aog is not None and TRACE_RANK[unit["trace_doc_level"]] < \
            TRACE_RANK[aog["min_trace_doc"]]:
        raise ApiError(ERR_TRACE_DOC_INSUFFICIENT, 422,
                       "Unit trace_doc_level below the required minimum")
    # constraint checks (priority 9)
    if line["allocation_status"] == "ALLOCATED":
        raise ApiError(ERR_LINE_ALREADY_ALLOCATED, 409,
                       "Line is already allocated")
    pinned_here = (aog is not None
                   and aog.get("reserved_unit_id") == unit["id"]
                   and unit["status"] == "RESERVED"
                   and unit["reserved_by_request_id"] == aog["id"])
    if unit["part_id"] != line["part_id"]:
        raise ApiError(ERR_UNIT_NOT_AVAILABLE, 409,
                       "Unit is not of the line's part")
    if not pinned_here and unit["status"] != "AVAILABLE":
        raise ApiError(ERR_UNIT_NOT_AVAILABLE, 409,
                       "Unit is not AVAILABLE or pinned by this request")
    # transition: RESERVED -> ALLOCATED or AVAILABLE -> ALLOCATED
    if unit["status"] == "RESERVED":
        unit["reserved_by_request_id"] = None
    bump_unit_status(unit, "ALLOCATED")
    if pinned_here and aog is not None and aog.get("reserved_unit_id"):
        aog["reserved_unit_id"] = None
        touch(aog)
    line["allocated_unit_id"] = unit["id"]
    line["allocation_status"] = "ALLOCATED"
    touch(line)
    # auto-flip the order when every line is allocated
    lines = order_lines_of(order["id"])
    if all(l["allocation_status"] == "ALLOCATED" for l in lines):
        if order["fulfillment_status"] == "PENDING_ALLOCATION":
            order["fulfillment_status"] = "ALLOCATED"
            touch(order)
    return success(ser_order_line(line))


@bp.post("/aog/order-lines/<lid>/release")
def release_line(lid):
    require_roles("WarehouseOperator")
    line = get_or_404("order_lines", lid, ERR_ORDER_LINE_NOT_FOUND,
                      "OrderLine")
    order = store["orders"][line["order_id"]]
    if order["fulfillment_status"] in ("SHIPPED", "DELIVERED", "CLOSED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Order fulfillment status does not permit release")
    if line["allocation_status"] == "ALLOCATED":
        unit = store["units"].get(line["allocated_unit_id"])
        if unit is not None and unit["status"] == "ALLOCATED":
            bump_unit_status(unit, "AVAILABLE")
        line["allocation_status"] = "PENDING"
        line["allocated_unit_id"] = None
        if order["fulfillment_status"] == "ALLOCATED":
            order["fulfillment_status"] = "PENDING_ALLOCATION"
            touch(order)
    else:
        # before allocation: release the still-RESERVED pinned unit
        aog = _request_of_line(line)
        if aog is not None and aog.get("reserved_unit_id"):
            unit = store["units"].get(aog["reserved_unit_id"])
            if unit is not None and unit["status"] == "RESERVED":
                bump_unit_status(unit, "AVAILABLE")
                unit["reserved_by_request_id"] = None
            aog["reserved_unit_id"] = None
            touch(aog)
    touch(line)
    return success(ser_order_line(line))
