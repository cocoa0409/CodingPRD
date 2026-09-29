"""Compliance posture cascade (PRD 2.9, 3.1, 3.9)."""
from decimal import Decimal

import constants
import db
import util
from services import ledger

ZERO = Decimal("0")


def settle_compliance_state(system):
    """PRD 2.9 precedence, highest first:
    RETIRED_EXEMPT > RETROFIT_MANDATED > CHRONIC_EXCEEDANCE > LEAK_OPEN > COMPLIANT.
    compliance_state is never set from a request body.
    """
    events = ledger.system_events(system["id"])
    previous = system["compliance_state"]
    if system["operational_status"] == "RETIRED":
        state = "RETIRED_EXEMPT"
    elif any(event["status"] == "RETROFIT_MANDATED" for event in events):
        state = "RETROFIT_MANDATED"
    elif system["exceedance_count_12mo"] >= constants.CHRONIC_EXCEEDANCE_COUNT:
        state = "CHRONIC_EXCEEDANCE"
    elif any(event["status"] not in constants.TERMINAL_LEAK_EVENT_STATUSES
             for event in events):
        state = "LEAK_OPEN"
    else:
        state = "COMPLIANT"
    system["compliance_state"] = state
    if state == "RETROFIT_MANDATED" and previous != "RETROFIT_MANDATED":
        system["retrofit_due_on"] = util.add_days(db.now(), constants.RETROFIT_DUE_DAYS)
    return state


def citation_exposure(citations, multiplier):
    """PRD 3.9: each citation is priced and rounded on its own, in payload order,
    and the rounded amounts are then summed. Returns (subtotal, capped_amount).
    """
    subtotal = ZERO
    for citation in citations:
        rate = constants.CITATION_DAILY_RATE[citation["severity"]]
        days = Decimal(int(citation["violation_days"]))
        subtotal = subtotal + util.q2(rate * days * multiplier)
    subtotal = util.q2(subtotal)
    if subtotal > constants.PENALTY_EXPOSURE_CAP:
        return subtotal, constants.PENALTY_EXPOSURE_CAP
    return subtotal, subtotal


def recompute_inspection(inspection, store):
    """Re-price a live inspection against the store's current posture."""
    multiplier = constants.CHRONIC_MULTIPLIER[store["compliance_status"]]
    subtotal, exposure = citation_exposure(inspection["citations"], multiplier)
    inspection["chronic_multiplier_applied"] = multiplier
    inspection["penalty_exposure_usd"] = exposure
    inspection["capped"] = subtotal > constants.PENALTY_EXPOSURE_CAP


def store_inspections(store_id, live_only=True):
    inspections = [
        inspection for inspection in db.values("inspections")
        if inspection["store_id"] == store_id
        and (not live_only or inspection["status"] in constants.LIVE_INSPECTION_STATUSES)
    ]
    inspections.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return inspections


def recompute_store(store):
    """PRD 2.9 steps 5, 6 and 7 -- store aggregates, then every live
    inspection's exposure, then the store's total exposure.
    """
    snap = db.snapshot(store)
    systems = [
        system for system in db.values("systems")
        if system["store_id"] == store["id"]
    ]
    regulated_active = [
        system for system in systems
        if system["operational_status"] == "ACTIVE"
        and system["applicability"] == "REGULATED"
    ]
    total_charge = ZERO
    for system in regulated_active:
        total_charge = total_charge + system["full_charge_lbs"]
    store["total_regulated_charge_lbs"] = util.q1(total_charge)
    store["regulated_system_count"] = len(regulated_active)

    system_ids = {system["id"] for system in systems}
    events = [
        event for event in db.values("leak_events")
        if event["system_id"] in system_ids
    ]
    store["open_leak_event_count"] = len([
        event for event in events
        if event["status"] not in constants.TERMINAL_LEAK_EVENT_STATUSES
    ])
    store["overdue_leak_event_count"] = len([
        event for event in events
        if event["status"] in constants.OVERDUE_LEAK_EVENT_STATUSES
    ])
    store["mandated_retrofit_count"] = len([
        system for system in systems
        if system["compliance_state"] == "RETROFIT_MANDATED"
    ])
    store["chronic_leaker_flag"] = any(
        system["compliance_state"] in ("CHRONIC_EXCEEDANCE", "RETROFIT_MANDATED")
        for system in systems
    )
    vented = ZERO
    for record in ledger.store_records(store["id"]):
        vented = vented + record["refrigerant_lost_lbs"]
    store["vented_loss_lbs"] = util.q1(vented)

    if store["mandated_retrofit_count"] > 0 or store["overdue_leak_event_count"] > 0:
        store["compliance_status"] = "NON_COMPLIANT"
    elif store["open_leak_event_count"] > 0 or store["chronic_leaker_flag"]:
        store["compliance_status"] = "AT_RISK"
    else:
        store["compliance_status"] = "COMPLIANT"

    total_exposure = ZERO
    for inspection in store_inspections(store["id"]):
        inspection_snap = db.snapshot(inspection)
        recompute_inspection(inspection, store)
        db.commit(inspection, inspection_snap)
        total_exposure = total_exposure + inspection["penalty_exposure_usd"]
    store["penalty_exposure_total_usd"] = util.q2(total_exposure)
    db.commit(store, snap)
    return store


def recompute_store_by_id(store_id):
    store = db.get("stores", store_id)
    if store is not None:
        recompute_store(store)
    return store


def system_cascade(system, bump=True, recompute_charge=False, recompute_rate=False):
    """PRD 2.9 steps 4 through 7 for one system, plus the version bump.

    Steps 1 and 2 (charge and leak rate) are opt-in because several callers
    have already performed them, or must not perform them at all.
    """
    if recompute_charge:
        ledger.recompute_charge(system)
    if recompute_rate:
        ledger.recompute_leak_rate(system)
    ledger.recompute_exceedance(system)
    settle_compliance_state(system)
    if bump:
        db.touch(system)
    recompute_store_by_id(system["store_id"])
    return system
