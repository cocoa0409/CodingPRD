"""Numeric thresholds and reusable defaults, every value taken from the PRD."""

# --- Declared thresholds ---------------------------------------------------

THRESHOLDS = {
    # Collection kit shelf life and receipt window
    "KIT_SHELF_LIFE_DAYS": 120,
    "MAX_HOURS_TO_RECEIPT": 48.0,
    "TRANSPORT_TEMP_MIN_C": 2.0,
    "TRANSPORT_TEMP_MAX_C": 30.0,
    # Maternal screening
    "SCREENING_WINDOW_DAYS": 7,
    "SCREENING_VALIDITY_DAYS": 180,
    # Confirmatory failure floors
    "CONFIRMATORY_VIABILITY_FLOOR_PCT": 70.0,
    "CONFIRMATORY_RECOVERY_FLOOR_PCT": 60.0,
    # Public donation quality floors
    "PUBLIC_TNC_MILLIONS_FLOOR": 900,
    "PUBLIC_CD34_THOUSANDS_FLOOR": 1500,
    "PUBLIC_VIABILITY_FLOOR_PCT": 85.0,
    "PUBLIC_SCORE_FLOOR": 70.00,
    # Private family quality floors
    "PRIVATE_TNC_MILLIONS_FLOOR": 400,
    "PRIVATE_CD34_THOUSANDS_FLOOR": 500,
    "PRIVATE_VIABILITY_FLOOR_PCT": 75.0,
    "PRIVATE_SCORE_FLOOR": 55.00,
    # Score composition weights
    "SCORE_WEIGHT_TNC": 0.45,
    "SCORE_WEIGHT_CD34": 0.35,
    "SCORE_WEIGHT_VIABILITY": 0.20,
    "SCORE_VOLUME_PENALTY": 0.10,
    # Potency grade cut-offs
    "GRADE_A_TNC_MILLIONS": 1500,
    "GRADE_A_CD34_THOUSANDS": 3000,
    "GRADE_B_TNC_MILLIONS": 1200,
    "GRADE_B_CD34_THOUSANDS": 2000,
    # Cryogenic storage
    "ALARM_TEMPERATURE_C": -150.0,
    "EXCURSION_BUDGET_MINUTES_30D": 120,
    # Reservations
    "HOLD_BUFFER_HOURS": 24,
    "CONFIRMATION_WINDOW_HOURS": 72,
    "MIN_POST_THAW_DOSE_X1E7_PER_KG": 2.50,
    # Consent
    "MAX_CONSENT_AMENDMENTS": 3,
    # Billing
    "ANNUAL_STORAGE_FEE_CENTS": 18000,
    "PREMIUM_SURCHARGE_RATE": 0.075,
    "ADMIN_RATE": 0.0125,
    "LATE_FEE_RATE": 0.015,
    "INVOICE_DUE_DAYS": 30,
    "PAST_DUE_AGE_DAYS": 30,
    "DELINQUENT_AGE_DAYS": 90,
    "DAYS_PER_YEAR": 365,
    # Disposition fee tiers keyed on the pre-fee subtotal
    "DISPOSITION_FEE_SUBTOTAL_NONPOSITIVE_CENTS": 2500,
    "DISPOSITION_FEE_SUBTOTAL_LOW_CENTS": 5000,
    "DISPOSITION_FEE_SUBTOTAL_HIGH_CENTS": 7500,
    "DISPOSITION_FEE_HIGH_TIER_FLOOR_CENTS": 10000,
    # Pagination
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    # Permitted storage plan terms
    "PLAN_TERM_YEARS_ALLOWED": (1, 5, 18),
}


# --- Reusable literals -----------------------------------------------------

TEST_DEFAULTS = {
    "CLOCK_EPOCH": "2026-08-01T00:00:00Z",
    "EXPECTED_DELIVERY_DATE": "2026-08-10",
    "COLLECTED_AT": "2026-08-10T05:00:00Z",
    "COLLECTION_CLOCK": "2026-08-10T06:00:00Z",
    "RECEIPT_CLOCK": "2026-08-11T00:00:00Z",
    "FREEZE_AT": "2026-08-11T02:00:00Z",
    "PREPAID_THROUGH_DATE": "2027-06-30",
    "BILLING_CONTACT_EMAIL": "family@example.test",
    "COLLECTION_VOLUME_ML": 130.0,
    "ANTICOAGULANT_VOLUME_ML": 25.0,
    "TRANSPORT_TEMP_C": 20.0,
    "REGISTRY_CODE": "NMDP",
    "HLA_A": "A*02:01",
    "HLA_B": "B*08:01",
    "HLA_DRB1": "DRB1*03:01",
}

# The logical clock's value before it has been set even once.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# A syntactically valid identifier that never names a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_UUID_THIRD = "00000000-0000-4000-8000-0000000000fe"

# Serology marker fields that govern a maternal panel's overall result.
GOVERNING_MARKER_FIELDS = (
    "hiv_result",
    "hbv_result",
    "hcv_result",
    "htlv_result",
    "syphilis_result",
)

# The ten counters the nightly batch reports.
NIGHTLY_COUNTERS = (
    "kits_expired",
    "screenings_expired",
    "reservations_expired",
    "excursions_escalated",
    "tanks_entered_maintenance",
    "tanks_exited_maintenance",
    "invoices_advanced_past_due",
    "invoices_advanced_delinquent",
    "accounts_advanced",
    "units_flagged_pending_abandonment",
)

# Fields projected by each unit-search result row.
SEARCH_ROW_FIELDS = (
    "unit_id",
    "unit_registry_code",
    "program_type",
    "potency_grade",
    "post_processing_tnc_millions",
    "post_processing_cd34_thousands",
    "post_processing_viability_pct",
    "pre_cryo_dose_x1e7_per_kg",
    "tank_code",
)
