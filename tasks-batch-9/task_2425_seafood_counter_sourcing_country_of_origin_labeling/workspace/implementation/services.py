"""Derived state, cascades and ledger movements (PRD 2.6, 2.10, 2.11, 3.x)."""

from decimal import Decimal

import calc
from common import base_record, dec, rhu, sort_records, touch
from store import db

ZERO3 = Decimal("0.000")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def lot_counter(lot):
    return db.counters.get(lot["counter_id"])


def lot_supplier(lot):
    return db.suppliers.get(lot["supplier_id"])


def published_labels_for_lot(lot_id):
    return sort_records(
        [
            label
            for label in db.case_labels.values()
            if label["lot_id"] == lot_id and label["status"] == "PUBLISHED"
        ]
    )


def published_ads_for_lot(lot_id):
    return sort_records(
        [
            item
            for item in db.ad_items.values()
            if item["lot_id"] == lot_id and item["status"] == "PUBLISHED"
        ]
    )


def counter_has_open_excursion(counter_id):
    for excursion in db.excursions.values():
        if excursion["counter_id"] == counter_id and excursion["status"] == "OPEN":
            return True
    return False


# --------------------------------------------------------------------------
# posture, supplier standing
# --------------------------------------------------------------------------

def derive_posture(counter):
    """Re-derive the gating surface.  The record is only marked dirty when a
    derived value actually moves, so a re-derivation that changes nothing does
    not count as a mutation for `version` purposes."""
    if counter is None:
        return
    open_excursions, points = calc.posture_aggregates(counter)
    posture = calc.posture_for(open_excursions, points)
    changed = (
        counter["open_excursion_count"] != open_excursions
        or counter["violation_points"] != points
        or counter["posture"] != posture
    )
    counter["open_excursion_count"] = open_excursions
    counter["violation_points"] = points
    counter["posture"] = posture
    if changed:
        touch(counter)


def recompute_supplier_indices(supplier):
    if supplier is None:
        return
    rolling = calc.rolling_risk_index(supplier["id"])
    lifetime = calc.lifetime_risk_index(supplier)
    status = calc.supplier_standing(supplier, lifetime)
    changed = (
        supplier["substitution_risk_index_rolling"] != rolling
        or supplier["substitution_risk_index_lifetime"] != lifetime
        or supplier["status"] != status
    )
    supplier["substitution_risk_index_rolling"] = rolling
    supplier["substitution_risk_index_lifetime"] = lifetime
    supplier["status"] = status
    if changed:
        touch(supplier)


# --------------------------------------------------------------------------
# violations
# --------------------------------------------------------------------------

def create_violation(counter, lot_id, category, detail):
    if counter is None:
        return None
    record = base_record("violation")
    record.update(
        {
            "counter_id": counter["id"],
            "lot_id": lot_id,
            "category": category,
            "points": calc.CATEGORY_POINTS[category],
            "status": "OPEN",
            "detail": detail,
            "cure_note": None,
            "expunge_note": None,
            "cured_at": None,
            "expunged_at": None,
        }
    )
    db.violations[record["id"]] = record
    derive_posture(counter)
    return record


# --------------------------------------------------------------------------
# shrink events
# --------------------------------------------------------------------------

def create_shrink_event(lot, reason, shrink_weight_kg, conversion_requested_kg=ZERO3):
    record = base_record("shrink_event")
    weight = rhu(dec(shrink_weight_kg), 3)
    record.update(
        {
            "lot_id": lot["id"],
            "reason": reason,
            "shrink_weight_kg": weight,
            "conversion_requested_kg": rhu(dec(conversion_requested_kg), 3),
            "approved_conversion_kg": ZERO3,
            "allowance_kg": ZERO3,
            "cook_yield_kg": ZERO3,
            "provisional_value_cents": calc.provisional_value_cents(lot, reason, weight),
            "final_value_cents": 0,
            "recovery_credit_cents": 0,
            "status": "VALUED",
            "posted_at": None,
            "reversed_at": None,
            "reversal_note": None,
        }
    )
    db.shrink_events[record["id"]] = record
    if reason == "MISLABEL_DESTRUCTION":
        assess_chargeback(lot)
    return record


# --------------------------------------------------------------------------
# chargeback assessment (cascade A links 4 and 5)
# --------------------------------------------------------------------------

def assess_chargeback(lot):
    if lot["chargeback_status"] != "NONE":
        return
    supplier = lot_supplier(lot)
    if supplier is None:
        return
    amount = calc.chargeback_assessment_cents(lot, supplier)
    lot["chargeback_assessed_cents"] = amount
    lot["chargeback_status"] = "ASSESSED"
    touch(lot)
    supplier["chargeback_assessed_total_cents"] += amount
    supplier["chargeback_outstanding_cents"] += amount
    touch(supplier)
    recompute_supplier_indices(supplier)


# --------------------------------------------------------------------------
# case-label withdrawal and its per-reason cascades
# --------------------------------------------------------------------------

