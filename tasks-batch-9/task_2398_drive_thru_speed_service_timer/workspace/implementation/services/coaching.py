"""coaching_priority_score (PRD §3.9)."""

from decimal import Decimal

from constants import (
    ACCURACY_NORMALIZER,
    BAND_WEIGHT,
    GAP_NORMALIZER_SECONDS,
    W_ACCURACY,
    W_BAND,
    W_GAP,
)
from db import db, dec, rhu

ZERO = Decimal("0")
ONE = Decimal("1")

SEGMENT_FIELDS = {
    "GREET": ("greet_seconds", "greet_target_pinned"),
    "ORDER": ("order_seconds", "order_target_pinned"),
    "PULL_FORWARD": ("pull_forward_seconds", "pull_forward_target_pinned"),
    "WINDOW": ("window_seconds", "window_target_pinned"),
}


def report_input_loops(report):
    loops = []
    for loop_id in report.get("_input_loop_ids", []):
        loop = db.timer_loops.get(loop_id)
        if loop is not None:
            loops.append(loop)
    return loops


def segment_gap(report, focus_segment):
    loops = report_input_loops(report)

    if focus_segment == "ACCURACY":
        cars_served = report["cars_served"]
        if not cars_served:
            return ZERO
        loop_ids = set(loop["id"] for loop in loops)
        penalties = 0
        for incident in db.accuracy_incidents.values():
            if incident["timer_loop_id"] in loop_ids and incident["incident_state"] in (
                    "LOGGED", "REMADE", "CLOSED"):
                penalties += incident["penalty_seconds"]
        return dec(penalties) / dec(cars_served)

    measured_field, target_field = SEGMENT_FIELDS[focus_segment]
    pairs = [(loop[measured_field], loop[target_field]) for loop in loops
             if loop[measured_field] is not None]
    if not pairs:
        return ZERO
    count = dec(len(pairs))
    observed_mean = dec(sum(pair[0] for pair in pairs)) / count
    target_mean = dec(sum(pair[1] for pair in pairs)) / count
    return max(ZERO, observed_mean - target_mean)


def priority_tier(score):
    if score >= Decimal("70"):
        return "TIER_C_RETRAIN"
    if score >= Decimal("40"):
        return "TIER_B_COACH"
    return "TIER_A_OBSERVE"


def score(report, focus_segment):
    gap = segment_gap(report, focus_segment)
    gap_component = W_GAP * min(ONE, gap / GAP_NORMALIZER_SECONDS)
    accuracy_component = W_ACCURACY * min(
        ONE, dec(report["open_remake_incident_count"]) / ACCURACY_NORMALIZER)
    band_component = W_BAND * BAND_WEIGHT.get(report["attainment_band"], ZERO)
    raw = gap_component + accuracy_component + band_component
    value = rhu(min(Decimal("100"), raw), 2)
    return gap, value, priority_tier(value)
