"""Enumerations, constants and the eight calculation rules (SCAFFOLD section 1.3).

Every derived decimal quantity is rounded to 2 decimal places using
round-half-up (PRD section 2.6); money is integer cents throughout.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from store import ZERO2, by_created, latest

getcontext().prec = 40

# --------------------------------------------------------------------------
# enumerations
# --------------------------------------------------------------------------
REBATE_BASIS = ("PER_CFM", "PERCENT_OF_INVOICE", "LESSER_OF_BOTH")
CERTIFICATION_STATUS = ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED")
PROJECT_STATUS = ("ACTIVE", "SAFETY_HOLD")
DUCT_MATERIAL = ("SHEET_METAL", "FLEX", "DUCT_BOARD", "ASBESTOS_WRAP")
CONDITION_GRADE = ("A", "B", "C", "FAIL")
SCREENING_RESULT = ("PENDING", "CLEARED", "SUSPECT", "CONFIRMED")
ELIGIBILITY_STATUS = ("PENDING_SCREENING", "ELIGIBLE", "EXCLUDED")
EXCLUSION_REASON = ("ASBESTOS_CONFIRMED", "STRUCTURAL_DAMAGE", "MATERIAL_NOT_SEALABLE",
                    "INACCESSIBLE")
MANUAL_EXCLUSION_REASON = ("STRUCTURAL_DAMAGE", "MATERIAL_NOT_SEALABLE", "INACCESSIBLE")
SEAL_STATUS = ("SEAL_PENDING", "SEALING", "SEALED", "VERIFIED")
TEST_PHASE = ("PRE", "POST")
TEST_METHOD = ("PRESSURE_PAN", "DUCT_BLASTER", "AEROSEAL_INTERNAL")
TEST_STATUS = ("DRAFT", "PRESSURIZED", "RECORDED", "ACCEPTED", "REJECTED")
FAN_RING_CONFIG = ("RING_1", "RING_2", "RING_3")
REVIEW_DECISION = ("ACCEPT", "REJECT")
SEAL_JOB_STATUS = ("SCHEDULED", "MASKING", "INJECTING", "PAUSED", "SEALED", "VERIFIED",
                   "RETEST_REQUIRED", "RETEST_CLOSED", "ABORTED_MANUAL", "ABORTED_SAFETY",
                   "ABORTED_EXCLUSION", "ABORTED_SUPERSEDED")
SEAL_JOB_TERMINAL = ("RETEST_CLOSED", "ABORTED_MANUAL", "ABORTED_SAFETY",
                     "ABORTED_EXCLUSION", "ABORTED_SUPERSEDED")
SEAL_JOB_OPEN = ("SCHEDULED", "MASKING", "INJECTING", "PAUSED")
APPLIANCE_TYPE = ("ATMOSPHERIC_WATER_HEATER", "FURNACE", "BOILER", "RANGE")
COMBUSTION_VERDICT = ("PASS", "MARGINAL", "FAIL")
REPORT_STATUS = ("DRAFT", "ISSUED", "CORRECTION_REQUIRED", "VOIDED")
CLAIM_STATUS = ("SUBMITTED", "APPROVED", "RETURNED_FOR_CORRECTION", "PAID", "WITHDRAWN")
INSPECTOR_OUTCOME = ("PENDING", "PASS", "FAIL")
COMPLAINT_STATUS = ("OPEN", "DIAGNOSED", "BALANCING", "RESOLVED")
COMPLAINT_TYPE = ("TOO_HOT", "TOO_COLD", "NOISE", "ODOR", "DUST")
DIAGNOSIS_CODE = ("UNDERSIZED_BRANCH", "DAMPER_MISADJUSTED", "BLOCKED_REGISTER",
                  "EXCESS_BYPASS", "RESIDUAL_LEAKAGE")
WARRANTY_STATUS = ("NOT_REGISTERED", "REGISTERED", "SUSPENDED", "LAPSED")

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
FLOW_EXPONENT = Decimal("0.60")
REFERENCE_PRESSURE_PA = Decimal("25")
GUARANTEE_DEFAULT_MIN_PCT = Decimal("80.00")
ADMIN_FEE_RATE = Decimal("0.05")
SPILLAGE_MAX_SECONDS = 60
DRAFT_MIN_PA = Decimal("1.0")
CO_MAX_PPM = {"ATMOSPHERIC_WATER_HEATER": Decimal("100"), "FURNACE": Decimal("100"),
              "BOILER": Decimal("100"), "RANGE": Decimal("800")}
CO_WARN_PPM = {"ATMOSPHERIC_WATER_HEATER": Decimal("50"), "FURNACE": Decimal("50"),
               "BOILER": Decimal("50"), "RANGE": Decimal("400")}
WCD_LIMIT_PA = {"ATMOSPHERIC_WATER_HEATER": Decimal("5.0"), "FURNACE": Decimal("5.0"),
                "BOILER": Decimal("5.0"), "RANGE": Decimal("999.0")}
MAX_INJECTION_PA = Decimal("1000.0")
MIN_SEAL_RATE_CFM_PER_MIN = Decimal("0.50")
STALL_WINDOW_SAMPLES = 3
DEFAULT_TOLERANCE_PCT = Decimal("10.00")
INSPECTOR_TOLERANCE_PCT = Decimal("10.00")
RETEST_INTERVAL_DAYS = 365
STABILIZATION_BUFFER_MINUTES = 30
TIER_BANDS = ((Decimal("90.00"), Decimal("0.20")),
              (Decimal("75.00"), Decimal("0.10")),
              (Decimal("60.00"), Decimal("0.05")))


# --------------------------------------------------------------------------
# rounding primitives
# --------------------------------------------------------------------------
def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=2):
    """Round half up to ``places`` decimals."""
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to a whole number of cents (an int)."""
    if value is None:
        return None
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pow_ratio(pressure_pa):
    """(25 / pressure) ** 0.60 evaluated in decimal arithmetic."""
    return (REFERENCE_PRESSURE_PA / dec(pressure_pa)) ** FLOW_EXPONENT