def withdraw_label(label, reason, system=True):
    label["status"] = "WITHDRAWN"
    label["withdraw_reason"] = reason
    label["withdrawn_at"] = db.clock
    touch(label)
    if not system:
        return
    lot = db.lots.get(label["lot_id"])
    if lot is None:
        return
    counter = lot_counter(lot)
    if reason == "SPECIES_MISMATCH":
        create_shrink_event(lot, "MISLABEL_DESTRUCTION", lot["remaining_weight_kg"])
    elif reason == "COLD_CHAIN_HOLD":
        for item in published_ads_for_lot(lot["id"]):
            retract_ad(item, "LABEL_WITHDRAWN")
            create_violation(
                counter,
                lot["id"],
                "COOL_MISSING",
                "Advertisement retracted because the case label for lot %s was withdrawn "
                "under a cold-chain hold." % lot["lot_code"],
            )
    elif reason == "CLAIM_REVOKED":
        create_violation(
            counter,
            lot["id"],
            "UNSUBSTANTIATED_CLAIM",
            "Case label withdrawn because the sustainability certificate it carried left ACTIVE.",
        )


def withdraw_published_labels(lot, reason):
    for label in published_labels_for_lot(lot["id"]):
        withdraw_label(label, reason)


def retract_ad(item, reason):
    item["status"] = "RETRACTED"
    item["retract_reason"] = reason
    touch(item)


# --------------------------------------------------------------------------
# advertised item fork-join
# --------------------------------------------------------------------------

def join_ad_review(item):
    if item["status"] != "DRAFT":
        return
    if item["cool_review_status"] == "COOL_REJECTED" or item["claim_review_status"] == "CLAIM_REJECTED":
        item["status"] = "REJECTED"
    elif (
        item["cool_review_status"] == "COOL_CLEARED"
        and item["claim_review_status"] == "CLAIM_CLEARED"
    ):
        item["status"] = "APPROVED"


# --------------------------------------------------------------------------
# substitution cascade (cascade A)
# --------------------------------------------------------------------------

def apply_result(sample, lot, observed_species_id):
    """PRD 3.8: record a laboratory result and run the substitution cascade."""
    mismatch = observed_species_id != lot["species_id"]
    sample["observed_species_id"] = observed_species_id
    sample["status"] = "MISMATCH" if mismatch else "MATCH"
    sample["result_recorded_at"] = db.clock
    touch(sample)

    supplier = lot_supplier(lot)
    if supplier is not None:
        if not sample.get("_counted"):
            sample["_counted"] = True
            supplier["lifetime_sample_count"] += 1
            if mismatch:
                sample["_mismatch_counted"] = True
                supplier["lifetime_mismatch_count"] += 1
        else:
            was_mismatch = bool(sample.get("_mismatch_counted"))
            if mismatch and not was_mismatch:
                sample["_mismatch_counted"] = True
                supplier["lifetime_mismatch_count"] += 1
            elif not mismatch and was_mismatch:
                sample["_mismatch_counted"] = False
                supplier["lifetime_mismatch_count"] -= 1
        touch(supplier)
        recompute_supplier_indices(supplier)

    if not mismatch:
        lot["label_status"] = "VERIFIED"
        touch(lot)
        return

    if lot["label_status"] == "MISMATCHED":
        # Idempotency guard (PRD 2.10): the cascade hangs off the *entry* into
        # MISMATCHED, so a retest mismatch advances the sample alone.
        return

    lot["label_status"] = "MISMATCHED"
    touch(lot)
    create_violation(
        lot_counter(lot),
        lot["id"],
        "SPECIES_SUBSTITUTION",
        "Laboratory verification identified a species other than the declared species "
        "for lot %s." % lot["lot_code"],
    )
    withdraw_published_labels(lot, "SPECIES_MISMATCH")


# --------------------------------------------------------------------------
# cold-chain cascade (cascade B)
# --------------------------------------------------------------------------

def slot_readings(counter_id, case_slot):
    return [
        record
        for record in db.readings.values()
        if record["counter_id"] == counter_id and record["case_slot"] == case_slot
    ]


def slot_cutoff(counter_id, case_slot):
    cutoff = None
    for excursion in db.excursions.values():
        if excursion["counter_id"] != counter_id or excursion["case_slot"] != case_slot:
            continue
        if excursion["status"] not in ("RESOLVED_RELEASED", "RESOLVED_DISPOSED"):
            continue
        ended = excursion["ended_at"]
        if ended is not None and (cutoff is None or ended > cutoff):
            cutoff = ended
    return cutoff


def open_excursion_for_slot(counter_id, case_slot):
    matches = [
        excursion
        for excursion in db.excursions.values()
        if excursion["counter_id"] == counter_id
        and excursion["case_slot"] == case_slot
        and excursion["status"] == "OPEN"
    ]
    if not matches:
        return None
    return sort_records(matches)[-1]


