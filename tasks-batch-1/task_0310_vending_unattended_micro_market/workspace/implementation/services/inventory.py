"""Derived-field recomputation: slot.on_hand, machine stock/cash/service posture.

Cascade hops follow PRD 2.5 / 3.2 / 3.3:
  lot mutation -> slot.on_hand -> machine.stock_status
Each re-derivation that mutates a resource refreshes updated_at and bumps version
(PRD 2.5), EXCEPT where a workflow prescribes its own version handling.
"""
import math

from db import db, touch


def slot_lots(slot_id):
    return [l for l in db.lots.values() if l["slot_id"] == slot_id]


def available_lots(slot_id):
    """AVAILABLE lots in a slot (status AVAILABLE, not SPOILED/DEPLETED)."""
    return [l for l in db.lots.values()
            if l["slot_id"] == slot_id and l["status"] == "AVAILABLE"]


def recompute_slot_on_hand(slot, bump_version=True):
    """on_hand = sum of remaining_units over the slot's non-expired AVAILABLE lots."""
    new_on_hand = sum(l["remaining_units"] for l in available_lots(slot["id"]))
    if new_on_hand != slot["on_hand"]:
        slot["on_hand"] = new_on_hand
        if bump_version:
            touch(slot)
    return new_on_hand


def derive_stock_status(machine):
    """Derive machine.stock_status from aggregate fill across ACTIVE slots (PRD 3.2).

    aggregate_fill_ratio = sum(slot.on_hand) / sum(slot.capacity) over ACTIVE slots.
      ratio <= par_fill_threshold_pct and total on_hand > 0 -> LOW_STOCK
      total on_hand == 0 (over ACTIVE slots)               -> STOCKOUT
      ratio  > par_fill_threshold_pct                       -> STOCKED
    A machine with no active slots / zero capacity is STOCKOUT.
    """
    active = [s for s in db.slots.values()
              if s["machine_id"] == machine["id"] and s["status"] == "ACTIVE"]
    total_on_hand = sum(s["on_hand"] for s in active)
    total_capacity = sum(s["capacity"] for s in active)

    if total_on_hand == 0:
        return "STOCKOUT"
    if total_capacity == 0:
        # no capacity but somehow on_hand>0 — defensive; treat as STOCKED
        return "STOCKED"
    ratio = total_on_hand / total_capacity
    if ratio <= machine["par_fill_threshold_pct"]:
        return "LOW_STOCK"
    return "STOCKED"


def rederive_machine_stock(machine, bump_version=True):
    new_status = derive_stock_status(machine)
    if new_status != machine["stock_status"]:
        machine["stock_status"] = new_status
        if bump_version:
            touch(machine)
    return new_status


def cash_alert_level(machine):
    """floor(cash_alert_threshold_pct * cash_capacity_cents) (calc cash_alert_check)."""
    return int(math.floor(machine["cash_alert_threshold_pct"] * machine["cash_capacity_cents"]))


def derive_cash_status(machine):
    """>= alert level WARNS (inclusive boundary)."""
    if machine["cash_on_hand_cents"] >= cash_alert_level(machine):
        return "CASH_FULL_WARN"
    return "CASH_OK"


def rederive_machine_cash(machine, bump_version=True):
    new_status = derive_cash_status(machine)
    if new_status != machine["cash_status"]:
        machine["cash_status"] = new_status
        if bump_version:
            touch(machine)
    return new_status


def has_active_blocking_ticket(machine_id):
    """Any ticket with blocking=true and status in {OPEN, IN_PROGRESS, REOPENED}."""
    for t in db.tickets.values():
        if (t["machine_id"] == machine_id and t["blocking"] and
                t["status"] in ("OPEN", "IN_PROGRESS", "REOPENED")):
            return True
    return False


def rederive_machine_service(machine, bump_version=True):
    new_status = "FROZEN" if has_active_blocking_ticket(machine["id"]) else "IN_SERVICE"
    if new_status != machine["service_status"]:
        machine["service_status"] = new_status
        if bump_version:
            touch(machine)
    return new_status
