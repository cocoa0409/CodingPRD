"""loop_target_pinning, loop_segment_durations and loop_adjusted_total."""

from decimal import Decimal

from constants import (
    MAX_COMBINED_RELIEF,
    MAX_OVERRIDE_RELIEF,
    OVERRIDE_RELIEF_FACTOR,
    PF_ESCALATION_PENALTY_SECONDS,
)
from db import db, dec, rhu_int, seconds_between
from services.rollup import active_override, lookup_band

ZERO = Decimal("0")
ONE = Decimal("1")


def combined_relief(restaurant):
    """Tier relief plus override relief, capped at MAX_COMBINED_RELIEF."""
    band = lookup_band(restaurant["cars_per_hour_effective"])
    tier_relief = dec(band["target_relief_pct"])

    override = active_override(restaurant["id"], db.clock)
    if override is None:
        override_relief = ZERO
    elif override["target_relief_pct_override"] is not None:
        override_relief = dec(override["target_relief_pct_override"])
    else:
        derived = dec(override["projected_cars_delta_pct"]) * OVERRIDE_RELIEF_FACTOR
        override_relief = min(MAX_OVERRIDE_RELIEF, max(ZERO, derived))

    return min(MAX_COMBINED_RELIEF, tier_relief + override_relief)


def pin_targets(restaurant, profile):
    """Relieve each segment target and round it, THEN sum the rounded values."""
    factor = ONE + combined_relief(restaurant)
    greet = rhu_int(dec(profile["greet_target_seconds"]) * factor)
    order = rhu_int(dec(profile["order_target_seconds"]) * factor)
    pull_forward = rhu_int(dec(profile["pull_forward_target_seconds"]) * factor)
    window = rhu_int(dec(profile["window_target_seconds"]) * factor)
    return {
        "greet_target_pinned": greet,
        "order_target_pinned": order,
        "pull_forward_target_pinned": pull_forward,
        "window_target_pinned": window,
        "target_total_seconds_pinned": greet + order + pull_forward + window,
    }


def recompute_segments(loop):
    """Durations and breach flags from whatever stamps exist so far."""
    if loop["greet_at"] is not None:
        loop["greet_seconds"] = seconds_between(loop["greet_at"], loop["arrive_at"])
    if loop["greet_at"] is not None and loop["order_complete_at"] is not None:
        loop["order_seconds"] = seconds_between(loop["order_complete_at"], loop["greet_at"])
    if loop["order_complete_at"] is not None and loop["merge_at"] is not None:
        loop["merge_wait_seconds"] = seconds_between(loop["merge_at"], loop["order_complete_at"])
    if loop["order_complete_at"] is not None and loop["window_arrive_at"] is not None:
        loop["pull_forward_seconds"] = seconds_between(
            loop["window_arrive_at"], loop["order_complete_at"])
    if loop["window_arrive_at"] is not None and loop["depart_at"] is not None:
        loop["window_seconds"] = seconds_between(loop["depart_at"], loop["window_arrive_at"])
    if loop["depart_at"] is not None:
        loop["total_seconds"] = seconds_between(loop["depart_at"], loop["arrive_at"])

    flags = []
    pairs = (
        ("GREET", "greet_seconds", "greet_target_pinned"),
        ("ORDER", "order_seconds", "order_target_pinned"),
        ("PULL_FORWARD", "pull_forward_seconds", "pull_forward_target_pinned"),
        ("WINDOW", "window_seconds", "window_target_pinned"),
    )
    for flag, measured, target in pairs:
        value = loop[measured]
        if value is not None and value > loop[target]:
            flags.append(flag)
    loop["breach_flags"] = flags
    return loop


def recompute_adjusted(loop):
    if loop["total_seconds"] is None:
        loop["adjusted_total_seconds"] = None
        return loop

    accuracy_penalty = 0
    for incident in db.accuracy_incidents.values():
        if incident["timer_loop_id"] != loop["id"]:
            continue
        if incident["incident_state"] in ("LOGGED", "REMADE", "CLOSED"):
            accuracy_penalty += incident["penalty_seconds"]

    escalations = 0
    for order in db.pull_forward_orders.values():
        if order["timer_loop_id"] != loop["id"]:
            continue
        if order["pf_state"] != "CANCELLED":
            escalations += order["escalation_count"]

    loop["adjusted_total_seconds"] = (
        loop["total_seconds"] + accuracy_penalty
        + PF_ESCALATION_PENALTY_SECONDS * escalations
    )
    return loop


def next_car_sequence(restaurant_id):
    last = db.car_sequences.get(restaurant_id, 0)
    nxt = last + 1
    db.car_sequences[restaurant_id] = nxt
    return nxt


def live_pull_forwards(loop_id):
    return [row for row in db.pull_forward_orders.values()
            if row["timer_loop_id"] == loop_id and row["pf_state"] in ("ISSUED", "PARKED")]


def slots_of_loop(loop_id, states):
    return [row for row in db.merge_slots.values()
            if row["timer_loop_id"] == loop_id and row["slot_state"] in states]
