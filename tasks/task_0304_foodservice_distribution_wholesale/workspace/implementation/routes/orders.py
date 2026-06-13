"""Order lifecycle routes: create, lines, remove, submit, approve-credit,
start-pick, cancel, plus order/order-line reads."""
from flask import Blueprint

import db
import errors
import middleware
import models
import response
from routes.listing import list_response
from services import calc, lookup, serialize
from services.clocks import (cutoff_instant, day_of_week_monday0, parse_iso,
                             whole_day_distance)

bp = Blueprint("orders", __name__)

READ_ROLES = {"DistributorAdmin", "SalesRep", "WarehouseOp", "CreditManager"}
ACTIVE_FULFILLMENT = {"SUBMITTED", "PICKING", "LOADED", "DELIVERED"}


# --- Order create / read -----------------------------------------------------

@bp.route("/orders", methods=["POST"])
def create_order():
    _, role = middleware.require_auth()
    middleware.require_role(role, {"SalesRep", "DistributorAdmin"})
    body = middleware.get_json_body()
    customer_id = models.require_str(body, "customer_id")
    rdd = models.require_str(body, "requested_delivery_date")
    # Validate it parses as ISO 8601.
    parse_iso(rdd, "requested_delivery_date")
    with db.lock:
        cust = lookup.customer(customer_id)
        if cust["ar_status"] == "CLOSED":
            raise errors.ApiError(errors.ERR_CUSTOMER_CLOSED, 409, "Customer is CLOSED.")
        rec = models.base_record({
            "customer_id": customer_id,
            "distributor_id": cust["distributor_id"],
            "route_id": None,
            "requested_delivery_date": rdd,
            "fulfillment_status": "DRAFT",
            "credit_status": "PENDING",
            "goods_subtotal_cents": 0,
            "split_fee_total_cents": 0,
            "order_total_cents": 0,
            "settled": False,
        })
        db.orders[rec["id"]] = rec
        return response.object_response(serialize.order(rec), 201)


@bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.order(order_id)
    return response.object_response(serialize.order(rec), 200)


@bp.route("/orders", methods=["GET"])
def list_orders():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.orders.values(), serialize.order,
                         {"customer_id": "customer_id",
                          "route_id": "route_id",
                          "distributor_id": "distributor_id",
                          "fulfillment_status": "fulfillment_status"})


# --- Order lines -------------------------------------------------------------

@bp.route("/orders/<order_id>/lines", methods=["POST"])
def add_line(order_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"SalesRep", "DistributorAdmin"})
    body = middleware.get_json_body()
    product_id = models.require_str(body, "product_id")
    uom = models.require_enum(body, "uom", {"CASE", "SPLIT"})
    ordered_qty = models.require_int(body, "ordered_qty", min_value=1)
    order_guide_item_id = models.opt_str(body, "order_guide_item_id", default=None)
    with db.lock:
        order = lookup.order(order_id)
        # Path id exists; now body FKs left-to-right.
        product = lookup.product(product_id)
        if order_guide_item_id is not None:
            lookup.order_guide_item(order_guide_item_id)
        # State: lines may only be added to a DRAFT order.
        if order["fulfillment_status"] != "DRAFT":
            raise errors.invalid_state("Lines may only be added to a DRAFT order.")
        # Business: SPLIT requires split_allowed.
        if uom == "SPLIT" and not product["split_allowed"]:
            raise errors.ApiError(errors.ERR_SPLIT_NOT_ALLOWED, 422,
                                  "Product does not allow SPLIT ordering.")
        # Cross-distributor: product must be under the order's distributor.
        if product["distributor_id"] != order["distributor_id"]:
            raise errors.cross_distributor("Product belongs to a different distributor.")
        rec = models.base_record({
            "order_id": order_id,
            "product_id": product_id,
            "order_guide_item_id": order_guide_item_id,
            "uom": uom,
            "ordered_qty": ordered_qty,
            "fulfilled_product_id": None,
            "allocated_splits": 0,
            "substituted": False,
            "short_splits": 0,
            "unit_case_price_cents": 0,
            "extended_price_cents": 0,
            "line_status": "OPEN",
        })
        db.order_lines[rec["id"]] = rec
        return response.object_response(serialize.order_line(rec), 201)


