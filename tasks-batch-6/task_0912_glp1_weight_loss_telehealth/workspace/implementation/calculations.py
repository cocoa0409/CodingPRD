"""The nine calculation rules of the PRD, with their pinned orders and rounding.

All money is whole cents computed through decimal.Decimal with ROUND_HALF_UP;
no float ever participates in a monetary result.
"""

from decimal import Decimal, ROUND_HALF_UP

from store import parse_iso, whole_days_between

# --- policy constants (PRD 2.9, 3.1-3.10; SCAFFOLD policy_constants) -------
CONSULT_BUFFER_MINUTES = 15
COACHING_BUFFER_MINUTES = 0
MAX_UNITS_PER_ORDER = 4
MAX_PA_APPEALS = 2
PA_VALIDITY_DAYS = 180
PAUSE_MAX_DAYS = 60
TITRATION_SECOND_SIGNER_MIN_LEVEL = 4
TITRATION_MAX_DOSE_LEVEL = 5
CYCLE_LENGTH_DAYS = 30
COACHING_CREDITS_PER_CYCLE = 4

BMI_OBESITY_MIN = Decimal("30.0")
BMI_COMORBID_MIN = Decimal("27.0")
COMORBIDITY_MIN_COUNT = 1
EGFR_EXCLUSION_MIN = Decimal("30.0")
LAB_VALIDITY_DAYS = 90

TITRATION_MIN_INTERVAL_DAYS = 28
TITRATION_EXTENDED_INTERVAL_DAYS = 42
TITRATION_TOLERABILITY_TRIGGER_INDEX = 4

NAUSEA_WEIGHT = 1
VOMITING_WEIGHT = 2
DEHYDRATION_WEIGHT = 4
CHECK_IN_ESCALATION_SCORE = 7
CHECK_IN_HOLD_SCORE = 9
SEVERITY_WINDOW_DAYS = 30

UNIT_PRICE_COMPOUNDED_CENTS = 20000
UNIT_PRICE_BRANDED_CENTS = 25000
DOSE_MULTIPLIER = {
    1: Decimal("1.00"),
    2: Decimal("1.00"),
    3: Decimal("1.25"),
    4: Decimal("1.25"),
    5: Decimal("1.50"),
}
CASH_DISCOUNT_PCT = Decimal("0.15")
CASH_DISCOUNT_MAX_CENTS = 9000
PLAN_ALLOWED_CAP_CENTS = 42000
COPAY_CENTS = 3500
COINSURANCE_PCT = Decimal("0.20")
OOP_MAX_PER_CYCLE_CENTS = 9000

COACHING_ADDON_FEE_CENTS = 4900
DISPENSING_FEE_CENTS = 2500
DISPENSING_FEE_WAIVER_SUBTOTAL_CENTS = 36000
ADHERENCE_CREDIT_TIER_0_CENTS = 0
ADHERENCE_CREDIT_TIER_1_2_CENTS = 1500
ADHERENCE_CREDIT_TIER_3_PLUS_CENTS = 3000

COACHING_CREDIT_REFUND_CENTS = 1000

LOT_MIN_SHELF_LIFE_DAYS = 30

DOSE_MG_BY_FAMILY_AND_LEVEL = {
    "SEMAGLUTIDE": {1: 0.25, 2: 0.5, 3: 1.0, 4: 1.7, 5: 2.4},
    "TIRZEPATIDE": {1: 2.5, 2: 5.0, 3: 7.5, 4: 12.5, 5: 15.0},
}


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def dec(value):
    return Decimal(str(value))


# --- 1. eligibility_bmi_assessment ----------------------------------------
def bmi(weight_kg, height_cm):
    """BMI rounded half-up to exactly one decimal place (PRD 2.9, 3.1)."""
    if weight_kg is None or height_cm is None:
        return None
    metres = dec(height_cm) / Decimal(100)
    if metres == 0:
        return None
    raw = dec(weight_kg) / (metres * metres)
    return round_half_up(raw, 1)


def bmi_float(weight_kg, height_cm):
    value = bmi(weight_kg, height_cm)
    return None if value is None else float(value)


def eligibility_band(assessed_bmi, comorbidity_count):
    if assessed_bmi is None:
        return "NONE"
    if assessed_bmi >= BMI_OBESITY_MIN:
        return "OBESITY"
    if assessed_bmi >= BMI_COMORBID_MIN and comorbidity_count >= COMORBIDITY_MIN_COUNT:
        return "COMORBID"
    return "NONE"


def screening_decision(egfr, lab_age_days, assessed_bmi, comorbidity_count):
    """PRD 3.2: a pinned, total ladder; the first matching clause wins."""
    if lab_age_days >= LAB_VALIDITY_DAYS:
        return "DEFERRED", "STALE_LABS", None
    if dec(egfr) < EGFR_EXCLUSION_MIN:
        return "INELIGIBLE", "RENAL_EXCLUSION", "NONE"
    band = eligibility_band(assessed_bmi, comorbidity_count)
    if band == "OBESITY":
        return "ELIGIBLE", "BMI_QUALIFIED", "OBESITY"
    if band == "COMORBID":
        return "ELIGIBLE", "COMORBID_QUALIFIED", "COMORBID"
    return "INELIGIBLE", "BMI_BELOW_BAND", "NONE"


def lab_age_days(clock_dt, lab_collected_raw):
    return whole_days_between(parse_iso(lab_collected_raw), clock_dt)


