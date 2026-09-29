"""Domain constants and the pure calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3).

Every rounding step is decimal half-up (ties away from zero); no float rounding
and no banker's rounding anywhere.
"""

from decimal import Decimal

from util import D, clamp, half_up_int, qd

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

ROLES = [
    "PlatformAdmin", "ComplianceManager", "ReceivingClerk", "WasteApprovalChemist",
    "TreatmentOperator", "RegulatoryInspector", "Generator",
]

TREATMENT_METHODS = ["INCINERATION", "STABILIZATION", "NEUTRALIZATION", "FUEL_BLENDING", "MACROENCAPSULATION"]
PERMIT_STATUSES = ["ACTIVE", "RENEWAL_PENDING", "EXPIRED", "TERMINATED"]
CORRECTIVE_ACTION_STATUSES = ["NONE", "OPEN", "IN_PROGRESS", "COMPLETED"]
ASSURANCE_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
GENERATOR_CATEGORIES = ["LQG", "SQG", "VSQG"]
GENERATOR_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
INSTRUMENT_TYPES = ["TRUST_FUND", "SURETY_BOND", "LETTER_OF_CREDIT", "INSURANCE"]
INSTRUMENT_STATUSES = ["ACTIVE", "SUPERSEDED", "CANCELLED"]
PHYSICAL_FORMS = ["BULK_LIQUID", "SLUDGE", "SOLID", "LAB_PACK"]
COMPATIBILITY_CLASSES = ["ACID", "ALKALINE", "OXIDIZER", "CYANIDE_BEARING", "WATER_REACTIVE", "ORGANIC_SOLVENT"]
LDR_SUBCATEGORIES = ["NONE", "D001_IGNITABLE", "D008_LEAD", "F001_SOLVENTS"]
PROFILE_STATUSES = ["DRAFT", "SUBMITTED", "SAMPLE_PASSED", "SAMPLE_FAILED", "APPROVED", "SUSPENDED", "EXPIRED", "REJECTED"]
SAMPLE_TYPES = ["FINGERPRINT", "FULL"]
SAMPLE_RESULTS = ["NONE", "PASS", "FAIL"]
SAMPLE_FAILURE_REASONS = ["NONE", "CONSTITUENT_DEVIATION", "FLASH_POINT_DEVIATION", "PH_DEVIATION"]
UNIT_TYPES = ["CONTAINER_AREA", "TANK_SYSTEM", "TEN_DAY_TRANSFER"]
UNIT_STATUSES = ["ACTIVE", "CLOSING", "CLOSED"]
AIR_LEVELS = ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
POSTURES = ["OPEN", "RESTRICTED", "SUSPENDED", "CLOSED"]
MANIFEST_STATUSES = ["EN_ROUTE", "DISCREPANT", "VERIFIED", "CERTIFIED", "REJECTED_RETURNED"]
DISCREPANCY_TYPES = ["NONE", "QUANTITY_SIGNIFICANT", "COUNT_MISMATCH", "UNDOCUMENTED"]
RESOLUTION_TYPES = ["NONE", "ACCEPT_ADJUSTED", "PARTIAL_REJECT", "REJECT_RETURN"]
LINE_STATUSES = ["DECLARED", "RECEIVED", "ACCEPTED", "ADJUSTED", "RETURNED"]
CONTAINER_TYPES = ["DRUM_55G", "TOTE", "CUBIC_YARD_BOX", "LAB_PACK_DRUM"]
CUSTODY_STATES = ["FILLING", "SEALED", "STAGED", "EMPTIED", "VOIDED"]
COMPLIANCE_STATES = ["COMPLIANT", "DEFICIENT", "CONDEMNED"]
BATCH_STATUSES = ["PLANNED", "HELD", "IN_TREATMENT", "TREATED", "VERIFIED", "LDR_FAILED", "ABORTED"]
LDR_RESULTS = ["PENDING", "PASS", "FAIL"]
HELD_REASONS = ["NONE", "UNIT_POSTURE", "PROFILE_SUSPENDED"]
INSPECTION_TYPES = ["WEEKLY_CONTAINER_AREA", "DAILY_TANK", "AISLE_CLEARANCE", "AIR_MONITORING"]
FINDING_CODES = ["NONE", "CONTAINER_LEAK", "TANK_SHELL_CORROSION", "LABEL_DEFICIENT", "AISLE_OBSTRUCTED", "OVERFILL"]
LEAK_TYPES = ["CONTAINER_LEAK", "TANK_LEAK"]
JUSTIFICATION_CODES = ["NONE", "UNIT_SHUTDOWN_REQUIRED", "PART_UNAVAILABLE"]
REPAIR_STATUSES = ["OPEN", "FIRST_ATTEMPTED", "DELAYED", "REPAIRED"]
FINDING_CLASSES = ["MINOR", "SIGNIFICANT", "SNC"]
COMPLIANCE_FINDING_STATUSES = ["OPEN", "RESPONDED", "CLOSED", "REOPENED"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_RATE_CENTS = {"BULK_LIQUID": 40, "SLUDGE": 55, "SOLID": 30, "LAB_PACK": 120}
HAZARD_MULTIPLIER = {
    "ACID": "1.10", "ALKALINE": "1.10", "OXIDIZER": "1.35",
    "CYANIDE_BEARING": "1.50", "WATER_REACTIVE": "1.45", "ORGANIC_SOLVENT": "1.20",
}
LDR_SURCHARGE_CENTS = 12
CONTAINER_HANDLING_CENTS = 750

CLOSURE_FIXED_CENTS = 25000000
CLOSURE_PER_KG_CENTS = 1800
TIER_1_CEILING = 30000000
TIER_2_CEILING = 60000000
TIER_CONTINGENCY = {"TIER_1": "0.05", "TIER_2": "0.10", "TIER_3": "0.18"}
SNC_RESERVE_CENTS = 5000000
TREATMENT_LIABILITY_PER_KG_CENTS = 220

RELIABILITY_DISCREPANCY_WEIGHT = 45
RELIABILITY_RETURN_WEIGHT = 35
RELIABILITY_PROFILE_FAIL_WEIGHT = 20
ROLLING_WINDOW_SIZE = 3
FULL_SAMPLE_SCORE_THRESHOLD = 60

TOLERANCES = {
    "FINGERPRINT": {"constituent_pct": "0.15", "flash": "5.0", "ph": "1.0"},
    "FULL": {"constituent_pct": "0.10", "flash": "3.0", "ph": "0.5"},
}

BULK_VARIANCE_TOLERANCE = "0.10"
CONTAINERIZED_VARIANCE_TOLERANCE = "0.02"
DISCREPANCY_PRIORITY = {"UNDOCUMENTED": 3, "COUNT_MISMATCH": 2, "QUANTITY_SIGNIFICANT": 1, "NONE": 0}
DISCREPANCY_REPORT_DAYS = 15

MIN_AISLE_WIDTH_CM = "76"
AISLE_PENALTY_CM = 6

INCOMPATIBLE_PAIRS = frozenset([
    frozenset(["ACID", "ALKALINE"]),
    frozenset(["ACID", "CYANIDE_BEARING"]),
    frozenset(["ACID", "WATER_REACTIVE"]),
    frozenset(["OXIDIZER", "ORGANIC_SOLVENT"]),
    frozenset(["OXIDIZER", "WATER_REACTIVE"]),
    frozenset(["WATER_REACTIVE", "ALKALINE"]),
])

UTILIZATION_RESTRICT_THRESHOLD = "0.9000"
FILL_FRACTION_LIMIT = "0.95"
TEN_DAY_LIMIT_DAYS = 10

LDR_CONCENTRATION_STANDARD_PPM = {"D008_LEAD": 750, "F001_SOLVENTS": 560}
LDR_FLASH_POINT_MIN_C = "60.0"

LEAK_DEFINITION_PPM = {"LEVEL_1": 500, "LEVEL_2": 250, "LEVEL_3": 100}
FIRST_ATTEMPT_DAYS = 5
REPAIR_DUE_DAYS = 15
MAX_DELAY_DAYS = 180
ALLOWED_DELAY_JUSTIFICATIONS = ("UNIT_SHUTDOWN_REQUIRED", "PART_UNAVAILABLE")

WINDOW_BUFFER_MINUTES = 240
NON_TERMINAL_BATCH_STATUSES = ("PLANNED", "HELD", "IN_TREATMENT", "TREATED", "LDR_FAILED")
RESIDUE_BATCH_STATUSES = ("TREATED", "LDR_FAILED", "VERIFIED")

INSPECTION_FREQUENCY_CEILING = {"CONTAINER_AREA": 7, "TEN_DAY_TRANSFER": 7, "TANK_SYSTEM": 1}

CLOSED_MANIFEST_STATUSES = ("CERTIFIED", "REJECTED_RETURNED")
LEDGER_MANIFEST_STATUSES = ("DISCREPANT", "VERIFIED", "CERTIFIED", "REJECTED_RETURNED")

REOPEN_DUE_DAYS = 30
MAX_REOPENS = 2
MAX_SAMPLE_ATTEMPTS = 3
MAX_RETREATS = 2


# ---------------------------------------------------------------------------
# acceptance_charge
# ---------------------------------------------------------------------------

def line_rate_cents(profile):
    """Per-kilogram rate in cents for a manifest line's waste profile."""
    if profile is None:
        # An undocumented receipt carries no profile, so no per-kilogram rate can
        # be formed; only the per-container handling fee applies.
        return Decimal(0)
    rate = D(BASE_RATE_CENTS[profile["physical_form"]]) * D(HAZARD_MULTIPLIER[profile["compatibility_class"]])
    if profile["ldr_subcategory"] != "NONE":
        rate += D(LDR_SURCHARGE_CENTS)
    return rate


def line_charge_cents(quantity_kg, container_count, profile):
    """round_half_up(quantity * rate) + 750 * container_count -- rounded per line."""
    rate = line_rate_cents(profile)
    return half_up_int(D(quantity_kg) * rate) + CONTAINER_HANDLING_CENTS * int(container_count or 0)


# ---------------------------------------------------------------------------
# financial_assurance_requirement
# ---------------------------------------------------------------------------

def assurance_figures(held_mass_kg, post_closure_cost_cents, open_snc_finding_count,
                      active_treatment_liability_cents, posted_assurance_cents):
    closure_base = CLOSURE_FIXED_CENTS + half_up_int(D(held_mass_kg) * D(CLOSURE_PER_KG_CENTS))
    # The tier is keyed on the pre-contingency base cost only.
    if closure_base < TIER_1_CEILING:
        tier = "TIER_1"
    elif closure_base < TIER_2_CEILING:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    estimate = half_up_int(D(closure_base) * (Decimal(1) + D(TIER_CONTINGENCY[tier])))
    reserve = int(open_snc_finding_count) * SNC_RESERVE_CENTS
    required = estimate + int(post_closure_cost_cents) + reserve + int(active_treatment_liability_cents)
    shortfall = max(0, required - int(posted_assurance_cents))
    return {
        "closure_base_cost_cents": closure_base,
        "assurance_tier": tier,
        "closure_cost_estimate_cents": estimate,
        "corrective_action_reserve_cents": reserve,
        "required_assurance_cents": required,
        "assurance_shortfall_cents": shortfall,
    }


def treatment_liability_cents(input_mass_kg):
    return half_up_int(D(input_mass_kg) * D(TREATMENT_LIABILITY_PER_KG_CENTS))


# ---------------------------------------------------------------------------
# generator_reliability_score
# ---------------------------------------------------------------------------

def reliability_score(closed_manifests, profile_statuses):
    """closed_manifests: the in-scope closed manifests for this variant.
    profile_statuses: effective statuses of every profile of the generator
    (never windowed -- identical in both variants)."""
    n = len(closed_manifests)
    if n == 0:
        return 100
    discrepancy = sum(1 for m in closed_manifests if m["discrepancy_type"] != "NONE")
    returned = sum(1 for m in closed_manifests if m["status"] == "REJECTED_RETURNED")
    considered = [s for s in profile_statuses if s != "DRAFT"]
    failed = [s for s in considered if s in ("SAMPLE_FAILED", "REJECTED")]
    discrepancy_rate = D(discrepancy) / D(n)
    return_rate = D(returned) / D(n)
    profile_fail_rate = (D(len(failed)) / D(len(considered))) if considered else Decimal(0)
    raw = (D(100)
           - D(RELIABILITY_DISCREPANCY_WEIGHT) * discrepancy_rate
           - D(RELIABILITY_RETURN_WEIGHT) * return_rate
           - D(RELIABILITY_PROFILE_FAIL_WEIGHT) * profile_fail_rate)
    return int(clamp(half_up_int(raw), 0, 100))


def required_sample_type(rolling_score, sample_attempt_count):
    """FULL when the rolling score is strictly below 60 or a sample was already
    consumed; FINGERPRINT otherwise."""
    if rolling_score < FULL_SAMPLE_SCORE_THRESHOLD or int(sample_attempt_count) >= 1:
        return "FULL"
    return "FINGERPRINT"


# ---------------------------------------------------------------------------
# sample_acceptance_evaluation
# ---------------------------------------------------------------------------

def evaluate_sample(applied_tolerance_type, declared_ppm, declared_flash, declared_ph,
                    measured_ppm, measured_flash, measured_ph):
    tol = TOLERANCES[applied_tolerance_type]
    deviation = qd(abs(D(measured_ppm) - D(declared_ppm)) / max(D(declared_ppm), D(1)), 4)
    if deviation > D(tol["constituent_pct"]):
        return deviation, "FAIL", "CONSTITUENT_DEVIATION"
    if abs(D(measured_flash) - D(declared_flash)) > D(tol["flash"]):
        return deviation, "FAIL", "FLASH_POINT_DEVIATION"
    if abs(D(measured_ph) - D(declared_ph)) > D(tol["ph"]):
        return deviation, "FAIL", "PH_DEVIATION"
    return deviation, "PASS", "NONE"


# ---------------------------------------------------------------------------
# discrepancy_classification
# ---------------------------------------------------------------------------

def variance_pct(declared_quantity_kg, received_quantity_kg):
    if D(declared_quantity_kg) == 0:
        return None
    return qd((D(declared_quantity_kg) - D(received_quantity_kg)) / D(declared_quantity_kg), 4)


def line_significance(line, variance):
    if line.get("_undocumented"):
        return "UNDOCUMENTED"
    if not line["is_bulk"] and int(line["received_container_count"] or 0) != int(line["declared_container_count"] or 0):
        return "COUNT_MISMATCH"
    if variance is not None:
        tolerance = D(BULK_VARIANCE_TOLERANCE) if line["is_bulk"] else D(CONTAINERIZED_VARIANCE_TOLERANCE)
        if abs(variance) >= tolerance:
            return "QUANTITY_SIGNIFICANT"
    return "NONE"


def dominant_discrepancy(significances):
    best = "NONE"
    for value in significances:
        if DISCREPANCY_PRIORITY[value] > DISCREPANCY_PRIORITY[best]:
            best = value
    return best


# ---------------------------------------------------------------------------
# effective_aisle_clearance
# ---------------------------------------------------------------------------

def effective_aisle_width(aisle_width_cm, container_count, aisle_free_container_capacity):
    excess = max(0, int(container_count) - int(aisle_free_container_capacity))
    return D(aisle_width_cm) - D(AISLE_PENALTY_CM) * D(excess)


# ---------------------------------------------------------------------------
# compatibility_segregation
# ---------------------------------------------------------------------------

def incompatible(class_a, class_b):
    return frozenset([class_a, class_b]) in INCOMPATIBLE_PAIRS


# ---------------------------------------------------------------------------
# treatment_window_conflict
# ---------------------------------------------------------------------------

def windows_overlap(candidate_start, candidate_end, other_start, other_end, buffer_minutes):
    from datetime import timedelta
    effective_end = other_end + timedelta(minutes=buffer_minutes)
    return candidate_start < effective_end and other_start < candidate_end
