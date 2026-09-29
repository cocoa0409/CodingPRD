"""Domain constants and pure calculations.

All arithmetic runs through decimal.Decimal with ROUND_HALF_UP; no float
rounding and no banker's rounding anywhere.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

# ---------------------------------------------------------------- constants

SYRINGE_VOLUME_L = Decimal("3.000")
CAL_TOLERANCE_PCT = Decimal("3.00")
AMBIENT_TEMP_MIN_C = 20
AMBIENT_TEMP_MAX_C = 27
BAROMETRIC_MIN_KPA = Decimal("80.00")
BAROMETRIC_MAX_KPA = Decimal("110.00")
BODY_TEMP_K = Decimal("310.15")
KELVIN_OFFSET = Decimal("273.15")
PH2O_BODY_KPA = Decimal("6.27")

PH2O_KPA = {
    20: Decimal("2.34"),
    21: Decimal("2.49"),
    22: Decimal("2.64"),
    23: Decimal("2.81"),
    24: Decimal("2.98"),
    25: Decimal("3.17"),
    26: Decimal("3.36"),
    27: Decimal("3.57"),
}

BASELINE_VALIDITY_DAYS = 180
ROLLING_WINDOW_SIZE = 3
BCS_PASS_PCT = Decimal("5.00")
BCS_WARN_PCT = Decimal("10.00")
MIN_DWELL_MINUTES = 20

Z_LLN = Decimal("1.645")
BEV_ABS_ML = 100
BEV_FRAC = Decimal("0.05")
EOFE_MIN_SEC = Decimal("15.0")
REPEAT_TIGHT_ML = 150
REPEAT_LOOSE_ML = 200

BD_PCT_BASELINE_MIN = Decimal("12.0")
BD_ML_MIN = 200
BD_PCT_PREDICTED_MIN = Decimal("10.0")

FVC_NORMAL_PCT = Decimal("80.0")
SEVERITY_MILD_PCT = Decimal("70.0")
SEVERITY_MODERATE_PCT = Decimal("60.0")
SEVERITY_MOD_SEVERE_PCT = Decimal("50.0")
SEVERITY_SEVERE_PCT = Decimal("35.0")

REPORT_TEMPLATE_VERSION = "PFT-2026.1"
BASE_SLA_MINUTES = {
    "ROUTINE_CLINICAL": 1440,
    "OCCUPATIONAL_SURVEILLANCE": 2880,
    "DISABILITY_EVALUATION": 4320,
}
LOAD_NORMAL_PCT = Decimal("50.00")
LOAD_ELEVATED_PCT = Decimal("80.00")
LOAD_MULTIPLIERS = {
    "NORMAL": Decimal("1.00"),
    "ELEVATED": Decimal("1.50"),
    "SURGE": Decimal("2.00"),
}

PC20_THRESHOLD_PCT = Decimal("20.00")
MAX_CUMULATIVE_DOSE_UNITS = Decimal("400")
CHALLENGE_MIN_FEV1_PCT = Decimal("60.0")
RESCUE_RESERVE_DOSES = 4
RESCUE_ADMIN_DOSES = 4

MAX_REJECTION_ROUNDS = 2
DEVICE_TURNAROUND_MINUTES = 20
TECH_MAX_CONCURRENT_SESSIONS = 2

HOLD_HOURS_BY_CLASS = {
    "SABA": 6,
    "SAMA": 8,
    "LABA": 24,
    "LAMA": 36,
    "ICS_LABA": 24,
    "ANTIHISTAMINE": 72,
    "CAFFEINE": 8,
}

MEDICATION_CLASSES = ["SABA", "SAMA", "LABA", "LAMA", "ICS_LABA",
                      "ANTIHISTAMINE", "CAFFEINE"]

MODALITIES = ["SPIROMETRY", "DLCO", "PLETHYSMOGRAPHY"]

APPROVED_INDICATION_MODALITIES = {
    "DYSPNEA_EVALUATION": ["SPIROMETRY", "DLCO"],
    "ASTHMA_DIAGNOSIS": ["SPIROMETRY"],
    "COPD_STAGING": ["SPIROMETRY", "DLCO", "PLETHYSMOGRAPHY"],
    "PREOP_ASSESSMENT": ["SPIROMETRY", "DLCO"],
    "DISABILITY_ASSESSMENT": ["SPIROMETRY", "DLCO", "PLETHYSMOGRAPHY"],
    "OCCUPATIONAL_SURVEILLANCE_ANNUAL": ["SPIROMETRY"],
    "RESTRICTIVE_DISEASE_EVALUATION": ["SPIROMETRY", "PLETHYSMOGRAPHY",
                                       "DLCO"],
}

CONTEXT_INDICATIONS = {
    "DISABILITY_EVALUATION": ["DISABILITY_ASSESSMENT"],
    "OCCUPATIONAL_SURVEILLANCE": ["OCCUPATIONAL_SURVEILLANCE_ANNUAL"],
    "ROUTINE_CLINICAL": ["DYSPNEA_EVALUATION", "ASTHMA_DIAGNOSIS",
                         "COPD_STAGING", "PREOP_ASSESSMENT",
                         "RESTRICTIVE_DISEASE_EVALUATION"],
}

INDICATION_CODES = list(APPROVED_INDICATION_MODALITIES.keys())
TEST_CONTEXTS = list(CONTEXT_INDICATIONS.keys())
CHALLENGE_TYPES = ["NONE", "METHACHOLINE", "MANNITOL"]
CHALLENGE_AGENTS = ["METHACHOLINE", "MANNITOL"]

REJECTION_REASON_ORDER = ["BEV_EXCEEDED", "EARLY_TERMINATION",
                          "COUGH_ARTIFACT", "GLOTTIC_CLOSURE"]


# ------------------------------------------------------------ numeric helpers

def D(value):
    """Coerce anything JSON-ish into a Decimal without float contamination."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rnd(value, places):
    """ROUND_HALF_UP quantisation to `places` decimal places."""
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rnd_int(value):
    """ROUND_HALF_UP quantisation to a whole number, returned as int."""
    if value is None:
        return None
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(value)


