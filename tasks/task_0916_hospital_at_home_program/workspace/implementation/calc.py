"""The ten calculation rules of the program, plus the program constants.

All money is Decimal arithmetic quantized to two decimals, ROUND_HALF_UP
(PRD 2.7). Never float.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- program constants ----------------------------------------------------
ELIGIBLE_REFERRAL_ORIGINS = ("ED", "INPATIENT_WARD")
QUALIFYING_CONDITION_CODES = (
    "CHF_EXAC",
    "COPD_EXAC",
    "CAP_PNEUMONIA",
    "CELLULITIS",
    "UTI_COMPLICATED",
    "COVID_MODERATE",
)
SERVICE_RADIUS_KM = Decimal("40.0")
PHYSICIAN_EVAL_WINDOW_HOURS = 24

WAIVER_REQUIRED_IN_PERSON_VISITS_PER_DAY = 2
WAIVER_REQUIRED_PHYSICIAN_EVALS_PER_DAY = 1
FFS_REQUIRED_IN_PERSON_VISITS_PER_DAY = 1
FFS_REQUIRED_PHYSICIAN_EVALS_PER_DAY = 0
MAX_MONITORING_LAPSE_MINUTES_PER_DAY = 240

TIER_ACK_SLA_MINUTES = {1: 10, 2: 20, 3: 30, 4: 15}
HIGH_ACUITY_SLA_MULTIPLIER = Decimal("0.5")

VISIT_TURNAROUND_BUFFER_MINUTES = 15
TRAVEL_BAND_1_MAX_KM = Decimal("10.0")
TRAVEL_BAND_2_MAX_KM = Decimal("25.0")
TRAVEL_BAND_1_USD_PER_KM = Decimal("0.92")
TRAVEL_BAND_2_USD_PER_KM = Decimal("0.74")
TRAVEL_BAND_3_USD_PER_KM = Decimal("0.61")
TRAVEL_MIN_PAYMENT_USD = Decimal("8.00")

CONTROLLED_HANDLING_BASE_USD = Decimal("45.00")
NON_CONTROLLED_HANDLING_BASE_USD = Decimal("12.00")
WITNESS_FEE_USD = Decimal("12.50")
COLD_CHAIN_SURCHARGE_USD = Decimal("22.00")
COLD_CHAIN_MAX_EXCURSION_MINUTES = 30
DELIVERY_WEIGHT_FEE_PER_KG_USD = Decimal("1.40")
REDELIVERY_FEE_USD = Decimal("9.00")
DELIVERY_FEE_FLOOR_USD = Decimal("15.00")
DELIVERY_FEE_CAP_USD = Decimal("120.00")
MAX_REDELIVERY_ATTEMPTS = 2

MEAL_CREDIT_PER_DAY_USD = Decimal("28.00")
MEAL_MIN_DAILY_DELIVERIES = 1
MEAL_MAX_DAILY_DELIVERIES = 3

REFURB_CYCLE_LIMIT = 5
BED_HOLD_MINUTES = 120

WAIVER_PER_DIEM_USD = Decimal("1850.00")
DRG_EQUIVALENT_BASE_USD = Decimal("9600.00")
DRG_EQUIVALENT_OUTLIER_PER_DIEM_USD = Decimal("640.00")
DRG_OUTLIER_THRESHOLD_DAYS = 6
CLAIM_WITHHOLD_TIER_THRESHOLD_USD = Decimal("9600.00")
CLAIM_WITHHOLD_RATE_LOW = Decimal("0.02")
CLAIM_WITHHOLD_RATE_HIGH = Decimal("0.05")
APPEAL_RECOVERY_RATE = Decimal("0.60")
MAX_APPEAL_ATTEMPTS = 2
MIN_BILLABLE_DAYS_FOR_CLAIM = 1

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value):
    """Quantize to two decimals, half up (PRD 2.7)."""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_int(value):
    """Whole-number rounding, half up (escalation SLA minutes, PRD 2.7)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- calculation: visit_travel_reimbursement ------------------------------

def visit_travel_payment(distance_km):
    """Average-rate banding: one rate applies to the whole distance (PRD 3.3)."""
    distance = to_decimal(distance_km)
    if distance <= TRAVEL_BAND_1_MAX_KM:
        rate = TRAVEL_BAND_1_USD_PER_KM
    elif distance <= TRAVEL_BAND_2_MAX_KM:
        rate = TRAVEL_BAND_2_USD_PER_KM
    else:
        rate = TRAVEL_BAND_3_USD_PER_KM
    payment = money(distance * rate)
    # Unconditional per-visit floor; no telehealth exemption.
    if payment < TRAVEL_MIN_PAYMENT_USD:
        payment = TRAVEL_MIN_PAYMENT_USD
    return money(payment)


def travel_total(per_visit_amounts):
    """Round per visit first, THEN sum (PRD 2.7 pinned order)."""
    total = ZERO
    for amount in per_visit_amounts:
        total = total + money(amount)
    return money(total)


# --- calculation: delivery_handling_fee -----------------------------------