# --------------------------------------------------------------------------
# 1. normalized_duct_leakage
# --------------------------------------------------------------------------
def normalized_duct_leakage(measured_leakage_cfm, test_pressure_pa,
                            conditioned_floor_area_sqft):
    """Returns (normalized_leakage_cfm25, leakage_per_100_sqft).

    The order is pinned: round, then divide the ALREADY-ROUNDED value, then
    round again (PRD section 2.6 / section 3.3)."""
    normalized = rhu(dec(measured_leakage_cfm) * pow_ratio(test_pressure_pa), 2)
    per_area = rhu(normalized / (dec(conditioned_floor_area_sqft) / Decimal("100")), 2)
    return normalized, per_area


# --------------------------------------------------------------------------
# 2. leakage_reduction_basis
# --------------------------------------------------------------------------
def reduction_pct(pre_value, post_value):
    pre = dec(pre_value)
    post = dec(post_value)
    if pre is None or pre == 0:
        return ZERO2
    return rhu((pre - post) / pre * Decimal("100"), 2)


def whole_house_basis(candidates, accepted_post_by_system):
    """Returns (cfm_reduced_whole_house, reduction_pct_whole_house_basis).

    ``candidates`` are the ELIGIBLE duct systems of the project that carry a
    baseline, in ascending created_at order.  A candidate with no accepted POST
    measurement is charged at its full baseline."""
    sum_pre = Decimal("0")
    sum_post = Decimal("0")
    for system in candidates:
        baseline = dec(system.get("baseline_leakage_cfm25"))
        sum_pre += baseline
        post_test = accepted_post_by_system.get(system["id"])
        if post_test is not None and post_test.get("normalized_leakage_cfm25") is not None:
            sum_post += dec(post_test["normalized_leakage_cfm25"])
        else:
            sum_post += baseline
    delta = sum_pre - sum_post
    cfm_reduced = rhu(delta, 2)
    if sum_pre == 0:
        pct = ZERO2
    else:
        pct = rhu(delta / sum_pre * Decimal("100"), 2)
    return cfm_reduced, pct


# --------------------------------------------------------------------------
# 3. rebate_payable_amount
# --------------------------------------------------------------------------
def tier_bonus_pct(whole_house_pct):
    value = dec(whole_house_pct)
    for threshold, bonus in TIER_BANDS:
        if value >= threshold:
            return bonus
    return Decimal("0.00")