@bp.route("/order-lines/<order_line_id>", methods=["GET"])
def get_order_line(order_line_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.order_line(order_line_id)
    return response.object_response(serialize.order_line(rec), 200)


@bp.route("/order-lines", methods=["GET"])
def list_order_lines():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.order_lines.values(), serialize.order_line,
                         {"order_id": "order_id",
                          "product_id": "product_id",
                          "fulfilled_product_id": "fulfilled_product_id",
                          "order_guide_item_id": "order_guide_item_id"})


@bp.route("/order-lines/<order_line_id>/remove", methods=["POST"])
def remove_line(order_line_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"SalesRep", "DistributorAdmin"})
    with db.lock:
        line = lookup.order_line(order_line_id)
        order = lookup.order(line["order_id"])
        if order["fulfillment_status"] != "DRAFT":
            raise errors.invalid_state("Lines may only be removed from a DRAFT order.")
        line["line_status"] = "REMOVED"
        models.touch(line)
        # Recompute order totals from remaining non-removed lines.
        cust = db.customers[order["customer_id"]]
        lines = lookup.lines_of_order(order["id"])
        calc.compute_order_totals(order, lines, cust)
        models.touch(order)
        return response.object_response(serialize.order_line(line), 200)


# --- Submit ------------------------------------------------------------------

@bp.route("/orders/<order_id>/submit", methods=["POST"])
def submit_order(order_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"SalesRep", "DistributorAdmin"})
    with db.lock:
        order = lookup.order(order_id)
        # State: transition DRAFT -> SUBMITTED only defined from DRAFT.
        if order["fulfillment_status"] != "DRAFT":
            raise errors.invalid_state("Order is not in DRAFT.")
        cust = db.customers[order["customer_id"]]
        lines = lookup.lines_of_order(order_id)

        # Business rules (PRD §3.3 precedence).
        active_lines = [l for l in lines if l["line_status"] != "REMOVED"]
        if len(active_lines) < 1:
            raise errors.ApiError(errors.ERR_EMPTY_ORDER, 409, "Order has no active lines.")
        # Customer-closed guard comes before delivery/cutoff/gap.
        if cust["ar_status"] == "CLOSED":
            raise errors.ApiError(errors.ERR_CUSTOMER_CLOSED, 409, "Customer is CLOSED.")
        # Credit-hold guard governs whether submission may proceed at all.
        if cust["ar_status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_CUSTOMER_ON_CREDIT_HOLD, 409,
                                  "Customer is on credit hold.")

        route = db.routes[cust["route_id"]]
        rdd = parse_iso(order["requested_delivery_date"], "requested_delivery_date")
        dist = db.distributors[order["distributor_id"]]
        current = parse_iso(dist["current_utc"], "current_utc")

        # Delivery-day-of-week must match route.delivery_dow.
        if day_of_week_monday0(rdd) != route["delivery_dow"]:
            raise errors.ApiError(errors.ERR_DELIVERY_DAY_MISMATCH, 409,
                                  "Delivery day-of-week does not match the route.")
        # Cutoff: current_utc must be <= (delivery midnight - cutoff_lead_hours).
        cutoff = cutoff_instant(rdd, route["cutoff_lead_hours"])
        if current > cutoff:
            raise errors.ApiError(errors.ERR_CUTOFF_PASSED, 409, "Order cutoff has passed.")
        # Delivery-gap buffer against other active orders for this customer.
        gap = route["min_delivery_gap_days"]
        if gap and gap > 0:
            for o in db.orders.values():
                if o["id"] == order_id:
                    continue
                if o["customer_id"] != order["customer_id"]:
                    continue
                if o["fulfillment_status"] not in ACTIVE_FULFILLMENT:
                    continue
                other_rdd = parse_iso(o["requested_delivery_date"], "requested_delivery_date")
                if whole_day_distance(rdd, other_rdd) < gap:
                    raise errors.ApiError(errors.ERR_DELIVERY_GAP_CONFLICT, 409,
                                          "Delivery date conflicts with the route gap buffer.")

        order["fulfillment_status"] = "SUBMITTED"
        order["credit_status"] = "PENDING"
        order["route_id"] = cust["route_id"]
        models.touch(order)
        return response.object_response(serialize.order(order), 200)


