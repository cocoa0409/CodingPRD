"""StaleReturn endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_field, make_entity, touch, lookup, list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN_FOR_ROLE,
    ERR_SEGREGATION_OF_DUTIES, ERR_RETURN_WINDOW_CLOSED, ERR_STORE_SUSPENDED,
    ERR_STALE_CREDIT_CAP_EXCEEDED, ERR_NOT_FOUND,
)
from services.calculations import (
    compute_stale_credit, parse_iso_z, CREDIT_CAP_CENTS,
)

bp = Blueprint("stale_returns", __name__)

RETURN_WINDOW_HOURS = 72


def _serialize(ret):
    return dict(ret)


def _validate_lines_payload(lines, require_batch_baked=True):
    if not isinstance(lines, list) or not lines:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array", 400)
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each line must be an object", 400)
        bid = ln.get("batch_id")
        qty = ln.get("qty")
        if not isinstance(bid, str) or not bid:
            raise ApiError(ERR_INVALID_REQUEST, "line batch_id required", 400)
        batch = DB.batches.get(bid)
        if batch is None:
            raise ApiError(ERR_NOT_FOUND, f"batch {bid} not found", 404)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "line qty must be a positive integer", 400)
        out.append({"batch_id": bid, "qty": qty, "_batch": batch})
    return out


def _check_return_window(lines_with_batch):
    """Reject if any line's bake_completed_at is more than 72h before pickup clock."""
    for ln in lines_with_batch:
        batch = ln["_batch"]
        bake = batch.get("bake_completed_at")
        if bake is None:
            continue
        bake_dt = parse_iso_z(bake)
        if DB.clock - bake_dt > timedelta(hours=RETURN_WINDOW_HOURS):
            raise ApiError(ERR_RETURN_WINDOW_CLOSED, "Stale pickup more than 72h after bake", 409)


@bp.route("/bakery/stale-returns", methods=["POST"])
def create_return():
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    data = body()
    store_id = req_string(data, "store_id")
    store = lookup(DB.stores, store_id, "store")
    route_stop_id = req_string(data, "route_stop_id")
    stop = lookup(DB.route_stops, route_stop_id, "route stop")
    lines = req_field(data, "lines")

    lines_with_batch = _validate_lines_payload(lines)

    if stop.get("status") != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, "Stop is not DELIVERED", 409)

    _check_return_window(lines_with_batch)

    stripped_lines = [{"batch_id": ln["batch_id"], "qty": ln["qty"]} for ln in lines_with_batch]
    provisional = compute_stale_credit(store, stripped_lines, DB.clock)

    ret = make_entity({
        "store_id": store_id,
        "route_stop_id": route_stop_id,
        "lines": stripped_lines,
        "verified_lines": None,
        "provisional_credit_cents": provisional,
        "final_credit_cents": None,
        "credited_amount_cents": None,
        "dispute_round": 0,
        "recorded_by_driver_id": user_id,
        "status": "PENDING_VERIFICATION",
        # Original creation clock, used by verified variant age recomputation.
        "created_at_logical": DB.clock_iso(),
    })
    DB.stale_returns[ret["id"]] = ret

    # Accrue into route.returned_stale_units
    route = DB.routes.get(stop.get("route_id"))
    if route is not None:
        qty_total = sum(int(ln["qty"]) for ln in stripped_lines)
        route["returned_stale_units"] = int(route.get("returned_stale_units") or 0) + qty_total
        touch(route)

    return success_object(_serialize(ret), status=201)


@bp.route("/bakery/stale-returns/<rid>", methods=["GET"])
def get_return(rid):
    get_auth()
    ret = lookup(DB.stale_returns, rid, "stale return")
    return success_object(_serialize(ret))


@bp.route("/bakery/stale-returns", methods=["GET"])
def list_returns():
    get_auth()
    filters = {
        "store_id": request.args.get("store_id"),
        "route_stop_id": request.args.get("route_stop_id"),
        "status": request.args.get("status"),
    }
    return list_response([_serialize(r) for r in DB.stale_returns.values()], filters)


