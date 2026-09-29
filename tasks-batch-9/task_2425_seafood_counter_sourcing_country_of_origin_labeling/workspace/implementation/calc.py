"""Calculation rules (PRD 2.6, 3.4, 3.7, 3.8, 3.9)."""

import math
from decimal import Decimal

from common import cents, dec, rhu, sort_records
from store import db

# ---- constants -----------------------------------------------------------
HANDLING_CENTS_PER_KG = Decimal("85")
DISPOSAL_CENTS_PER_KG = Decimal("40")
DISPOSAL_FACTOR = {
    "UNSOLD_FRESH": Decimal("1.0"),
    "MISLABEL_DESTRUCTION": Decimal("1.5"),
    "COLD_CHAIN_DISPOSAL": Decimal("2.0"),
}

MAX_CONVERSION_SHARE = Decimal("0.60")
COOK_YIELD_RATIO = Decimal("0.65")
PREVIOUSLY_FROZEN_PENALTY = Decimal("0.15")
FRESH_CLAIM_PENALTY = Decimal("0.05")
LABOR_CENTS_PER_KG = Decimal("90")

BASE_PENALTY_CENTS = 25000
RELABEL_LABOR_CENTS = 4000
GOODWILL_TIER_1_RATE = Decimal("0.15")
GOODWILL_TIER_2_RATE = Decimal("0.08")
GOODWILL_TIER_3_RATE = Decimal("0.00")
PROBATION_MULTIPLIER = Decimal("1.25")

MISMATCH_WEIGHT = Decimal("40")
HIGH_RISK_BONUS = Decimal("10")
DECAY_PER_CYCLE = Decimal("0.5")
INDEX_CAP = Decimal("100.00")
PROBATION_LIFETIME_THRESHOLD = Decimal("25.00")
SUSPENSION_LIFETIME_THRESHOLD = Decimal("60.00")

BASE_SAMPLES = 1
HIGH_RISK_DIVISOR = 3
HIGH_RISK_SURCHARGE = 2
RISK_SURCHARGE_THRESHOLD = Decimal("40.00")

ICE_BED_LIMIT_C = Decimal("4.4")
MINOR_MAX_MINUTES = 60
MAJOR_MAX_MINUTES = 180

SUSPEND_EXCURSION_COUNT = 2
SUSPEND_VIOLATION_POINTS = 12
RESTRICT_EXCURSION_COUNT = 1
RESTRICT_VIOLATION_POINTS = 6

CATEGORY_POINTS = {
    "SPECIES_SUBSTITUTION": 6,
    "COOL_MISSING": 4,
    "FROZEN_DISCLOSURE": 4,
    "SIMP_DEFICIENT": 5,
    "COLD_CHAIN": 3,
    "UNSUBSTANTIATED_CLAIM": 6,
}

CREDIT_HOLD_CENTS = 75000
SANITATION_BUFFER_MINUTES = 30


# ---- cool_label_content_derivation --------------------------------------

def label_statements(lot, species, certification):
    display_market_name = species["market_name"]
    if lot["production_method"] == "WILD":
        origin_statement = "Wild caught in %s (%s)" % (
            lot["origin_country_code"],
            lot["harvest_method"],
        )
    else:
        processing = lot.get("processing_country_code")
        if processing is not None and processing != lot["origin_country_code"]:
            origin_statement = "Farm raised in %s, processed in %s" % (
                lot["origin_country_code"],
                processing,
            )
        else:
            origin_statement = "Farm raised in %s" % lot["origin_country_code"]

    production_method_statement = (
        "WILD CAUGHT" if lot["production_method"] == "WILD" else "FARM RAISED"
    )

    if lot["previously_frozen"]:
        frozen_disclosure_statement = "PREVIOUSLY FROZEN"
    elif lot["fresh_claim"]:
        frozen_disclosure_statement = "FRESH - NEVER FROZEN"
    else:
        frozen_disclosure_statement = "FRESH"

    claim_text = None if certification is None else certification["claim_text"]
    return {
        "display_market_name": display_market_name,
        "origin_statement": origin_statement,
        "production_method_statement": production_method_statement,
        "frozen_disclosure_statement": frozen_disclosure_statement,
        "sustainability_claim_text": claim_text,
    }


def cool_statement(lot, species):
    parts = label_statements(lot, species, None)
    return " | ".join(
        [
            parts["display_market_name"],
            parts["production_method_statement"],
            parts["origin_statement"],
            parts["frozen_disclosure_statement"],
        ]
    )


# ---- shrink_valuation ----------------------------------------------------

def provisional_value_cents(lot, reason, shrink_weight_kg):
    weight = dec(shrink_weight_kg)
    factor = DISPOSAL_FACTOR[reason]
    line_cost = cents(weight * dec(lot["unit_cost_cents_per_kg"]))
    line_handling = cents(weight * HANDLING_CENTS_PER_KG)
    line_disposal = cents(weight * DISPOSAL_CENTS_PER_KG * factor)
    return line_cost + line_handling + line_disposal


# ---- cook_conversion_recovery -------------------------------------------

def conversion_allowance_kg(lot, shrink_weight_kg):
    cap = dec(lot["received_weight_kg"]) * MAX_CONVERSION_SHARE
    return rhu(min(dec(shrink_weight_kg), cap), 3)


def approved_conversion_kg(requested_kg, allowance_kg):
    value = min(dec(requested_kg), dec(allowance_kg))
    if value < 0:
        value = Decimal("0")
    return rhu(value, 3)


def cook_yield_kg(lot, approved_kg):
    penalty = Decimal("0.00")
    if lot["previously_frozen"]:
        penalty += PREVIOUSLY_FROZEN_PENALTY
    if lot["fresh_claim"]:
        penalty += FRESH_CLAIM_PENALTY
    return rhu(dec(approved_kg) * COOK_YIELD_RATIO * (Decimal("1") - penalty), 3)