def trunc_int(value):
    if value is None:
        return None
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_DOWN))


# ------------------------------------------------- calibration / BTPS (2.3, 3.2)

def calibration_result(measured_volume_l, ambient_temp_c, barometric_pressure_kpa):
    """Return (btps_factor, corrected_volume_l, error_pct, outcome).

    corrected_volume_l is rounded to three decimals BEFORE error_pct is
    derived from it; the chain is normative.
    """
    temp = int(ambient_temp_c)
    ph2o = PH2O_KPA[temp]
    baro = D(barometric_pressure_kpa)
    factor = (BODY_TEMP_K / (KELVIN_OFFSET + D(temp))) * \
             ((baro - ph2o) / (baro - PH2O_BODY_KPA))
    btps_factor = rnd(factor, 4)
    corrected = rnd(D(measured_volume_l) * btps_factor, 3)
    error_pct = rnd(abs(corrected - SYRINGE_VOLUME_L) / SYRINGE_VOLUME_L
                    * Decimal(100), 2)
    outcome = "FAIL" if error_pct > CAL_TOLERANCE_PCT else "PASS"
    return btps_factor, corrected, error_pct, outcome


# --------------------------------------- biologic control deviation (2.3, 3.2)

def biologic_deviation(measured_fev1_l, comparator_fev1_l):
    """Return (deviation_pct, outcome) for a biologic control survey."""
    comparator = D(comparator_fev1_l)
    deviation = rnd(abs(D(measured_fev1_l) - comparator) / comparator
                    * Decimal(100), 2)
    if deviation <= BCS_PASS_PCT:
        outcome = "PASS"
    elif deviation <= BCS_WARN_PCT:
        outcome = "WARN"
    else:
        outcome = "FAIL"
    return deviation, outcome


def rolling_mean(values):
    total = sum((D(v) for v in values), Decimal(0))
    return rnd(total / Decimal(len(values)), 3)


# ------------------------------------- predicted values / LLN (2.3, 3.5, 3.9)

def predicted_values(equation, height_cm, age_years):
    """Return (predicted_fev1_l, predicted_fvc_l, lln_fev1_l).

    rsd_fev1 is rounded to three decimals BEFORE the LLN subtraction.
    """
    height = D(height_cm)
    age = D(age_years)
    predicted_fev1 = rnd(D(equation["a_fev1"]) + D(equation["b_fev1"]) * height
                         - D(equation["c_fev1"]) * age / Decimal(10), 3)
    predicted_fvc = rnd(D(equation["a_fvc"]) + D(equation["b_fvc"]) * height
                        - D(equation["c_fvc"]) * age / Decimal(10), 3)
    rsd_fev1 = rnd(predicted_fev1 * D(equation["rsd_frac"]), 3)
    lln_fev1 = rnd(predicted_fev1 - Z_LLN * rsd_fev1, 3)
    return predicted_fev1, predicted_fvc, lln_fev1


# ------------------------------------------- maneuver acceptability (2.3, 3.6)

def maneuver_acceptability(fvc_l, back_extrapolated_volume_ml,
                           expiratory_time_s, plateau_reached,
                           cough_in_first_second, glottic_closure):
    """Return (bev_limit_ml, acceptability, rejection_reasons)."""
    bev_limit_ml = max(BEV_ABS_ML,
                       rnd_int(D(fvc_l) * BEV_FRAC * Decimal(1000)))
    start_ok = D(back_extrapolated_volume_ml) <= D(bev_limit_ml)
    end_ok = (D(expiratory_time_s) >= EOFE_MIN_SEC) or bool(plateau_reached)
    artifact_free = (not bool(cough_in_first_second)
                     and not bool(glottic_closure))
    if start_ok and end_ok and artifact_free:
        acceptability = "ACCEPTABLE"
    elif start_ok and artifact_free and not end_ok:
        acceptability = "USABLE_FEV1_ONLY"
    else:
        acceptability = "UNACCEPTABLE"
    flags = {
        "BEV_EXCEEDED": not start_ok,
        "EARLY_TERMINATION": not end_ok,
        "COUGH_ARTIFACT": bool(cough_in_first_second),
        "GLOTTIC_CLOSURE": bool(glottic_closure),
    }
    reasons = [name for name in REJECTION_REASON_ORDER if flags[name]]
    return bev_limit_ml, acceptability, reasons


