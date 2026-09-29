"""State policies, the logical clock, delivery zones and pickup hubs."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import (
    ALL_ROLES,
    ANONYMOUS,
    COOK,
    DINER,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
    guard,
)
from core import ApiError, created, db, new_row, ok, parse_dt, public, touch
from listing import list_rows

bp = Blueprint("config", __name__)

ZONE_READ_ROLES = [ANONYMOUS, COOK, DINER, PLATFORM_ADMIN]
HUB_READ_ROLES = [ANONYMOUS, COOK, DINER, FINANCE_OPERATOR, PLATFORM_ADMIN]


# ------------------------------------------------------------- state policies
@bp.route("/state-policies", methods=["POST"])
@guard([PLATFORM_ADMIN])
def create_state_policy():
    body = v.body()
    state_code = v.s_str(body, "state_code", 2, 2)
    if not v.STATE_CODE_RE.match(state_code):
        raise ApiError(v.BAD, "state_code must be exactly two uppercase letters")
    cap = v.s_int(body, "cottage_food_annual_cap_cents", minimum=0)
    kitchen_types = v.s_enum_list(body, "allowed_kitchen_types", v.KITCHEN_TYPES)
    tcs = v.s_bool(body, "tcs_requires_commercial_kitchen")
    shelf = v.s_int(body, "max_shelf_life_days_non_refrigerated", minimum=1)
    label_fields = v.s_str_list(body, "label_required_fields")
    validity = v.s_int(body, "cert_validity_max_days", minimum=1)

    if calc.policy_for_state(state_code) is not None:
        raise ApiError("ERR_DUPLICATE_STATE_POLICY", "state_code %s already registered" % state_code)

    row = new_row(
        db.state_policies,
        {
            "state_code": state_code,
            "cottage_food_annual_cap_cents": cap,
            "allowed_kitchen_types": kitchen_types,
            "tcs_requires_commercial_kitchen": tcs,
            "max_shelf_life_days_non_refrigerated": shelf,
            "label_required_fields": label_fields,
            "cert_validity_max_days": validity,
        },
    )
    return created(public(row))


@bp.route("/state-policies/<policy_id>", methods=["GET"])
@guard(ALL_ROLES)
def get_state_policy(policy_id):
    row = db.state_policies.get(policy_id)
    if row is None:
        raise ApiError("ERR_STATE_POLICY_NOT_FOUND")
    return ok(public(row))


@bp.route("/state-policies", methods=["GET"])
@guard(ALL_ROLES)
def list_state_policies():
    return list_rows(list(db.state_policies.values()), ["state_code"])


# ----------------------------------------------------------------- the clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard([PLATFORM_ADMIN])
def set_clock():
    body = v.body()
    raw, parsed = v.s_dt(body, "to_iso8601")
    db.clock = parsed
    services.reevaluate_all_safety_scores()
    return ok({"current_utc": raw})


# ------------------------------------------------------------- delivery zones
@bp.route("/delivery-zones", methods=["POST"])
@guard([PLATFORM_ADMIN])
def create_zone():
    body = v.body()
    policy_id = v.s_id(body, "state_policy_id")
    zone_code = v.s_str(body, "zone_code", 1, 60)
    state_code = v.s_str(body, "state_code", 2, 2)
    service_mode = v.s_enum(body, "service_mode", v.SERVICE_MODES)
    postal_codes = v.s_str_list(body, "postal_codes", pattern=v.POSTAL_RE)
    max_cold = v.s_int(body, "max_cold_chain_minutes", minimum=1)

    policy = db.state_policies.get(policy_id)
    if policy is None:
        raise ApiError("ERR_STATE_POLICY_NOT_FOUND")
    for zone in db.zones.values():
        if zone["zone_code"] == zone_code:
            raise ApiError("ERR_DUPLICATE_ZONE_CODE", "zone_code %s already exists" % zone_code)
    if state_code != policy["state_code"]:
        raise ApiError("ERR_ZONE_STATE_MISMATCH", "zone state_code must equal the policy state_code")

    row = new_row(
        db.zones,
        {
            "state_policy_id": policy_id,
            "zone_code": zone_code,
            "state_code": state_code,
            "service_mode": service_mode,
            "postal_codes": postal_codes,
            "max_cold_chain_minutes": max_cold,
        },
    )
    return created(public(row))


@bp.route("/delivery-zones/<zone_id>", methods=["GET"])
@guard(ZONE_READ_ROLES)
def get_zone(zone_id):
    row = db.zones.get(zone_id)
    if row is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    return ok(public(row))


@bp.route("/delivery-zones", methods=["GET"])
@guard(ZONE_READ_ROLES)
def list_zones():
    return list_rows(list(db.zones.values()), ["state_policy_id", "state_code", "service_mode"])


# ---------------------------------------------------------------- pickup hubs
@bp.route("/pickup-hubs", methods=["POST"])
@guard([PLATFORM_ADMIN])
def create_hub():
    body = v.body()
    zone_id = v.s_id(body, "delivery_zone_id")
    name = v.s_str(body, "name", 1, 200)
    address = v.s_str(body, "address", 1, 400)
    slots = v.s_int(body, "slot_capacity_orders", minimum=1)
    start_raw, start = v.s_dt(body, "hub_window_start_at")
    end_raw, end = v.s_dt(body, "hub_window_end_at")
    if end <= start:
        raise ApiError(v.BAD, "hub_window_end_at must fall strictly after hub_window_start_at")

    if db.zones.get(zone_id) is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")

    row = new_row(
        db.hubs,
        {
            "delivery_zone_id": zone_id,
            "name": name,
            "address": address,
            "slot_capacity_orders": slots,
            "hub_window_start_at": start_raw,
            "hub_window_end_at": end_raw,
            "assigned_order_count": 0,
            "status": "OPEN",
        },
    )
    return created(public(row))


@bp.route("/pickup-hubs/<hub_id>", methods=["GET"])
@guard(HUB_READ_ROLES)
def get_hub(hub_id):
    row = db.hubs.get(hub_id)
    if row is None:
        raise ApiError("ERR_HUB_NOT_FOUND")
    return ok(public(row))


@bp.route("/pickup-hubs", methods=["GET"])
@guard(HUB_READ_ROLES)
def list_hubs():
    return list_rows(list(db.hubs.values()), ["delivery_zone_id", "status"])


def _hub_routed_orders(window_id):
    """Orders of the window whose zone runs HUB_PICKUP and which hold a slot."""
    out = []
    for order in calc.ordered_window_orders(window_id):
        if order["fulfillment_status"] not in ("ROUTED", "IN_PRODUCTION"):
            continue
        zone = db.zones.get(order["delivery_zone_id"])
        if zone is None or zone["service_mode"] != "HUB_PICKUP":
            continue
        out.append(order)
    return out


@bp.route("/pickup-hubs/<hub_id>/consolidate", methods=["POST"])
@guard([PLATFORM_ADMIN, FINANCE_OPERATOR])
def consolidate_hub(hub_id):
    body = v.body()
    window_id = v.s_id(body, "production_window_id")

    hub = db.hubs.get(hub_id)
    if hub is None:
        raise ApiError("ERR_HUB_NOT_FOUND")
    window = db.windows.get(window_id)
    if window is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND")

    # 17 - the window must have reached its cutoff.
    if db.now() < parse_dt(window["order_cutoff_at"]):
        raise ApiError("ERR_CUTOFF_NOT_REACHED", "the window has not reached order_cutoff_at")
    # 35 - buffered interval collision on the named hub.
    if calc.hub_slot_conflict(hub, window):
        raise ApiError("ERR_HUB_SLOT_CONFLICT", "another window already holds colliding slots")
    # 44 - the hub's zone must be a hub-pickup zone in the cook's state.
    zone = db.zones.get(hub["delivery_zone_id"])
    cook = db.cooks.get(window["cook_id"])
    if (
        zone is None
        or zone["service_mode"] != "HUB_PICKUP"
        or cook is None
        or zone["state_code"] != cook["state_code"]
    ):
        raise ApiError("ERR_HUB_ZONE_INELIGIBLE", "hub zone is not eligible for this window")
    # 50 - the consolidation input set must be non-empty.
    eligible = _hub_routed_orders(window_id)
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_ORDERS", "no hub-routed order of that window is consolidatable")

    previous_hubs = set()
    for order in eligible:
        if order["pickup_hub_id"] != hub_id:
            if order["pickup_hub_id"]:
                previous_hubs.add(order["pickup_hub_id"])
            order["pickup_hub_id"] = hub_id
            touch(order)
    for other in previous_hubs:
        services.recompute_hub_by_id(other)
    services.recompute_hub(hub)

    return ok(
        {
            "pickup_hub_id": hub["id"],
            "production_window_id": window["id"],
            "consolidated_order_count": len(eligible),
            "assigned_order_count": int(hub["assigned_order_count"]),
            "status": hub["status"],
        }
    )
