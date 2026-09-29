"""Fleet catalogue and per-voyage pricing: cabin categories, allotments, fare rules."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import ALL_ROLES, actor
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("catalog", __name__)

OPERATOR_ROLES = ("RevenueManager", "ReservationAgent", "GroupSalesAgent",
                  "PortOpsCoordinator")
PRICING_READ_ROLES = ("RevenueManager", "ReservationAgent", "GroupSalesAgent")


# ==========================================================================
# CabinCategory
# ==========================================================================
@bp.post("/cabin-categories")
def create_cabin_category():
    actor("RevenueManager")
    data = shape.body()

    code = shape.req_str(data, "code", max_len=8)
    tier_rank = shape.req_int(data, "tier_rank", minimum=1)
    max_occupancy = shape.req_int(data, "max_occupancy", minimum=2, maximum=4)
    spend_lower = shape.req_int(data, "onboard_spend_lower_per_night_cents", minimum=0)
    spend_upper = shape.req_int(data, "onboard_spend_upper_per_night_cents", minimum=0)
    is_guarantee = shape.opt_bool(data, "is_guarantee", False)
    lower_berths = shape.opt_int(data, "lower_berths", 2, allowed=(1, 2))
    upgrade_to_category_id = shape.opt_ref(data, "upgrade_to_category_id")

    # Tier 4 uniqueness: the specific code wins over the generic one.
    for other in store.cabin_categories.values():
        if other["code"] == code:
            raise ApiError("ERR_DUPLICATE_CATEGORY_CODE")
    for other in store.cabin_categories.values():
        if other["tier_rank"] == tier_rank:
            raise ApiError("ERR_DUPLICATE_TIER_RANK")

    # Tier 6: the upgrade target must resolve.
    target = None
    if upgrade_to_category_id is not None:
        target = cascade.category_or_404(upgrade_to_category_id)
        # Tier 17: an edge is legal only toward a strictly richer tier.
        if target["tier_rank"] <= tier_rank:
            raise ApiError("ERR_UPGRADE_PATH_INVALID")

    row = store.stamp_new({})
    row.update({
        "code": code,
        "tier_rank": tier_rank,
        "max_occupancy": max_occupancy,
        "lower_berths": lower_berths,
        "is_guarantee": is_guarantee,
        "onboard_spend_lower_per_night_cents": spend_lower,
        "onboard_spend_upper_per_night_cents": spend_upper,
        "upgrade_to_category_id": upgrade_to_category_id,
        # Stamped once at creation and never re-derived.
        "upgrade_chain_length": calcs.chain_length(target),
    })
    store.cabin_categories[row["id"]] = row
    return created(row)


@bp.get("/cabin-categories/<category_id>")
def read_cabin_category(category_id):
    actor(*ALL_ROLES)
    return object_response(cascade.category_or_404(category_id))


@bp.get("/cabin-categories")
def list_cabin_categories():
    actor(*ALL_ROLES)
    limit, offset = shape.pagination()
    is_guarantee = shape.filter_bool("is_guarantee")
    upgrade_to = shape.filter_str("upgrade_to_category_id")
    code = shape.filter_str("code")

    rows = []
    for row in store.cabin_categories.values():
        if is_guarantee is not None and row["is_guarantee"] != is_guarantee:
            continue
        if upgrade_to is not None and row["upgrade_to_category_id"] != upgrade_to:
            continue
        if code is not None and row["code"] != code:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


# ==========================================================================
# SailingInventory (the allotment)
# ==========================================================================
def new_inventory_row():
    row = store.stamp_new({})
    row.update({
        "sailing_id": None,
        "cabin_category_id": None,
        "physical_cabins": 0,
        "oversell_allowance": 0,
        "effective_oversell_cabins": 0,
        "group_held_cabins": 0,
        "booked_cabins": 0,
        "waitlisted_bookings_count": 0,
        "released_cabins_total": 0,
        "available_cabins": 0,
    })
    return row


@bp.post("/sailing-inventories")
def create_sailing_inventory():
    actor("RevenueManager")
    data = shape.body()

    sailing_id = shape.req_str(data, "sailing_id")
    cabin_category_id = shape.req_str(data, "cabin_category_id")
    physical_cabins = shape.req_int(data, "physical_cabins", minimum=1)
    oversell_allowance = shape.opt_int(data, "oversell_allowance", 0, minimum=0)

    # Tier 6, in the declared field order: sailing_id then cabin_category_id.
    sailing = cascade.sailing_or_404(sailing_id)
    category = cascade.category_or_404(cabin_category_id)

    # Tier 14: only a guarantee category may carry oversell appetite.
    if oversell_allowance > 0 and not category["is_guarantee"]:
        raise ApiError("ERR_OVERSELL_NOT_PERMITTED")

    # Tier 19: at most one allotment per sailing-and-category pair.
    if cascade.inventory_for(sailing_id, cabin_category_id) is not None:
        raise ApiError("ERR_DUPLICATE_INVENTORY")

    row = new_inventory_row()
    row.update({
        "sailing_id": sailing["id"],
        "cabin_category_id": category["id"],
        "physical_cabins": physical_cabins,
        "oversell_allowance": oversell_allowance,
    })
    store.sailing_inventories[row["id"]] = row
    # The availability derivation runs immediately, without moving version off 1.
    cascade.recompute_inventory(row, bump=False)
    return created(row)


@bp.get("/sailing-inventories/<inventory_id>")
def read_sailing_inventory(inventory_id):
    actor(*OPERATOR_ROLES)
    return object_response(cascade.inventory_or_404(inventory_id))


@bp.get("/sailing-inventories")
def list_sailing_inventories():
    actor(*OPERATOR_ROLES)
    limit, offset = shape.pagination()
    sailing_id = shape.filter_str("sailing_id")
    category_id = shape.filter_str("cabin_category_id")

    rows = []
    for row in store.sailing_inventories.values():
        if sailing_id is not None and row["sailing_id"] != sailing_id:
            continue
        if category_id is not None and row["cabin_category_id"] != category_id:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.patch("/sailing-inventories/<inventory_id>")
def patch_sailing_inventory(inventory_id):
    actor("RevenueManager")
    data = shape.body()
    oversell_allowance = shape.req_int(data, "oversell_allowance", minimum=0)
    expected = shape.req_int(data, "expected_inventory_version")

    inv = cascade.inventory_or_404(inventory_id)

    # Tier 9: optimistic concurrency on the allotment's own version.
    if expected != inv["version"]:
        raise ApiError("ERR_STALE_INVENTORY_VERSION")

    category = store.cabin_categories.get(inv["cabin_category_id"])
    # Tier 14: a named category may never be oversold.
    if oversell_allowance > 0 and not (category and category["is_guarantee"]):
        raise ApiError("ERR_OVERSELL_NOT_PERMITTED")

    inv["oversell_allowance"] = oversell_allowance
    cascade.recompute_inventory(inv, bump=False)
    # The write itself always moves the version by exactly 1.
    store.touch(inv)
    return object_response(inv)


# ==========================================================================
# FareRule
# ==========================================================================
def _windows_overlap(open_a, close_a, open_b, close_b):
    """Half-open [close, open) intervals. Touching at an endpoint is not overlap."""
    return close_a < open_b and close_b < open_a


@bp.post("/fare-rules")
def create_fare_rule():
    actor("RevenueManager")
    data = shape.body()

    sailing_id = shape.req_str(data, "sailing_id")
    cabin_category_id = shape.req_str(data, "cabin_category_id")
    window_open = shape.req_int(data, "window_open_days_to_sail", minimum=0, maximum=730)
    window_close = shape.req_int(data, "window_close_days_to_sail", minimum=0)
    if window_open <= window_close:
        raise ApiError("ERR_INVALID_REQUEST")
    base_fare = shape.req_int(data, "base_lower_berth_fare_cents", minimum=1)
    third_fare = shape.req_int(data, "third_berth_fare_cents", minimum=0)
    fourth_fare = shape.req_int(data, "fourth_berth_fare_cents", minimum=0)

    # Tier 6.
    sailing = cascade.sailing_or_404(sailing_id)
    category = cascade.category_or_404(cabin_category_id)

    # Tier 16: no overlapping window for the same sailing and category.
    for other in cascade.fare_rules_of(sailing_id, cabin_category_id):
        if _windows_overlap(window_open, window_close,
                            other["window_open_days_to_sail"],
                            other["window_close_days_to_sail"]):
            raise ApiError("ERR_FARE_WINDOW_OVERLAP")

    # Tier 17: the category must actually exist on the voyage.
    if cascade.inventory_for(sailing_id, cabin_category_id) is None:
        raise ApiError("ERR_CATEGORY_NOT_ON_SAILING")

    row = store.stamp_new({})
    row.update({
        "sailing_id": sailing["id"],
        "cabin_category_id": category["id"],
        "window_open_days_to_sail": window_open,
        "window_close_days_to_sail": window_close,
        "base_lower_berth_fare_cents": base_fare,
        "third_berth_fare_cents": third_fare,
        "fourth_berth_fare_cents": fourth_fare,
        "bookings_pinned_count": 0,
    })
    store.fare_rules[row["id"]] = row
    return created(row)


@bp.get("/fare-rules/<rule_id>")
def read_fare_rule(rule_id):
    actor(*PRICING_READ_ROLES)
    return object_response(cascade.fare_rule_or_404(rule_id))


@bp.get("/fare-rules")
def list_fare_rules():
    actor(*PRICING_READ_ROLES)
    limit, offset = shape.pagination()
    sailing_id = shape.filter_str("sailing_id")
    category_id = shape.filter_str("cabin_category_id")

    rows = []
    for row in store.fare_rules.values():
        if sailing_id is not None and row["sailing_id"] != sailing_id:
            continue
        if category_id is not None and row["cabin_category_id"] != category_id:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)
