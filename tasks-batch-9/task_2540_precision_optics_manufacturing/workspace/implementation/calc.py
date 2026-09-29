"""§1.3 calculations: pinned rounding, pinned evaluation order, exact decimals."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

D0 = Decimal("0")

# --- tolerance_stack_analysis
CONTRIBUTION_DECIMALS = 4
STACK_DECIMALS = 4

# --- spectral_performance_verification
MIN_IN_BAND_SAMPLES = 5
MAX_BAND_AVERAGE_REFLECTANCE_PCT = Decimal("0.5000")
MAX_POINT_REFLECTANCE_PCT = Decimal("1.2000")
AGGREGATE_DECIMALS = 4

# --- metrology_capability_index
K_TEST_ACCURACY = Decimal("4")
UNCERTAINTY_DRIFT_PER_DAY = Decimal("0.0200")
UNCERTAINTY_DRIFT_CAP_MULTIPLE = Decimal("2")
MAX_CAPABILITY_RATIO = Decimal("0.2500")
UNCERTAINTY_DECIMALS = 6
RATIO_DECIMALS = 4

# --- assembly_transmitted_wavefront
DECENTER_SENSITIVITY_WAVES_PER_UM = Decimal("0.0012")
TILT_SENSITIVITY_WAVES_PER_ARCMIN = Decimal("0.0080")
CEMENT_DERATE_TIER_1_LIMIT = Decimal("0.0500")
CEMENT_DERATE_TIER_2_LIMIT = Decimal("0.1000")
CEMENT_DERATE_TIER_1_WAVES = Decimal("0.0020")
CEMENT_DERATE_TIER_2_WAVES = Decimal("0.0060")
CEMENT_DERATE_TIER_3_WAVES = Decimal("0.0150")
MAX_ALIGNMENT_ATTEMPTS = 3

# --- metrology_acceptance_verdict
STAGE_FIGURE_MULTIPLIER = {
    "GRINDING": Decimal("10"),
    "POLISHING": Decimal("3"),
    "FIGURING": Decimal("1"),
}
STAGE_ADVANCE_MAP = {
    "GRINDING": "POLISHING",
    "POLISHING": "FIGURING",
    "FIGURING": "FIGURE_ACCEPTED",
}

# --- figuring_removal_convergence
MAX_FIGURING_ITERATIONS = 2
THICKNESS_DECIMALS = 4
NM_PER_UM = Decimal("1000.0")

# --- blank_conservation_ledger
SPARE_BLANK_RATE = Decimal("0.25")
MIN_SPARE_BLANKS = 1

# --- instrument_minutes_ledger
INSTRUMENT_PURGE_MINUTES = 15
MIN_WINDOW_MINUTES = 30
MAX_WINDOW_MINUTES = 480

# --- cleanliness_inspection_verdict
MAX_SCRATCHES_AT_LIMIT = 2
WAIVER_DEFECT_MULTIPLE = 2

# --- documentation_completeness
BASE_DOCUMENT_TYPES = [
    "CERTIFICATE_OF_CONFORMANCE",
    "MELT_CERTIFICATE",
    "INTERFEROGRAM_REPORT",
]
DOCUMENT_TYPE_ENUM = [
    "CERTIFICATE_OF_CONFORMANCE",
    "COATING_SPECTRAL_DATA",
    "EXPORT_LICENSE",
    "INSPECTION_WAIVER",
    "INTERFEROGRAM_REPORT",
    "MELT_CERTIFICATE",
]
PCT_DECIMALS = 2

# --- export_control_classification
CONTROLLED_APERTURE_MM = Decimal("100.0")
CONTROLLED_RMS_WAVES = Decimal("0.0500")
CONTROLLED_FIGURE_OF_MERIT = Decimal("4000.00")
LICENSE_EXEMPT_DESTINATIONS = ["CA", "AU", "GB"]
FOM_DECIMALS = 2

# --- grade scales (§2.11)
INDEX_HOMOGENEITY_RANK = {"H1": 1, "H2": 2, "H3": 3, "H4": 4, "H5": 5}
STRIAE_RANK = {"A": 1, "B": 2, "C": 3, "D": 4}

INDEX_HOMOGENEITY_GRADES = ["H1", "H2", "H3", "H4", "H5"]
STRIAE_GRADES = ["A", "B", "C", "D"]


# ------------------------------------------------------------------- rounding
def rhu(value, places):
    """round_half_up to `places` decimals (halves away from zero)."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def dsqrt(value):
    value = Decimal(value)
    if value <= 0:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 50
        return +value.sqrt()


