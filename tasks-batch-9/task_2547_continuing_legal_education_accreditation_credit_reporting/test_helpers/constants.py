"""Domain thresholds and constants stated by the PRD."""

# --- The logical clock -------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Minutes, credit hours and rounding --------------------------------
CREDIT_HOUR_MINUTES = 60
ROUNDING_INCREMENT_MINUTES = 15
MIN_CREDITABLE_MINUTES = 30

# --- Compliance period requirements ------------------------------------
CYCLE_MONTHS = 24
TOTAL_REQUIRED_MINUTES = 1800
ETHICS_REQUIRED_MINUTES = 180
TECHNOLOGY_REQUIRED_MINUTES = 60
BIAS_REQUIRED_MINUTES = 120
PRORATION_SPECIALTY_THRESHOLD_MONTHS = 12
PRORATED_ETHICS_REQUIRED_MINUTES = 90
PRORATED_TECHNOLOGY_REQUIRED_MINUTES = 60
PRORATED_BIAS_REQUIRED_MINUTES = 60
DEADLINE_OFFSET_DAYS = {"GROUP_1": 31, "GROUP_2": 61, "GROUP_3": 91}

# --- Format ceilings and carryover -------------------------------------
SELF_STUDY_CAP_MINUTES = 360
ON_DEMAND_CAP_MINUTES = 720
NONLIVE_CAP_MINUTES = 900
RECIPROCITY_CAP_MINUTES = 900
CARRYOVER_CAP_GENERAL_MINUTES = 600
CARRYOVER_CAP_ETHICS_MINUTES = 120

# --- Course and accreditation windows ----------------------------------
APPROVAL_VALID_MONTHS = 36
ACCREDITATION_TERM_MONTHS = 24
APPEAL_WINDOW_DAYS = 30
MAX_INFO_REQUEST_ROUNDS = 2
MAX_REMANDS = 1
PROVIDER_CONCURRENT_LIVE_CAPACITY = 2

# --- Rosters ------------------------------------------------------------
ROSTER_DUE_DAYS = 30
ROSTER_HARD_WINDOW_DAYS = 90

# --- Delinquency, suspension and fees ----------------------------------
DELINQUENCY_TO_SUSPENSION_DAYS = 60
LATE_FEE_VOID_GRACE_DAYS = 7
LATE_FEE_BASE_TIERS_CENTS = {"0": 15000, "1_5": 25000, "6_15": 40000, "16_plus": 60000}
LATE_FEE_PER_HOUR_CENTS = 2500
LATE_FEE_SURCHARGE_HOUR_CAP = 20
LATE_FEE_CAP_CENTS = 100000
REINSTATEMENT_FEE_CENTS = 50000
AUDIT_SANCTION_FEE_CENTS = 250000
DEFAULT_PROVIDER_ANNUAL_FEE_CENTS = 120000

# --- Risk scoring and audit sampling -----------------------------------
RISK_WEIGHT_DELINQUENCY = 0.35
RISK_WEIGHT_COMPLAINT = 0.30
RISK_WEIGHT_FINDING = 0.25
RISK_WEIGHT_STALENESS = 0.10
COMPLAINT_NORMALIZER = 3
STALENESS_NORMALIZER_MONTHS = 24
RISK_SAMPLE_TIER_HIGH = 0.60
RISK_SAMPLE_TIER_MID = 0.30
RISK_SAMPLE_N_HIGH = 10
RISK_SAMPLE_N_MID = 5
RISK_SAMPLE_N_LOW = 2
AUDIT_CLEAR_MAX_FINDINGS = 1

# --- Jurisdictions -------------------------------------------------------
HOME_JURISDICTION = "ST"
RECIPROCITY_JURISDICTIONS = ["NY", "CA", "TX", "IL", "FL"]
COMITY_JURISDICTIONS = ["NY", "IL"]
ORIGIN_HOUR_MINUTES = {"NY": 50, "CA": 60, "TX": 60, "IL": 60, "FL": 50}
ORIGIN_CATEGORY_MAP = {
    "GENERAL": "GENERAL",
    "PROFESSIONALISM": "ETHICS",
    "ETHICS": "ETHICS",
    "TECHNOLOGY": "TECHNOLOGY",
    "DIVERSITY_INCLUSION": "BIAS_ELIMINATION",
}

# --- Pagination -----------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Every field the cycle summary reports --------------------------------
CYCLE_SUMMARY_FIELDS = [
    "cycle_id",
    "credit_status",
    "administrative_status",
    "required_total_minutes",
    "required_ethics_minutes",
    "required_technology_minutes",
    "required_bias_minutes",
    "provisional_total_minutes",
    "provisional_ethics_minutes",
    "provisional_technology_minutes",
    "provisional_bias_minutes",
    "provisional_live_minutes",
    "provisional_deficiency_total_minutes",
    "provisional_deficiency_ethics_minutes",
    "projected_final_total_minutes",
    "projected_final_ethics_minutes",
    "projected_final_technology_minutes",
    "projected_final_bias_minutes",
    "projected_final_live_minutes",
    "projected_final_deficiency_total_minutes",
    "projected_final_deficiency_ethics_minutes",
    "projected_final_deficiency_technology_minutes",
    "projected_final_deficiency_bias_minutes",
    "self_study_used_minutes",
    "on_demand_used_minutes",
    "nonlive_used_minutes",
    "reciprocity_used_minutes",
    "carryover_in_general_minutes",
    "carryover_in_ethics_minutes",
    "projected_carryover_out_general_minutes",
    "projected_carryover_out_ethics_minutes",
    "projected_late_fee_cents",
    "records_counted",
    "records_excluded",
]
