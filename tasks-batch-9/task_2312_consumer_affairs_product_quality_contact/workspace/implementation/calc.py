"""The ten calculations of SCAFFOLD §1.3 / PRD §3, with every constant literal."""

import re
from decimal import Decimal

from common import (
    dec,
    days,
    hours,
    hours_between,
    now,
    round_half_up,
    store,
)

# --- complaint_severity_score ------------------------------------------------
TYPE_POINTS = {"FOREIGN_MATERIAL": 40, "ILLNESS": 50, "PACKAGING": 20, "QUALITY": 10}
OBJECT_POINTS = {"NONE": 0, "SOFT": 5, "HARD_BLUNT": 15, "HARD_SHARP": 30}
MEDICAL_ATTENTION_POINTS = 25
HOSPITALIZATION_POINTS = 35
SYMPTOM_POINTS_PER_CODE = Decimal("3.5")
SYMPTOM_CODE_CAP = 4
VULNERABLE_MULTIPLIER = Decimal("1.15")
REGULATED_MULTIPLIER = Decimal("1.075")
BAND_S1_MIN = Decimal(90)
BAND_S2_MIN = Decimal(60)
BAND_S3_MIN = Decimal(30)

# --- rates -------------------------------------------------------------------
PPM_SCALE = Decimal(1000000)

# --- trend -------------------------------------------------------------------
TREND_WINDOW_DAYS = 30
SEVERITY_WEIGHT = {"S1": Decimal(3), "S2": Decimal(2), "S3": Decimal(1), "S4": Decimal(0)}
THRESHOLD_PPM = {"LOT": Decimal("25.0"), "LINE": Decimal("12.0"), "PLANT": Decimal("6.0")}
MIN_WEIGHTED_COUNT = Decimal("3.0")

# --- goodwill ----------------------------------------------------------------
SAMPLE_RETURN_CREDIT_CENTS = 799
REPLACEMENT_UNIT_CAP = 3
REPLACEMENT_HANDLING_MULTIPLIER = Decimal("1.15")
UPLIFT_MID_MIN = 1000
UPLIFT_HIGH_MIN = 5000
TIER_1_MAX_CENTS = 2500
TIER_2_MAX_CENTS = 7500
GOODWILL_MAX_PAYOUT_CENTS = 25000

# --- sentiment ---------------------------------------------------------------
NEUTRAL_BASE = Decimal(50)
BAND_PENALTY = {"S1": Decimal(20), "S2": Decimal(12), "S3": Decimal(6), "S4": Decimal(3)}
PROVISIONAL_SURCHARGE = Decimal(5)
DECAY_AFTER_DAYS = 90
DECAY_FACTOR = Decimal("0.5")
LOOKBACK_DAYS = 180
REMEDY_FULFILLED_CREDIT = Decimal(8)
RESPONSE_CREDIT = Decimal(4)
INDEX_MIN = Decimal("0.00")
INDEX_MAX = Decimal("100.00")

# --- custody -----------------------------------------------------------------
REQUIRED_SEQUENCE = ["KIT_ISSUED", "CONSUMER_SEALED", "CARRIER_PICKUP", "LAB_RECEIVED", "LAB_OPENED"]
MAX_TRANSIT_HOURS = Decimal(240)

# --- kit window --------------------------------------------------------------
KIT_RETURN_WINDOW_DAYS = 14
KIT_COOLDOWN_HOURS = 48

# --- regulatory --------------------------------------------------------------
S1_DEADLINE_HOURS = 24
STANDARD_DEADLINE_HOURS = 72

# --- remedy ------------------------------------------------------------------
MAX_REMEDY_REVISIONS = 2

TIER_RANK = {"TIER_1": 1, "TIER_2": 2, "TIER_3": 3}
BAND_SEVERITY_RANK = {"S1": 4, "S2": 3, "S3": 2, "S4": 1}

NORMALIZE_PATTERN = re.compile(r"[^A-Z0-9]")


# =============================================================================
# 1. complaint_severity_score
# =============================================================================
def band_for(score):
    score = dec(score)
    if score >= BAND_S1_MIN:
        return "S1"
    if score >= BAND_S2_MIN:
        return "S2"
    if score >= BAND_S3_MIN:
        return "S3"
    return "S4"


def additive_hazard_total(complaint):
    codes = complaint.get("symptom_codes") or []
    symptom_units = len(codes)
    if symptom_units > SYMPTOM_CODE_CAP:
        symptom_units = SYMPTOM_CODE_CAP
    total = dec(TYPE_POINTS[complaint["complaint_type"]])
    total += dec(OBJECT_POINTS[complaint.get("foreign_object_class") or "NONE"])
    if complaint.get("medical_attention_sought"):
        total += dec(MEDICAL_ATTENTION_POINTS)
    if complaint.get("hospitalization"):
        total += dec(HOSPITALIZATION_POINTS)
    total += SYMPTOM_POINTS_PER_CODE * dec(symptom_units)
    return total