def quality_grade(acceptable_count, repeatability_delta_ml,
                  fvc_repeatability_delta_ml):
    """First matching rung of the grade ladder wins; null never satisfies."""
    tight = (repeatability_delta_ml is not None
             and repeatability_delta_ml <= REPEAT_TIGHT_ML)
    loose = (repeatability_delta_ml is not None
             and repeatability_delta_ml <= REPEAT_LOOSE_ML)
    fvc_tight = (fvc_repeatability_delta_ml is not None
                 and fvc_repeatability_delta_ml <= REPEAT_TIGHT_ML)
    if acceptable_count >= 3 and tight and fvc_tight:
        return "A"
    if acceptable_count >= 3 and loose:
        return "B"
    if acceptable_count == 2 and tight:
        return "C"
    if acceptable_count >= 1:
        return "D"
    return "F"


# ------------------------------------- bronchodilator response (2.3, 3.6, 3.9)

def bronchodilator_response(criterion, best_pre_l, best_post_l,
                            predicted_fev1_l):
    """Return (bd_response_pct, bd_response_ml, variant, positive)."""
    pre = D(best_pre_l)
    post = D(best_post_l)
    delta_ml = rnd_int((post - pre) * Decimal(1000))
    if criterion == "PCT_PREDICTED_2021":
        pct = rnd((post - pre) / D(predicted_fev1_l) * Decimal(100), 1)
        positive = pct >= BD_PCT_PREDICTED_MIN
    else:
        criterion = "PCT_BASELINE_2005"
        pct = rnd((post - pre) / pre * Decimal(100), 1)
        positive = (pct >= BD_PCT_BASELINE_MIN and delta_ml >= BD_ML_MIN)
    return pct, delta_ml, criterion, bool(positive)


# ------------------------------------------- pattern and severity (2.3, 3.9)

def pattern_and_severity(fev1_fvc_ratio, ratio_lln, fvc_pct_predicted,
                         fev1_pct_predicted):
    ratio = D(fev1_fvc_ratio)
    lln = D(ratio_lln)
    fvc_pct = D(fvc_pct_predicted)
    obstructed = ratio < lln
    restricted = fvc_pct < FVC_NORMAL_PCT
    if obstructed and restricted:
        pattern = "MIXED"
    elif obstructed:
        pattern = "OBSTRUCTION"
    elif restricted:
        pattern = "RESTRICTION"
    else:
        pattern = "NORMAL"
    if pattern == "NORMAL":
        return pattern, "NONE"
    fev1_pct = D(fev1_pct_predicted)
    if fev1_pct >= SEVERITY_MILD_PCT:
        severity = "MILD"
    elif fev1_pct >= SEVERITY_MODERATE_PCT:
        severity = "MODERATE"
    elif fev1_pct >= SEVERITY_MOD_SEVERE_PCT:
        severity = "MODERATELY_SEVERE"
    elif fev1_pct >= SEVERITY_SEVERE_PCT:
        severity = "SEVERE"
    else:
        severity = "VERY_SEVERE"
    return pattern, severity


# ------------------------------------------------ interpretation SLA (2.3, 3.9)

def load_tier(queue_load_pct):
    if queue_load_pct <= LOAD_NORMAL_PCT:
        return "NORMAL"
    if queue_load_pct <= LOAD_ELEVATED_PCT:
        return "ELEVATED"
    return "SURGE"


def sla_minutes_for(test_context, tier):
    base = BASE_SLA_MINUTES[test_context]
    return int(D(base) * LOAD_MULTIPLIERS[tier])


# ---------------------------------------------------- challenge PC20 (2.3, 3.7)

def step_drop_pct(baseline_fev1_l, post_step_fev1_l):
    baseline = D(baseline_fev1_l)
    return rnd((baseline - D(post_step_fev1_l)) / baseline * Decimal(100), 2)


def pc20_interpolate(prev_cumulative, new_cumulative, prev_drop_pct,
                     drop_pct):
    prev_cum = D(prev_cumulative)
    new_cum = D(new_cumulative)
    prev = D(prev_drop_pct)
    current = D(drop_pct)
    span = current - prev
    if span == 0:
        return rnd(new_cum, 3)
    return rnd(prev_cum + (new_cum - prev_cum)
               * (PC20_THRESHOLD_PCT - prev) / span, 3)
