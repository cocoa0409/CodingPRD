"""Delivery zones, pickup hubs and pickup windows (PRD 3.1, 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import authz
import cascades
import clock
import constants as C
import guards
import lookup
import store
import validate as V
from routes.common import created, filter_eq, listing, ok, always

bp = Blueprint("catalog", __name__)


# --------------------------------------------------------------------------
# Delivery zones
# --------------------------------------------------------------------------
@bp.post("/delivery-zones")
def create_zone():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "zone_code", "fee_tier", "transit_hours")            # rung 4
    fee_tier = V.enum_field(body["fee_tier"], C.FEE_TIERS, "fee_tier")   # rung 5
    zone_code = V.string_field(body["zone_code"], "zone_code", 1, 32)    # rung 6
    transit_hours = V.pounds_field(body["transit_hours"], "transit_hours")
    serviceable = body.get("is_serviceable")
    serviceable = True if serviceable is None else \
        V.bool_field(serviceable, "is_serviceable")
    guards.unique("DeliveryZone", lambda z: z["zone_code"] == zone_code)  # rung 53
    rec = store.create("DeliveryZone", {
        "zone_code": zone_code, "fee_tier": fee_tier,
        "transit_hours": transit_hours, "is_serviceable": serviceable,
    })
    return created(rec)


# --------------------------------------------------------------------------
# Pickup hubs
# --------------------------------------------------------------------------
@bp.post("/pickup-hubs")
def create_hub():
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "hub_code", "cooler_slots_default")                  # rung 4
    hub_code = V.string_field(body["hub_code"], "hub_code", 1, 32)       # rung 6
    slots = V.int_field(body["cooler_slots_default"], "cooler_slots_default",
                        minimum=1)
    grace = body.get("grace_minutes")
    grace = C.DEFAULT_GRACE_MINUTES if grace is None else \
        V.int_field(grace, "grace_minutes", 0, 480)
    guards.unique("PickupHub", lambda h: h["hub_code"] == hub_code)      # rung 53
    rec = store.create("PickupHub", {
        "hub_code": hub_code, "cooler_slots_default": slots,
        "grace_minutes": grace,
    })
    return created(rec)


# --------------------------------------------------------------------------
# POST /csf/pickup-hubs/{id}/windows
# --------------------------------------------------------------------------
@bp.post("/pickup-hubs/<hid>/windows")
def create_window(hid):
    authz.require_roles(C.ROLE_ADMIN)
    body = V.body_of(request)
    V.require(body, "season_id", "week_index", "opens_at", "closes_at")  # rung 4
    V.id_field(body["season_id"], "season_id")
    week_index = V.int_field(body["week_index"], "week_index", minimum=1)  # rung 6
    opens_at = V.datetime_field(body["opens_at"], "opens_at")
    closes_at = V.datetime_field(body["closes_at"], "closes_at")
    if closes_at <= opens_at:
        raise_validation("closes_at must be strictly after opens_at.")
    # The upper bound of week_index is the season's total_weeks; when the season
    # cannot be resolved the bound is unknowable and rung 7 speaks instead.
    season_peek = lookup.maybe("Season", body["season_id"])
    if season_peek is not None and week_index > season_peek["total_weeks"]:
        raise_validation("week_index must be at most the season's total_weeks.")
    slots = body.get("cooler_slots_total")
    if slots is not None:
        slots = V.int_field(slots, "cooler_slots_total", minimum=1)

    season = lookup.season(body["season_id"])                            # rung 7
    hub = lookup.pickup_hub(hid)                                         # rung 8
    guards.season_not_closed(season)                                     # rung 24
    guards.unique("PickupWindow",
                  lambda w: w["pickup_hub_id"] == hub["id"]
                  and w["season_id"] == season["id"]
                  and w["week_index"] == week_index)                     # rung 53

    total = hub["cooler_slots_default"] if slots is None else slots
    rec = store.create("PickupWindow", {
        "pickup_hub_id": hub["id"], "season_id": season["id"],
        "week_index": week_index, "opens_at": opens_at, "closes_at": closes_at,
        "grace_minutes": hub["grace_minutes"], "cooler_slots_total": total,
        "slots_reserved": 0, "slots_occupied": 0, "slots_forfeited": 0,
        "slots_free": total, "status": "SCHEDULED",
    })
    return created(rec)


def raise_validation(message):
    from errors import ApiError
    raise ApiError("ERR_VALIDATION", message)


@bp.get("/pickup-windows/<wid>")
def read_window(wid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER, C.ROLE_HUB)
    return ok(lookup.pickup_window(wid))


@bp.get("/pickup-windows")
def list_windows():
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_MEMBER, C.ROLE_HUB)
    pred = filter_eq(request.args, "pickup_hub_id", lambda r: r["pickup_hub_id"], always)
    pred = filter_eq(request.args, "season_id", lambda r: r["season_id"], pred)
    pred = filter_eq(request.args, "week_index", lambda r: r["week_index"], pred)
    return listing("PickupWindow", request.args, pred)


# --------------------------------------------------------------------------
# POST /csf/pickup-windows/{id}/open
# --------------------------------------------------------------------------
@bp.post("/pickup-windows/<wid>/open")
def open_window(wid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_HUB)
    window = lookup.pickup_window(wid)                                   # rung 8
    guards.season_not_closed(lookup.maybe("Season", window["season_id"]))  # rung 24
    guards.state_in(window["status"], ("SCHEDULED",))                    # rung 28
    guards.state_require(clock.now() >= window["opens_at"],
                         "The window cannot be opened before opens_at.")
    window["status"] = "OPEN"
    store.touch(window)
    return ok(window)


# --------------------------------------------------------------------------
# POST /csf/pickup-windows/{id}/close
# --------------------------------------------------------------------------
@bp.post("/pickup-windows/<wid>/close")
def close_window(wid):
    authz.require_roles(C.ROLE_ADMIN, C.ROLE_HUB)
    window = lookup.pickup_window(wid)                                   # rung 8
    guards.season_not_closed(lookup.maybe("Season", window["season_id"]))  # rung 24
    # Rung 45 explicitly names closing ("closing it requires it to be OPEN or
    # GRACE"), so the window's own status on this endpoint is rung 45's subject
    # and not rung 28's; reading it the other way round would make rung 45's
    # close clause unreachable behind ERR_INVALID_STATE.
    guards.window_status(window, ("OPEN", "GRACE"))                      # rung 45
    deadline = window["closes_at"] + timedelta(minutes=window["grace_minutes"])
    guards.state_require(clock.now() > deadline,
                         "The window cannot be closed until the grace tail has passed.")

    window["status"] = "CLOSED"
    store.touch(window)
    cascades.no_show_cascade(window)
    # CLOSED -> RECONCILED inside the same request.
    still_staged = any(
        d["fulfillment_status"] == "AT_HUB"
        for d in store.all_of("ShareDelivery")
        if d.get("pickup_window_id") == window["id"])
    if not still_staged:
        window["status"] = "RECONCILED"
    cascades.recompute_slots(window)
    return ok(window)
