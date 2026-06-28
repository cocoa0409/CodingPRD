"""Shared business-logic helpers: vial volume bookkeeping, billing reconcile,
and the three domain cascades (PRD 3.4, 3.5, 3.6, 3.7, 3.9).
"""

from decimal import Decimal

import calc
from db import store, touch
from clock import LogicalClock


# --- Vial volume bookkeeping (PRD 3.5) ---------------------------------------

def administered_sum_for_vial(vial_id):
    """Sum of administered volumes from RELEASED/reaction-resolved visits.

    Per PRD 3.5: remaining_volume_ml is prepared_volume_ml less the sum of
    administered volumes from all released or reaction-resolved shot visits
    drawn from this vial.
    """
    total = Decimal("0")
    for v in store.visits.values():
        if v["vial_id"] != vial_id:
            continue
        if v["status"] in ("RELEASED", "REACTION_LOCAL", "REACTION_SYSTEMIC"):
            total += Decimal(str(v["administered_volume_ml"]))
    return total


def recompute_vial_remaining(vial):
    """Recompute remaining_volume_ml and needs_refill for a vial.

    The remaining reflects resolved draws plus any provisional reservation held
    by visits still ADMINISTERED (PRD 3.6: administration provisionally debits).
    """
    prepared = Decimal(str(vial["prepared_volume_ml"]))
    resolved = administered_sum_for_vial(vial["id"])
    # Provisional reservation by currently-open (ADMINISTERED) visits.
    reserved = Decimal("0")
    for v in store.visits.values():
        if v["vial_id"] == vial["id"] and v["status"] == "ADMINISTERED":
            reserved += Decimal(str(v["administered_volume_ml"]))
    remaining = prepared - resolved - reserved
    vial["remaining_volume_ml"] = calc.round2(remaining)
    # needs_refill: true exactly when remaining < 1.0 mL strictly (PRD 3.5).
    vial["needs_refill"] = remaining < Decimal("1.0")


def find_95165_for_vial(vial_id):
    for b in store.billing_entries.values():
        if b.get("vial_id") == vial_id and b["cpt_code"] == "CPT_95165":
            return b
    return None


def reconcile_95165(vial):
    """Reconcile a vial's provisional 95165 entry to FINAL (PRD 3.9).

    Applies only to a POSTED, PROVISIONAL CPT_95165 entry. Final dose units are
    ceil(sum of administered volumes actually drawn from the vial), capped at 10.
    """
    entry = find_95165_for_vial(vial["id"])
    if entry is None:
        return
    if entry["status"] != "POSTED" or entry["variant"] != "PROVISIONAL":
        return
    drawn = administered_sum_for_vial(vial["id"])
    units = calc.final_95165_units(drawn)
    entry["billed_dose_units"] = units
    entry["charge_cents"] = units * calc.PRICE_95165_PER_DOSE_CENTS
    entry["variant"] = "FINAL"
    entry["status"] = "RECONCILED"
    touch(entry)


def close_vial(vial, new_status):
    """Move a vial out of IN_USE and reconcile its prep charge (PRD 3.5)."""
    vial["status"] = new_status
    touch(vial)
    reconcile_95165(vial)


# --- Cascade: lot recall (PRD 3.4) -------------------------------------------

def cascade_lot_recall(lot):
    """Three cascade hops after a lot transitions AVAILABLE -> RECALLED.

    Hop 1: every IN_USE vial backed by this lot -> DISCARDED.
    Hop 2: each such discarded vial's provisional 95165 entry -> RECONCILED.
    Hop 3: any plan whose current_vial_color has no surviving IN_USE vial -> HELD.
    """
    affected_plan_ids = set()
    for vial in list(store.vials.values()):
        if vial["lot_id"] == lot["id"] and vial["status"] == "IN_USE":
            close_vial(vial, "DISCARDED")  # hop 1 + hop 2 (reconcile)
            affected_plan_ids.add(vial["plan_id"])

    # Hop 3: plans whose current_vial_color now has no surviving IN_USE vial.
    for plan_id in affected_plan_ids:
        plan = store.plans.get(plan_id)
        if plan is None or plan["status"] != "ACTIVE":
            continue
        if not _has_in_use_vial_of_color(plan_id, plan["current_vial_color"]):
            plan["status"] = "HELD"
            touch(plan)


def _has_in_use_vial_of_color(plan_id, color):
    for v in store.vials.values():
        if v["plan_id"] == plan_id and v["status"] == "IN_USE" and v["vial_color"] == color:
            return True
    return False


# --- Cascade: plan discontinue (PRD 3.7) -------------------------------------

def cascade_plan_discontinue(plan):
    """All IN_USE vials on the plan -> DISCARDED; reconcile their 95165 entries."""
    for vial in list(store.vials.values()):
        if vial["plan_id"] == plan["id"] and vial["status"] == "IN_USE":
            close_vial(vial, "DISCARDED")


# --- Clock advance: auto-expire vials (PRD 2.7) ------------------------------

def expire_vials_for_clock():
    """Expire IN_USE vials whose beyond-use date is at/before the clock.

    Returns the list of expired vial ids. Each expiry reconciles the vial's
    provisional 95165 entry to FINAL (PRD 2.7).
    """
    expired_ids = []
    now = store.clock.now()
    for vial in list(store.vials.values()):
        if vial["status"] != "IN_USE":
            continue
        bud = LogicalClock.parse(vial["beyond_use_date_iso"])
        if now >= bud:
            close_vial(vial, "EXPIRED")
            expired_ids.append(vial["id"])
    return expired_ids
