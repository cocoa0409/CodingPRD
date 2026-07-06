"""Shipment routes: GET, skip, source, allocations create/list, confirm-sourced, ship, deliver."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request, g

from common import new_common, touch
from errors import (
    ApiError, bad_request, invalid_state,
    ERR_SHIPMENT_NOT_FOUND, ERR_STEM_LOT_NOT_FOUND, ERR_ROUTE_NOT_FOUND,
    ERR_SHIPMENT_NOT_SKIPPABLE, ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_LOT_EXPIRED,
    ERR_NOT_OWNER, ERR_SKIP_WINDOW_CLOSED,
    ERR_INSUFFICIENT_STEMS, ERR_ROUTE_WINDOW_CONFLICT, ERR_LOT_HOLD_CONFLICT,
    ERR_SUBSTITUTION_NOT_ALLOWED,
)
from middleware import auth_required
import db
from response import created, ok, list_ok
from pagination import parse_pagination, apply_page
from util import parse_iso
from services import validators as v
from services import calculations as calc
from services import subscription as svc
from services.views import shipment_view, allocation_view

bp = Blueprint("shipments", __name__)


def _get_shipment_or_404(shid):
    sh = db.shipments.get(shid)
    if sh is None:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, "shipment not found", 404)
    return sh


def _customer_owns_shipment(sh):
    sub = db.subscriptions.get(sh["subscription_id"])
    if sub is None:
        return False
    return sub["customer_id"] == g.user_id


# -------------------- GET /shipments/{id} --------------------
@bp.route("/shipments/<shid>", methods=["GET"])
@auth_required("Customer", "FulfillmentOps")
def get_shipment(shid):
    sh = _get_shipment_or_404(shid)
    if g.user_role == "Customer" and not _customer_owns_shipment(sh):
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)
    return ok(shipment_view(sh))


# -------------------- POST /shipments/{id}/skip --------------------
@bp.route("/shipments/<shid>/skip", methods=["POST"])
@auth_required("Customer")
def skip_shipment(shid):
    sh = _get_shipment_or_404(shid)

    # State (40): must be SCHEDULED. Precedes ownership per PRD §2.9.
    if sh["status"] != "SCHEDULED":
        raise ApiError(ERR_SHIPMENT_NOT_SKIPPABLE, "shipment not skippable", 409)

    # Ownership (50)
    if not _customer_owns_shipment(sh):
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)

    # Temporal (55): now <= scheduled_delivery_date - SKIP_CUTOFF_HOURS (inclusive).
    sched = parse_iso(sh["scheduled_delivery_date"])
    cutoff = sched - timedelta(hours=calc.SKIP_CUTOFF_HOURS)
    if db.now() > cutoff:
        raise ApiError(ERR_SKIP_WINDOW_CLOSED, "skip window closed", 422)

    # Transition to SKIPPED.
    sh["status"] = "SKIPPED"
    touch(sh)

    # Release RESERVED allocations of this shipment (COMMITTED shouldn't exist
    # for a SCHEDULED shipment, but we defensively include RESERVED only per PRD).
    for a in list(db.allocations.values()):
        if a["shipment_id"] != sh["id"]:
            continue
        if a["status"] == "RESERVED":
            svc.release_allocation(a)

    # Wallet credit = per_shipment_value of the subscription.
    sub = db.subscriptions[sh["subscription_id"]]
    plan = db.plans[sub["plan_id"]]
    psv = calc.per_shipment_value_cents(
        svc._effective_renewal_price(sub), plan["cadence"]
    )
    svc.create_wallet_entry(
        customer_id=sub["customer_id"],
        amount_cents=psv,
        reason="SKIP_CREDIT",
    )
    return ok(shipment_view(sh))


# -------------------- POST /shipments/{id}/source --------------------
@bp.route("/shipments/<shid>/source", methods=["POST"])
@auth_required("FulfillmentOps")
def source_shipment(shid):
    sh = _get_shipment_or_404(shid)
    # State (40): status == SCHEDULED and Subscription must be ACTIVE+CURRENT
    if sh["status"] != "SCHEDULED":
        raise invalid_state("shipment not in SCHEDULED state")
    sub = db.subscriptions[sh["subscription_id"]]
    if sub["lifecycle_status"] != "ACTIVE" or sub["billing_status"] != "CURRENT":
        raise ApiError(ERR_SUBSCRIPTION_NOT_ACTIVE,
                       "subscription not ACTIVE+CURRENT", 409)
    sh["status"] = "SOURCING"
    touch(sh)
    return ok(shipment_view(sh))


# -------------------- POST /shipments/{id}/allocations --------------------
@bp.route("/shipments/<shid>/allocations", methods=["POST"])
@auth_required("FulfillmentOps")
def create_allocation(shid):
    sh = _get_shipment_or_404(shid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    lot_id = v.require_str(body, "lot_id")
    quantity_reserved = v.require_int(body, "quantity_reserved", min_value=1)
    _hs_dt, hold_start_str = v.require_datetime(body, "hold_start")
    _he_dt, hold_end_str = v.require_datetime(body, "hold_end")

    # Existence for lot_id (body-referenced) treated as invalid request per PRD?
    # SCAFFOLD lists ERR_STEM_LOT_NOT_FOUND for path resources; but body fk to lot
    # is a business fk. Return 404 with ERR_STEM_LOT_NOT_FOUND when missing —
    # aligned with existence semantics for any resource id the caller supplies.
    lot = db.stem_lots.get(lot_id)
    if lot is None:
        raise ApiError(ERR_STEM_LOT_NOT_FOUND, "stem lot not found", 404)

    hs = parse_iso(hold_start_str)
    he = parse_iso(hold_end_str)
    if he < hs:
        raise bad_request("hold_end must be >= hold_start")

    # State (40): shipment must be SOURCING.
    if sh["status"] != "SOURCING":
        raise invalid_state("shipment not in SOURCING state")

    # Constraints (60):
    # a) insufficient stems on the lot
    from services.views import _lot_quantity_available
    available = _lot_quantity_available(lot_id, lot["quantity_total"])
    if quantity_reserved > available:
        raise ApiError(ERR_INSUFFICIENT_STEMS, "not enough stems", 422)

    # b) hold-window collision on the same lot within CLEAN_BUFFER_MINUTES
    #    (closed interval + buffer). Only against active (RESERVED/COMMITTED) holds.
    buffer = timedelta(minutes=calc.CLEAN_BUFFER_MINUTES)
    for other in db.allocations.values():
        if other["lot_id"] != lot_id:
            continue
        if other["status"] not in ("RESERVED", "COMMITTED"):
            continue
        ohs = parse_iso(other["hold_start"])
        ohe = parse_iso(other["hold_end"])
        # Two closed intervals [a,b] and [c,d] "conflict" when they overlap OR
        # lie within CLEAN_BUFFER of each other.
        # gap_after_ours  = ohs - he (positive when 'other' starts after ours ends)
        # gap_after_other = hs - ohe
        # Non-conflict iff at least one gap is strictly greater than buffer.
        gap1 = ohs - he
        gap2 = hs - ohe
        if gap1 > buffer or gap2 > buffer:
            continue
        raise ApiError(ERR_LOT_HOLD_CONFLICT, "hold window conflict", 422)

    # Compute reserved_value_cents at reserve time.
    reserved_value = calc.stem_value_cents(lot, quantity_reserved, db.now())

    a = {
        **new_common(),
        "shipment_id": sh["id"],
        "lot_id": lot_id,
        "quantity_reserved": quantity_reserved,
        "hold_start": hold_start_str,
        "hold_end": hold_end_str,
        "status": "RESERVED",
        "reserved_value_cents": reserved_value,
        "committed_value_cents": None,
    }
    db.allocations[a["id"]] = a
    return created(allocation_view(a))


@bp.route("/shipments/<shid>/allocations", methods=["GET"])
@auth_required("FulfillmentOps")
def list_shipment_allocations(shid):
    limit, offset = parse_pagination()
    sh = _get_shipment_or_404(shid)
    status_filter = request.args.get("status")

    items = [a for a in db.allocations.values() if a["shipment_id"] == shid]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: a["created_at"])
    page, total = apply_page(items, limit, offset)
    return list_ok([allocation_view(a) for a in page], limit, offset, total)


# -------------------- POST /shipments/{id}/confirm-sourced --------------------
@bp.route("/shipments/<shid>/confirm-sourced", methods=["POST"])
@auth_required("FulfillmentOps")
def confirm_sourced(shid):
    sh = _get_shipment_or_404(shid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)

    substitution_applied = v.optional_bool(body, "substitution_applied", default=False)
    from_variety = v.optional_str(body, "from_variety")
    to_variety = v.optional_str(body, "to_variety")

    # State (40): shipment must be SOURCING; every RESERVED allocation's lot FRESH.
    if sh["status"] != "SOURCING":
        raise invalid_state("shipment not in SOURCING state")

    reserved_allocs = [a for a in db.allocations.values()
                       if a["shipment_id"] == sh["id"] and a["status"] == "RESERVED"]

    # Cross-entity state: lot freshness
    for a in reserved_allocs:
        lot = db.stem_lots[a["lot_id"]]
        state, _ = calc.cold_chain_state(lot, db.now())
        if state == "EXPIRED":
            raise ApiError(ERR_LOT_EXPIRED, "stem lot expired", 409)

    # Constraints (60): substitution branch requires an allowed rule.
    if substitution_applied:
        if not from_variety or not to_variety:
            raise bad_request("from_variety and to_variety required when substitution_applied")
        rule = None
        for r in db.substitution_rules.values():
            if (r["from_variety"] == from_variety
                    and r["to_variety"] == to_variety
                    and r.get("allowed", True)):
                rule = r
                break
        if rule is None:
            raise ApiError(ERR_SUBSTITUTION_NOT_ALLOWED,
                           "substitution not allowed", 422)

    # Commit each RESERVED allocation.
    ordered_reserved = sorted(reserved_allocs, key=lambda a: a["created_at"])
    for a in ordered_reserved:
        lot = db.stem_lots[a["lot_id"]]
        committed_val = calc.stem_value_cents(lot, a["quantity_reserved"], db.now())
        a["status"] = "COMMITTED"
        a["committed_value_cents"] = committed_val
        touch(a)

    # Compute stem_cost_cents = sum over ALL COMMITTED allocations of the shipment.
    committed_allocs = [a for a in db.allocations.values()
                       if a["shipment_id"] == sh["id"] and a["status"] == "COMMITTED"]
    sh["stem_cost_cents"] = calc.shipment_stem_cost_cents(committed_allocs)

    if substitution_applied:
        sh["status"] = "SUBSTITUTED"
        sh["substitution_applied"] = True
    else:
        sh["status"] = "SOURCED"
        sh["substitution_applied"] = False
    touch(sh)
    return ok(shipment_view(sh))


# -------------------- POST /shipments/{id}/ship --------------------
@bp.route("/shipments/<shid>/ship", methods=["POST"])
@auth_required("FulfillmentOps")
def ship_shipment(shid):
    sh = _get_shipment_or_404(shid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)

    route_id = v.require_str(body, "route_id")
    _wsdt, ws_str = v.require_datetime(body, "delivery_window_start")
    _wedt, we_str = v.require_datetime(body, "delivery_window_end")

    # Existence for route_id (body-referenced FK).
    route = db.carrier_routes.get(route_id)
    if route is None:
        raise ApiError(ERR_ROUTE_NOT_FOUND, "route not found", 404)

    ws = parse_iso(ws_str)
    we = parse_iso(we_str)
    if we <= ws:
        raise bad_request("delivery_window_end must be > delivery_window_start")

    # State (40): must be SOURCED or SUBSTITUTED.
    if sh["status"] not in ("SOURCED", "SUBSTITUTED"):
        raise invalid_state("shipment not ready to ship")

    # Constraints (60): route window non-overlap on same route.
    # Windows are half-open [ws, we); adjacency (touching) is allowed.
    for other in db.shipments.values():
        if other["id"] == sh["id"]:
            continue
        if other.get("route_id") != route_id:
            continue
        if other["status"] != "SHIPPED":
            continue
        ows = parse_iso(other["delivery_window_start"])
        owe = parse_iso(other["delivery_window_end"])
        # Half-open overlap: not (we <= ows or owe <= ws)
        if not (we <= ows or owe <= ws):
            raise ApiError(ERR_ROUTE_WINDOW_CONFLICT, "window conflict", 422)

    sh["route_id"] = route_id
    sh["delivery_window_start"] = ws_str
    sh["delivery_window_end"] = we_str
    sh["status"] = "SHIPPED"
    touch(sh)
    return ok(shipment_view(sh))


# -------------------- POST /shipments/{id}/deliver --------------------
@bp.route("/shipments/<shid>/deliver", methods=["POST"])
@auth_required("FulfillmentOps")
def deliver_shipment(shid):
    sh = _get_shipment_or_404(shid)
    if sh["status"] != "SHIPPED":
        raise invalid_state("shipment not SHIPPED")
    sh["status"] = "DELIVERED"
    touch(sh)
    # Customer.lifetime_cycles and loyalty_tier are computed on read (see views).
    return ok(shipment_view(sh))
