"""Protocol lifecycle helpers: the stop cascade and the titration ladder."""

from datetime import timedelta

import config
from clock import clock, parse_instant
from store import db, ordered, touch
from services.dispensary import apply_reversal, reversible_within_window
from services.money import dec, round_half_up


def protocol_items(protocol_id):
    return ordered(
        [i for i in db.protocol_items.values() if i["protocol_id"] == protocol_id]
    )


def live_items(protocol_id):
    return [i for i in protocol_items(protocol_id) if i["status"] in ("ACTIVE", "HELD")]


def stop_lines(items, reason):
    """Close a set of lines; clears the review anchor and records the reason."""
    for item in items:
        item["status"] = "DISCONTINUED"
        item["next_review_due_at"] = None
        item["discontinue_reason"] = reason
        touch(item)


def complete_lines(items):
    for item in items:
        item["status"] = "COMPLETED"
        item["next_review_due_at"] = None
        touch(item)


def reverse_recent_dispenses(items):
    """Reverse every DISPENSED fill of these lines inside the 14-day window."""
    for item in items:
        for dispense in ordered(
            [d for d in db.dispenses.values() if d["protocol_item_id"] == item["id"]]
        ):
            if dispense["status"] != "DISPENSED":
                continue
            if not reversible_within_window(dispense):
                continue
            apply_reversal(dispense)


def cascade_after_line_stop(protocol):
    """Links 2..4: the protocol re-evaluates, then money and stock unwind."""
    items = protocol_items(protocol["id"])
    if not items:
        return
    if any(i["status"] != "DISCONTINUED" for i in items):
        return
    if protocol["status"] != "ACTIVE":
        return
    protocol["status"] = "DISCONTINUED"
    touch(protocol)
    reverse_recent_dispenses(items)


# --- titration ----------------------------------------------------------------


def decide(baseline, current_score):
    delta = baseline - current_score
    if delta >= config.TITRATION_ADVANCE_DELTA_MIN:
        return "ADVANCE", delta
    if delta >= config.TITRATION_HOLD_DELTA_MIN:
        return "HOLD", delta
    if delta >= config.TITRATION_REDUCE_DELTA_MIN:
        return "REDUCE", delta
    return "DISCONTINUE", delta


def next_dose(decision, dose):
    if decision == "ADVANCE":
        return round_half_up(dec(dose) * config.TITRATION_DOSE_ADVANCE_MULTIPLIER)
    if decision == "REDUCE":
        return round_half_up(dec(dose) * config.TITRATION_DOSE_REDUCE_MULTIPLIER)
    return dose


def next_review(decision, item, decision_at):
    """The anchoring fork: re-anchor on ADVANCE/REDUCE, preserve it on HOLD."""
    interval = timedelta(days=item["titration_interval_days"])
    if decision in ("ADVANCE", "REDUCE"):
        return clock.render(parse_instant(decision_at) + interval)
    if decision == "HOLD":
        previous = item.get("next_review_due_at") or item["created_at"]
        return clock.render(parse_instant(previous) + interval)
    return None
