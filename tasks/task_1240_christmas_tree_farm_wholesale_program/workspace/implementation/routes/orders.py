"""WholesaleOrder and Allocation endpoints (PRD 3.3, 3.4)."""
from flask import Blueprint, request

from authz import require_role
from db import now, store
from errors import (credit_limit_exceeded, forbidden, invalid_state,
                    no_eligible_inventory, order_has_cut_allocations,
                    posture_forbids, stale_version, buyer_credit_hold)
from helpers import (body, get_or_404, has_field, new_record, paginate,
                     req_enum, req_field, req_int, req_str, touch)
from respond import success
from serialize import allocation_out, order_out
from services import (HEIGHT_CLASSES, SPECIES, buyer_exposure_cents,
                      compute_invoice, recompute_order_status,
                      release_allocation, waterfall)

bp = Blueprint("orders", __name__)


def _own_order_or_403(order, user_id, role):
    if role == "WholesaleBuyer" and order["buyer_account_id"] != user_id:
        raise forbidden("A wholesale buyer may act only on its own orders")


@bp.post("/api/wholesale-orders")
def create_order():
    user_id, role = require_role("WholesaleBuyer")
    data = body()
    # Ownership (priority 2): buyers create orders only under their own account.
    if has_field(data, "buyer_account_id") and data["buyer_account_id"] != user_id:
        raise forbidden("buyer_account_id must equal the acting buyer")
    # Existence of body FK references, left to right (priority 4).
    season_id = req_field(data, "season_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season_id does not exist")
    buyer_id = req_field(data, "buyer_account_id")
    if isinstance(buyer_id, str):
        get_or_404(store.buyers, buyer_id, "buyer_account_id does not exist")
    # Well-formedness (priority 5).
    season_id = req_str(data, "season_id")
    buyer_id = req_str(data, "buyer_account_id")
    species = req_enum(data, "species", SPECIES)
    height_class = req_enum(data, "height_class", HEIGHT_CLASSES)
    quantity = req_int(data, "quantity", minimum=1)
    unit_price_cents = req_int(data, "unit_price_cents", minimum=0)
    # Posture (priority 7): order creation requires BOOKING.
    if store.seasons[season_id]["posture"] != "BOOKING":
        raise posture_forbids("Order creation requires BOOKING posture")
    rec = new_record({
        "season_id": season_id,
        "buyer_account_id": buyer_id,
        "species": species,
        "height_class": height_class,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "allocated_qty": 0,
        "invoice_subtotal_cents": None,
        "discount_pct_applied": None,
        "invoice_discount_cents": None,
        "invoice_total_cents": None,
        "submitted_at": None,
        "status": "DRAFT",
    })
    store.orders[rec["id"]] = rec
    return success(order_out(rec), status=201)


@bp.get("/api/wholesale-orders/<oid>")
def get_order(oid):
    user_id, role = require_role("Owner", "FarmManager", "WholesaleBuyer")
    order = get_or_404(store.orders, oid)
    _own_order_or_403(order, user_id, role)
    return success(order_out(order))


