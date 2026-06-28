"""Calculation engine (scaffold §1.3, PRD §2.6/§2.7/§3.3/§3.4/§3.6/§3.7/§3.8).

All monetary/ratio outputs round half-up. Room counts are integers; ceilings
use floor(). Division by zero yields 0.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db, clock_date
from services.common import (
    round_money,
    round_ratio,
    round_half_up_int,
)

# Calculation constants (scaffold §1.3).
PACE_FACTOR = Decimal("1.5")
TRAILING_DAILY_PICKUP = 2
LRV_SCARCITY_ROOMS = 5
LRV_PREMIUM_PCT = Decimal("0.20")
PARITY_TOLERANCE = Decimal("0.02")


# ----------------------------------------------------------------------------
# Property lookups via the room-type chain
# ----------------------------------------------------------------------------
def property_for_room_type(room_type_id):
    rt = db.room_types.get(room_type_id)
    if rt is None:
        return None
    return db.properties.get(rt["property_id"])


def property_for_inventory_day(inv):
    return property_for_room_type(inv["room_type_id"])


def oversell_ceiling(physical_capacity, overbooking_limit_pct):
    """floor(physical_capacity * (1 + overbooking_limit_pct)) — PRD §2.7."""
    val = Decimal(str(physical_capacity)) * (Decimal("1") + Decimal(str(overbooking_limit_pct)))
    return int(math.floor(val))


# ----------------------------------------------------------------------------
# availability (scaffold calc: availability) — recompute derived fields
# ----------------------------------------------------------------------------
def group_held_for(room_type_id, stay_date_iso):
    """Sum rooms_per_night over COMMITTED GroupBlocks of the same RoomType whose
    [arrival, arrival+nights) interval contains stay_date."""
    total = 0
    for gb in db.group_blocks.values():
        if gb["room_type_id"] != room_type_id:
            continue
        if gb["status"] != "COMMITTED":
            continue
        if _block_covers(gb, stay_date_iso):
            total += gb["rooms_per_night"]
    return total


def _block_covers(gb, stay_date_iso):
    """True if stay_date is within [arrival_date, arrival_date+nights)."""
    arrival = gb["arrival_date"]  # stored as 'YYYY-MM-DD' night key
    nights = gb["nights"]
    return arrival <= stay_date_iso < _add_days_key(arrival, nights)


def _add_days_key(day_key, n):
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dt = dt + timedelta(days=n)
    return dt.strftime("%Y-%m-%d")


def recompute_availability(inv):
    """rooms_sold, rooms_available, group_held_rooms — scaffold calc availability."""
    prop = property_for_inventory_day(inv)
    ob = prop["overbooking_limit_pct"] if prop else 0.0
    held = group_held_for(inv["room_type_id"], inv["stay_date_key"])
    inv["group_held_rooms"] = held
    rooms_sold = inv["transient_sold_rooms"] + held
    inv["rooms_sold"] = rooms_sold
    ceiling = oversell_ceiling(inv["physical_capacity"], ob)
    inv["rooms_available"] = max(0, ceiling - rooms_sold)
    return inv


def ceiling_for_inv(inv):
    prop = property_for_inventory_day(inv)
    ob = prop["overbooking_limit_pct"] if prop else 0.0
    return oversell_ceiling(inv["physical_capacity"], ob)


# ----------------------------------------------------------------------------
# pickup_forecast (scaffold calc: pickup_forecast) — two variants
# ----------------------------------------------------------------------------
def days_to_arrival(stay_date_key):
    """max(0, whole days between logical clock date and stay_date) — PRD §3.3."""
    from datetime import datetime, timezone
    clock = clock_date()
    stay = datetime.strptime(stay_date_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    delta_days = (stay - clock).days
    return max(0, delta_days)


def pickup_forecast(inv, method="SNAPSHOT_PACE"):
    """Returns (forecast_final_sold:int, forecast_occupancy_pct:float).

    Transient-only (group_held_rooms excluded). Capped at oversell ceiling.
    """
    sold = inv["transient_sold_rooms"]
    if method == "TRAILING_PICKUP":
        dta = days_to_arrival(inv["stay_date_key"])
        raw = Decimal(str(sold)) + (Decimal(TRAILING_DAILY_PICKUP) * Decimal(dta))
    else:  # SNAPSHOT_PACE (default)
        raw = Decimal(str(sold)) * PACE_FACTOR
    final = round_half_up_int(raw)
    ceiling = ceiling_for_inv(inv)
    final = min(final, ceiling)
    cap = inv["physical_capacity"]
    if cap == 0:
        occ = 0.0
    else:
        occ = round_ratio(Decimal(final) / Decimal(cap))
    return final, occ


def snapshot_pace_final_sold(inv):
    final, _ = pickup_forecast(inv, "SNAPSHOT_PACE")
    return final


def snapshot_pace_occupancy(inv):
    _, occ = pickup_forecast(inv, "SNAPSHOT_PACE")
    return occ


# ----------------------------------------------------------------------------
# rate_yield (scaffold calc: rate_yield) — pinned order
# ----------------------------------------------------------------------------
def compute_yield(plan, inv, property_id):
    """Returns (yielded_rate:float, applied_yield_rule_id, last_room_premium_applied).

    Order (PRD §3.4): basis occ -> at-most-one rule -> LRV premium -> clamp ->
    round (premium then clamp then round, pinned).
    """
    # Step 1: forecast occupancy basis (SNAPSHOT_PACE).
    basis_occ = Decimal(str(snapshot_pace_occupancy(inv)))

    # Step 2: choose at most one eligible enabled YieldRule of the property.
    eligible = [
        r for r in db.yield_rules.values()
        if r["property_id"] == property_id
        and r["enabled"]
        and basis_occ >= Decimal(str(r["occupancy_threshold_pct"]))
    ]
    chosen = None
    if eligible:
        # Highest occupancy_threshold_pct; tie-break lower priority; then earlier created_at.
        chosen = sorted(
            eligible,
            key=lambda r: (
                -Decimal(str(r["occupancy_threshold_pct"])),
                r["priority"],
                r["created_at"],
                r.get("_seq", 0),
            ),
        )[0]

    running = Decimal(str(plan["requested_rate_for_calc"]))
    if chosen is not None:
        running = running * (Decimal("1") + Decimal(str(chosen["adjustment_pct"])))

    # Step 3: last-room-value premium.
    last_room_premium_applied = False
    if inv["rooms_available"] <= LRV_SCARCITY_ROOMS:
        running = running * (Decimal("1") + LRV_PREMIUM_PCT)
        last_room_premium_applied = True

    # Step 4: clamp to band (floor first, then ceiling), then round half-up to 2.
    floor_r = Decimal(str(plan["floor_rate"]))
    ceil_r = Decimal(str(plan["ceiling_rate"]))
    clamped = max(floor_r, running)
    clamped = min(ceil_r, clamped)
    yielded = float(clamped.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    applied_rule_id = chosen["id"] if chosen is not None else None
    return yielded, applied_rule_id, last_room_premium_applied


# ----------------------------------------------------------------------------
# group_displacement (scaffold calc: group_displacement) — two variants
# ----------------------------------------------------------------------------
def master_bar_plan(room_type_id):
    for p in db.rate_plans.values():
        if p["room_type_id"] == room_type_id and p["is_master_bar"]:
            return p
    return None


def effective_bar_rate(room_type_id):
    """published_rate if master BAR exists & published; else base_rate if master
    BAR exists; else 0 (PRD §3.7)."""
    mb = master_bar_plan(room_type_id)
    if mb is None:
        return Decimal("0")
    if mb["published_rate"] is not None:
        return Decimal(str(mb["published_rate"]))
    return Decimal(str(mb["base_rate"]))


def compute_displacement(gb, method="LRV"):
    """Returns (displacement_cost:float, recommendation:str)."""
    rpn = gb["rooms_per_night"]
    nights = gb["nights"]
    total_group_rooms = rpn * nights
    group_value = Decimal(str(gb["offered_rate"])) * Decimal(total_group_rooms)
    group_value_rounded = group_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    eff_bar = effective_bar_rate(gb["room_type_id"])

    displaced = Decimal("0")
    for stay_key in _block_night_keys(gb):
        inv = _inv_for(gb["room_type_id"], stay_key)
        # forecast demand: SNAPSHOT_PACE final sold for that night.
        demand = snapshot_pace_final_sold(inv)
        capacity = inv["physical_capacity"]  # NO oversell — true rooms.
        held_excl = _group_held_excluding(gb, stay_key)
        would_be = min(demand, capacity - held_excl)
        spill = max(0, (would_be + rpn) - capacity)
        if spill <= 0:
            continue
        if method == "FORECAST_REV":
            tsr = inv["transient_sold_rooms"]
            denom = tsr if tsr >= 1 else 1
            adr = Decimal(str(inv["transient_revenue"])) / Decimal(denom)
            displaced += Decimal(spill) * adr
        else:  # LRV (default)
            displaced += Decimal(spill) * eff_bar

    displacement_cost = float(displaced.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    gv = float(group_value_rounded)
    recommendation = "ACCEPT" if gv >= displacement_cost else "REJECT"
    return displacement_cost, recommendation


def _group_held_excluding(gb, stay_key):
    """Sum rooms_per_night over COMMITTED blocks of the same RoomType covering
    stay_key, excluding this block."""
    total = 0
    for other in db.group_blocks.values():
        if other["id"] == gb["id"]:
            continue
        if other["room_type_id"] != gb["room_type_id"]:
            continue
        if other["status"] != "COMMITTED":
            continue
        if _block_covers(other, stay_key):
            total += other["rooms_per_night"]
    return total


def _block_night_keys(gb):
    from datetime import datetime, timedelta, timezone
    start = datetime.strptime(gb["arrival_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(gb["nights"])]


def _inv_for(room_type_id, stay_key):
    for inv in db.inventory_days.values():
        if inv["room_type_id"] == room_type_id and inv["stay_date_key"] == stay_key:
            return inv
    return None


# ----------------------------------------------------------------------------
# channel_sync (scaffold calc: channel_sync) — channel_rate + parity_status
# ----------------------------------------------------------------------------
def _direct_mapping(rate_plan_id):
    for m in db.channel_mappings.values():
        if m["rate_plan_id"] == rate_plan_id and m["channel"] == "DIRECT":
            return m
    return None


def _channel_rate_for(mapping, published_rate):
    """manual_rate_override if set, else round(published_rate*(1+markup),2).

    Returns Decimal or None when no rate can be derived (no override and no
    published_rate)."""
    if mapping["manual_rate_override"] is not None:
        return Decimal(str(mapping["manual_rate_override"]))
    if published_rate is None:
        return None
    raw = Decimal(str(published_rate)) * (Decimal("1") + Decimal(str(mapping["markup_pct"])))
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sync_channel(mapping):
    """Set channel_rate and parity_status on a single ChannelMapping.

    PRD §3.6. The DIRECT mapping is always IN_PARITY (its own reference).
    """
    plan = db.rate_plans.get(mapping["rate_plan_id"])
    published_rate = plan["published_rate"] if plan else None

    cr = _channel_rate_for(mapping, published_rate)
    mapping["channel_rate"] = (float(cr) if cr is not None else None)

    # DIRECT mapping is always its own reference -> IN_PARITY.
    if mapping["channel"] == "DIRECT":
        mapping["parity_status"] = "IN_PARITY"
        return mapping

    direct = _direct_mapping(mapping["rate_plan_id"])
    # Without a DIRECT reference or a derivable channel rate, default IN_PARITY.
    if direct is None or cr is None:
        mapping["parity_status"] = "IN_PARITY"
        return mapping

    direct_rate = _channel_rate_for(direct, published_rate)
    if direct_rate is None:
        mapping["parity_status"] = "IN_PARITY"
        return mapping

    net_channel = cr / (Decimal("1") + Decimal(str(mapping["markup_pct"])))
    net_direct = direct_rate / (Decimal("1") + Decimal(str(direct["markup_pct"])))

    if net_channel < net_direct * (Decimal("1") - PARITY_TOLERANCE):
        mapping["parity_status"] = "OUT_OF_PARITY"
    else:
        mapping["parity_status"] = "IN_PARITY"
    return mapping


def resync_plan_channels(rate_plan_id, bump_fn):
    """Re-sync every ChannelMapping under a plan (publish cascade hop 2).

    Each mutated mapping gets its version bumped via bump_fn.
    """
    for m in db.channel_mappings.values():
        if m["rate_plan_id"] != rate_plan_id:
            continue
        sync_channel(m)
        bump_fn(m)


# ----------------------------------------------------------------------------
# property_kpi (scaffold calc: property_kpi)
# ----------------------------------------------------------------------------
def recompute_property_kpi(prop):
    """Recompute occupancy_pct, adr, revpar for the logical clock date (PRD §3.8)."""
    from datetime import datetime, timezone
    clock = clock_date()
    clock_key = clock.strftime("%Y-%m-%d")

    # All InventoryDays across the property's room types whose stay_date == clock date.
    rt_ids = {rt["id"] for rt in db.room_types.values() if rt["property_id"] == prop["id"]}
    invs = [
        inv for inv in db.inventory_days.values()
        if inv["room_type_id"] in rt_ids and inv["stay_date_key"] == clock_key
    ]

    total_available = 0
    total_sold = 0
    total_revenue = Decimal("0")
    for inv in invs:
        recompute_availability(inv)
        total_available += inv["physical_capacity"]
        total_sold += inv["rooms_sold"]
        total_revenue += Decimal(str(inv["transient_revenue"]))

    # Plus committed group revenue for that date.
    for gb in db.group_blocks.values():
        if gb["status"] != "COMMITTED":
            continue
        if gb["room_type_id"] not in rt_ids:
            continue
        if _block_covers(gb, clock_key):
            total_revenue += Decimal(gb["rooms_per_night"]) * Decimal(str(gb["offered_rate"]))

    if total_available == 0:
        prop["occupancy_pct"] = 0
    else:
        prop["occupancy_pct"] = round_ratio(Decimal(total_sold) / Decimal(total_available))

    if total_sold == 0:
        prop["adr"] = 0
    else:
        prop["adr"] = round_money(total_revenue / Decimal(total_sold))

    if total_available == 0:
        prop["revpar"] = 0
    else:
        prop["revpar"] = round_money(total_revenue / Decimal(total_available))

    return prop
