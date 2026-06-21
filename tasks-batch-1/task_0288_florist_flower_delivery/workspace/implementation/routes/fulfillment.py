"""Wire-fulfillment, substitution, and zone delivery-slot routes
(PRD §3.4-§3.5)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_auth, require_role
from helpers import (
    get_body, make_record, touch, public, parse_pagination, paginate,
    require_fields, as_int, as_str,
)
from response import success, success_list
from services import pricing

bp = Blueprint("fulfillment", __name__)


# ===========================================================================
# Wire fulfillments
# ===========================================================================
@bp.route("/floral/wire-fulfillments/<wid>", methods=["GET"])
def get_wire_fulfillment(wid):
    _, role = require_auth()
    require_role(role, {"Florist", "Dispatcher", "CatalogAdmin"})
    rec = store.wire_fulfillments.get(wid)
    if rec is None:
        raise errors.not_found("Wire fulfillment not found")
    return success(public(rec))


@bp.route("/floral/wire-fulfillments", methods=["GET"])
def list_wire_fulfillments():
    _, role = require_auth()
    require_role(role, {"Florist", "Dispatcher", "CatalogAdmin"})
    limit, offset = parse_pagination()
    rows = list(store.wire_fulfillments.values())
    florist_id = request.args.get("florist_id")
    order_id = request.args.get("order_id")
    if florist_id is not None:
        rows = [r for r in rows if r["florist_id"] == florist_id]
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/wire-fulfillments/<wid>/accept", methods=["POST"])
def accept_wire_fulfillment(wid):
    user_id, role = require_auth()
    require_role(role, {"Florist", "Dispatcher"})
    rec = store.wire_fulfillments.get(wid)
    if rec is None:
        raise errors.not_found("Wire fulfillment not found")
    # Ownership: acting Florist must own this fulfillment.
    if role == "Florist" and rec["florist_id"] != user_id:
        raise errors.not_resource_owner("Florist does not own this fulfillment")
    # State: only from ASSIGNED.
    if rec["status"] != "ASSIGNED":
        raise errors.invalid_state("Accept is only defined from ASSIGNED")
    # Cross-entity precondition: linked order must be BOOKED.
    order = store.orders.get(rec["order_id"])
    if order is None or order["fulfillment_status"] != "BOOKED":
        raise errors.precondition_not_met("Linked order must be BOOKED")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return success(public(rec))


# ===========================================================================
# Substitutions
# ===========================================================================
@bp.route("/floral/substitutions", methods=["POST"])
def create_substitution():
    user_id, role = require_auth()
    require_role(role, {"Florist", "Dispatcher"})
    body = get_body()
    require_fields(body, ["order_id", "florist_id", "removed_stem",
                          "added_stem", "price_delta_cents"])
    order_id = as_str(body, "order_id")
    florist_id = as_str(body, "florist_id")
    removed_stem = as_str(body, "removed_stem")
    added_stem = as_str(body, "added_stem")
    price_delta = as_int(body, "price_delta_cents")

    # Ownership: a Florist may only act under its own identity.
    if role == "Florist" and florist_id != user_id:
        raise errors.not_resource_owner("Florist identity mismatch")

    # Existence: FKs left-to-right.
    order = store.orders.get(order_id)
    if order is None:
        raise errors.not_found("order_id not found")
    if florist_id not in store.florists:
        raise errors.not_found("florist_id not found")

    arrangement = store.arrangements[order["arrangement_id"]]
    policy = arrangement["substitution_policy"]

    # Policy validation (priority 10).
    if policy == "NONE":
        raise errors.ApiError(errors.ERR_SUBSTITUTION_NOT_ALLOWED, 409,
                              "Substitutions are not allowed for this arrangement")
    if policy == "SAME_VALUE":
        if price_delta > 0:
            raise errors.ApiError(errors.ERR_SUBSTITUTION_NOT_ALLOWED, 409,
                                  "SAME_VALUE forbids price-raising swaps")
    if policy == "FLORIST_CHOICE":
        existing_sum = sum(
            s["price_delta_cents"] for s in store.substitutions.values()
            if s["order_id"] == order_id and s["accepted"])
        cap = pricing.substitution_cap_cents(arrangement)
        if existing_sum + price_delta > cap:
            raise errors.ApiError(errors.ERR_SUBSTITUTION_NOT_ALLOWED, 409,
                                  "Substitution would exceed the cap")

    rec = make_record()
    rec.update({
        "order_id": order_id,
        "florist_id": florist_id,
        "removed_stem": removed_stem,
        "added_stem": added_stem,
        "price_delta_cents": price_delta,
        "accepted": True,
    })
    store.substitutions[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/substitutions/<sid>", methods=["GET"])
def get_substitution(sid):
    _, role = require_auth()
    require_role(role, {"Florist", "Dispatcher", "CatalogAdmin"})
    rec = store.substitutions.get(sid)
    if rec is None:
        raise errors.not_found("Substitution not found")
    return success(public(rec))


@bp.route("/floral/substitutions", methods=["GET"])
def list_substitutions():
    _, role = require_auth()
    require_role(role, {"Florist", "Dispatcher", "CatalogAdmin"})
    limit, offset = parse_pagination()
    rows = list(store.substitutions.values())
    order_id = request.args.get("order_id")
    florist_id = request.args.get("florist_id")
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if florist_id is not None:
        rows = [r for r in rows if r["florist_id"] == florist_id]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


# ===========================================================================
# Zone delivery slots (read)
# ===========================================================================
@bp.route("/floral/zones/<zid>/delivery-slots", methods=["GET"])
def zone_delivery_slots(zid):
    _, role = require_auth()
    require_role(role, {"Dispatcher", "CatalogAdmin"})
    if zid not in store.zones:
        raise errors.not_found("Zone not found")
    limit, offset = parse_pagination()
    rows = [s for s in store.delivery_slots.values() if s["zone_id"] == zid]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)
