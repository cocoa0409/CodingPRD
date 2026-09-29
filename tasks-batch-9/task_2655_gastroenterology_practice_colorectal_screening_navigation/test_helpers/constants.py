"""Domain thresholds and constants stated in the PRD."""

# The logical clock reads exactly this instant before any request moves it (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ─── Payer plan defaults (PRD §3.1) ───────────────────
PLAN_DEFAULTS = {
    "PREVENTIVE_COVERAGE_PCT": 1.00,
    "DIAGNOSTIC_COINSURANCE_PCT": 0.20,
    "DEDUCTIBLE_CENTS": 0,
    "OUT_OF_POCKET_MAX_CENTS": 400000,
    "POLYPECTOMY_CARVEOUT": "DIAGNOSTIC_CONVERTED",
    "MODIFIER_33_HONORED": True,
    "ANESTHESIA_BUNDLED": False,
}

# ─── Clinician defaults (PRD §3.1) ────────────────────
CLINICIAN_DEFAULTS = {
    "MAX_OVERLAPPING_ROOMS": 1,
    "ADR_BENCHMARK_PCT": 0.25,
    "CREDENTIAL_STATUS": "ACTIVE",
}

# ─── Patient defaults (PRD §3.1) ──────────────────────
PATIENT_DEFAULTS = {
    "ASA_CLASS": 2,
    "NAVIGATION_HIGH_PRIORITY_EPISODES": 2,
}

# ─── Referral triage (PRD §3.2) ───────────────────────
TRIAGE = {
    "MAX_INFO_REQUEST_ROUNDS": 2,
    "OPEN_ACCESS_MAX_ASA": 3,
    "AUTO_DECLINE_NOTE": "AUTO_DECLINED_INFO_EXHAUSTED",
}

# ─── Episode eligibility and due dates (PRD §3.3) ─────
ELIGIBILITY = {
    "AVERAGE_RISK_MIN_AGE": 45,
    "AVERAGE_RISK_MAX_AGE": 75,
    "HIGH_RISK_MIN_AGE": 40,
    "OTHER_MIN_AGE": 18,
}

DUE_DATE_DAYS = {
    "DIAGNOSTIC_FOLLOWUP": 90,
    "STANDARD": 180,
    "HIGH_PRIORITY": 30,
}

# ─── Preparation adherence score (PRD §3.5) ───────────
CHANNEL_WEIGHTS = {
    "PHONE": 3.0,
    "SMS": 2.0,
    "PORTAL": 1.5,
    "MAIL": 1.0,
}

PREP_SCORE = {
    "ACKNOWLEDGED_MULTIPLIER": 1.0,
    "UNACKNOWLEDGED_MULTIPLIER": 0.4,
    "DECAY_PER_DAY": 0.05,
    "DECAY_FLOOR": 0.25,
    "DECAY_CEILING": 1.00,
    "ATTESTATION_COMPLETED_BONUS": 2.50,
    "ATTESTATION_NOT_COMPLETED_BONUS": -1.00,
    "SCORE_MIN": 0.00,
    "SCORE_MAX": 10.00,
    "OUTREACH_THRESHOLD": 3.00,
    "ATTESTATION_THRESHOLD": 5.00,
}

# ─── Room block geometry (PRD §3.6) ───────────────────
SESSION_DEFAULTS = {
    "ANESTHESIA_MODE": "MODERATE_SEDATION",
    "TURNOVER_MINUTES": 15,
    "MAX_PROCEDURES": 8,
    "MIN_TURNOVER_MINUTES": 0,
    "MAX_TURNOVER_MINUTES": 60,
}

BOOKING_DURATION = {
    "MIN_MINUTES": 15,
    "MAX_MINUTES": 120,
}

# ─── Surveillance interval rule (PRD §3.8) ────────────
SURVEILLANCE_BASE_MONTHS = {
    "HGD_OR_CARCINOMA": 6,
    "CLEAN_EXAM": 120,
    "ADENOMA_10_PLUS": 12,
    "ADENOMA_5_PLUS_OR_LARGE_OR_VILLOUS": 36,
    "SESSILE_SERRATED": 60,
    "DEFAULT": 84,
}

SURVEILLANCE_RISK_CAP_MONTHS = {
    "AVERAGE": 120,
    "INCREASED": 60,
    "HIGH": 24,
}

SURVEILLANCE = {
    "ADENOMA_HIGH_COUNT": 10,
    "ADENOMA_MID_COUNT": 5,
    "LARGE_ADENOMA_MM": 10,
    "POOR_PREP_BBPS": 5,
    "POOR_PREP_CAP_MONTHS": 12,
    "GLOBAL_FLOOR_MONTHS": 6,
    "OVERRIDE_MIN_MONTHS": 6,
    "OVERRIDE_MAX_MONTHS": 120,
    "OVERRIDE_MAX_DELTA_MONTHS": 48,
}

# ─── Claim pricing waterfall (PRD §3.9) ───────────────
PRICING = {
    "FACILITY_BASE_CENTS": 78000,
    "FACILITY_PER_MINUTE_CENTS": 950,
    "PROFESSIONAL_BASE_CENTS": 41500,
    "PROFESSIONAL_PER_POLYP_CENTS": 13750,
    "ANESTHESIA_BASE_CENTS": 22000,
    "ANESTHESIA_PER_MINUTE_CENTS": 410,
    "ABORTED_TECHNICAL_CENTS": 30000,
    "TIER_3_FLOOR_CENTS": 250000,
    "TIER_2_FLOOR_CENTS": 150000,
    "TIER_1_ADDON_CENTS": 0,
    "TIER_2_ADDON_CENTS": 8500,
    "TIER_3_ADDON_CENTS": 19000,
}

# ─── Detection rate measurement (PRD §3.9) ────────────
QUALITY = {
    "MIN_MEASURABLE_VOLUME": 1,
    "ADR_DECIMAL_PLACES": 4,
}
