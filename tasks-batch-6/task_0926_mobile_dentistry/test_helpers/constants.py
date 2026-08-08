"""Domain thresholds and code tables stated in the PRD."""

# The logical clock reads exactly this instant from server start until moved (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# The instant most fixtures pin the clock to before doing anything else.
BASE_CLOCK_UTC = "2026-05-11T09:00:00Z"

THRESHOLDS = {
    "SPORE_INCUBATION_HOURS": 24,
    "TELEDENTISTRY_REVIEW_WINDOW_HOURS": 72,
    "REFERRAL_MAX_ATTEMPTS": 3,
    "REFERRAL_NO_RESPONSE_DAYS": 21,
    "VISIT_RESCHEDULE_MAX_COUNT": 2,
    "VISIT_RESCHEDULE_WINDOW_DAYS": 30,
    "UNIT_CALIBRATION_VALID_DAYS": 180,
    "UNIT_CALIBRATION_DUE_WINDOW_DAYS": 30,
    "UNIT_TRANSPORT_BUFFER_MINUTES": 90,
    "CHAIR_UTILIZATION_CAP_PCT": 0.85,
    "VARNISH_MIN_INTERVAL_DAYS": 90,
    "VARNISH_MAX_APPLICATIONS_PER_PERIOD": 2,
    "SNF_CONSENT_VALID_DAYS": 365,
    "FOLLOW_UP_GRACE_DAYS": 14,
    "MEDICAID_ENCOUNTER_RATE_CENTS": 18500,
    "COMMERCIAL_PATIENT_COINSURANCE_PCT": 0.20,
    "UNINSURED_NOMINAL_FEE_CENTS": 2500,
    "FPL_BASE_CENTS": 1_560_000,
    "FPL_PER_PERSON_CENTS": 550_000,
}

# PRD §3.5 — the code tables. Each code fixes three attributes at creation.
PROCEDURE_REQUIRED_TIER = {
    "D0190": "SCREENING_ONLY",
    "D0150": "SCREENING_ONLY",
    "D1206": "SCREENING_FLUORIDE",
    "D1351": "SCREENING_FLUORIDE_SEALANT",
    "D0272": "FULL_WITH_RADIOGRAPHS",
}

PROCEDURE_CHAIR_MINUTES = {
    "D0190": 10,
    "D0150": 15,
    "D1206": 8,
    "D1351": 12,
    "D0272": 10,
}

PROCEDURE_CHARGE_CENTS = {
    "D0190": 3475,
    "D0150": 5825,
    "D1206": 4525,
    "D1351": 6350,
    "D0272": 4150,
}

# PRD §3.6 — the contracted commercial schedule amounts.
COMMERCIAL_SCHEDULE_CENTS = {
    "D0190": 2600,
    "D0150": 4300,
    "D1206": 3375,
    "D1351": 4725,
    "D0272": 3100,
}

# PRD §3.6 — sliding-fee discount fractions by band.
SLIDING_FEE_DISCOUNT = {"A": 1.00, "B": 0.75, "C": 0.55, "D": 0.35, "E": 0.00}

# PRD §3.2 — the ordered permission ladder.
CONSENT_TIER_RANK = {
    "SCREENING_ONLY": 1,
    "SCREENING_FLUORIDE": 2,
    "SCREENING_FLUORIDE_SEALANT": 3,
    "FULL_WITH_RADIOGRAPHS": 4,
}

SUPERVISION_RANK = {"DIRECT": 1, "INDIRECT": 2, "GENERAL": 3, "SELF": 4}

# PRD §3.5 — the eight permanent molars the programme seals.
SEALANT_ELIGIBLE_TOOTH_NUMBERS = [2, 3, 14, 15, 18, 19, 30, 31]
SEALANT_ELIGIBLE_SURFACES = ["O", "B", "L"]

# PRD §3.7 — follow-up cadence in calendar days, keyed on the plan's urgency band.
FOLLOW_UP_CADENCE_DAYS = {
    "URGENT": 7,
    "EARLY_CARE_NEEDED": 30,
    "NO_OBVIOUS_PROBLEM": 180,
}

# PRD §3.7 — referral deadlines, dual-variant by site type.
REFERRAL_SLA_SCHOOL_BUSINESS_DAYS = {
    "URGENT": 3,
    "EARLY_CARE_NEEDED": 15,
    "NO_OBVIOUS_PROBLEM": 45,
}

TEST_DEFAULTS = {
    "PERIOD_NAME": "SY2025-26",
    "PERIOD_STARTS_ON": "2025-08-01",
    "PERIOD_ENDS_ON": "2026-06-30",
    "SCHOOL_NAME": "Lincoln Elementary",
    "SNF_NAME": "Cedar Grove SNF",
    "STATE_CODE": "CA",
    "VISIT_START": "2026-05-11T09:00:00Z",
    "VISIT_END": "2026-05-11T15:00:00Z",
    "LOAD_CYCLE_COMPLETED_AT": "2026-05-10T08:00:00Z",
    "CONSENT_SIGNED_AT": "2026-05-01T00:00:00Z",
    "COVERAGE_THROUGH": "2026-12-31",
}