def ceil_div(value):
    """ceil of a Decimal, as an int."""
    value = Decimal(value)
    whole = int(value)
    if value > whole:
        whole += 1
    return whole


# --------------------------------------------------------- 1. tolerance stack
def contribution_waves(sensitivity, tolerance_units):
    return rhu(Decimal(sensitivity) * Decimal(tolerance_units), CONTRIBUTION_DECIMALS)


def tolerance_stack_analysis(contributions, tolerance_method, tolerance_budget):
    squares = sum((c * c for c in contributions), D0)
    rss = rhu(dsqrt(squares), STACK_DECIMALS)
    worst = rhu(sum(contributions, D0), STACK_DECIMALS)
    governing = rss if tolerance_method == "STATISTICAL" else worst
    verdict = "PASS" if governing <= Decimal(tolerance_budget) else "FAIL"
    return rss, worst, governing, verdict


# ------------------------------------------------------ 2. spectral verdict
def spectral_aggregates(in_band):
    total = sum((s["reflectance_pct"] for s in in_band), D0)
    avg = rhu(total / Decimal(len(in_band)), AGGREGATE_DECIMALS)
    worst = rhu(max(s["reflectance_pct"] for s in in_band), AGGREGATE_DECIMALS)
    ok = (avg <= MAX_BAND_AVERAGE_REFLECTANCE_PCT
          and worst <= MAX_POINT_REFLECTANCE_PCT)
    return avg, worst, ("PASS" if ok else "FAIL")