# --- Approve credit ----------------------------------------------------------

@bp.route("/orders/<order_id>/approve-credit", methods=["POST"])
def approve_credit(order_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"CreditManager"})
    body = middleware.get_json_body()
    expected_customer_version = models.require_int(body, "expected_customer_version")
    with db.lock:
        order = lookup.order(order_id)
        cust = db.customers[order["customer_id"]]

        # OCC check (priority 6, before state per scaffold §1.4) ...
        # ... but state precedence: credit_status must be PENDING.
        # Per PRD §3.4: requires credit_status PENDING (ERR_INVALID_STATE) first,
        # then expected_customer_version match (ERR_STALE_CUSTOMER_VERSION),
        # then customer ar_status ACTIVE (ERR_CUSTOMER_ON_CREDIT_HOLD), then the
        # perishable freshness guard.
        if order["credit_status"] != "PENDING":
            raise errors.invalid_state("Order credit_status is not PENDING.")
        if expected_customer_version != cust["version"]:
            raise errors.ApiError(errors.ERR_STALE_CUSTOMER_VERSION, 412,
                                  "expected_customer_version does not match the customer version.")
        if cust["ar_status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_CUSTOMER_ON_CREDIT_HOLD, 409,
                                  "Customer is on credit hold.")

        route = db.routes[order["route_id"]]
        warehouse_id = route["warehouse_id"]
        rdd = parse_iso(order["requested_delivery_date"], "requested_delivery_date")
        lines = lookup.lines_of_order(order_id)
        # Lines to allocate: every non-REMOVED line, processed in created_at ASC.
        # On a first approval these are all OPEN; on a re-approval of an order
        # that previously went ON_HOLD they may be ALLOCATED/SHORTED but their
        # reservations were already released, so we reset and re-allocate from
        # scratch deterministically.
        open_lines = [l for l in lines if l["line_status"] != "REMOVED"]

        # Perishable freshness guard: for every perishable line, at least one
        # eligible lot (primary or substitute) whose expires_on > delivery date.
        for line in open_lines:
            product = db.products[line["product_id"]]
            if not product["perishable"]:
                continue
            eligible = calc._has_eligible_perishable_lot(product, warehouse_id, rdd)
            if not eligible:
                sub_id = product.get("substitute_product_id")
                if sub_id and sub_id in db.products:
                    sub = db.products[sub_id]
                    if sub["perishable"]:
                        eligible = calc._has_eligible_perishable_lot(sub, warehouse_id, rdd)
                    else:
                        # Non-perishable substitute lots are always fresh-eligible
                        # if any candidate exists.
                        eligible = len(calc._candidate_lots(sub, warehouse_id, rdd)) > 0
            if not eligible:
                raise errors.ApiError(errors.ERR_LOT_EXPIRES_BEFORE_DELIVERY, 409,
                                      "No eligible lot whose freshness window contains the delivery instant.")

        products_by_id = db.products

        # Allocation first, per line in created_at ASC order. Reset each line's
        # allocation/pricing fields so a re-approval starts from a clean slate.
        for line in open_lines:
            line["_lot_allocations"] = {}
            line["allocated_splits"] = 0
            line["short_splits"] = 0
            line["substituted"] = False
            line["fulfilled_product_id"] = None
            line["unit_case_price_cents"] = 0
            line["extended_price_cents"] = 0
            product = db.products[line["product_id"]]
            calc.allocate_line(line, product, warehouse_id, rdd, products_by_id)

        # Aggregate per-lot reservations added by this approval.
        touched_lots = {}  # lot_id -> reserved added during this approval
        for line in open_lines:
            for lid, splits in (line.get("_lot_allocations") or {}).items():
                touched_lots[lid] = touched_lots.get(lid, 0) + splits

        # Pricing per line on the fulfilled product.
        for line in open_lines:
            fulfilled = db.products[line["fulfilled_product_id"]]
            calc.price_line(line, fulfilled)
            models.touch(line)

        # Totals.
        calc.compute_order_totals(order, lines, cust)

        # Credit decision.
        if cust["ar_balance_cents"] + order["order_total_cents"] <= cust["credit_limit_cents"]:
            order["credit_status"] = "APPROVED"
            cust["ar_balance_cents"] += order["order_total_cents"]
            # Bump version on each lot whose reservation changed (cascade).
            for lid in touched_lots:
                models.touch(db.inventory_lots[lid])
        else:
            order["credit_status"] = "ON_HOLD"
            # Roll back every reservation made by this approval (PRD §3.4). AR is
            # left unchanged. allocated_splits / line_status / pricing and the
            # order totals stay as computed — order_total_cents is what the
            # credit-release / issue-credit cascades test against the customer's
            # headroom (PRD §3.5/§3.7). Only the physical lot reservations are
            # released; clear each line's reservation map so a later re-approval
            # re-reserves cleanly. No lot version bump (net reservation zero).
            for lid, added in touched_lots.items():
                lot = db.inventory_lots[lid]
                lot["reserved_splits"] -= added
            for line in open_lines:
                line["_lot_allocations"] = {}

        models.touch(order)
        models.touch(cust)  # advance even on ON_HOLD path (OCC guard well-defined)
        return response.object_response(serialize.order(order), 200)


