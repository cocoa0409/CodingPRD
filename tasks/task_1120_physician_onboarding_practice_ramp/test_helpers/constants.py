"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Credential service-level expectations in whole days (PRD §3.3).
SLA_DAYS = {
    "STATE_LICENSE": 90,
    "DEA_REGISTRATION": 45,
    "BOARD_CERTIFICATION": 30,
    "PAYER_ENROLLMENT_MEDICARE": 60,
    "PAYER_ENROLLMENT_COMMERCIAL": 75,
    "HOSPITAL_PRIVILEGES": 50,
}
START_DATE_BUFFER_DAYS = 14

# Required weekly clinic minutes per specialty (PRD §3.5).
REQUIRED_WEEKLY_CLINIC_MINUTES = {
    "FAMILY_MEDICINE": 1200,
    "INTERNAL_MEDICINE": 1200,
    "PEDIATRICS": 1100,
    "CARDIOLOGY": 1000,
    "ORTHOPEDICS": 900,
}

# Training (PRD §3.4).
PASS_SCORE = 80
TEMPLATES_REQUIRED_NEW_GRAD = 5
TEMPLATES_REQUIRED_DEFAULT = 3
REQUIRED_MODULE_COUNT_NEW_GRAD = 4
REQUIRED_MODULE_COUNT_DEFAULT = 3

# Negotiation (PRD §3.2).
MAX_NEGOTIATION_ROUNDS = 5

# Income guarantee (PRD §3.8).
COLLECTION_CREDIT_CAP_CENTS = 1800000
MISSED_PENALTY_PCT = 0.10
FORGIVENESS_PER_ATTAINED_MONTH_CENTS = 100000
REPORT_GRACE_DAYS = 15
WRVU_TARGET_CURVE = [100, 150, 200, 250, 300, 350, 400, 420, 440, 460, 480, 500]

# Retention risk (PRD §3.9).
RAMP_FILL_CURVE = [0.10, 0.18, 0.26, 0.34, 0.42, 0.50, 0.58, 0.65, 0.71, 0.77, 0.82, 0.85]
WEIGHT_MILESTONE = 0.35
WEIGHT_PANEL = 0.25
WEIGHT_SENTIMENT = 0.25
WEIGHT_SCHEDULE = 0.15
BAND_CRITICAL_MIN = 75
BAND_HIGH_MIN = 50
BAND_MODERATE_MIN = 25
SENTIMENT_SCORES = {"POSITIVE": 0, "NEUTRAL": 40, "CONCERN": 70, "CRISIS": 100}
SENTIMENT_RISK_DEFAULT = 50

# Standard offer terms used across fixtures.
DEFAULT_TERMS = {
    "base_salary_cents": 25000000,
    "signing_bonus_cents": 2000000,
    "guarantee_monthly_cents": 2000000,
    "guarantee_term_months": 12,
    "panel_capacity": 1000,
    "proposed_start_date": "2027-06-01",
    "expires_at": "2026-08-01T00:00:00Z",
}
