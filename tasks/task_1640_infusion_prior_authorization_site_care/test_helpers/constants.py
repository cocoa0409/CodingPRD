"""Domain thresholds and defaults — numeric constants named in the PRD."""

# Logical clock startup instant (PRD: the logical clock reads exactly
# 2026-08-01T00:00:00Z at server startup, with no wall-clock fallback).
CLOCK_START = "2026-08-01T00:00:00Z"

# Dose-change re-authorization threshold (PRD: exactly 20.00 triggers
# re-authorization, while 19.99 does not).
REAUTH_THRESHOLD_PCT = 20.00

# Appeal window length in days after denial (PRD: appeal_deadline is sixty
# days after denied_at).
APPEAL_WINDOW_DAYS = 60

# Site steering score constants (PRD site-of-care section).
BURDEN_CAP_MINUTES = 120
DEFAULT_STEER_THRESHOLD = 1.50

# Peer-to-peer reschedule limit (PRD: the third attempt is rejected).
P2P_MAX_RESCHEDULES = 2

# Appointment auto-transition grace (PRD: sixty minutes past scheduled_start).
MISSED_GRACE_MINUTES = 60

# Standard payloads used across fixtures.
DEFAULT_POLICY = {
    "payer_code": "PAYERX",
    "drug_code": "J9001",
    "regimen_name": "DrugA q4w",
    "benefit_channel": "MEDICAL",
    "validity_days": 90,
    "max_course_days": 60,
    "max_dose_mg": 1000,
    "deductible_cents": 100000,
    "coinsurance_pct": 0.20,
    "oop_max_cents": 500000,
    "prepay_limit_cents": 250000,
}

DEFAULT_PATIENT = {
    "member_id": "M1001",
    "full_name": "Pat One",
    "diagnosis_code": "C50",
    "payer_code": "PAYERX",
    "plan_year_end": "2026-12-31T00:00:00Z",
    "deductible_remaining_cents": 50000,
    "oop_remaining_cents": 300000,
}

DEFAULT_SITE_AMOUNTS = {
    "home_allowed_cents": 100000,
    "hospital_allowed_cents": 300000,
    "home_billed_cents": 120000,
    "hospital_billed_cents": 360000,
}

DEFAULT_REQUEST = {
    "requested_site_type": "OFFICE",
    "requested_dose_mg": 500,
    "patient_weight_kg": 70,
}