def provisional_severity(complaint):
    score = round_half_up(additive_hazard_total(complaint), 2)
    return score, band_for(score)


def adjudicated_severity(complaint):
    """Stepwise multipliers, rounding half up to 2dp after EACH multiplication."""
    additive = additive_hazard_total(complaint)
    consumer = store.consumers.get(complaint.get("consumer_id")) or {}
    vulnerable = bool(complaint.get("vulnerable_consumer")) or bool(
        consumer.get("is_vulnerable_flag")
    )
    step_1 = round_half_up(additive * (VULNERABLE_MULTIPLIER if vulnerable else Decimal(1)), 2)

    regulated = False
    lot = store.production_lots.get(complaint.get("lot_id"))
    if lot is not None:
        product = store.products.get(lot.get("product_id"))
        if product is not None:
            regulated = bool(product.get("is_regulated_food"))
    step_2 = round_half_up(step_1 * (REGULATED_MULTIPLIER if regulated else Decimal(1)), 2)
    return step_2, band_for(step_2)


def effective_band(complaint):
    if complaint.get("adjudicated_severity_score") is not None:
        return complaint.get("adjudicated_severity_band")
    return complaint.get("provisional_severity_band")


# =============================================================================
# 2. lot_complaint_rate_ppm
# =============================================================================
def lot_complaint_rate(lot, variant):
    numerator = 0
    for c in store.complaints.values():
        if c.get("lot_id") != lot["id"]:
            continue
        if c.get("handling_status") == "DUPLICATE":
            continue
        if variant == "adjudicated" and c.get("adjudicated_severity_score") is None:
            continue
        numerator += 1
    units = lot.get("units_produced") or 0
    if units == 0:
        return numerator, units, Decimal("0.00"), True
    rate = round_half_up(dec(numerator) / dec(units) * PPM_SCALE, 2)
    return numerator, units, rate, False


# =============================================================================
# 3. trend_signal_evaluation helpers
# =============================================================================
def trend_window():
    clock = now()
    return clock - days(TREND_WINDOW_DAYS), clock


def complaint_in_window(complaint, window_start, window_end):
    created = complaint["created_at"]
    return window_start <= created < window_end


def eligible_complaints(window_start, window_end):
    out = []
    for c in store.complaints.values():
        if not c.get("lot_id"):
            continue
        if c.get("handling_status") == "DUPLICATE":
            continue
        if not complaint_in_window(c, window_start, window_end):
            continue
        out.append(c)
    return sorted(out, key=lambda r: (r["created_at"], r["_seq"]))


def weight_of(complaint):
    return SEVERITY_WEIGHT.get(effective_band(complaint), Decimal(0))


def included_variant(complaint):
    return "ADJUDICATED" if complaint.get("adjudicated_severity_score") is not None else "PROVISIONAL"


def observed_rate(weighted, units):
    if not units:
        return Decimal("0.00")
    return round_half_up(dec(weighted) / dec(units) * PPM_SCALE, 2)


def fires(weighted, rate, scope_level):
    return weighted >= MIN_WEIGHTED_COUNT and rate >= THRESHOLD_PPM[scope_level]


# =============================================================================
# 4. goodwill_authorization
# =============================================================================
def goodwill_authorization(remedy, complaint):
    remedy_type = remedy["remedy_type"]
    requested = int(remedy["requested_value_cents"])
    units_claimed = int(complaint.get("units_claimed") or 1)

    unit_price = None
    lot = store.production_lots.get(complaint.get("lot_id"))
    if lot is not None:
        product = store.products.get(lot.get("product_id"))
        if product is not None:
            unit_price = int(product["unit_retail_price_cents"])

    credit_applied = False
    if remedy_type == "COUPON":
        base = dec(requested)
    elif remedy_type == "REFUND":
        if unit_price is None:
            base = dec(requested)
        else:
            capped = min(requested, unit_price * units_claimed)
            base = dec(capped)
        if _kit_lab_accepted(complaint):
            base = base + dec(SAMPLE_RETURN_CREDIT_CENTS)
            credit_applied = True
    else:  # REPLACEMENT
        if unit_price is None:
            base = dec(requested)
        else:
            units = min(units_claimed, REPLACEMENT_UNIT_CAP)
            base = round_half_up(
                dec(unit_price) * dec(units) * REPLACEMENT_HANDLING_MULTIPLIER, 0
            )
    base_value_cents = int(round_half_up(base, 0))

    if base_value_cents < UPLIFT_MID_MIN:
        uplift_pct = Decimal("0.00")
    elif base_value_cents < UPLIFT_HIGH_MIN:
        uplift_pct = Decimal("0.10")
    else:
        uplift_pct = Decimal("0.05")

    uplift_cents = int(round_half_up(dec(base_value_cents) * uplift_pct, 0))
    payout_cents = base_value_cents + uplift_cents

    if payout_cents <= TIER_1_MAX_CENTS:
        tier = "TIER_1"
    elif payout_cents <= TIER_2_MAX_CENTS:
        tier = "TIER_2"
    else:
        tier = "TIER_3"

    return {
        "base_value_cents": base_value_cents,
        "uplift_pct": uplift_pct,
        "uplift_cents": uplift_cents,
        "payout_cents": payout_cents,
        "authority_tier_required": tier,
        "kit_returned_credit_applied": credit_applied,
    }


