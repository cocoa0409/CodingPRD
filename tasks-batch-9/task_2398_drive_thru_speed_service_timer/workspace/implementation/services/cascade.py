"""Shared multi-hop side effects (slot forfeits/releases, pull-forward sweeps)."""

from db import base_row, db, snapshot, touch, touch_if_changed
from services.loops import recompute_adjusted


def _slots_of_loop(loop_id, states):
    return [row for row in db.merge_slots.values()
            if row["timer_loop_id"] == loop_id and row["slot_state"] in states]


def _live_pull_forwards(loop_id):
    return [row for row in db.pull_forward_orders.values()
            if row["timer_loop_id"] == loop_id and row["pf_state"] in ("ISSUED", "PARKED")]


def release_committed_slot(loop):
    """Cascade hop 1 of depart: COMMITTED -> RELEASED."""
    for slot in _slots_of_loop(loop["id"], ("COMMITTED",)):
        before = snapshot(slot)
        slot["slot_state"] = "RELEASED"
        touch_if_changed(slot, before)


def forfeit_slots(loop, states):
    for slot in _slots_of_loop(loop["id"], states):
        before = snapshot(slot)
        slot["slot_state"] = "FORFEITED"
        touch_if_changed(slot, before)


def clear_live_pull_forwards(loop):
    for order in _live_pull_forwards(loop["id"]):
        order["pf_state"] = "CLEARED"
        order["cleared_at"] = db.clock
        touch(order)


def cancel_live_pull_forwards(loop):
    changed = False
    for order in _live_pull_forwards(loop["id"]):
        order["pf_state"] = "CANCELLED"
        touch(order)
        changed = True
    if changed:
        recompute_adjusted(loop)


def auto_issue_remake_pull_forward(loop):
    """Incident cascade hops 1 and 2: auto pull-forward, then slot forfeit."""
    held = _slots_of_loop(loop["id"], ("RESERVED",))
    if not held:
        return None
    order = base_row()
    order.update({
        "restaurant_id": loop["restaurant_id"],
        "timer_loop_id": loop["id"],
        "reason": "REMAKE_OPEN",
        "lag_seconds": 0,
        "issued_at": db.clock,
        "reissued_at": None,
        "cleared_at": None,
        "escalation_count": 0,
        "pf_state": "ISSUED",
    })
    db.pull_forward_orders[order["id"]] = order
    for slot in held:
        before = snapshot(slot)
        slot["slot_state"] = "FORFEITED"
        touch_if_changed(slot, before)
    return order
