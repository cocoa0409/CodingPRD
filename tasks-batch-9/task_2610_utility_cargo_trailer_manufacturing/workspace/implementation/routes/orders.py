"""Dealer orders, stock allocation, cancellation and delivery (PRD 3.8)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import clock_now, db, new_id, now_iso, public, public_list, stamp_new, touch
from middleware import actor, endpoint, is_dealer
from response import created, listing, ok
from services import calc, rollups

bp = Blueprint("orders", __name__)

STOCKING_PROGRAMS = ("STOCK", "SOLD_ORDER", "DEMO")
ORDER_STATUSES = ("PENDING", "ALLOCATED", "DELIVERED", "CANCELLED")
READ_ROLES = ["SalesAdmin", "PlantEngineer", "Dealer"]


@bp.route("/dealer-orders", methods=["POST"])
@endpoint(["SalesAdmin", "Dealer"])
def create_order():
    data = v.body()
    if is_dealer() and data.get("dealer_id") != actor():
        raise errors.dealer_scope(actor(), data.get("dealer_id"))
    dealer = lookups.dealer_or_404(v.req_id(data, "dealer_id"))
    model = lookups.model_or_404(v.req_id(data, "model_id"))
    po_ref = v.req_str(data, "po_ref", min_len=4, max_len=24)
    stocking_program = v.req_enum(data, "stocking_program", STOCKING_PROGRAMS)

    row = {
        "id": new_id(),
        "dealer_id": dealer["id"],
        "model_id": model["id"],
        "po_ref": po_ref,
        "stocking_program": stocking_program,
        "status": "PENDING",
        "allocated_unit_id": None,
        "invoice_subtotal_cents": None,
        "volume_discount_pct": None,
        "volume_discount_cents": None,
        "freight_cents": None,
        "invoice_total_cents": None,
        "floor_plan_draw_cents": 0,
        "floor_plan_status": "NONE",
        "allocated_at": None,
        "delivered_at": None,
        "cancelled_at": None,
        "_allocated_at_dt": None,
    }
    stamp_new(row)
    db.orders[row["id"]] = row
    return created(public(row))


@bp.route("/dealer-orders/<order_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_order(order_id):
    return ok(public(lookups.order_or_404(order_id)))


@bp.route("/dealer-orders", methods=["GET"])
@endpoint(READ_ROLES)
def list_orders():
    dealer_id = v.request_arg("dealer_id")
    if is_dealer() and dealer_id != actor():
        raise errors.dealer_scope(actor(), dealer_id)
    model_id = v.request_arg("model_id")
    allocated_unit_id = v.request_arg("allocated_unit_id")
    status = v.query_enum("status", ORDER_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.orders.values())
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if model_id is not None:
        rows = [r for r in rows if r["model_id"] == model_id]
    if allocated_unit_id is not None:
        rows = [r for r in rows if r["allocated_unit_id"] == allocated_unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)


def _eligible(unit):
    return (unit["build_status"] == "RELEASED_TO_STOCK"
            and unit.get("dealer_order_id") is None
            and rollups.issued_label(unit["id"]) is not None)


def _ranked_candidates(order):
    """released_to_stock_at asc, then created_at asc, then serial_number asc."""
    candidates = [u for u in db.units.values()
                  if u["model_id"] == order["model_id"] and _eligible(u)]
    candidates.sort(key=lambda u: (u["released_to_stock_at"] or "",
                                   u["created_at"], u["serial_number"]))
    return candidates


@bp.route("/dealer-orders/<order_id>/allocation", methods=["POST"])
@endpoint(["SalesAdmin"])
def allocate_order(order_id):
    order = lookups.order_or_404(order_id)
    data = v.body()
    named_unit = None
    if v.present(data, "unit_id"):
        named_unit = lookups.unit_or_404(v.req_id(data, "unit_id"))
    expected_version = v.req_version(data, "expected_dealer_version")

    dealer = db.dealers.get(order["dealer_id"])
    if expected_version != dealer["version"]:
        raise errors.ApiError("ERR_STALE_DEALER_VERSION", 412,
                              "expected_dealer_version %s does not match the dealer's current "
                              "version %s" % (expected_version, dealer["version"]))
    if order["status"] != "PENDING":
        raise errors.ApiError("ERR_ORDER_STATE_INVALID", 409,
                              "An order in status %s may not be allocated" % order["status"])

    if named_unit is not None:
        if named_unit["model_id"] != order["model_id"]:
            raise errors.ApiError("ERR_UNIT_MODEL_MISMATCH", 422,
                                  "Trailer %s is not built to the ordered model"
                                  % named_unit["id"])
        if not _eligible(named_unit):
            raise errors.ApiError("ERR_UNIT_NOT_ALLOCATABLE", 409,
                                  "Trailer %s is not allocatable" % named_unit["id"])
        unit = named_unit
    else:
        candidates = _ranked_candidates(order)
        if not candidates:
            raise errors.ApiError("ERR_NO_ALLOCATABLE_UNIT", 409,
                                  "No trailer of that model is available in stock")
        unit = candidates[0]

    model = db.models.get(order["model_id"])
    # Both counters are read live against the logical clock's current calendar
    # month and year, not from the values last persisted on the dealer row.
    month_count, ytd_count = rollups.allocation_counts(dealer)
    figures = calc.invoice(model, rollups.options_of_unit(unit["id"]),
                           ytd_count, order["stocking_program"])

    if dealer["status"] != "ACTIVE":
        raise errors.ApiError("ERR_DEALER_CREDIT_HOLD", 409,
                              "Dealer %s is in status %s" % (dealer["id"], dealer["status"]))
    if month_count + 1 > dealer["allocation_quota_per_month"]:
        raise errors.ApiError("ERR_ALLOCATION_QUOTA_EXCEEDED", 409,
                              "Dealer %s has used its monthly allocation quota of %s"
                              % (dealer["id"], dealer["allocation_quota_per_month"]))
    if order["stocking_program"] != "DEMO":
        projected = dealer["floor_plan_outstanding_cents"] + figures["floor_plan_draw_cents"]
        if projected > dealer["floor_plan_limit_cents"]:
            raise errors.ApiError("ERR_FLOOR_PLAN_LIMIT_EXCEEDED", 402,
                                  "A draw of %s would take the dealer's outstanding balance to "
                                  "%s against a limit of %s"
                                  % (figures["floor_plan_draw_cents"], projected,
                                     dealer["floor_plan_limit_cents"]))

    order.update(figures)
    order["status"] = "ALLOCATED"
    order["allocated_unit_id"] = unit["id"]
    order["allocated_at"] = now_iso()
    order["_allocated_at_dt"] = clock_now()
    if order["stocking_program"] != "DEMO":
        order["floor_plan_status"] = "DRAWN"
    touch(order)

    unit["build_status"] = "ALLOCATED"
    unit["dealer_order_id"] = order["id"]
    touch(unit)
    rollups.recompute_dealer(dealer)
    return ok(public(order))


@bp.route("/dealer-orders/<order_id>/cancellation", methods=["POST"])
@endpoint(["SalesAdmin", "Dealer"])
def cancel_order(order_id):
    order = lookups.order_or_404(order_id)
    if is_dealer() and order["dealer_id"] != actor():
        raise errors.dealer_scope(actor(), order["dealer_id"])
    data = v.body()
    reason = v.opt_str(data, "cancellation_reason", max_len=500)

    if order["status"] not in ("PENDING", "ALLOCATED"):
        raise errors.ApiError("ERR_ORDER_STATE_INVALID", 409,
                              "An order in status %s may not be cancelled" % order["status"])

    was_allocated = order["status"] == "ALLOCATED"
    unit = db.units.get(order.get("allocated_unit_id"))
    order["status"] = "CANCELLED"
    order["cancelled_at"] = now_iso()
    if reason is not None:
        order["cancellation_reason"] = reason
    if was_allocated:
        order["allocated_unit_id"] = None
    touch(order)

    if was_allocated:
        if unit is not None:
            # released_to_stock_at is deliberately NOT rewritten: stock age survives.
            unit["build_status"] = "RELEASED_TO_STOCK"
            unit["dealer_order_id"] = None
            touch(unit)
        if order["floor_plan_status"] == "DRAWN":
            order["floor_plan_status"] = "RELEASED"
        rollups.recompute_dealer(db.dealers.get(order["dealer_id"]))
    return ok(public(order))


@bp.route("/dealer-orders/<order_id>/delivery", methods=["POST"])
@endpoint(["SalesAdmin"])
def deliver_order(order_id):
    order = lookups.order_or_404(order_id)
    data = v.body()
    note = v.opt_str(data, "delivery_note", max_len=500)

    unit = db.units.get(order.get("allocated_unit_id"))
    if order["status"] != "ALLOCATED" or unit is None or unit["build_status"] != "ALLOCATED":
        raise errors.ApiError("ERR_ORDER_STATE_INVALID", 409,
                              "An order in status %s with that trailer may not be delivered"
                              % order["status"])

    order["status"] = "DELIVERED"
    order["delivered_at"] = now_iso()
    if note is not None:
        order["delivery_note"] = note
    touch(order)

    unit["build_status"] = "SHIPPED"
    unit["warranty_start_date"] = now_iso()
    unit["_warranty_start_dt"] = clock_now()
    touch(unit)
    rollups.recompute_model_active_unit_count(db.models.get(unit["model_id"]))
    return ok(public(order))