# --- Start pick --------------------------------------------------------------

@bp.route("/orders/<order_id>/start-pick", methods=["POST"])
def start_pick(order_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"WarehouseOp"})
    with db.lock:
        order = lookup.order(order_id)
        # State: transition SUBMITTED -> PICKING.
        if order["fulfillment_status"] != "SUBMITTED":
            raise errors.invalid_state("Order is not SUBMITTED.")
        if order["credit_status"] != "APPROVED":
            raise errors.ApiError(errors.ERR_CREDIT_NOT_APPROVED, 409,
                                  "Order credit is not APPROVED.")
        lines = lookup.lines_of_order(order_id)
        if not any(l["line_status"] == "ALLOCATED" for l in lines):
            raise errors.ApiError(errors.ERR_NOTHING_TO_PICK, 409,
                                  "No ALLOCATED lines to pick.")
        route = db.routes[order["route_id"]]
        order["fulfillment_status"] = "PICKING"
        models.touch(order)
        shipment = models.base_record({
            "order_id": order_id,
            "distributor_id": order["distributor_id"],
            "warehouse_id": route["warehouse_id"],
            "pod_signature": None,
            "delivered_total_cents": 0,
            "status": "PICKING",
        })
        db.shipments[shipment["id"]] = shipment
        return response.object_response(serialize.order(order), 200)


# --- Cancel ------------------------------------------------------------------

@bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"SalesRep", "DistributorAdmin"})
    with db.lock:
        order = lookup.order(order_id)
        status = order["fulfillment_status"]
        if status == "DRAFT":
            order["fulfillment_status"] = "CANCELLED"
            models.touch(order)
            return response.object_response(serialize.order(order), 200)
        if status == "SUBMITTED":
            cust = db.customers[order["customer_id"]]
            if order["credit_status"] == "APPROVED":
                # Compensate: release reservations and decrease AR (PRD §3.6).
                lines = lookup.lines_of_order(order_id)
                for line in lines:
                    _release_line_reservations(line)
                cust["ar_balance_cents"] -= order["order_total_cents"]
                models.touch(cust)
                order["credit_status"] = "PENDING"
            order["fulfillment_status"] = "CANCELLED"
            models.touch(order)
            return response.object_response(serialize.order(order), 200)
        # Any other state: transition not defined.
        raise errors.invalid_state("Order cannot be cancelled from its current state.")


def _release_line_reservations(line):
    """Decrement reserved_splits on the exact lots this line reserved at approval.

    Uses the per-line _lot_allocations map recorded by allocate_inventory, so
    reservations net back to zero precisely. Each touched lot is version-bumped.
    """
    alloc = line.get("_lot_allocations") or {}
    for lot_id, splits in alloc.items():
        lot = db.inventory_lots.get(lot_id)
        if lot is None or splits <= 0:
            continue
        lot["reserved_splits"] -= splits
        models.touch(lot)
    line["_lot_allocations"] = {}
