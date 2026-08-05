"""The calculation rules of PRD 2.10 and section 3, with every declared constant."""

import math
from decimal import Decimal

from store import add_days, dec, round_half_up

# --- study quality and severity -------------------------------------------
MIN_HSAT_RECORDING_MINUTES = 240
MAX_HSAT_ARTIFACT_PCT = 20
MIN_PSG_TST_MINUTES = 180
AHI_MILD_MIN = Decimal("5.0")
AHI_MODERATE_MIN = Decimal("15.0")
AHI_SEVERE_MIN = Decimal("30.0")

# --- referral currency and medical necessity ------------------------------
HSAT_VALIDITY_DAYS = 365
PSG_VALIDITY_DAYS = 1095
MIN_CPAP_TRIAL_NIGHTS = 30
CPAP_LOOKBACK_DAYS = 730
MIN_SYMPTOM_SCORE = 10

# --- device fabrication and titration -------------------------------------
START_ADVANCEMENT_PCT = Decimal("0.60")
PREFAB_START_MM = Decimal("4.00")
PREFAB_START_PCT = Decimal("0.50")
MM_INCREMENT = Decimal("0.25")
MAX_INCREMENT_PER_VISIT_MM = Decimal("1.00")
SEVERE_SIDE_EFFECT_REDUCTION_MM = Decimal("0.50")
MIN_TITRATION_INTERVAL_DAYS = 14
PLATEAU_MIN_VISITS = 3
WARRANTY_MONTHS = 36

# --- adherence ------------------------------------------------------------
ADHERENCE_WINDOW_DAYS = 30
ADHERENCE_MIN_HOURS = Decimal("4.0")
ADHERENCE_MIN_NIGHTS_PCT = Decimal("0.70")

# --- efficacy -------------------------------------------------------------
PARTIAL_AHI_CEILING = Decimal("10.0")
EFFICACY_REPORT_DUE_DAYS = 30

# --- money ----------------------------------------------------------------
FEE_SCHEDULE_E0486_CENTS = 185000
FEE_SCHEDULE_A9270_CENTS = 0
LABOR_RATE_CENTS_PER_15MIN = 2500
REPAIR_CAP_PCT = Decimal("0.50")

# --- documentation --------------------------------------------------------
F2F_LOOKBACK_DAYS = 180
PA_VALIDITY_DAYS = 90

# --- patient recall cadence ----------------------------------------------
FIRST_RECALL_DAYS = 90
SUBSEQUENT_RECALL_DAYS = 365
RECALL_GRACE_DAYS = 30

LIVE_LIFECYCLE = (
    "DELIVERED", "IN_TITRATION", "TITRATION_SUSPENDED",
    "TITRATION_PLATEAU", "EFFICACY_PENDING", "ACTIVE_THERAPY",
)


def severity_denominator_hours(modality, recording_minutes, sleep_minutes):
    """Dual variant: HSAT counts every monitored minute, PSG only scored sleep."""
    if modality == "HSAT":
        minutes = recording_minutes
    else:
        minutes = sleep_minutes
    if minutes is None:
        return None
    return dec(minutes) / dec(60)


def severity_index(respiratory_events, denominator_hours):
    return round_half_up(dec(respiratory_events) / denominator_hours, 1)


def study_is_diagnostic(modality, recording_minutes, artifact_pct, sleep_minutes, attended):
    if modality == "HSAT":
        return (recording_minutes is not None
                and recording_minutes >= MIN_HSAT_RECORDING_MINUTES
                and dec(artifact_pct if artifact_pct is not None else 0) <= dec(MAX_HSAT_ARTIFACT_PCT))
    return (sleep_minutes is not None
            and sleep_minutes >= MIN_PSG_TST_MINUTES
            and bool(attended))


def severity_band(index):
    if index >= AHI_SEVERE_MIN:
        return "SEVERE"
    if index >= AHI_MODERATE_MIN:
        return "MODERATE"
    if index >= AHI_MILD_MIN:
        return "MILD"
    return "NONE"