# -------------------------------------------------- 3. metrology capability
def days_since(now_dt, last_dt):
    if now_dt is None or last_dt is None:
        return 0
    delta = (now_dt - last_dt).total_seconds()
    return int(Decimal(delta) // Decimal(86400))


def effective_uncertainty(base, days):
    base = Decimal(base)
    drifted = base * (Decimal(1) + UNCERTAINTY_DRIFT_PER_DAY * Decimal(days))
    capped = UNCERTAINTY_DRIFT_CAP_MULTIPLE * base
    return rhu(min(drifted, capped), UNCERTAINTY_DECIMALS)


def capability_ratio(eff_uncertainty, tolerance_budget):
    return rhu(K_TEST_ACCURACY * Decimal(eff_uncertainty) / Decimal(tolerance_budget),
               RATIO_DECIMALS)


# --------------------------------------------- 4. assembly transmitted front
def assembly_wavefront(components):
    if not components:
        return None, None, None, None, None
    el_sq = sum((Decimal(c["element_wavefront_rms_waves"]) ** 2 for c in components), D0)
    element_rss = rhu(dsqrt(el_sq), 4)
    cen_sq = D0
    for c in components:
        dec_term = Decimal(c["decenter_um"]) * DECENTER_SENSITIVITY_WAVES_PER_UM
        tilt_term = Decimal(c["tilt_arcmin"]) * TILT_SENSITIVITY_WAVES_PER_ARCMIN
        cen_sq += dec_term * dec_term + tilt_term * tilt_term
    centration = rhu(dsqrt(cen_sq), 4)
    subtotal = rhu(element_rss + centration, 4)
    if subtotal < CEMENT_DERATE_TIER_1_LIMIT:
        derate = CEMENT_DERATE_TIER_1_WAVES
    elif subtotal < CEMENT_DERATE_TIER_2_LIMIT:
        derate = CEMENT_DERATE_TIER_2_WAVES
    else:
        derate = CEMENT_DERATE_TIER_3_WAVES
    total = rhu(subtotal + derate, 4)
    return element_rss, centration, subtotal, derate, total


# ------------------------------------------------- 5. metrology acceptance
def stage_figure_budget(surface_figure_budget, run_stage):
    return rhu(Decimal(surface_figure_budget) * STAGE_FIGURE_MULTIPLIER[run_stage], 4)


def acceptance_verdict(report, run_stage, design):
    figure_ok = Decimal(report["surface_rms_waves"]) <= Decimal(
        report["stage_figure_budget_waves"])
    if run_stage == "GRINDING":
        roughness_ok = True
    else:
        roughness_ok = Decimal(report["surface_roughness_nm_rms"]) <= Decimal(
            design["surface_roughness_budget_nm"])
    if run_stage != "FIGURING":
        twf_ok = True
    else:
        twf_ok = Decimal(report["transmitted_wavefront_rms_waves"]) <= Decimal(
            design["transmitted_wavefront_budget_waves"])
    return "ACCEPTED" if (figure_ok and roughness_ok and twf_ok) else "REWORK_REQUIRED"


# ----------------------------------------------------- 7. reservation sizing
def reservation_sizing(element_count):
    spare = max(MIN_SPARE_BLANKS, ceil_div(Decimal(element_count) * SPARE_BLANK_RATE))
    return spare, element_count + spare


# --------------------------------------------------- 8/9. window arithmetic
def window_minutes(start_dt, end_dt):
    seconds = (end_dt - start_dt).total_seconds()
    return int(Decimal(seconds) // Decimal(60))


# ------------------------------------------------ 10. cleanliness inspection
def cleanliness_verdict(record, design):
    scratch_dig_pass = (
        record["max_scratch_number"] <= design["scratch_dig_scratch_limit"]
        and record["max_dig_number"] <= design["scratch_dig_dig_limit"]
        and record["scratch_count_at_limit"] <= MAX_SCRATCHES_AT_LIMIT
    )
    cleanliness_pass = (
        record["particle_count_per_cm2"] <= design["cleanliness_limit_per_cm2"])
    status = "PASSED" if (scratch_dig_pass and cleanliness_pass) else "FAILED"
    return scratch_dig_pass, cleanliness_pass, status


def waivable(record, design):
    return (
        bool(record["cleanliness_pass"])
        and record["max_dig_number"] <= design["scratch_dig_dig_limit"] * WAIVER_DEFECT_MULTIPLE
        and record["max_scratch_number"] <= design["scratch_dig_scratch_limit"] * WAIVER_DEFECT_MULTIPLE
    )


# ---------------------------------------------- 11. documentation completeness
def completeness_pct(required, present):
    present_set = set(present)
    hits = len([t for t in required if t in present_set])
    return rhu(Decimal(100) * Decimal(hits) / Decimal(len(required)), PCT_DECIMALS)


# --------------------------------------------------- 12. export classification
def export_classification(design, destination_country):
    fom = rhu(Decimal(design["aperture_mm"])
              / Decimal(design["required_rms_wavefront_waves"]), FOM_DECIMALS)
    controlled = (
        (Decimal(design["aperture_mm"]) >= CONTROLLED_APERTURE_MM
         and Decimal(design["required_rms_wavefront_waves"]) <= CONTROLLED_RMS_WAVES)
        or fom >= CONTROLLED_FIGURE_OF_MERIT
    )
    eccn = "6A004.A.1" if controlled else "EAR99"
    license_required = bool(
        controlled and destination_country not in LICENSE_EXEMPT_DESTINATIONS)
    status = "LICENSE_REQUIRED" if license_required else "EXEMPT_CLEARED"
    return fom, eccn, license_required, status