@bp.get("/api/wholesale-orders")
def list_orders():
    user_id, role = require_role("Owner", "FarmManager", "WholesaleBuyer")
    items = sorted(store.orders.values(), key=lambda o: o["_seq"])
    if role == "WholesaleBuyer":
        items = [o for o in items if o["buyer_account_id"] == user_id]
    buyer_id = request.args.get("buyer_account_id")
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    if buyer_id is not None:
        items = [o for o in items if o["buyer_account_id"] == buyer_id]
    if season_id is not None:
        items = [o for o in items if o["season_id"] == season_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    return success([order_out(o) for o in page], response_type="array",
                   pagination=meta)


@bp.post("/api/wholesale-orders/<oid>/submit")
def submit_order(oid):
    user_id, role = require_role("WholesaleBuyer")
    order = get_or_404(store.orders, oid)
    _own_order_or_403(order, user_id, role)
    # State (priority 6): only a DRAFT order can be submitted.
    if order["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT order can be submitted")
    # Posture (priority 7): submission requires BOOKING.
    if store.seasons[order["season_id"]]["posture"] != "BOOKING":
        raise posture_forbids("Order submission requires BOOKING posture")
    buyer = store.buyers[order["buyer_account_id"]]
    # Referential (priority 15): the buyer must be in GOOD_STANDING.
    if buyer["standing"] != "GOOD_STANDING":
        raise buyer_credit_hold("The buyer is not in GOOD_STANDING")
    subtotal, pct, discount, total = compute_invoice(
        order["quantity"], order["unit_price_cents"])
    # Fiscal (priority 29): exposure + invoice_total <= credit_limit (inclusive).
    exposure = buyer_exposure_cents(buyer["id"])
    if exposure + total > buyer["credit_limit_cents"]:
        raise credit_limit_exceeded(
            "Submitting would exceed the buyer's credit limit")
    order["invoice_subtotal_cents"] = subtotal
    order["discount_pct_applied"] = pct
    order["invoice_discount_cents"] = discount
    order["invoice_total_cents"] = total
    order["submitted_at"] = now()
    order["status"] = "SUBMITTED"
    touch(order)
    return success(order_out(order))


@bp.post("/api/wholesale-orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = require_role("WholesaleBuyer", "FarmManager")
    order = get_or_404(store.orders, oid)
    _own_order_or_403(order, user_id, role)
    # State (priority 6): DRAFT/SUBMITTED/ALLOCATED are cancellable; the
    # terminal states (CLOSED/CANCELLED/EXPIRED) are locked down.
    if order["status"] not in ("DRAFT", "SUBMITTED", "ALLOCATED"):
        raise invalid_state("The order is in a terminal state")
    allocs = [a for a in store.allocations.values() if a["order_id"] == oid]
    # Referential (priority 19): no allocation may be cut or loaded yet.
    if any(a["status"] in ("CUT", "LOADED") or a["cut_qty"] > 0
           or a["loaded_qty"] > 0 for a in allocs):
        raise order_has_cut_allocations(
            "The order has cut or loaded allocations")
    for a in allocs:
        if a["status"] == "RESERVED":
            bucket = store.stand_buckets[a["bucket_id"]]
            bucket["reserved_count"] -= a["quantity"]
            touch(bucket)
            a["status"] = "RELEASED"
            touch(a)
    order["allocated_qty"] = 0
    order["status"] = "CANCELLED"
    touch(order)
    return success(order_out(order))


@bp.post("/api/wholesale-orders/<oid>/allocate")
def allocate_order(oid):
    require_role("FarmManager")
    order = get_or_404(store.orders, oid)
    data = body()
    # Well-formedness (priority 5).
    quantity = req_int(data, "quantity", minimum=1)
    expected_version = req_int(data, "expected_order_version")
    # State (priority 6): only a live (submitted) order can be allocated.
    if order["status"] not in ("SUBMITTED", "ALLOCATED"):
        raise invalid_state("Only a SUBMITTED or ALLOCATED order can be allocated")
    # Posture (priority 7): allocation requires BOOKING or HARVEST.
    if store.seasons[order["season_id"]]["posture"] not in ("BOOKING", "HARVEST"):
        raise posture_forbids("Allocation requires BOOKING or HARVEST posture")
    # Optimistic concurrency on the order (ERR_STALE_VERSION, 412).
    if expected_version != order["version"]:
        raise stale_version("expected_order_version does not match the order version")
    # Constraint (priority 20): the waterfall must reserve at least one tree.
    allocated_now, allocation_ids = waterfall(order, quantity)
    if allocated_now == 0:
        raise no_eligible_inventory("No eligible inventory could be reserved")
    order["allocated_qty"] += allocated_now
    recompute_order_status(order)
    touch(order)
    return success({
        "order_id": order["id"],
        "allocated_now": allocated_now,
        "allocated_total": order["allocated_qty"],
        "allocation_ids": allocation_ids,
        "order_status": order["status"],
        "order_version": order["version"],
    })


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

def _own_allocation_or_403(alloc, user_id, role):
    if role == "WholesaleBuyer":
        order = store.orders[alloc["order_id"]]
        if order["buyer_account_id"] != user_id:
            raise forbidden("A wholesale buyer may read only its own allocations")


@bp.get("/api/allocations/<aid>")
def get_allocation(aid):
    user_id, role = require_role("Owner", "FarmManager", "WholesaleBuyer")
    alloc = get_or_404(store.allocations, aid)
    _own_allocation_or_403(alloc, user_id, role)
    return success(allocation_out(alloc))


@bp.get("/api/allocations")
def list_allocations():
    user_id, role = require_role("Owner", "FarmManager", "WholesaleBuyer")
    items = sorted(store.allocations.values(), key=lambda a: a["_seq"])
    if role == "WholesaleBuyer":
        own_order_ids = {o["id"] for o in store.orders.values()
                         if o["buyer_account_id"] == user_id}
        items = [a for a in items if a["order_id"] in own_order_ids]
    order_id = request.args.get("order_id")
    bucket_id = request.args.get("bucket_id")
    status = request.args.get("status")
    if order_id is not None:
        items = [a for a in items if a["order_id"] == order_id]
    if bucket_id is not None:
        items = [a for a in items if a["bucket_id"] == bucket_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return success([allocation_out(a) for a in page], response_type="array",
                   pagination=meta)


@bp.post("/api/allocations/<aid>/release")
def release_allocation_endpoint(aid):
    require_role("FarmManager")
    alloc = get_or_404(store.allocations, aid)
    if alloc["status"] != "RESERVED":
        raise invalid_state("Only a RESERVED allocation can be released")
    release_allocation(alloc)
    return success(allocation_out(alloc))
