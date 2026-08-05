"""Domain thresholds and prices named by the PRD narratives."""

# ── The logical clock ────────────────────────────────────────────────────────
CLOCK_STARTUP_UTC = "2026-05-01T00:00:00Z"

# ── Pellet ladders (PRD 3.3) ─────────────────────────────────────────────────
PELLET_LADDER = {
    "TESTOSTERONE": {"large": 200, "small": 100},
    "ESTRADIOL": {"large": 25, "small": 10},
}

# ── Dose ceilings (PRD 3.4) ──────────────────────────────────────────────────
MAX_DOSE_PER_PROCEDURE_MG = {"TESTOSTERONE": 2000, "ESTRADIOL": 150}
ROLLING_MG_WINDOW_DAYS = 365
ROLLING_MG_CAP = {"TESTOSTERONE": 4800, "ESTRADIOL": 400}

# ── The laboratory's two rulers and the safety diversion (PRD 3.3) ───────────
LAB_REFERENCE_INTERVAL = {
    "TOTAL_TESTOSTERONE": (264, 916),
    "ESTRADIOL": (30, 400),
    "HEMATOCRIT": (38.0, 50.0),
}
CLINIC_OPTIMAL_BAND = {
    "TOTAL_TESTOSTERONE": (600, 900),
    "ESTRADIOL": (80, 200),
    "HEMATOCRIT": (40.0, 46.0),
}
CRITICAL_HIGH = {
    "TOTAL_TESTOSTERONE": 1500,
    "ESTRADIOL": 500,
    "HEMATOCRIT": 54.0,
}
ANALYTE_UNIT = {
    "TOTAL_TESTOSTERONE": "ng/dL",
    "ESTRADIOL": "pg/mL",
    "HEMATOCRIT": "percent",
}
HEMATOCRIT_SAFETY_CEILING = 52.0
LAB_MAX_AGE_DAYS = 45

# ── The re-dose gate (PRD 3.4) ───────────────────────────────────────────────
MIN_REDOSE_INTERVAL_DAYS = {"TESTOSTERONE": 84, "ESTRADIOL": 70}
TROUGH_WINDOW_DAYS = {"TESTOSTERONE": (70, 98), "ESTRADIOL": (56, 84)}
REDOSE_MIN_SYMPTOM_SCORE = 40
PRIMARY_ANALYTE = {
    "TESTOSTERONE": "TOTAL_TESTOSTERONE",
    "ESTRADIOL": "ESTRADIOL",
}

# ── Scheduling geometry (PRD 3.4, 3.7) ───────────────────────────────────────
PROCEDURE_DURATION_MINUTES = 45
INJECTION_DURATION_MINUTES = 15
PROVIDER_SLOT_BUFFER_MINUTES = 20
POST_INSERTION_RESTRICTION_DAYS = 14

# ── The cancellation lead-time ladder (PRD 3.6) ──────────────────────────────
LATE_CANCEL_TIER1_LEAD_HOURS = 48
LATE_CANCEL_TIER2_LEAD_HOURS = 24
LATE_CANCEL_TIER1_FEE_CENTS = 5000
LATE_CANCEL_TIER2_FEE_CENTS = 12500
NO_SHOW_FEE_CENTS = 20000

# ── Procedure pricing (PRD 3.5) ──────────────────────────────────────────────
INSERTION_BASE_FEE_CENTS = 25000
PELLET_PRICE_CENTS_PER_MG = {"TESTOSTERONE": 21.5, "ESTRADIOL": 176.25}
FACILITY_FEE_BASE_CENTS = 7500
FACILITY_FEE_WAIVER_THRESHOLD_CENTS = 42625

# ── Wellness injection list prices (PRD 3.7) ─────────────────────────────────
INJECTION_LIST_PRICE_CENTS = {
    "B12": 3500,
    "LIPOTROPIC": 4500,
    "VITAMIN_D": 5500,
    "GLUTATHIONE": 8500,
}

# ── Memberships (PRD 3.7) ────────────────────────────────────────────────────
MEMBERSHIP_FEE_CENTS = {"BASIC": 4900, "PLUS": 9900, "ELITE": 19900}
MEMBERSHIP_DISCOUNT_PCT = {"BASIC": 0.00, "PLUS": 0.10, "ELITE": 0.20}
MEMBERSHIP_INCLUDED_VISITS = {"BASIC": 0, "PLUS": 2, "ELITE": 4}
MEMBERSHIP_PERIOD_DAYS = 30
MAX_PAUSE_DAYS_PER_YEAR = 90

# ── Prepaid series packs (PRD 3.7) ───────────────────────────────────────────
SERIES_PACK_VISITS = 8
SERIES_PACK_DISCOUNT_PCT = 0.15
SERIES_ENROLLMENT_FEE_CENTS = 2500
SERIES_VALIDITY_DAYS = 365
# The four packs as the PRD prices them out.
SERIES_PACK_PRICE_CENTS = {
    "B12": 26300,
    "LIPOTROPIC": 33100,
    "VITAMIN_D": 39900,
    "GLUTATHIONE": 60300,
}
SERIES_PACK_PER_VISIT_VALUE_CENTS = {
    "B12": 3287,
    "LIPOTROPIC": 4137,
    "VITAMIN_D": 4987,
    "GLUTATHIONE": 7537,
}

# ── Self-pay financing (PRD 3.9) ─────────────────────────────────────────────
FINANCING_MIN_DOWN_PAYMENT_PCT = 0.20
FINANCING_MIN_INSTALLMENTS = 2
FINANCING_MAX_INSTALLMENTS = 12
FINANCING_INSTALLMENT_INTERVAL_DAYS = 30
FINANCING_GRACE_PERIOD_DAYS = 10
FINANCING_DEFAULT_MISSED_THRESHOLD = 3
FINANCING_LATE_FEE_CENTS = 2500

# ── Notifications, adverse events, delegation (PRD 3.8) ──────────────────────
RECALL_NOTIFICATION_DUE_DAYS = 7
MODERATE_REVIEW_DUE_DAYS = 14
SEVERE_REVIEW_DUE_HOURS = 24
STANDING_ORDER_MAX_VALIDITY_DAYS = 365

# ── Pagination (PRD 2.3) ─────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ── Values reused across fixtures ────────────────────────────────────────────
TEST_DEFAULTS = {
    "PHYSICIAN_NPI": "1000000001",
    "SECOND_PHYSICIAN_NPI": "1000000002",
    "NURSE_NPI": "1000000003",
    "THIRD_PHYSICIAN_NPI": "1000000004",
    "STANDING_ORDER_MAX_DOSE_MG": 1500,
    "STANDING_ORDER_VALID_FROM": "2026-05-01T00:00:00Z",
    "STANDING_ORDER_VALID_UNTIL": "2026-10-01T00:00:00Z",
    "LOT_EXPIRY": "2026-12-01T00:00:00Z",
}