def recovery_credit_cents(lot, approved_kg, yield_kg, provisional_cents):
    gross = cents(dec(yield_kg) * dec(lot["cooked_retail_price_cents_per_kg"]))
    labor = cents(dec(approved_kg) * LABOR_CENTS_PER_KG)
    return min(provisional_cents, max(0, gross - labor))


# ---- supplier_chargeback_assessment -------------------------------------

def chargeback_assessment_cents(lot, supplier):
    lot_value = cents(dec(lot["remaining_weight_kg"]) * dec(lot["retail_price_cents_per_kg"]))
    subtotal = BASE_PENALTY_CENTS + lot_value + RELABEL_LABOR_CENTS
    if subtotal < 50000:
        rate = GOODWILL_TIER_1_RATE
    elif subtotal < 120000:
        rate = GOODWILL_TIER_2_RATE
    else:
        rate = GOODWILL_TIER_3_RATE
    goodwill = cents(dec(subtotal) * rate)
    net = subtotal - goodwill
    multiplier = PROBATION_MULTIPLIER if supplier["status"] == "PROBATION" else Decimal("1.00")
    return cents(dec(net) * multiplier)


# ---- substitution_risk_index --------------------------------------------

def mismatch_samples_for_supplier(supplier_id):
    result = []
    for sample in db.samples.values():
        if sample["status"] != "MISMATCH":
            continue
        lot = db.lots.get(sample["lot_id"])
        if lot is None or lot["supplier_id"] != supplier_id:
            continue
        result.append(sample)
    return sort_records(result)


def rolling_risk_index(supplier_id):
    samples = mismatch_samples_for_supplier(supplier_id)
    decayed = Decimal("0")
    bonus = Decimal("0")
    for sample in samples:
        lot = db.lots[sample["lot_id"]]
        counter = db.counters.get(lot["counter_id"])
        cycle_now = counter["verification_cycle_index"] if counter else 0
        age = cycle_now - sample["cycle_index"]
        if age < 0:
            age = 0
        decayed += MISMATCH_WEIGHT * (DECAY_PER_CYCLE ** age)
        species = db.species.get(lot["species_id"])
        if species is not None and species["high_risk_substitution"]:
            bonus = HIGH_RISK_BONUS
    return rhu(min(INDEX_CAP, decayed + bonus), 2)


def lifetime_risk_index(supplier):
    if supplier["lifetime_sample_count"] == 0:
        return Decimal("0.00")
    return rhu(
        Decimal("100")
        * dec(supplier["lifetime_mismatch_count"])
        / dec(supplier["lifetime_sample_count"]),
        2,
    )


def supplier_standing(supplier, lifetime_index):
    if supplier["lifetime_sample_count"] >= 2 and lifetime_index >= SUSPENSION_LIFETIME_THRESHOLD:
        return "SUSPENDED"
    if supplier["lifetime_sample_count"] >= 2 and lifetime_index >= PROBATION_LIFETIME_THRESHOLD:
        return "PROBATION"
    return "GOOD_STANDING"


# ---- verification_sampling_plan -----------------------------------------

def sampling_plan(counter):
    candidates = [
        lot
        for lot in db.lots.values()
        if lot["counter_id"] == counter["id"]
        and lot["intake_status"] in ("CASED", "HELD")
        and lot["label_status"] in ("UNVERIFIED", "RELABELED")
    ]
    if not candidates:
        return 0, Decimal("0.00")

    high_risk_count = 0
    max_index = Decimal("0.00")
    for lot in candidates:
        species = db.species.get(lot["species_id"])
        if species is not None and species["high_risk_substitution"]:
            high_risk_count += 1
        supplier = db.suppliers.get(lot["supplier_id"])
        if supplier is not None:
            value = dec(supplier["substitution_risk_index_rolling"])
            if value > max_index:
                max_index = value
    max_index = rhu(max_index, 2)

    required = BASE_SAMPLES + int(math.ceil(high_risk_count / float(HIGH_RISK_DIVISOR)))
    if max_index >= RISK_SURCHARGE_THRESHOLD:
        required += HIGH_RISK_SURCHARGE
    return required, max_index


# ---- cold_chain_exposure -------------------------------------------------

def severity_for(exposure_minutes):
    if exposure_minutes <= MINOR_MAX_MINUTES:
        return "MINOR"
    if exposure_minutes <= MAJOR_MAX_MINUTES:
        return "MAJOR"
    return "CRITICAL"


def exposure_minutes_between(started_at, ended_at):
    seconds = (ended_at - started_at).total_seconds()
    return int(rhu(dec(seconds) / dec(60), 0))


# ---- counter_posture_derivation -----------------------------------------

def posture_aggregates(counter):
    open_excursions = 0
    for excursion in db.excursions.values():
        if excursion["counter_id"] == counter["id"] and excursion["status"] == "OPEN":
            open_excursions += 1
    points = 0
    for violation in db.violations.values():
        if violation["counter_id"] != counter["id"]:
            continue
        weight = CATEGORY_POINTS[violation["category"]]
        if violation["status"] == "OPEN":
            points += weight
        elif violation["status"] == "CURED":
            points += int(math.ceil(weight / 2.0))
    return open_excursions, points


def posture_for(open_excursions, points):
    if open_excursions >= SUSPEND_EXCURSION_COUNT or points >= SUSPEND_VIOLATION_POINTS:
        return "SUSPENDED"
    if open_excursions >= RESTRICT_EXCURSION_COUNT or points >= RESTRICT_VIOLATION_POINTS:
        return "RESTRICTED"
    return "OPEN"
