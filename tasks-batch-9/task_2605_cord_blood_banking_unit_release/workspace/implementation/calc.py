"""All 18 calculations (PRD 3 / SCAFFOLD calculations), with pinned rounding order."""
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
KIT_SHELF_LIFE_DAYS = 120
MAX_CONSENT_AMENDMENTS = 3
MAX_HOURS_COLLECTION_TO_RECEIPT = Decimal("48.0")
MIN_TRANSPORT_TEMP_C = Decimal("2.0")
MAX_TRANSPORT_TEMP_C = Decimal("30.0")

PUBLIC_TEST_TIER = {"tnc_min": 900, "cd34_min": 1500, "viability_floor": Decimal("85.0")}
PRIVATE_TEST_TIER = {"tnc_min": 400, "cd34_min": 500, "viability_floor": Decimal("75.0")}
CONFIRMATORY_MIN_VIABILITY_PCT = Decimal("70.0")
CONFIRMATORY_MIN_RECOVERY_PCT = Decimal("60.0")

W_TNC = Decimal("0.45")
W_CD34 = Decimal("0.35")
W_VIAB = Decimal("0.20")
VOLUME_PENALTY = Decimal("0.10")
PUBLIC_SCORE_TIER = {
    "tnc_target": Decimal("1500"), "cd34_target": Decimal("3000"),
    "viability_floor": Decimal("85.0"),
    "volume_min": Decimal("24.0"), "volume_max": Decimal("26.0"),
}
PRIVATE_SCORE_TIER = {
    "tnc_target": Decimal("900"), "cd34_target": Decimal("1500"),
    "viability_floor": Decimal("75.0"),
    "volume_min": Decimal("20.0"), "volume_max": Decimal("30.0"),
}
PUBLIC_ACCEPT_SCORE_MIN = Decimal("70.00")
PRIVATE_ACCEPT_SCORE_MIN = Decimal("55.00")

MATERNAL_SCREEN_WINDOW_DAYS = 7
MATERNAL_SCREEN_VALIDITY_DAYS = 180

MIN_RELEASE_DOSE_X1E7 = Decimal("2.50")

GRADE_A_TNC = 1500
GRADE_A_CD34 = 3000
GRADE_B_TNC = 1200
GRADE_B_CD34 = 2000

PUBLIC_LISTING_MIN_TNC_MILLIONS = 900
PUBLIC_LISTING_MIN_CD34_THOUSANDS = 1500
PUBLIC_LISTING_MIN_VIABILITY_PCT = Decimal("85.0")

ANNUAL_STORAGE_FEE_CENTS = Decimal("18000")
DAYS_PER_BILLING_YEAR = Decimal("365")
TANK_PREMIUM_SURCHARGE_PCT = Decimal("0.075")
ADMIN_FEE_PCT = Decimal("0.0125")
LATE_FEE_PCT = Decimal("0.015")
INVOICE_NET_DAYS = 30

DISPOSITION_FEE_CREDIT_CENTS = 2500
DISPOSITION_FEE_SMALL_CENTS = 5000
DISPOSITION_FEE_LARGE_CENTS = 7500
SMALL_TIER_UPPER_CENTS = 9999

EXCURSION_WINDOW_DAYS = 30
CUMULATIVE_EXCURSION_LIMIT_MINUTES = 120
ALARM_THRESHOLD_C = Decimal("-150.0")
MAX_ACK_MINUTES = 30

RESERVATION_HOLD_BUFFER_HOURS = 24
CONFIRM_WINDOW_HOURS = 72

PAST_DUE_DAYS = 30
DELINQUENT_DAYS = 90
ABANDONMENT_NOTICE_DAYS = 180
ABANDONMENT_DAYS = 365


# ---------------------------------------------------------------- primitives
def D(value):
    """Exact Decimal from any numeric-ish value."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    """round_half_up to `places` decimals (PRD 2.8)."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """round_half_up to whole cents."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Decimal -> JSON number."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------- 1. collection_net_volume
def net_volume_ml(gross, anticoagulant):
    return rhu(D(gross) - D(anticoagulant), 1)


# ---------------------------------------------------------------- 2. collection_transit_hours
def elapsed_hours_exact(start_dt, end_dt):
    delta = end_dt - start_dt
    seconds = (Decimal(delta.days) * Decimal(86400)
               + Decimal(delta.seconds)
               + Decimal(delta.microseconds) / Decimal(1000000))
    return seconds / Decimal(3600)


# ---------------------------------------------------------------- 3. volume_reduction_recovery
def tnc_recovery_pct(post_tnc, pre_tnc):
    return rhu(D(post_tnc) / D(pre_tnc) * Decimal(100), 2)


def volume_reduction_pct(pre_volume, post_volume):
    return rhu((D(pre_volume) - D(post_volume)) / D(pre_volume) * Decimal(100), 2)


# ---------------------------------------------------------------- 4. quality_test_outcome
def test_tier(program_type):
    return PUBLIC_TEST_TIER if program_type == "PUBLIC_DONATION" else PRIVATE_TEST_TIER


def post_processing_outcome(program_type, tnc, cd34, viability, sterility):
    tier = test_tier(program_type)
    codes = []
    if sterility != "NEGATIVE":
        codes.append("STERILITY")
    if int(tnc) < tier["tnc_min"]:
        codes.append("TNC")
    if int(cd34) < tier["cd34_min"]:
        codes.append("CD34")
    if D(viability) < tier["viability_floor"]:
        codes.append("VIABILITY")
    codes = sorted(codes)
    return ("PASS" if not codes else "FAIL"), codes