def replay_slot_exposure(counter, case_slot):
    """PRD 3.7: full chronological replay of the slot's breach set."""
    cutoff = slot_cutoff(counter["id"], case_slot)
    breaches = [
        record
        for record in slot_readings(counter["id"], case_slot)
        if record["breach"] and (cutoff is None or record["reading_at"] > cutoff)
    ]
    if not breaches:
        return None, False

    breaches.sort(key=lambda r: (r["reading_at"], r["created_at"], r["_seq"]))
    started_at = breaches[0]["reading_at"]
    ended_at = breaches[-1]["reading_at"]
    exposure = calc.exposure_minutes_between(started_at, ended_at)
    peak = max(dec(r["temperature_c"]) for r in breaches)

    excursion = open_excursion_for_slot(counter["id"], case_slot)
    created = False
    if excursion is None:
        excursion = base_record("excursion")
        excursion.update(
            {
                "counter_id": counter["id"],
                "case_slot": case_slot,
                "started_at": started_at,
                "ended_at": ended_at,
                "exposure_minutes": exposure,
                "peak_temperature_c": rhu(peak, 1),
                "severity": calc.severity_for(exposure),
                "status": "OPEN",
                "resolution": None,
                "resolution_note": None,
            }
        )
        db.excursions[excursion["id"]] = excursion
        created = True
    else:
        updated = {
            "started_at": started_at,
            "ended_at": ended_at,
            "exposure_minutes": exposure,
            "peak_temperature_c": rhu(peak, 1),
            "severity": calc.severity_for(exposure),
        }
        changed = any(excursion[key] != value for key, value in updated.items())
        excursion.update(updated)
        if changed:
            touch(excursion)

    if created:
        hold_slot_lots(counter, case_slot)
    derive_posture(counter)
    return excursion, created


def hold_slot_lots(counter, case_slot):
    lots = sort_records(
        [
            lot
            for lot in db.lots.values()
            if lot["counter_id"] == counter["id"]
            and lot["case_slot"] == case_slot
            and lot["intake_status"] == "CASED"
        ]
    )
    for lot in lots:
        lot["intake_status"] = "HELD"
        touch(lot)
        withdraw_published_labels(lot, "COLD_CHAIN_HOLD")


def held_slot_lots(counter, case_slot):
    return sort_records(
        [
            lot
            for lot in db.lots.values()
            if lot["counter_id"] == counter["id"]
            and lot["case_slot"] == case_slot
            and lot["intake_status"] == "HELD"
        ]
    )


def release_slot_lots(counter, case_slot):
    for lot in held_slot_lots(counter, case_slot):
        lot["intake_status"] = "CASED"
        touch(lot)


def dispose_slot_lots(counter, case_slot):
    for lot in held_slot_lots(counter, case_slot):
        vacate_lot(lot, "DISPOSED")
        create_shrink_event(lot, "COLD_CHAIN_DISPOSAL", lot["remaining_weight_kg"])
        create_violation(
            counter,
            lot["id"],
            "COLD_CHAIN",
            "Held product destroyed following disposal of a cold-chain excursion in slot %d."
            % case_slot,
        )


def vacate_lot(lot, intake_status):
    lot["intake_status"] = intake_status
    lot["vacated_at"] = db.clock
    lot["_vacated_slot"] = lot["case_slot"]
    lot["case_slot"] = None
    touch(lot)


# --------------------------------------------------------------------------
# certificate enforcement cascade
# --------------------------------------------------------------------------

def enforce_certification_cascade(certification):
    labels = sort_records(
        [
            label
            for label in db.case_labels.values()
            if label["certification_id"] == certification["id"]
            and label["status"] == "PUBLISHED"
        ]
    )
    for label in labels:
        withdraw_label(label, "CLAIM_REVOKED")
    items = sort_records(
        [
            item
            for item in db.ad_items.values()
            if item["certification_id"] == certification["id"] and item["status"] == "PUBLISHED"
        ]
    )
    for item in items:
        retract_ad(item, "CLAIM_REVOKED")


# --------------------------------------------------------------------------
# verification cycle close
# --------------------------------------------------------------------------

def close_verification_cycle(counter):
    required, max_index = calc.sampling_plan(counter)
    counter["last_cycle_required_samples"] = required
    counter["last_cycle_max_supplier_risk_index"] = max_index
    counter["verification_cycle_index"] += 1
    supplier_ids = []
    for lot in db.lots.values():
        if lot["counter_id"] == counter["id"] and lot["supplier_id"] not in supplier_ids:
            supplier_ids.append(lot["supplier_id"])
    for supplier_id in supplier_ids:
        recompute_supplier_indices(db.suppliers.get(supplier_id))
    derive_posture(counter)
    touch(counter)


# --------------------------------------------------------------------------
# claim substantiation shared by labels, ad drafts and claim review
# --------------------------------------------------------------------------

def check_claim(certification, counter_id, supplier_id, species_id):
    """PRD 3.4 / 2.9 items 41-42, evaluated in that order."""
    from errors import fail

    if certification["status"] != "ACTIVE":
        fail("ERR_CLAIM_NOT_SUBSTANTIATED")
    if (
        certification["counter_id"] != counter_id
        or certification["supplier_id"] != supplier_id
        or certification["species_id"] != species_id
    ):
        fail("ERR_CLAIM_NOT_SUBSTANTIATED")
    check_validity_window(certification)


def check_validity_window(certification):
    from errors import fail

    if not (certification["valid_from"] <= db.clock < certification["valid_until"]):
        fail("ERR_CERTIFICATION_EXPIRED")
