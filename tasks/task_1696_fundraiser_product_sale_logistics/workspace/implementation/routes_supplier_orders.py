"""SupplierOrder endpoints: create (case-pack aggregation), patch, submit,
unsubmit, acknowledge, deliver, cancel."""

from flask import Blueprint

import db
import errors
import helpers
import middleware
import services
from helpers import (
    get_campaign, get_supplier_order, new_id, now_iso, paginate, sort_created,
    req_string, req_datetime,
    serialize_supplier_order, serialize_supplier_order_line,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("supplier_orders", __name__)


def _recompute_line_cases(line):
    cases = -(-line["requested_units"] // line["case_pack_size"])  # ceil
    line["ordered_cases"] = cases
    line["ordered_units"] = cases * line["case_pack_size"]


def _recompute_total_ordered(so):
    so["total_ordered_units"] = sum(
        ln["ordered_units"] for ln in db.supplier_order_lines.values()
        if ln["supplier_order_id"] == so["id"]
    )


@bp.post("/fundraiser/supplier-orders")
def create_supplier_order():
    middleware.require_role("FundraiserAdmin")
    body = get_body(required=True)
    campaign_id = req_string(body, "campaign_id")
    campaign = get_campaign(campaign_id)
    if campaign["status"] != "ORDERING_CLOSED":
        raise errors.err_invalid_state("Campaign must be ORDERING_CLOSED to create a supplier order")
    for so in db.supplier_orders.values():
        if so["campaign_id"] == campaign_id and so["status"] not in ("CANCELLED", "DELIVERED"):
            raise errors.err_campaign_has_active_supplier_order()

    # Aggregate demand per product over SUBMITTED/LOCKED orders
    demand = {}
    for o in db.orders.values():
        if o["campaign_id"] != campaign_id or o["status"] not in ("SUBMITTED", "LOCKED"):
            continue
        for ln in db.order_lines.values():
            if ln["order_id"] == o["id"]:
                demand[ln["product_id"]] = demand.get(ln["product_id"], 0) + ln["quantity"]

    soid = new_id()
    supplier_order = {
        "id": soid,
        "campaign_id": campaign_id,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "acknowledged_by_user_id": None,
        "delivered_by_user_id": None,
        "confirmed_delivery_date": None,
        "actual_delivery_date": None,
        "estimated_cost_cents": 0,
        "actual_cost_cents": 0,
        "total_ordered_units": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.supplier_orders[soid] = supplier_order

    # Products of the campaign (ACTIVE or DISCONTINUED) with non-zero demand
    campaign_products = [p for p in db.products.values() if p["campaign_id"] == campaign_id]
    campaign_products.sort(key=lambda p: p["created_at"])
    for product in campaign_products:
        requested = demand.get(product["id"], 0)
        if requested == 0:
            continue
        lid = new_id()
        line = {
            "id": lid,
            "supplier_order_id": soid,
            "product_id": product["id"],
            "requested_units": requested,
            "case_pack_size": product["case_pack_size"],
            "ordered_cases": 0,
            "ordered_units": 0,
            "unit_cost_estimated_cents": product["supplier_unit_cost_cents"],
            "unit_cost_actual_cents": None,
            "delivered_units": None,
            "shortage_units": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
        }
        _recompute_line_cases(line)
        db.supplier_order_lines[lid] = line
    _recompute_total_ordered(supplier_order)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_supplier_order(supplier_order), status=201)


@bp.get("/fundraiser/supplier-orders/<sid>")
def read_supplier_order(sid):
    middleware.any_role()
    so = get_supplier_order(sid)
    return success_object(serialize_supplier_order(so))


@bp.get("/fundraiser/supplier-orders/<sid>/lines")
def list_supplier_order_lines(sid):
    middleware.any_role()
    get_supplier_order(sid)
    limit, offset = parse_pagination()
    items = sort_created([ln for ln in db.supplier_order_lines.values() if ln["supplier_order_id"] == sid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_supplier_order_line(ln) for ln in page], limit, offset, total)


@bp.patch("/fundraiser/supplier-orders/<sid>")
def patch_supplier_order(sid):
    middleware.require_role("FundraiserAdmin")
    so = get_supplier_order(sid)
    body = get_body(required=True)
    if "expected_supplier_order_version" not in body or not isinstance(body.get("expected_supplier_order_version"), int) or isinstance(body.get("expected_supplier_order_version"), bool):
        raise errors.err_validation("expected_supplier_order_version is required and must be an integer")
    expected = body["expected_supplier_order_version"]
    line_adjustments = body.get("line_adjustments")
    if not isinstance(line_adjustments, list):
        raise errors.err_validation("line_adjustments must be an array")
    parsed_adjustments = []
    for item in line_adjustments:
        if not isinstance(item, dict):
            raise errors.err_validation("each line adjustment must be an object")
        # Each adjustment addresses a line either by its supplier-order-line id
        # or by the product it aggregates (one line per product per order).
        line_id = item.get("line_id")
        if not isinstance(line_id, str) or line_id == "":
            line_id = None
        product_id = item.get("product_id")
        if not isinstance(product_id, str) or product_id == "":
            product_id = None
        if line_id is None and product_id is None:
            raise errors.err_validation("line_adjustments[] requires line_id or product_id")
        units = item.get("requested_units")
        if isinstance(units, bool) or not isinstance(units, int) or units < 0:
            raise errors.err_validation("line_adjustments[].requested_units must be an integer >= 0")
        parsed_adjustments.append((line_id, product_id, units))
    # OCC (priority 7)
    if expected != so["version"]:
        raise errors.err_stale_version()
    # State (priority 8)
    if so["status"] != "DRAFT":
        raise errors.err_invalid_state("Supplier order is not DRAFT")
    # Apply adjustments
    lines_by_id = {ln["id"]: ln for ln in db.supplier_order_lines.values() if ln["supplier_order_id"] == sid}
    lines_by_product = {ln["product_id"]: ln for ln in db.supplier_order_lines.values() if ln["supplier_order_id"] == sid}
    for line_id, product_id, units in parsed_adjustments:
        ln = lines_by_id.get(line_id) if line_id is not None else lines_by_product.get(product_id)
        if ln is None:
            raise errors.err_validation("line_adjustments references an unknown line")
        ln["requested_units"] = units
        _recompute_line_cases(ln)
        helpers.touch(ln)
    _recompute_total_ordered(so)
    helpers.touch(so)
    services.recompute_campaign_totals(db.campaigns[so["campaign_id"]])
    return success_object(serialize_supplier_order(so))


@bp.post("/fundraiser/supplier-orders/<sid>/submit")
def submit_supplier_order(sid):
    user_id, _role = middleware.require_role("FundraiserAdmin")
    so = get_supplier_order(sid)
    get_body()
    if so["status"] != "DRAFT":
        raise errors.err_invalid_state("Supplier order is not DRAFT")
    lines = [ln for ln in db.supplier_order_lines.values() if ln["supplier_order_id"] == sid]
    if not lines:
        raise errors.err_no_submitted_orders()
    so["estimated_cost_cents"] = sum(ln["ordered_units"] * ln["unit_cost_estimated_cents"] for ln in lines)
    so["submitted_by_user_id"] = user_id
    so["status"] = "SUBMITTED"
    helpers.touch(so)
    services.recompute_campaign_totals(db.campaigns[so["campaign_id"]])
    return success_object(serialize_supplier_order(so))


@bp.post("/fundraiser/supplier-orders/<sid>/unsubmit")
def unsubmit_supplier_order(sid):
    middleware.require_role("FundraiserAdmin")
    so = get_supplier_order(sid)
    get_body()
    if so["status"] != "SUBMITTED":
        raise errors.err_invalid_state("Supplier order is not SUBMITTED")
    so["status"] = "DRAFT"
    helpers.touch(so)
    services.recompute_campaign_totals(db.campaigns[so["campaign_id"]])
    return success_object(serialize_supplier_order(so))


@bp.post("/fundraiser/supplier-orders/<sid>/acknowledge")
def acknowledge_supplier_order(sid):
    user_id, _role = middleware.require_role("SupplierRep")
    so = get_supplier_order(sid)
    body = get_body(required=True)
    confirmed = req_datetime(body, "confirmed_delivery_date")
    line_costs = body.get("line_costs")
    if not isinstance(line_costs, (dict, list)):
        raise errors.err_validation("line_costs must be provided")
    # Normalize to {product_id: cost}
    costs = {}
    if isinstance(line_costs, dict):
        for k, v in line_costs.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise errors.err_validation("line_costs values must be integers >= 0")
            costs[k] = v
    else:
        for item in line_costs:
            if not isinstance(item, dict):
                raise errors.err_validation("line_costs entries must be objects")
            pid = item.get("product_id")
            cost = item.get("unit_cost_actual_cents", item.get("cost_cents"))
            if not isinstance(pid, str) or isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
                raise errors.err_validation("line_costs entries require product_id and integer cost")
            if pid in costs:
                raise errors.err_validation("line_costs covers a product more than once")
            costs[pid] = cost
    if so["status"] != "SUBMITTED":
        raise errors.err_invalid_state("Supplier order is not SUBMITTED")
    lines = [ln for ln in db.supplier_order_lines.values() if ln["supplier_order_id"] == sid]
    needed = {ln["product_id"] for ln in lines}
    if set(costs.keys()) != needed:
        raise errors.err_validation("line_costs must cover every line product exactly once")
    for ln in lines:
        ln["unit_cost_actual_cents"] = costs[ln["product_id"]]
        helpers.touch(ln)
    so["confirmed_delivery_date"] = body["confirmed_delivery_date"]
    so["acknowledged_by_user_id"] = user_id
    so["status"] = "ACKNOWLEDGED"
    helpers.touch(so)
    # Auto-advance campaign ORDERING_CLOSED -> SUPPLIER_ORDERED
    campaign = db.campaigns[so["campaign_id"]]
    if campaign["status"] == "ORDERING_CLOSED":
        campaign["status"] = "SUPPLIER_ORDERED"
        helpers.touch(campaign)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_supplier_order(so))


@bp.post("/fundraiser/supplier-orders/<sid>/deliver")
def deliver_supplier_order(sid):
    user_id, _role = middleware.require_role("SupplierRep")
    so = get_supplier_order(sid)
    body = get_body(required=True)
    req_datetime(body, "actual_delivery_date")
    delivered = body.get("delivered")
    if not isinstance(delivered, (dict, list)):
        raise errors.err_validation("delivered must be provided")
    delivered_map = {}
    if isinstance(delivered, dict):
        for k, v in delivered.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise errors.err_validation("delivered values must be integers >= 0")
            delivered_map[k] = v
    else:
        for item in delivered:
            if not isinstance(item, dict):
                raise errors.err_validation("delivered entries must be objects")
            pid = item.get("product_id")
            units = item.get("delivered_units")
            if not isinstance(pid, str) or isinstance(units, bool) or not isinstance(units, int) or units < 0:
                raise errors.err_validation("delivered entries require product_id and integer delivered_units")
            if pid in delivered_map:
                raise errors.err_validation("delivered covers a product more than once")
            delivered_map[pid] = units
    if so["status"] != "ACKNOWLEDGED":
        raise errors.err_invalid_state("Supplier order is not ACKNOWLEDGED")
    lines = [ln for ln in db.supplier_order_lines.values() if ln["supplier_order_id"] == sid]
    needed = {ln["product_id"] for ln in lines}
    if set(delivered_map.keys()) != needed:
        raise errors.err_validation("delivered must cover every line product exactly once")
    for ln in lines:
        units = delivered_map[ln["product_id"]]
        if units > ln["ordered_units"]:
            raise errors.err_quantity_invalid("delivered_units exceeds ordered_units")
    # Segregation of duties (priority 9)
    if user_id == so["acknowledged_by_user_id"]:
        raise errors.err_segregation("Deliverer must differ from acknowledger")
    for ln in lines:
        ln["delivered_units"] = delivered_map[ln["product_id"]]
        ln["shortage_units"] = ln["ordered_units"] - ln["delivered_units"]
        helpers.touch(ln)
    so["actual_delivery_date"] = body["actual_delivery_date"]
    so["delivered_by_user_id"] = user_id
    so["actual_cost_cents"] = sum(
        ln["delivered_units"] * ln["unit_cost_actual_cents"] for ln in lines
    )
    so["status"] = "DELIVERED"
    helpers.touch(so)
    # Auto-advance campaign SUPPLIER_ORDERED -> DELIVERED; product buckets
    campaign = db.campaigns[so["campaign_id"]]
    if campaign["status"] == "SUPPLIER_ORDERED":
        for ln in lines:
            product = db.products[ln["product_id"]]
            product["delivered_units"] = ln["delivered_units"]
            product["surplus_units"] += ln["delivered_units"]
            helpers.touch(product)
        campaign["status"] = "DELIVERED"
        helpers.touch(campaign)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_supplier_order(so))


@bp.post("/fundraiser/supplier-orders/<sid>/cancel")
def cancel_supplier_order(sid):
    middleware.require_role("FundraiserAdmin")
    so = get_supplier_order(sid)
    get_body()
    if so["status"] not in ("DRAFT", "SUBMITTED"):
        raise errors.err_invalid_state("Supplier order cannot be cancelled from its current state")
    so["status"] = "CANCELLED"
    helpers.touch(so)
    services.recompute_campaign_totals(db.campaigns[so["campaign_id"]])
    return success_object(serialize_supplier_order(so))