@bp.route("/bakery/stale-returns/<rid>/verify", methods=["POST"])
def verify_return(rid):
    user_id, role = get_auth()
    require_role(role, {"QALead"})
    ret = lookup(DB.stale_returns, rid, "stale return")
    if ret.get("status") != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, "Return is not PENDING_VERIFICATION", 409)
    if user_id == ret.get("recorded_by_driver_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Verifier must differ from recording driver", 403)
    data = body()
    verified_lines_raw = req_field(data, "verified_lines")
    lines_with_batch = _validate_lines_payload(verified_lines_raw)
    verified_lines = [{"batch_id": ln["batch_id"], "qty": ln["qty"]} for ln in lines_with_batch]

    store = DB.stores.get(ret["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)

    # Verified variant: age recomputed at ORIGINAL creation clock
    pickup_clock = parse_iso_z(ret.get("created_at_logical") or ret.get("created_at"))
    final_credit = compute_stale_credit(store, verified_lines, pickup_clock)

    ret["verified_lines"] = verified_lines
    ret["final_credit_cents"] = final_credit
    ret["status"] = "VERIFIED"
    touch(ret)

    store["lifetime_stale_units"] = int(store.get("lifetime_stale_units") or 0) + sum(
        int(ln["qty"]) for ln in verified_lines
    )
    touch(store)

    return success_object(_serialize(ret))


@bp.route("/bakery/stale-returns/<rid>/dispute", methods=["POST"])
def dispute_return(rid):
    user_id, role = get_auth()
    require_role(role, {"StoreReceiver"})
    ret = lookup(DB.stale_returns, rid, "stale return")
    if user_id != ret.get("store_id"):
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "StoreReceiver does not own this return", 403)
    if ret.get("status") != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, "Return is not VERIFIED", 409)
    ret["status"] = "DISPUTED"
    touch(ret)
    return success_object(_serialize(ret))


@bp.route("/bakery/stale-returns/<rid>/resolve-dispute", methods=["POST"])
def resolve_dispute(rid):
    user_id, role = get_auth()
    require_role(role, {"QALead"})
    ret = lookup(DB.stale_returns, rid, "stale return")
    if ret.get("status") != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, "Return is not DISPUTED", 409)
    data = body()
    verified_lines_raw = req_field(data, "verified_lines")
    lines_with_batch = _validate_lines_payload(verified_lines_raw)
    verified_lines = [{"batch_id": ln["batch_id"], "qty": ln["qty"]} for ln in lines_with_batch]

    store = DB.stores.get(ret["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)

    pickup_clock = parse_iso_z(ret.get("created_at_logical") or ret.get("created_at"))
    final_credit = compute_stale_credit(store, verified_lines, pickup_clock)

    ret["verified_lines"] = verified_lines
    ret["final_credit_cents"] = final_credit
    ret["dispute_round"] = int(ret.get("dispute_round") or 0) + 1
    ret["status"] = "VERIFIED"
    touch(ret)
    return success_object(_serialize(ret))


@bp.route("/bakery/stale-returns/<rid>/credit", methods=["POST"])
def credit_return(rid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    ret = lookup(DB.stale_returns, rid, "stale return")
    if ret.get("status") != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, "Return is not VERIFIED", 409)
    store = DB.stores.get(ret["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)
    if store.get("status") != "ACTIVE":
        raise ApiError(ERR_STORE_SUSPENDED, "Store is SUSPENDED", 409)
    final_credit = int(ret.get("final_credit_cents") or 0)
    if final_credit > CREDIT_CAP_CENTS:
        raise ApiError(ERR_STALE_CREDIT_CAP_EXCEEDED, "final_credit_cents exceeds 50000", 409)
    ret["credited_amount_cents"] = final_credit
    ret["status"] = "CREDITED"
    touch(ret)
    store["credit_balance_cents"] = int(store.get("credit_balance_cents") or 0) + final_credit
    touch(store)
    return success_object(_serialize(ret))


@bp.route("/bakery/stale-returns/<rid>/reverse-credit", methods=["POST"])
def reverse_credit(rid):
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    ret = lookup(DB.stale_returns, rid, "stale return")
    if ret.get("status") != "CREDITED":
        raise ApiError(ERR_INVALID_STATE, "Return is not CREDITED", 409)
    store = DB.stores.get(ret["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)
    credited = int(ret.get("credited_amount_cents") or 0)
    store["credit_balance_cents"] = int(store.get("credit_balance_cents") or 0) - credited
    touch(store)
    ret["status"] = "REVERSED"
    touch(ret)
    return success_object(_serialize(ret))


@bp.route("/bakery/stale-returns/<rid>/reject", methods=["POST"])
def reject_return(rid):
    _, role = get_auth()
    require_role(role, {"QALead"})
    ret = lookup(DB.stale_returns, rid, "stale return")
    if ret.get("status") != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, "Return is not PENDING_VERIFICATION", 409)
    ret["status"] = "REJECTED"
    touch(ret)
    return success_object(_serialize(ret))
