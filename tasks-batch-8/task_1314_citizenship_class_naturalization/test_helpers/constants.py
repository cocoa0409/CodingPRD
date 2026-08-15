"""Domain thresholds and well-known values from the PRD (§3.1 defaults, §3 formulas)."""

# The logical clock reads exactly this instant before any client adjusts it (PRD §2.5).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Program operating-parameter defaults (PRD §3.1).
PROGRAM_DEFAULTS = {
    "n400_fee_cents": 76000,
    "biometric_fee_cents": 8501,
    "translation_stipend_cents": 3001,
    "poverty_base_cents": 1565000,
    "poverty_per_additional_cents": 550000,
    "full_waiver_threshold_pct": 150,
    "partial_waiver_threshold_pct": 200,
    "attendance_complete_bp": 8000,
    "attendance_midterm_floor_bp": 5000,
    "readiness_certify_threshold": 70,
    "rfe_deadline_days": 84,
    "accreditation_valid_months": 24,
    "general_training_hours": 10,
    "legal_supervised_hours": 8,
    "renewal_training_hours": 4,
    "promotion_offer_hours": 72,
    "mock_buffer_minutes": 15,
    "mock_max_attempts": 3,
}

# Screening thresholds (PRD §3.2) — fixed constants, not Program-tunable.
RESIDENCE_MONTHS_STANDARD = 60
RESIDENCE_MONTHS_MARITAL = 36
PRESENCE_DAYS_STANDARD = 913
PRESENCE_DAYS_MARITAL = 548
EXEMPTION_AGE = 55
EXEMPTION_LPR_MONTHS = 180
SCREENING_VALID_DAYS = 180

# Fee results under the default schedule (PRD §3.8 pinned evaluation order).
FILING_FEE_NO_WAIVER_CENTS = 87502          # 76000 + 8501 + 3001
FILING_FEE_PARTIAL_CENTS = 43752            # 38000 + 4251 + 1501 (per-line half-up, then sum)

# Attendance (PRD §3.4).
BP_PERFECT = 10000

# Readiness weights (PRD §3.3).
READINESS_W_RESIDENCE = 25
READINESS_W_PRESENCE = 25
READINESS_W_ENGLISH = 20
READINESS_W_CIVICS = 20
READINESS_W_LEGAL = 10
READINESS_PROJECTED_CIVICS_FLOOR = 70
MOCK_ELIGIBILITY_MIN_SCORE = 40

# Mock interview scoring (PRD §3.3).
MOCK_PASS_OVERALL = 70
MOCK_PASS_CIVICS_FLOOR = 60

# Training window (PRD §3.5).
TRAINING_WINDOW_DAYS = 730

# Linear case stage order used to walk a case forward (PRD §3.9).
CASE_STAGE_ORDER = [
    "FILED",
    "RECEIPTED",
    "BIOMETRICS_COMPLETE",
    "INTERVIEW_SCHEDULED",
    "INTERVIEW_PASSED",
    "APPROVED_PENDING_OATH",
]
