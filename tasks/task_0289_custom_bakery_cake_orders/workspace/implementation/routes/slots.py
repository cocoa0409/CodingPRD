"""Slot reservations: create (HELD), commit (OCC + overlap + capacity), release, list."""
from flask import Blueprint, request, g

import serializers as S
import validators as V
from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_STALE_ORDER_VERSION, ERR_ROUTE_WINDOW_CONFLICT,
    ERR_PRODUCTION_DAY_FULL,
)
from middleware import require_auth
from response import success, list_response, parse_pagination
from services import calculations as calc
from services.orders import get_order_or_404, assert_owner, order_units

bp = Blueprint("slots", __name__)


def _get_reservation(oid, rid):
    res = store.reservations.get(rid)
    if res is None or res["order_id"] != oid:
        raise err(ERR_NOT_FOUND, "reservation not found")
    return res


@bp.route("/orders/<oid>/slot", methods=["POST"])
@require_auth(["Customer", "DeliveryDispatcher"])
def create_slot(oid):
    order = get_order_or_404(oid)
    assert_owner(order)

    data = V.body()
    mode = V.require_enum(data, "fulfillment_mode", {"PICKUP", "DELIVERY"})
    route_id = None
    window_start = None

    if mode == "DELIVERY":
        route_id = V.require_str(data, "route_id")
        window_start = V.require_int(data, "window_start_min", minimum=0, maximum=1439)
        if route_id not in store.routes:
            raise err(ERR_REFERENCE_NOT_FOUND, "route_id does not resolve")
    else:
        # PICKUP: route_id stays null, window optional/ignored. If a window is
        # provided, validate its range for safety.
        if data.get("window_start_min") is not None:
            window_start = V.optional_int(data, "window_start_min", minimum=0, maximum=1439)
        if data.get("route_id") is not None and data.get("route_id") not in store.routes:
            raise err(ERR_REFERENCE_NOT_FOUND, "route_id does not resolve")

    res = {
        "order_id": oid,
        "fulfillment_mode": mode,
        "route_id": route_id,
        "window_start_min": window_start,
        "status": "HELD",
    }
    store.stamp_create(res)
    store.reservations[res["id"]] = res

    store.touch(order)
    return success(S.reservation(res), status=201)


@bp.route("/orders/<oid>/slot", methods=["GET"])
@require_auth(["Customer", "DeliveryDispatcher", "BakeryStaff", "BakeryManager"])
def list_slots(oid):
    order = get_order_or_404(oid)
    assert_owner(order)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.reservations.values() if r["order_id"] == oid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([S.reservation(r) for r in items], limit, offset)


@bp.route("/orders/<oid>/slot/<rid>/commit", methods=["POST"])
@require_auth(["DeliveryDispatcher"])
def commit_slot(oid, rid):
    order = get_order_or_404(oid)
    res = _get_reservation(oid, rid)

    data = V.body()
    expected_version = V.require_int(data, "expected_order_version")

    # state (priority 6): reservation HELD->COMMITTED defined, and order PROOF_APPROVED
    if res["status"] != "HELD":
        raise err(ERR_INVALID_STATE, "reservation not in HELD state")
    if order["production_status"] != "PROOF_APPROVED":
        raise err(ERR_INVALID_STATE, "order not in PROOF_APPROVED state")

    # OCC (priority 7)
    if expected_version != order["version"]:
        raise err(ERR_STALE_ORDER_VERSION, "stale order version")

    units = order_units(oid)
    pday = store.production_days[order["production_day_id"]]

    # route-window overlap (priority 12) — DELIVERY only
    if res["fulfillment_mode"] == "DELIVERY":
        route = store.routes[res["route_id"]]
        stop = route["stop_minutes"]
        start = res["window_start_min"]
        end = start + stop
        for other in store.reservations.values():
            if other["id"] == rid:
                continue
            if other.get("route_id") != res["route_id"]:
                continue
            if other["status"] != "COMMITTED":
                continue
            o_start = other["window_start_min"]
            o_end = o_start + stop
            # half-open overlap: [start,end) intersects [o_start,o_end)
            if start < o_end and o_start < end:
                raise err(ERR_ROUTE_WINDOW_CONFLICT, "route window conflict")

    # capacity (priority 14)
    if not calc.capacity_admissible(pday, units):
        raise err(ERR_PRODUCTION_DAY_FULL, "production day full")

    # commit
    res["status"] = "COMMITTED"
    store.touch(res)
    pday["units_committed"] += units
    store.touch(pday)
    store.touch(order)
    return success(S.reservation(res), status=200)


@bp.route("/orders/<oid>/slot/<rid>/release", methods=["POST"])
@require_auth(["DeliveryDispatcher"])
def release_slot(oid, rid):
    order = get_order_or_404(oid)
    res = _get_reservation(oid, rid)

    # state: HELD or COMMITTED -> RELEASED
    if res["status"] not in ("HELD", "COMMITTED"):
        raise err(ERR_INVALID_STATE, "reservation already released")

    was_committed = res["status"] == "COMMITTED"
    res["status"] = "RELEASED"
    store.touch(res)

    if was_committed:
        units = order_units(oid)
        pday = store.production_days[order["production_day_id"]]
        pday["units_committed"] -= units
        store.touch(pday)

    return success(S.reservation(res), status=200)
