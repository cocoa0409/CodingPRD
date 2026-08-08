"""Shared cascade machinery (PRD §2.11, §3.1, §3.4, §3.10).

Cascades are never gated: the write gate constrains inbound API writes only.
"""

import calc
import store
from clockutil import clock, shift

SYSTEM_ACTOR = "SYSTEM"
OPEN_TIERS = ("OPEN_TIER_1", "OPEN_TIER_2", "OPEN_TIER_3")


def tier_deadline(tier_entered_at, tier):
    return shift(tier_entered_at, hours=calc.TIER_ACK_SLA_HOURS[tier])


def open_escalation(patient_id, source_flag, opened_by_user_id, note=None,
                    source_referral_id=None, source_screening_id=None,
                    blocking_offering_id=None):
    entered = clock.now_raw()
    return store.insert("escalation", {
        "patient_id": patient_id,
        "source_flag": source_flag,
        "source_referral_id": source_referral_id,
        "source_screening_id": source_screening_id,
        "blocking_offering_id": blocking_offering_id,
        "status": "OPEN_TIER_1",
        "current_tier": 1,
        "opened_by_user_id": opened_by_user_id,
        "acknowledged_by_user_id": None,
        "tier_entered_at": entered,
        "ack_deadline_at": tier_deadline(entered, 1),
        "promotion_count": 0,
        "resolution_reason": None,
        "note": note,
    })


def resolve_resource_escalations(offering):
    """Auto-resolve an offering's open RESOURCE_EXHAUSTED escalations."""
    for escalation in store.all_rows("escalation"):
        if escalation.get("source_flag") != "RESOURCE_EXHAUSTED":
            continue
        if escalation.get("blocking_offering_id") != offering["id"]:
            continue
        if escalation.get("status") not in OPEN_TIERS:
            continue
        escalation["status"] = "RESOLVED"
        escalation["resolution_reason"] = "RESOURCE_RESTORED"
        store.touch(escalation)


def restore_availability(offering, previously_available):
    """Flip EXHAUSTED -> AVAILABLE when units rise from 0, and cascade."""
    if previously_available == 0 and offering["available_units"] > 0:
        offering["availability_state"] = "AVAILABLE"
        offering["exhausted_since"] = None
        resolve_resource_escalations(offering)


def place_hold(offering, units, patient_id):
    """Hold units for a new referral, with the exhaustion cascade."""
    offering["allocated_units"] += units
    offering["available_units"] -= units
    offering["lifetime_allocated_units"] += units
    store.touch(offering)
    if offering["available_units"] == 0:
        offering["availability_state"] = "EXHAUSTED"
        offering["exhausted_since"] = clock.now_raw()
        open_escalation(patient_id, "RESOURCE_EXHAUSTED", SYSTEM_ACTOR,
                        blocking_offering_id=offering["id"])


def release_hold(referral, offering, bucket):
    """Return held units to availability; ``bucket`` is released_ or expired_units."""
    units = referral["units_requested"]
    previously_available = offering["available_units"]
    offering["allocated_units"] -= units
    offering["available_units"] += units
    offering[bucket] += units
    store.touch(offering)
    restore_availability(offering, previously_available)
    return units


def consume_hold(referral, offering):
    """Delivery: allocated units leave the pool permanently."""
    units = referral["units_requested"]
    offering["allocated_units"] -= units
    offering["delivered_units"] += units
    store.touch(offering)
    return units


def bump_unfulfilled(patient, referral):
    """Count an unfulfilled referral; open an escalation at exactly 2."""
    if patient is None:
        return
    patient["unfulfilled_referral_count"] = patient.get("unfulfilled_referral_count", 0) + 1
    store.touch(patient)
    if patient["unfulfilled_referral_count"] == calc.UNFULFILLED_REFERRAL_ESCALATION_THRESHOLD:
        open_escalation(patient["id"], "REFERRAL_UNFULFILLED", SYSTEM_ACTOR,
                        source_referral_id=referral["id"])


def lapse_referral(referral, lapse_reason, bucket):
    """Move a referral to LAPSED and run the full release cascade."""
    referral["status"] = "LAPSED"
    referral["lapse_reason"] = lapse_reason
    store.touch(referral)
    offering = store.get("offering", referral.get("offering_id"))
    units = 0
    if offering is not None:
        units = release_hold(referral, offering, bucket)
    bump_unfulfilled(store.get("patient", referral.get("patient_id")), referral)
    return units


def void_draft_encounters_for_visit(visit):
    """Documentation VOID cascade: every DRAFT encounter on the visit is voided."""
    for encounter in store.all_rows("encounter"):
        if encounter.get("home_visit_id") != visit["id"]:
            continue
        if encounter.get("status") != "DRAFT":
            continue
        encounter["status"] = "VOIDED"
        store.touch(encounter)


def reverse_charge_line(line, reason):
    """Reverse a POSTED line and give the money back to its award."""
    line["reversed_at"] = clock.now_raw()
    line["reversal_reason"] = reason
    line["status"] = "REVERSED"
    store.touch(line)
    award = store.get("award", line.get("grant_award_id"))
    if award is not None:
        award["committed_cents"] -= line["total_amount_cents"]
        award["remaining_budget_cents"] = award["budget_cap_cents"] - award["committed_cents"]
        store.touch(award)
    return line


def unlock_encounter(encounter):
    """Compensating action: minutes return to the unfunded bucket."""
    encounter["status"] = "SUBMITTED"
    encounter["funding_source"] = "UNFUNDED"
    encounter["funding_claim_id"] = None
    store.touch(encounter)