def diagnosis_valid_until(modality, performed_on):
    window = HSAT_VALIDITY_DAYS if modality == "HSAT" else PSG_VALIDITY_DAYS
    return add_days(performed_on, window)


def starting_advancement(appliance_kind, max_protrusive_mm):
    """Scale to the mechanical grain first, round once, multiply back."""
    ceiling = dec(max_protrusive_mm)
    if appliance_kind == "CUSTOM_FABRICATED":
        raw = START_ADVANCEMENT_PCT * ceiling
    else:
        raw = min(PREFAB_START_MM, PREFAB_START_PCT * ceiling)
    grains = round_half_up(raw / MM_INCREMENT, 0)
    return (grains * MM_INCREMENT).quantize(Decimal("0.01"))


def adherence_rates(nights_at_or_above, nights_recorded):
    rate_of_window = round_half_up(dec(nights_at_or_above) / dec(ADHERENCE_WINDOW_DAYS), 4)
    if nights_recorded == 0:
        rate_of_recorded = None
    else:
        rate_of_recorded = round_half_up(dec(nights_at_or_above) / dec(nights_recorded), 4)
    compliant = rate_of_window >= ADHERENCE_MIN_NIGHTS_PCT
    return rate_of_window, rate_of_recorded, compliant


def efficacy_outcome(baseline_index, residual_index, residual_target, pct_target):
    baseline = dec(baseline_index)
    residual = dec(residual_index)
    if baseline == 0:
        pct_reduction = None
    else:
        pct_reduction = round_half_up((baseline - residual) / baseline, 4)
    meets_absolute = residual <= dec(residual_target)
    meets_relative = (pct_reduction is not None
                      and pct_reduction >= dec(pct_target)
                      and residual < PARTIAL_AHI_CEILING)
    if meets_absolute and meets_relative:
        outcome = "COMPLETE"
    elif meets_absolute or meets_relative:
        outcome = "PARTIAL"
    else:
        outcome = "FAILED"
    return pct_reduction, meets_absolute, meets_relative, outcome


def repair_billability(reason, reported_on, warranty_end_date, labor_minutes):
    in_warranty = (reason == "DEFECT"
                   and warranty_end_date is not None
                   and reported_on <= warranty_end_date)
    billable = not in_warranty
    if billable:
        labor_units = int(math.ceil(dec(labor_minutes) / dec(15)))
        uncapped = labor_units * LABOR_RATE_CENTS_PER_15MIN
        cap = int(round_half_up(REPAIR_CAP_PCT * dec(FEE_SCHEDULE_E0486_CENTS), 0))
        charge = min(uncapped, cap)
    else:
        labor_units = 0
        charge = 0
    return in_warranty, billable, labor_units, charge


def fee_basis(hcpcs_code, repair_order):
    if hcpcs_code == "E0486":
        return FEE_SCHEDULE_E0486_CENTS
    if hcpcs_code == "A9270":
        return FEE_SCHEDULE_A9270_CENTS
    if repair_order is None:
        return 0
    return repair_order.get("repair_charge_cents") or 0


def claim_allowed(billed_cents, basis):
    allowed = min(billed_cents, basis)
    return allowed, billed_cents - allowed


def patient_responsibility(allowed_cents, deductible_remaining, coinsurance_pct):
    """Deductible first, coinsurance on the remainder, rounded exactly once."""
    deductible_applied = min(allowed_cents, deductible_remaining)
    base = allowed_cents - deductible_applied
    coinsurance = int(round_half_up(dec(coinsurance_pct) * dec(base), 0))
    responsibility = deductible_applied + coinsurance
    payer_paid = allowed_cents - responsibility
    return deductible_applied, coinsurance, responsibility, payer_paid


def recall_posture(clock_day, next_due):
    """The lapse edge is tested first, so a single large jump skips DUE."""
    if next_due is None:
        return None
    if clock_day >= add_days(next_due, RECALL_GRACE_DAYS):
        return "LAPSED"
    if clock_day >= next_due:
        return "DUE"
    return None