def _kit_lab_accepted(complaint):
    for kit in store.sample_kits.values():
        if kit.get("complaint_id") == complaint["id"] and kit.get("status") == "LAB_ACCEPTED":
            return True
    return False


# =============================================================================
# 5. consumer_sentiment_index
# =============================================================================
def consumer_sentiment(consumer, view="agent_view"):
    clock = now()
    lookback_start = clock - days(LOOKBACK_DAYS)

    penalty_total = Decimal(0)
    in_window_count = 0
    response_credits = 0
    for c in store.complaints.values():
        if c.get("consumer_id") != consumer["id"]:
            continue
        if c.get("handling_status") == "DUPLICATE":
            continue
        if c["created_at"] < lookback_start:
            continue
        in_window_count += 1
        raw = BAND_PENALTY.get(effective_band(c), Decimal(0))
        if c.get("adjudicated_severity_score") is None:
            raw = raw + PROVISIONAL_SURCHARGE
        if view == "agent_view":
            age_days = (clock - c["created_at"]).days
            if age_days >= DECAY_AFTER_DAYS:
                raw = raw * DECAY_FACTOR
        penalty_total += raw
        if c.get("responded_at") is not None:
            response_credits += 1

    fulfilled = 0
    for r in store.remedies.values():
        if r.get("consumer_id") == consumer["id"] and r.get("status") == "FULFILLED":
            fulfilled += 1

    credit_total = REMEDY_FULFILLED_CREDIT * dec(fulfilled) + RESPONSE_CREDIT * dec(
        response_credits
    )
    index = round_half_up(NEUTRAL_BASE - penalty_total + credit_total, 2)
    if index < INDEX_MIN:
        index = INDEX_MIN
    if index > INDEX_MAX:
        index = INDEX_MAX
    return {
        "penalty_total": round_half_up(penalty_total, 2),
        "credit_total": round_half_up(credit_total, 2),
        "sentiment_index": index,
        "complaint_count_in_window": in_window_count,
    }


# =============================================================================
# 6. custody_chain_integrity
# =============================================================================
def kit_events(kit_id):
    events = [e for e in store.custody_events.values() if e.get("sample_kit_id") == kit_id]
    return sorted(events, key=lambda e: e["sequence_no"])


def custody_projection(kit):
    """Returns (chain_integrity_status, transit_hours or None)."""
    events = kit_events(kit["id"])
    violated = False

    for idx, event in enumerate(events):
        if idx >= len(REQUIRED_SEQUENCE) or event["event_type"] != REQUIRED_SEQUENCE[idx]:
            violated = True
            break

    if not violated:
        for prev, curr in zip(events, events[1:]):
            if curr["occurred_at"] < prev["occurred_at"]:
                violated = True
                break

    by_type = {}
    for event in events:
        by_type.setdefault(event["event_type"], event)

    transit_hours = None
    pickup = by_type.get("CARRIER_PICKUP")
    received = by_type.get("LAB_RECEIVED")
    if pickup is not None and received is not None:
        transit_hours = round_half_up(
            hours_between(pickup["occurred_at"], received["occurred_at"]), 2
        )
        if transit_hours > MAX_TRANSIT_HOURS:
            violated = True

    sealed = by_type.get("CONSUMER_SEALED")
    if sealed is not None and sealed.get("seal_id_observed") != kit.get("seal_id_issued"):
        violated = True
    if received is not None and received.get("seal_id_observed") != kit.get("seal_id_issued"):
        violated = True

    if violated:
        return "BROKEN", transit_hours
    if len(events) < len(REQUIRED_SEQUENCE):
        return "PENDING", transit_hours
    return "INTACT", transit_hours


# =============================================================================
# 7. batch_code_resolution
# =============================================================================
def normalize_batch_code(raw):
    return NORMALIZE_PATTERN.sub("", (raw or "").upper())


# =============================================================================
# 8. plant_oversight_posture — see services.sync_plant
# 9. regulatory_due_at
# =============================================================================
def regulatory_due_at(escalated_at, band):
    if band == "S1":
        return escalated_at + hours(S1_DEADLINE_HOURS)
    return escalated_at + hours(STANDARD_DEADLINE_HOURS)


# =============================================================================
# 10. sample_kit_retention_window
# =============================================================================
def kit_retention_window(shipped_at):
    expected_return_by = shipped_at + days(KIT_RETURN_WINDOW_DAYS)
    return {
        "shipped_at": shipped_at,
        "expected_return_by": expected_return_by,
        "occupied_from": shipped_at - hours(KIT_COOLDOWN_HOURS),
        "occupied_until": expected_return_by + hours(KIT_COOLDOWN_HOURS),
    }