# --- 2. dose_schedule_lookup ----------------------------------------------
def dose_mg_for(drug_family, dose_level):
    return DOSE_MG_BY_FAMILY_AND_LEVEL[drug_family][dose_level]


# --- 3. titration_readiness_interval --------------------------------------
def required_interval_days(severity_index_since_dose_change):
    if severity_index_since_dose_change >= TITRATION_TOLERABILITY_TRIGGER_INDEX:
        return TITRATION_EXTENDED_INTERVAL_DAYS
    return TITRATION_MIN_INTERVAL_DAYS


# --- 4. side_effect_severity_index ----------------------------------------
def severity_score(nausea_score, vomiting_score, dehydration_flag):
    return (nausea_score * NAUSEA_WEIGHT
            + vomiting_score * VOMITING_WEIGHT
            + (DEHYDRATION_WEIGHT if dehydration_flag else 0))


def index_of(check_ins):
    scores = [c["severity_score"] for c in check_ins]
    return max(scores) if scores else 0


# --- 5. cycle_medication_charge -------------------------------------------
def medication_charge(active_route_mode, dose_level, units_per_cycle):
    """Returns (charge_basis, medication_charge_cents).

    The per-unit price is rounded to whole cents BEFORE it is multiplied by
    units_per_cycle -- never after (PRD 2.9, 3.9).
    """
    branded = active_route_mode == "INSURANCE"
    unit_list_cents = UNIT_PRICE_BRANDED_CENTS if branded else UNIT_PRICE_COMPOUNDED_CENTS
    per_unit_cents = cents(Decimal(unit_list_cents) * DOSE_MULTIPLIER[dose_level])
    gross_cents = per_unit_cents * units_per_cycle

    if branded:
        allowed_cents = min(gross_cents, PLAN_ALLOWED_CAP_CENTS)
        coins_cents = cents(Decimal(max(0, allowed_cents - COPAY_CENTS)) * COINSURANCE_PCT)
        insured_due = min(COPAY_CENTS + coins_cents, OOP_MAX_PER_CYCLE_CENTS)
        return "INSURANCE_ADJUDICATED", insured_due

    cash_discount_cents = min(CASH_DISCOUNT_MAX_CENTS,
                              cents(Decimal(gross_cents) * CASH_DISCOUNT_PCT))
    return "CASH_PAY", gross_cents - cash_discount_cents


# --- 6. cycle_invoice_total -----------------------------------------------
def adherence_credit(triaged_count):
    if triaged_count == 0:
        return ADHERENCE_CREDIT_TIER_0_CENTS
    if triaged_count <= 2:
        return ADHERENCE_CREDIT_TIER_1_2_CENTS
    return ADHERENCE_CREDIT_TIER_3_PLUS_CENTS


def invoice_total(medication_charge_cents, coaching_addon_enabled, triaged_count):
    """The six pinned steps of PRD 3.9; no rounding happens anywhere here."""
    coaching_addon_fee_cents = COACHING_ADDON_FEE_CENTS if coaching_addon_enabled else 0
    subtotal_cents = medication_charge_cents + coaching_addon_fee_cents
    dispensing_fee_cents = (0 if subtotal_cents >= DISPENSING_FEE_WAIVER_SUBTOTAL_CENTS
                            else DISPENSING_FEE_CENTS)
    adherence_credit_cents = adherence_credit(triaged_count)
    total_due_cents = max(0, subtotal_cents + dispensing_fee_cents - adherence_credit_cents)
    return {
        "coaching_addon_fee_cents": coaching_addon_fee_cents,
        "dispensing_fee_cents": dispensing_fee_cents,
        "adherence_credit_cents": adherence_credit_cents,
        "total_due_cents": total_due_cents,
    }


# --- 7. subscription_proration_credit -------------------------------------
def proration_credit(cycle, clock_dt):
    """Each component prorated and rounded separately, then summed (PRD 3.9)."""
    days_elapsed = whole_days_between(parse_iso(cycle["period_start_at"]), clock_dt)
    days_elapsed = min(max(days_elapsed, 0), CYCLE_LENGTH_DAYS)
    unused_days = CYCLE_LENGTH_DAYS - days_elapsed

    def slice_of(amount):
        return cents(Decimal(amount) * Decimal(unused_days) / Decimal(CYCLE_LENGTH_DAYS))

    return (slice_of(cycle["medication_charge_cents"])
            + slice_of(cycle["coaching_addon_fee_cents"])
            + slice_of(cycle["dispensing_fee_cents"]))


# --- 8. coaching_entitlement_balance --------------------------------------
def credits_available(subscription):
    """RESERVED_INCLUSIVE reading -- the booking gate (PRD 3.10)."""
    return (subscription["coaching_credits_granted"]
            - subscription["coaching_credits_reserved"]
            - subscription["coaching_credits_consumed"]
            - subscription["coaching_credits_forfeited"])


def coaching_unused_credit(subscription):
    """COMPLETED_ONLY reading -- the settle credit-back (PRD 3.10)."""
    unused_for_refund = max(0, subscription["coaching_credits_granted"]
                            - subscription["coaching_credits_consumed"])
    return min(unused_for_refund * COACHING_CREDIT_REFUND_CENTS, COACHING_ADDON_FEE_CENTS)


# --- 9. supply_lot_routing_selection --------------------------------------
def strengths_match(a, b):
    return dec(a) == dec(b)
