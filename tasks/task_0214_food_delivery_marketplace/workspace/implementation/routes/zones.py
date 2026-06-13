"""Zone endpoints (PRD §3.1)."""
from flask import Blueprint

import common
import lookups
from db import store
from middleware import get_user_context, require_roles
from response import success, list_success
from serializers import serialize_zone

bp = Blueprint("zones", __name__)

ALL_ROLES = ["PlatformAdmin", "Restaurant", "Dasher", "Customer"]


@bp.route("/zones", methods=["POST"])
def create_zone():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin"])
    body = common.get_json_body()

    name = common.require_str(body, "name")
    base_delivery_fee_cents = common.require_int(body, "base_delivery_fee_cents", minimum=0)
    per_km_fee_cents = common.require_int(body, "per_km_fee_cents", minimum=0)
    small_order_threshold_cents = common.require_int(body, "small_order_threshold_cents")
    small_order_fee_cents = common.require_int(body, "small_order_fee_cents", minimum=0)
    delivery_fee_cap_cents = common.require_int(body, "delivery_fee_cap_cents")
    dasher_min_guarantee_cents = common.require_int(body, "dasher_min_guarantee_cents")
    dasher_per_km_pay_cents = common.require_int(body, "dasher_per_km_pay_cents")
    dasher_base_pay_cents = common.require_int(body, "dasher_base_pay_cents")

    service_fee_bps = common.optional_int(body, "service_fee_bps", default=0, minimum=0)
    surge_tier_1_demand = common.optional_int(body, "surge_tier_1_demand", default=5)
    surge_tier_2_demand = common.optional_int(body, "surge_tier_2_demand", default=10)
    surge_multiplier_tier_0 = common.optional_number(body, "surge_multiplier_tier_0", default=1.0)
    surge_multiplier_tier_1 = common.optional_number(body, "surge_multiplier_tier_1", default=1.25)
    surge_multiplier_tier_2 = common.optional_number(body, "surge_multiplier_tier_2", default=1.6)

    z = common.init_common(versioned=True)
    z.update({
        "name": name,
        "base_delivery_fee_cents": base_delivery_fee_cents,
        "per_km_fee_cents": per_km_fee_cents,
        "small_order_threshold_cents": small_order_threshold_cents,
        "small_order_fee_cents": small_order_fee_cents,
        "service_fee_bps": service_fee_bps,
        "surge_tier_1_demand": surge_tier_1_demand,
        "surge_tier_2_demand": surge_tier_2_demand,
        "surge_multiplier_tier_0": surge_multiplier_tier_0,
        "surge_multiplier_tier_1": surge_multiplier_tier_1,
        "surge_multiplier_tier_2": surge_multiplier_tier_2,
        "delivery_fee_cap_cents": delivery_fee_cap_cents,
        "dasher_min_guarantee_cents": dasher_min_guarantee_cents,
        "dasher_per_km_pay_cents": dasher_per_km_pay_cents,
        "dasher_base_pay_cents": dasher_base_pay_cents,
    })
    store.zones[z["id"]] = z
    return success(serialize_zone(z), status=201)


@bp.route("/zones", methods=["GET"])
def list_zones():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = common.parse_pagination()
    items = common.sorted_by_creation(list(store.zones.values()))
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_zone(z) for z in page], limit, offset, total)


@bp.route("/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    z = lookups.get_zone(zone_id)
    return success(serialize_zone(z))