def confirmatory_recovery_pct(conf_tnc, unit_tnc):
    return rhu(D(conf_tnc) / D(unit_tnc) * Decimal(100), 2)


def confirmatory_outcome(recovery_pct, viability, sterility):
    codes = []
    if sterility == "POSITIVE":
        codes.append("STERILITY")
    if D(viability) < CONFIRMATORY_MIN_VIABILITY_PCT:
        codes.append("VIABILITY")
    if D(recovery_pct) < CONFIRMATORY_MIN_RECOVERY_PCT:
        codes.append("RECOVERY")
    codes = sorted(codes)
    return ("PASS" if not codes else "FAIL"), codes


# ---------------------------------------------------------------- 5. unit_quality_acceptance_score
def score_tier(program_type):
    return PUBLIC_SCORE_TIER if program_type == "PUBLIC_DONATION" else PRIVATE_SCORE_TIER


def acceptance_score(program_type, tnc, cd34, viability, volume, sterility):
    """Components and the weighted sum are NEVER rounded; the score is rounded once."""
    tier = score_tier(program_type)
    tnc_component = min(Decimal("1.0"), D(tnc) / tier["tnc_target"])
    cd34_component = min(Decimal("1.0"), D(cd34) / tier["cd34_target"])
    viability_component = max(
        Decimal("0.0"),
        (D(viability) - tier["viability_floor"]) / (Decimal("100.0") - tier["viability_floor"]),
    )
    penalty = Decimal("0.0")
    if volume is not None:
        vol = D(volume)
        if vol < tier["volume_min"] or vol > tier["volume_max"]:
            penalty = VOLUME_PENALTY
    gate = Decimal("1.0") if sterility == "NEGATIVE" else Decimal("0.0")
    weighted = (W_TNC * tnc_component + W_CD34 * cd34_component
                + W_VIAB * viability_component)
    return rhu(gate * max(Decimal("0.0"), weighted - penalty) * Decimal(100), 2)


def accept_score_min(program_type):
    return (PUBLIC_ACCEPT_SCORE_MIN if program_type == "PUBLIC_DONATION"
            else PRIVATE_ACCEPT_SCORE_MIN)


# ---------------------------------------------------------------- 8. nucleated_cell_dose
def pre_cryo_dose(unit_tnc, patient_weight_kg):
    return rhu(D(unit_tnc) / (Decimal(10) * D(patient_weight_kg)), 2)


def post_thaw_dose(unit_tnc, conf_tnc, conf_viability, patient_weight_kg):
    recovery = confirmatory_recovery_pct(conf_tnc, unit_tnc)
    effective_tnc = rhu(
        D(unit_tnc) * (D(conf_viability) / Decimal(100)) * (recovery / Decimal(100)), 2)
    dose = rhu(effective_tnc / (Decimal(10) * D(patient_weight_kg)), 2)
    return recovery, effective_tnc, dose


# ---------------------------------------------------------------- 9. registry_potency_grade
def potency_grade(tnc, cd34):
    tnc = int(tnc)
    cd34 = int(cd34)
    if tnc >= GRADE_A_TNC and cd34 >= GRADE_A_CD34:
        return "A"
    if tnc >= GRADE_B_TNC and cd34 >= GRADE_B_CD34:
        return "B"
    return "C"


# ---------------------------------------------------------------- 10. storage_invoice_total
def invoice_lines(prorated_days, premium_tank):
    """Per-line rounding, then a plain sum.  Order is pinned."""
    base = rhu_cents(ANNUAL_STORAGE_FEE_CENTS * Decimal(int(prorated_days))
                     / DAYS_PER_BILLING_YEAR)
    surcharge = rhu_cents(Decimal(base) * TANK_PREMIUM_SURCHARGE_PCT) if premium_tank else 0
    admin = rhu_cents(ANNUAL_STORAGE_FEE_CENTS * ADMIN_FEE_PCT)
    return base, surcharge, admin


def late_fee_increment(residual_cents):
    return rhu_cents(Decimal(int(residual_cents)) * LATE_FEE_PCT)


# ---------------------------------------------------------------- 11. storage_fee_assessment
def prorated_refund_cents(plan_term_years, unused_days):
    if int(plan_term_years) == 1:
        return 0  # ANNIVERSARY_ACCRUAL
    return rhu_cents(ANNUAL_STORAGE_FEE_CENTS * Decimal(int(unused_days))
                     / DAYS_PER_BILLING_YEAR)  # PRORATED_TERMINATION


# ---------------------------------------------------------------- 12. disposition_settlement
def disposition_fee_cents(subtotal):
    if subtotal <= 0:
        return DISPOSITION_FEE_CREDIT_CENTS
    if subtotal <= SMALL_TIER_UPPER_CENTS:
        return DISPOSITION_FEE_SMALL_CENTS
    return DISPOSITION_FEE_LARGE_CENTS


def settlement_total_cents(balance_cents, refund_cents):
    subtotal = int(balance_cents) - int(refund_cents)
    return subtotal + disposition_fee_cents(subtotal)


# ---------------------------------------------------------------- 15. cumulative_excursion_minutes
def duration_minutes(detected_dt, resolved_dt):
    delta = resolved_dt - detected_dt
    total_seconds = delta.days * 86400 + delta.seconds
    if total_seconds < 0:
        return 0
    return total_seconds // 60


# ---------------------------------------------------------------- 18. delinquency_stage_advance
def days_past_due(due_dt, clock_dt):
    days = (clock_dt.date() - due_dt.date()).days
    return days if days > 0 else 0


def unused_days(clock_dt, paid_through_dt):
    if paid_through_dt is None:
        return 0
    days = (paid_through_dt.date() - clock_dt.date()).days
    return days if days > 0 else 0