def delivery_handling_fee(is_controlled, cold_chain_required, weight_kg, redelivery_count):
    if is_controlled:
        base = CONTROLLED_HANDLING_BASE_USD
        witness = WITNESS_FEE_USD
    else:
        base = NON_CONTROLLED_HANDLING_BASE_USD
        witness = ZERO
    cold = COLD_CHAIN_SURCHARGE_USD if cold_chain_required else ZERO
    weight_fee = money(to_decimal(weight_kg) * DELIVERY_WEIGHT_FEE_PER_KG_USD)
    redelivery_fee = to_decimal(redelivery_count) * REDELIVERY_FEE_USD
    raw = base + witness + cold + weight_fee + redelivery_fee
    # Pinned order: floor first, then cap.
    bounded = raw
    if bounded < DELIVERY_FEE_FLOOR_USD:
        bounded = DELIVERY_FEE_FLOOR_USD
    if bounded > DELIVERY_FEE_CAP_USD:
        bounded = DELIVERY_FEE_CAP_USD
    return money(bounded)


# --- calculation: escalation_sla_deadline ---------------------------------

def effective_sla_minutes(tier, acuity):
    base = TIER_ACK_SLA_MINUTES[tier]
    if acuity == "HIGH":
        return round_half_up_int(to_decimal(base) * HIGH_ACUITY_SLA_MULTIPLIER)
    return base


# --- calculation: episode_reimbursement_amount ----------------------------

def episode_reimbursement(program_track, billable_day_count):
    billable = int(billable_day_count)
    if program_track == "CMS_WAIVER":
        return money(to_decimal(billable) * WAIVER_PER_DIEM_USD)
    if billable == 0:
        return ZERO
    outlier_days = max(0, billable - DRG_OUTLIER_THRESHOLD_DAYS)
    return money(
        DRG_EQUIVALENT_BASE_USD + to_decimal(outlier_days) * DRG_EQUIVALENT_OUTLIER_PER_DIEM_USD
    )


# --- calculation: meal_credit_accrual -------------------------------------

def meal_credit(program_track, credited_day_count):
    if program_track == "CMS_WAIVER":
        return ZERO
    return money(to_decimal(credited_day_count) * MEAL_CREDIT_PER_DAY_USD)


# --- calculation: claim_net_payable ---------------------------------------

def claim_money(reimbursement_amount_usd, meal_credit_total_usd):
    """Four pinned steps: gross, rate keyed on gross, withhold, net."""
    gross = money(to_decimal(reimbursement_amount_usd) + to_decimal(meal_credit_total_usd))
    if gross <= CLAIM_WITHHOLD_TIER_THRESHOLD_USD:
        rate = CLAIM_WITHHOLD_RATE_LOW
    else:
        rate = CLAIM_WITHHOLD_RATE_HIGH
    withhold = money(gross * rate)
    net = money(gross - withhold)
    return gross, rate, withhold, net


def appeal_recovery(net_payable_usd):
    return money(to_decimal(net_payable_usd) * APPEAL_RECOVERY_RATE)


# --- calculation: monitoring_lapse_daily_minutes --------------------------

def merge_lapse_minutes(clipped_intervals):
    """Interval merge; adjacency with a zero gap merges. Floor to whole minutes."""
    merged = []
    for start, end in clipped_intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            if end > merged[-1][1]:
                merged[-1][1] = end
    total_seconds = 0
    for start, end in merged:
        total_seconds += int((end - start).total_seconds())
    return total_seconds // 60


# --- calculation: daily_visit_compliance ----------------------------------

CARVE_INSUFFICIENT_IN_PERSON_VISITS = "INSUFFICIENT_IN_PERSON_VISITS"
CARVE_MISSING_PHYSICIAN_EVAL = "MISSING_PHYSICIAN_EVAL"
CARVE_MONITORING_LAPSE_EXCEEDED = "MONITORING_LAPSE_EXCEEDED"
CARVE_KIT_NOT_DEPLOYED = "KIT_NOT_DEPLOYED"


def track_requirements(program_track):
    if program_track == "CMS_WAIVER":
        return (
            WAIVER_REQUIRED_IN_PERSON_VISITS_PER_DAY,
            WAIVER_REQUIRED_PHYSICIAN_EVALS_PER_DAY,
            True,
        )
    return (
        FFS_REQUIRED_IN_PERSON_VISITS_PER_DAY,
        FFS_REQUIRED_PHYSICIAN_EVALS_PER_DAY,
        False,
    )


def score_day(program_track, qualified_in_person_visit_count, physician_eval_present,
              monitoring_lapse_minutes, kit_deployed_all_day):
    """Four clauses in a fixed order; the first failure names the carve-out reason."""
    required_in_person, required_physician, kit_clause_applies = track_requirements(program_track)
    if qualified_in_person_visit_count < required_in_person:
        return "CARVED_OUT", CARVE_INSUFFICIENT_IN_PERSON_VISITS
    if not (required_physician == 0 or physician_eval_present):
        return "CARVED_OUT", CARVE_MISSING_PHYSICIAN_EVAL
    if not (monitoring_lapse_minutes <= MAX_MONITORING_LAPSE_MINUTES_PER_DAY):
        return "CARVED_OUT", CARVE_MONITORING_LAPSE_EXCEEDED
    if not ((not kit_clause_applies) or kit_deployed_all_day):
        return "CARVED_OUT", CARVE_KIT_NOT_DEPLOYED
    return "COMPLIANT", None
