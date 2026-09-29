"""Calculations, derived fields and cascades shared by the route modules."""
import clock
import db
from services import constants as K
from services.money import apply_bps, round_half_up


# ===========================================================================
# channel_listing_price
# ===========================================================================
def listing_price_cents(base_price_cents, markup_bps, rounding_mode):
    cent_price = round_half_up(
        base_price_cents * (K.BPS_DENOMINATOR + markup_bps), K.BPS_DENOMINATOR
    )
    if rounding_mode == "NICKEL":
        step = K.NICKEL_STEP_CENTS
        return step * ((cent_price + step - 1) // step)
    return cent_price


# ===========================================================================
# listing_availability_state
# ===========================================================================
def derive_availability_state(listing, channel=None, store=None):
    channel = channel or db.channels.get(listing["channel_id"])
    store = store or db.stores.get(listing["store_id"])
    if listing["suppressed"]:
        return "SUPPRESSED"
    if listing["eighty_sixed"]:
        return "EIGHTY_SIXED"
    if (channel is not None and store is not None
            and channel["throttle_policy"] == "SUPPRESS_ON_THROTTLE"
            and store["throttle_state"] in ("THROTTLED", "PAUSED")):
        return "THROTTLE_SUPPRESSED"
    return "AVAILABLE"


def refresh_listing_availability(listing, channel=None, store=None, force_touch=False):
    """Re-derive availability_state; the record is only touched when it moves."""
    new_state = derive_availability_state(listing, channel, store)
    if new_state != listing["availability_state"]:
        listing["availability_state"] = new_state
        db.touch(listing)
        return True
    if force_touch:
        db.touch(listing)
    return False


def store_listings(store_id):
    return [l for l in db.listings.values() if l["store_id"] == store_id]


def refresh_store_listing_availability(store):
    for listing in store_listings(store["id"]):
        refresh_listing_availability(listing, db.channels.get(listing["channel_id"]), store)


def recompute_channel_listing_count(channel):
    count = sum(1 for l in db.listings.values() if l["channel_id"] == channel["id"])
    if channel["listing_count"] != count:
        channel["listing_count"] = count
        db.touch(channel)


def recompute_menu_version_item_count(version):
    count = sum(1 for i in db.menu_items.values() if i["menu_version_id"] == version["id"])
    if version["item_count"] != count:
        version["item_count"] = count
        db.touch(version)


# ===========================================================================
# store_throttle_state
# ===========================================================================
def throttle_target(store):
    if store["active_menu_version_id"] is None:
        return "PAUSED"
    if store["reserved_prep_slots"] >= K.PAUSE_CAPACITY_MULTIPLIER * store["prep_capacity_per_bucket"]:
        return "PAUSED"
    if store["reserved_prep_slots"] >= store["prep_capacity_per_bucket"]:
        return "THROTTLED"
    return "NORMAL"


# ===========================================================================
# capacity_bucket_load
# ===========================================================================
def bucket_index_for(store, at=None):
    at = at or clock.now()
    local_minute, _day = clock.local_parts(at, store["timezone_offset_minutes"])
    return local_minute // K.BUCKET_MINUTES


def bucket_load(store, bucket_index, exclude_order_id=None):
    count = 0
    for order in db.orders.values():
        if order["store_id"] != store["id"]:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["bucket_index"] != bucket_index:
            continue
        if order["injection_status"] not in K.BUCKET_INJECTION_STATUSES:
            continue
        if order["fulfillment_status"] != "PREPARING":
            continue
        count += 1
    return count


def store_open_window(store, at=None):
    """Return the matching StoreHourWindow, or None when the store is closed."""
    at = at or clock.now()
    local_minute, day_of_week = clock.local_parts(at, store["timezone_offset_minutes"])
    for window in db.hour_windows.values():
        if window["store_id"] != store["id"]:
            continue
        if window["day_of_week"] != day_of_week:
            continue
        if window["opens_at_minute"] <= local_minute < window["closes_at_minute"]:
            return window
    return None


# ===========================================================================
# quote_time_calculation
# ===========================================================================
def _quote_load_count(store, before=None):
    count = 0
    for order in db.orders.values():
        if order["store_id"] != store["id"]:
            continue
        if order["injection_status"] not in K.QUOTE_INJECTION_STATUSES:
            continue
        if order["fulfillment_status"] != "PREPARING":
            continue
        # The CONFIRMED replay counts orders created strictly before the new order.
        # The new order is not stored yet, so every order still in the table that
        # carries a timestamp at or before the cut-off was created before it; a
        # backward clock movement is what makes the comparison bite.
        if before is not None and not (order["created_at"] <= before):
            continue
        count += 1
    return count


def compute_quote(store, fulfillment_mode, variant, at=None, before=None):
    """Returns the quote figures; the caller enforces ERR_QUOTE_WINDOW_EXCEEDED."""
    at = at or clock.now()
    load_count = _quote_load_count(store, before=before)
    prep_minutes = (
        store["base_prep_minutes"]
        + K.LOAD_PAD_MINUTES_PER_ORDER * load_count
        + (K.THROTTLE_PAD_MINUTES if store["throttle_state"] == "THROTTLED" else 0)
    )
    travel_minutes = K.COURIER_TRAVEL_MINUTES if fulfillment_mode == "DELIVERY" else 0
    total_minutes = prep_minutes + travel_minutes
    return {
        "variant": variant,
        "load_count": load_count,
        "prep_minutes": prep_minutes,
        "travel_minutes": travel_minutes,
        "total_minutes": total_minutes,
        "ready_at": clock.plus_minutes(at, total_minutes),
    }


# ===========================================================================
# order_channel_totals
# ===========================================================================
def compute_order_totals(order, lines, channel):
    subtotal = sum(l["line_subtotal_cents"] for l in lines)
    tax = sum(l["line_tax_cents"] for l in lines)
    base_total = sum(l["base_price_cents"] * l["quantity"] for l in lines)
    service_fee = channel["service_fee_cents"]
    tip = order["tip_cents"]
    commission = apply_bps(subtotal + service_fee, channel["commission_bps"])
    order["subtotal_cents"] = subtotal
    order["tax_cents"] = tax
    order["markup_cents"] = subtotal - base_total
    order["service_fee_cents"] = service_fee
    order["commission_cents"] = commission
    order["channel_collected_cents"] = subtotal + tax + service_fee + tip
    order["brand_net_cents"] = subtotal + tax + tip - commission


# ===========================================================================
# courier network occupancy / selection
# ===========================================================================
def occupancy_count(network_id, at=None, exclude_assignment_id=None):
    at = at or clock.now()
    count = 0
    for assignment in db.assignments.values():
        if assignment["courier_network_id"] != network_id:
            continue
        if exclude_assignment_id is not None and assignment["id"] == exclude_assignment_id:
            continue
        if assignment["state"] not in ("OFFERED", "ACCEPTED"):
            continue
        if assignment["offered_at"] <= at <= assignment["occupancy_until"]:
            count += 1
    return count


def open_assignment_count(network_id):
    """An assignment is open while its state is OFFERED or ACCEPTED.

    This is a maintained counter, so it may not depend on the current clock:
    moving the clock is inert and refreshes no derived field.
    """
    return sum(
        1 for assignment in db.assignments.values()
        if assignment["courier_network_id"] == network_id
        and assignment["state"] in ("OFFERED", "ACCEPTED")
    )


def recompute_network_open_assignments(network):
    if network is None:
        return
    count = open_assignment_count(network["id"])
    if network["open_assignment_count"] != count:
        network["open_assignment_count"] = count
        db.touch(network)


def select_courier_network(order, channel):
    at = clock.now()
    candidates = []
    for network in db.courier_networks.values():
        if not network["is_active"]:
            continue
        if not (network["network_type"] == "COURIER"
                or channel["channel_type"] == "MARKETPLACE"):
            continue
        if occupancy_count(network["id"], at) >= network["max_concurrent_assignments"]:
            continue
        candidates.append(network)
    if not candidates:
        return None
    candidates.sort(key=lambda n: (
        n["priority_rank"],
        n["per_delivery_fee_cents"],
        n["handoff_sla_seconds"],
        n["created_at"],
        n["_seq"],
    ))
    return candidates[0]


def order_assignments(order_id, states=None):
    result = [a for a in db.assignments.values() if a["order_id"] == order_id
              and (states is None or a["state"] in states)]
    result.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return result


def withdraw_open_assignments(order, states=("OFFERED", "ACCEPTED")):
    """Move the order's open offers to WITHDRAWN, releasing network capacity."""
    for assignment in order_assignments(order["id"], states):
        assignment["state"] = "WITHDRAWN"
        assignment["occupancy_until"] = clock.now()
        db.touch(assignment)
        recompute_network_open_assignments(
            db.courier_networks.get(assignment["courier_network_id"]))


# ===========================================================================
# handoff_sla_penalty
# ===========================================================================
def handoff_penalty_cents(lateness_seconds):
    if lateness_seconds <= K.HANDOFF_GRACE_SECONDS:
        return 0
    if lateness_seconds <= K.PENALTY_TIER_2_SECONDS:
        return K.PENALTY_TIER_1_CENTS
    if lateness_seconds <= K.PENALTY_TIER_3_SECONDS:
        return K.PENALTY_TIER_2_CENTS
    return K.PENALTY_TIER_3_CENTS


# ===========================================================================
# remittance_settlement
# ===========================================================================
def statement_orders(statement_id):
    orders = [o for o in db.orders.values() if o["remittance_statement_id"] == statement_id]
    orders.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return orders


def statement_accepted_adjustments(statement_id):
    return [a for a in db.adjustments.values()
            if a["remittance_statement_id"] == statement_id and a["state"] == "ACCEPTED"]


def select_tier(tier_base_cents):
    if tier_base_cents < K.TIER_2_THRESHOLD_CENTS:
        return "TIER_1"
    if tier_base_cents < K.TIER_3_THRESHOLD_CENTS:
        return "TIER_2"
    return "TIER_3"


def settlement_figures(statement, channel):
    """The normative pipeline: tier base, tier, commission, rebate, net."""
    orders = statement_orders(statement["id"])
    gross = sum(o["subtotal_cents"] + o["service_fee_cents"] for o in orders)
    adjustments = statement_accepted_adjustments(statement["id"])
    adjustment_total = sum(a["amount_cents"] for a in adjustments)
    tier_base = max(0, gross - adjustment_total)
    tier = select_tier(tier_base)
    effective_bps = max(0, channel["commission_bps"] - K.TIER_DISCOUNT_BPS[tier])
    commission = apply_bps(tier_base, effective_bps)
    rebate = apply_bps(tier_base, K.TIER_REBATE_BPS[tier])
    gross_mode_net = tier_base + rebate
    net_mode_net = tier_base - commission + rebate
    net = gross_mode_net if channel["settlement_mode"] == "GROSS_MODE" else net_mode_net
    return {
        "order_count": len(orders),
        "gross_sales_cents": gross,
        "adjustment_total_cents": adjustment_total,
        "tier_base_cents": tier_base,
        "tier": tier,
        "effective_commission_bps": effective_bps,
        "commission_cents": commission,
        "rebate_cents": rebate,
        "net_payable_cents": net,
        "gross_mode_net_payable_cents": gross_mode_net,
        "net_mode_net_payable_cents": net_mode_net,
        "open_adjustment_count": count_open_adjustments(statement["id"], orders),
    }


def count_open_adjustments(statement_id, orders=None):
    orders = orders if orders is not None else statement_orders(statement_id)
    order_ids = set(o["id"] for o in orders)
    if not order_ids:
        return 0
    return sum(1 for a in db.adjustments.values()
               if a["order_id"] in order_ids and a["state"] in K.OPEN_ADJUSTMENT_STATES)


def apply_settlement_figures(statement, channel=None):
    channel = channel or db.channels.get(statement["channel_id"])
    figures = settlement_figures(statement, channel)
    changed = False
    for field in ("order_count", "gross_sales_cents", "adjustment_total_cents",
                  "tier_base_cents", "tier", "commission_cents", "rebate_cents",
                  "net_payable_cents", "open_adjustment_count"):
        if statement[field] != figures[field]:
            statement[field] = figures[field]
            changed = True
    if changed:
        db.touch(statement)
    return figures


def recompute_statement_open_adjustments(statement):
    count = count_open_adjustments(statement["id"])
    if statement["open_adjustment_count"] != count:
        statement["open_adjustment_count"] = count
        db.touch(statement)


def statement_for_order(order):
    statement_id = order.get("remittance_statement_id")
    if statement_id is None:
        return None
    return db.statements.get(statement_id)


# ===========================================================================
# order line helpers
# ===========================================================================
def lines_of_order(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


def listing_for(store_id, channel_id, sku):
    for listing in db.listings.values():
        if (listing["store_id"] == store_id and listing["channel_id"] == channel_id
                and listing["sku"] == sku):
            return listing
    return None


# ===========================================================================
# MenuVersion PUBLISHED <-> EXHAUSTED bubble (PRD 3.4)
# ===========================================================================
def bubble_menu_version_exhaustion(version):
    if version is None:
        return
    item_ids = set(i["id"] for i in db.menu_items.values()
                   if i["menu_version_id"] == version["id"])
    if not item_ids:
        return
    relevant = [l for l in db.listings.values() if l["menu_item_id"] in item_ids]
    if not relevant:
        return
    if version["state"] == "PUBLISHED":
        if version["published_store_count"] >= 1 and all(l["eighty_sixed"] for l in relevant):
            version["state"] = "EXHAUSTED"
            db.touch(version)
    elif version["state"] == "EXHAUSTED":
        if any(not l["eighty_sixed"] for l in relevant):
            version["state"] = "PUBLISHED"
            db.touch(version)