def rebate_payable_amount(program, project, report):
    """The six pinned steps of PRD section 3.8.  Returns a dict of frozen money."""
    per_cfm = rhu_cents(dec(program["rate_cents_per_cfm_reduced"])
                        * dec(report["cfm_reduced_whole_house"]))
    pct_invoice = rhu_cents(dec(project["invoice_amount_cents"])
                            * dec(program["pct_of_invoice_bps"]) / Decimal("10000"))
    basis = program["rebate_basis"]
    if basis == "PER_CFM":
        base = per_cfm
        applied = "PER_CFM"
    elif basis == "PERCENT_OF_INVOICE":
        base = pct_invoice
        applied = "PERCENT_OF_INVOICE"
    else:
        if per_cfm <= pct_invoice:
            base = per_cfm
            applied = "PER_CFM"
        else:
            base = pct_invoice
            applied = "PERCENT_OF_INVOICE"
    bonus = tier_bonus_pct(report["reduction_pct_whole_house_basis"])
    bonused = rhu_cents(Decimal(base) * (Decimal("1") + bonus))
    capped = min(bonused, int(program["cap_cents"]))
    fee = rhu_cents(Decimal(capped) * ADMIN_FEE_RATE)
    return {
        "per_cfm_candidate_cents": per_cfm,
        "percent_of_invoice_candidate_cents": pct_invoice,
        "basis_applied": applied,
        "tier_bonus_pct": rhu(bonus, 2),
        "capped_subtotal_cents": capped,
        "admin_fee_cents": fee,
        "payable_cents": capped - fee,
    }


# --------------------------------------------------------------------------
# 4. combustion_safety_verdict
# --------------------------------------------------------------------------
def combustion_safety_verdict(appliance_type, spillage_seconds, co_ppm_air_free,
                              draft_pressure_pa, worst_case_depressurization_pa):
    co_max = CO_MAX_PPM[appliance_type]
    co_warn = CO_WARN_PPM[appliance_type]
    wcd_max = WCD_LIMIT_PA[appliance_type]
    co = dec(co_ppm_air_free)
    draft = dec(draft_pressure_pa)
    wcd = dec(worst_case_depressurization_pa)
    spill = int(spillage_seconds)
    if co > co_max or spill > SPILLAGE_MAX_SECONDS or (wcd > wcd_max and draft < DRAFT_MIN_PA):
        return "FAIL"
    if co >= co_warn or spill == SPILLAGE_MAX_SECONDS:
        return "MARGINAL"
    return "PASS"


# --------------------------------------------------------------------------
# 5. sealing_run_curve_monitor
# --------------------------------------------------------------------------
def seal_rate(older_sample, newer_sample):
    """Three-sample backward rate in CFM per minute, or None when undefined."""
    elapsed_delta = dec(newer_sample["elapsed_seconds"]) - dec(older_sample["elapsed_seconds"])
    if elapsed_delta == 0:
        return None
    drop = (dec(older_sample["instantaneous_leakage_cfm"])
            - dec(newer_sample["instantaneous_leakage_cfm"]))
    return rhu(drop / (elapsed_delta / Decimal("60")), 2)


# --------------------------------------------------------------------------
# 6. airflow_balance_deviation
# --------------------------------------------------------------------------
def deviation_pct(measured_cfm, design_cfm):
    design = dec(design_cfm)
    if design == 0:
        return ZERO2
    return rhu((dec(measured_cfm) - design) / design * Decimal("100"), 2)


# --------------------------------------------------------------------------
# 7. inspector_spot_check_variance
# --------------------------------------------------------------------------
def inspector_spot_check(spot_check_leakage_cfm, spot_check_pressure_pa, post_leakage_cfm25):
    spot_cfm25 = rhu(dec(spot_check_leakage_cfm) * pow_ratio(spot_check_pressure_pa), 2)
    post = dec(post_leakage_cfm25)
    if post is None or post == 0:
        variance = ZERO2 if (spot_cfm25 == 0) else Decimal("100.00")
    else:
        variance = rhu(abs(spot_cfm25 - post) / post * Decimal("100"), 2)
    outcome = "FAIL" if variance > INSPECTOR_TOLERANCE_PCT else "PASS"
    return spot_cfm25, variance, outcome


__all__ = [name for name in dir() if not name.startswith("_")]
