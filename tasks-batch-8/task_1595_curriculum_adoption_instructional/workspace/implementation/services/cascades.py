"""Cascade / system-transition helpers (PRD §3.3, §3.7, §3.9).

State changes always bump the mutated entity's version (PRD §2.9); derived
counter recomputes refresh updated_at only.
"""

from db import bump, now_clock, refresh, stamp_new, store, new_id
from services.calculations import (compute_official_scores,
                                   lot_available_units,
                                   recompute_open_backorder_count)


# ---------------------------------------------------------------------------
# Close-pilots scoring (PILOT_OPEN -> SCORING, PRD §3.3): for each material of
# the cycle with at least one pilot, compute and persist official_composite
# (trimmed variant) and participation_rate.
# ---------------------------------------------------------------------------


def close_pilots_scoring(cycle):
    for material in store.materials.values():
        if material["cycle_id"] != cycle["id"]:
            continue
        has_pilot = any(
            p["cycle_id"] == cycle["id"] and p["material_id"] == material["id"]
            for p in store.pilots.values()
        )
        if not has_pilot:
            continue
        official, participation = compute_official_scores(material)
        material["official_composite"] = official
        material["participation_rate"] = participation
        refresh(material)


# ---------------------------------------------------------------------------
# Backorder promotion pass (PRD §3.7): rank the material's BACKORDERED orders
# by need_priority DESC, created_at ASC; promote the head to APPROVED while it
# fits available_units; stop at the first order that does not fit
# (head-of-line blocking — later orders are not considered).
# ---------------------------------------------------------------------------


def run_backorder_promotion(material):
    lot = store.inventory_lots.get(material["id"])
    if lot is None:
        return
    backordered = [
        do for do in store.distribution_orders.values()
        if do["material_id"] == material["id"] and do["status"] == "BACKORDERED"
    ]
    backordered.sort(
        key=lambda d: (-d["need_priority"], d["created_at"], d.get("_seq", 0))
    )
    for do in backordered:
        if lot_available_units(lot) >= do["quantity"]:
            do["status"] = "APPROVED"
            bump(do)
        else:
            break  # head-of-line blocking


# ---------------------------------------------------------------------------
# Challenge decision cascades (PRD §3.9)
# ---------------------------------------------------------------------------


def apply_challenge_decision(challenge):
    """Fire the target cascade for a freshly DECIDED challenge. The challenge
    itself (decision/decided_at fields) is updated by the caller.

    The second decision after an appeal is final (PRD §3.9), so the decision
    effect also applies when the target was restored by the first decision
    (material USABLE again / request REAFFIRMED)."""
    decision = challenge["decision"]
    if challenge["target_type"] == "MATERIAL":
        material = store.materials.get(challenge["target_id"])
        if material is None:
            return
        availability = material["availability_status"]
        if decision == "UPHELD":
            # UPHELD returns availability from UNDER_CHALLENGE to USABLE.
            if availability in ("UNDER_CHALLENGE", "RESTRICTED"):
                material["availability_status"] = "USABLE"
                bump(material)
        elif decision == "RESTRICTED":
            if availability != "RESTRICTED" and availability != "REMOVED":
                material["availability_status"] = "RESTRICTED"
                bump(material)
        elif decision == "REMOVED":
            # Reachable from UNDER_CHALLENGE and from RESTRICTED alike.
            if availability != "REMOVED":
                material["availability_status"] = "REMOVED"
                bump(material)
                _material_removal_cascade(material)
    else:  # SUPPLEMENTAL_REQUEST
        sr = store.supplemental_requests.get(challenge["target_id"])
        if sr is None:
            return
        if decision == "UPHELD":
            if sr["status"] == "UNDER_CHALLENGE":
                sr["status"] = "REAFFIRMED"
                bump(sr)
        else:  # RESTRICTED or REMOVED -> REVOKED with encumbrance release
            if sr["status"] in ("UNDER_CHALLENGE", "APPROVED", "REAFFIRMED"):
                sr["status"] = "REVOKED"
                bump(sr)
                ledger = store.ledgers.get(sr["cycle_id"])
                if ledger is not None:
                    ledger["encumbered_total"] -= sr["estimated_cost"]
                    refresh(ledger)


def _material_removal_cascade(material):
    """REMOVED cascade: cancel every DO of the material in REQUESTED /
    APPROVED / BACKORDERED (approved orders release their allocation, which is
    derived so it re-resolves on read), recompute the lot's derived figures,
    and flag replacement_due on the adopting cycle."""
    for do in store.distribution_orders.values():
        if (do["material_id"] == material["id"]
                and do["status"] in ("REQUESTED", "APPROVED", "BACKORDERED")):
            do["status"] = "CANCELLED"
            bump(do)
    lot = store.inventory_lots.get(material["id"])
    if lot is not None:
        refresh(lot)  # derived allocated/available re-resolve on read
    cycle = store.cycles.get(material["cycle_id"])
    if cycle is not None:
        if cycle.get("adopted_material_id") == material["id"]:
            cycle["replacement_due"] = True
            refresh(cycle)
        recompute_open_backorder_count(cycle)


# ---------------------------------------------------------------------------
# Challenge freeze on filing (PRD §3.9)
# ---------------------------------------------------------------------------


def freeze_challenge_target(challenge):
    if challenge["target_type"] == "MATERIAL":
        material = store.materials.get(challenge["target_id"])
        if material is not None and material["availability_status"] == "USABLE":
            material["availability_status"] = "UNDER_CHALLENGE"
            bump(material)
    else:
        sr = store.supplemental_requests.get(challenge["target_id"])
        if sr is not None and sr["status"] in ("APPROVED", "REAFFIRMED"):
            sr["status"] = "UNDER_CHALLENGE"
            bump(sr)


# ---------------------------------------------------------------------------
# Inventory lot upsert on first publisher receipt (PRD §2.11)
# ---------------------------------------------------------------------------


def lot_for_receipt(material_id):
    lot = store.inventory_lots.get(material_id)
    if lot is None:
        lot = {
            "id": new_id(),
            "material_id": material_id,
            "on_hand_units": 0,
            "in_transit_units": 0,
            "delivered_units": 0,
            "total_received_units": 0,
        }
        stamp_new(lot)
        store.inventory_lots[material_id] = lot
    return lot
