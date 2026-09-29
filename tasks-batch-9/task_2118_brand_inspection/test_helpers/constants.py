"""Numeric constants the PRD fixes for the board's calculations."""

# Inspection fee assessment (PRD §3.9).
FEE_BANDS = {
    "BAND_1_MAX_HEAD": 50,
    "BAND_1_RATE_CENTS_PER_HEAD": 110,
    "BAND_2_MAX_HEAD": 200,
    "BAND_2_RATE_CENTS_PER_HEAD": 85,
    "BAND_3_RATE_CENTS_PER_HEAD": 60,
}

THRESHOLDS = {
    # Inspection fee assessment (PRD §3.9)
    "ADMIN_SURCHARGE_RATE": 0.125,
    "AFTER_HOURS_FLAT_CENTS": 4500,
    "AFTER_HOURS_START_HOUR_UTC": 18,
    "AFTER_HOURS_END_HOUR_UTC": 7,
    "FEE_DUE_DAYS": 30,
    # Owner arrears and standing (PRD §3.9)
    "ARREARS_SUSPENSION_THRESHOLD_CENTS": 25000,
    # Estray proceeds distribution (PRD §3.8)
    "STATUTORY_HOLD_DAYS": 20,
    "CARE_RATE_CENTS_PER_HEAD_PER_DAY": 275,
    "HANDLING_RATE_OF_GROSS": 0.15,
    "HANDLING_CAP_RATE_OF_NET": 0.20,
    # Facility intake posture (PRD §3.1)
    "INTAKE_RESTRICTION_PERCENT": 90,
    # Brand priority ranking (PRD §3.2, §3.3)
    "PRIOR_USE_CAP_YEARS": 10,
    "DAYS_PER_PRIOR_USE_YEAR": 365,
    # Filing fees and the registration calendar (PRD §3.2, §3.3)
    "NEW_FILING_FEE_CENTS": 9000,
    "BASE_RENEWAL_FEE_CENTS": 12000,
    "REGISTRATION_TERM_DAYS": 1825,
    "GRACE_DAYS": 30,
    "LAPSE_RECOVERY_DAYS": 90,
    "GRACE_PENALTY_RATE": 0.25,
    "LAPSE_PENALTY_RATE": 0.75,
    # Inspector scheduling (PRD §3.5)
    "TRAVEL_BUFFER_MINUTES": 45,
    "DEFAULT_MAX_DAILY_ASSIGNMENTS": 3,
    # Correction and reopen ceilings (PRD §3.2, §3.7)
    "MAX_CORRECTION_ROUNDS": 2,
    "MAX_REOPENS": 1,
}

# The logical clock reads exactly this instant before any client moves it (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00.000Z"

TEST_DEFAULTS = {
    "TRAVEL_SURCHARGE_CENTS": 2500,
    "IMPOUND_CAPACITY_HEAD": 100,
    "CERTIFICATION_EXPIRES_ON": "2027-12-31T00:00:00Z",
    "MAILING_STATE": "MT",
    "STATE_CODE": "MT",
}

# Opaque operator identifiers used where the PRD calls for attribution only.
EXAMINER_ID = "recorder-01"
RECORDER_ID = "recorder-02"
SECOND_RECORDER_ID = "recorder-03"
FEE_ADMIN_ID = "fee-01"
INVESTIGATOR_ID = "inv-01"
SECOND_INVESTIGATOR_ID = "inv-02"
BOARD_ADMIN_ID = "admin-01"
