"""The declared calculations (PRD 2.8, 3.x).

Every rounding is ROUND_HALF_UP and happens exactly at the point the PRD pins.
Money is whole cents held as ``int``; MME quantities are ``Decimal`` with one
decimal place.
"""

from decimal import Decimal, ROUND_HALF_UP

import config
from store import days, minutes

ZERO = Decimal("0")
ONE_DP = Decimal("0.1")
WHOLE = Decimal("1")


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ referral
def referral_triage_variant(source):
    return "PAYER_SOURCED" if source in config.PAYER_SOURCED_SOURCES else "CLINICIAN_SOURCED"


def referral_triage_score(source, prognosis_months, criteria_count):
    gap = max(0, config.REFERRAL_PROGNOSIS_MAX_MONTHS - prognosis_months)
    variant = referral_triage_variant(source)
    if variant == "PAYER_SOURCED":
        weight = (config.TRIAGE_SOURCE_WEIGHT_HOSPITAL_DISCHARGE
                  if source == "HOSPITAL_DISCHARGE" else config.TRIAGE_SOURCE_WEIGHT_PAYER)
        raw = (weight
               + config.TRIAGE_CRITERION_POINTS * criteria_count
               + config.TRIAGE_PROGNOSIS_POINTS_PER_MONTH * gap)
    else:
        raw = (config.TRIAGE_CRITERION_POINTS
               * config.TRIAGE_CLINICIAN_CRITERION_MULTIPLIER * criteria_count
               + config.TRIAGE_CLINICIAN_PROGNOSIS_POINTS_PER_MONTH * gap)
    return variant, min(config.TRIAGE_SCORE_CAP, raw)


# ------------------------------------------------------------------ symptoms
def symptom_distress_score(reporter_type, pain, dyspnea, nausea, anxiety, fatigue):
    objective = Decimal(pain + dyspnea + nausea)
    subjective = Decimal(anxiety + fatigue)
    if reporter_type == "SELF":
        raw = (objective + subjective) * Decimal(config.SELF_REPORT_MULTIPLIER)
    else:
        raw = ((objective + Decimal(config.PROXY_SUBJECTIVE_WEIGHT) * subjective)
               * Decimal(config.PROXY_REPORT_MULTIPLIER))
    return min(config.DISTRESS_SCORE_CAP, int(round_half_up(raw, 0)))


def severity_tier(distress_score):
    if distress_score >= config.DISTRESS_TIER_SEVERE_MIN:
        return "SEVERE"
    if distress_score >= config.DISTRESS_TIER_MODERATE_MIN:
        return "MODERATE"
    if distress_score >= config.DISTRESS_TIER_MILD_MIN:
        return "MILD"
    return "MINIMAL"


def response_due_at(created_at, tier):
    sla = {
        "SEVERE": config.SLA_MINUTES_SEVERE,
        "MODERATE": config.SLA_MINUTES_MODERATE,
        "MILD": config.SLA_MINUTES_MILD,
        "MINIMAL": config.SLA_MINUTES_MINIMAL,
    }[tier]
    return created_at + minutes(sla)


# ---------------------------------------------------------------- medication
def medication_daily_mme(drug, dose_amount, opioid_status):
    factor = Decimal(config.MME_FACTORS[drug])
    base = Decimal(dose_amount) * factor
    if opioid_status == "OPIOID_TOLERANT":
        return "TOLERANT", round_half_up(base, 1)
    return "NAIVE", round_half_up(base * Decimal(config.OPIOID_NAIVE_SAFETY_FACTOR), 1)


def breakthrough_dose_mg(active_mme_values, breakthrough_drug):
    if breakthrough_drug is None:
        return None
    total = sum(active_mme_values, ZERO)
    bt_mme = total * Decimal(config.BREAKTHROUGH_FRACTION)
    factor = Decimal(config.MME_FACTORS[breakthrough_drug])
    return round_half_up(bt_mme / factor, 1)


def next_refill_allowed_at(last_fill_at, days_supply):
    return last_fill_at + days(days_supply) - days(config.EARLY_REFILL_WINDOW_DAYS)


# ------------------------------------------------------------------- billing
def acp_billable_units(documented_minutes):
    extra = (documented_minutes - config.ACP_FIRST_UNIT_MIN_MINUTES) // config.ACP_ADDITIONAL_UNIT_MINUTES
    return min(config.ACP_MAX_UNITS, 1 + extra)


def claim_allowed_amount_cents(billable_units, modality, acp_paid_cents_ytd):
    base = (config.ACP_BASE_RATE_CENTS
            + (billable_units - 1) * config.ACP_ADDITIONAL_UNIT_RATE_CENTS)
    if modality == "TELEHEALTH":
        rated = int(round_half_up(Decimal(base) * Decimal(config.TELEHEALTH_RATE_FACTOR), 0))
        modifier = config.TELEHEALTH_MODIFIER_CODE
    else:
        rated = int(round_half_up(Decimal(base) * Decimal(config.IN_PERSON_RATE_FACTOR), 0))
        modifier = None
    cap_remaining = max(0, config.ACP_ANNUAL_CAP_CENTS - acp_paid_cents_ytd)
    return min(rated, cap_remaining), modifier


def claim_net_payable_cents(allowed_amount_cents):
    if allowed_amount_cents <= config.COINSURANCE_TIER_LOW_MAX_CENTS:
        pct = Decimal(config.COINSURANCE_PCT_LOW)
    else:
        pct = Decimal(config.COINSURANCE_PCT_HIGH)
    responsibility = int(round_half_up(Decimal(allowed_amount_cents) * pct, 0))
    return pct, responsibility, allowed_amount_cents - responsibility


# ----------------------------------------------------------------- documents
def document_execution_requirement(document, jurisdiction_code):
    if jurisdiction_code == "JUR_TWO_WITNESS":
        base_ok = document["witness_signature_count"] >= config.WITNESS_COUNT_REQUIRED_TWO_WITNESS
    else:
        base_ok = document["notary_signature_count"] >= config.NOTARY_COUNT_REQUIRED_NOTARY
    if document["document_type"] == "POLST":
        polst_ok = (document["physician_signature_count"] >= config.POLST_PHYSICIAN_SIGNATURE_REQUIRED
                    and document["patient_or_surrogate_signature_count"]
                    >= config.POLST_PATIENT_OR_SURROGATE_SIGNATURE_REQUIRED)
    else:
        polst_ok = True
    return bool(base_ok and polst_ok), bool(base_ok), bool(polst_ok)


# ------------------------------------------------------------------- hospice
def benefit_period_length_days(period_number):
    if period_number == 1:
        return config.BENEFIT_PERIOD_1_DAYS
    if period_number == 2:
        return config.BENEFIT_PERIOD_2_DAYS
    return config.BENEFIT_PERIOD_SUBSEQUENT_DAYS


def face_to_face_valid(face_to_face_at, period_start):
    if face_to_face_at is None:
        return False
    lower = period_start - days(config.FACE_TO_FACE_WINDOW_DAYS)
    return lower <= face_to_face_at < period_start


def idt_days_since(now, held_at):
    return int((now - held_at).total_seconds() // 86400)


# ---------------------------------------------------------------- escalation
def ack_due_at(tier_notified_at, tier):
    return tier_notified_at + minutes(config.ESCALATION_ACK_SLA_MINUTES[tier])
