"""Domain thresholds — numeric constants from PRD calculations (§2.5, §2.8, §3)."""

# PRD §2.5: the logical clock before any advance.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.5: no member may be granted more than 100 points per UTC calendar day.
    "DAILY_POINTS_CAP": 100,
    # PRD §3.5: raw conversion divisors/multiplier.
    "STEPS_PER_POINT": 1000,
    "MINUTES_PER_POINT": 30,
    "VISITS_POINTS_EACH": 10,
    # PRD §3.4: risk band cut lines.
    "HRA_MODERATE_MIN": 30,
    "HRA_HIGH_MIN": 60,
    # PRD §3.4: biometric strict targets.
    "BMI_TARGET": 30.0,
    "SYSTOLIC_BP_TARGET": 140,
    "TOTAL_CHOLESTEROL_TARGET": 200,
    "GLUCOSE_TARGET": 100,
    # PRD §3.7: GOLD requires a best targets_met of at least 3.
    "GOLD_MIN_TARGETS": 3,
    # PRD §3.7: dispute window in days after confirmed_at.
    "APPEAL_WINDOW_DAYS": 30,
}

# Standard tenant/program fixture values shared across tests.
TEST_DEFAULTS = {
    "ANNUAL_SELF_ONLY_PREMIUM_CENTS": 120000,
    "TOBACCO_SURCHARGE_CENTS": 50000,
    "PMPM_FEE_CENTS": 10000,
    "COACHING_SESSION_FEE_CENTS": 7500,
    "K_ANONYMITY_THRESHOLD": 5,
    "KIOSK_CAPACITY": 2,
    "INVOICE_APPROVAL_LIMIT_CENTS": 5000,
    "BRONZE_THRESHOLD": 500,
    "SILVER_THRESHOLD": 1500,
    "GOLD_THRESHOLD": 3000,
    "BRONZE_AWARD_CENTS": 10000,
    "SILVER_AWARD_CENTS": 30000,
    "GOLD_AWARD_CENTS": 60000,
    "PREMIUM_CAP_PCT": 0.30,
    # round_half_up(0.30 * 120000)
    "PREMIUM_CAP_CENTS": 36000,
    "COACHING_REQUIRED_SESSIONS": 4,
}

# Common instants/windows used across tests (all inside the standard plan year).
WINDOW = {
    "CHALLENGE_START": "2026-04-01T00:00:00Z",
    "CHALLENGE_END": "2026-06-01T00:00:00Z",
    "EVENT_AT": "2026-04-15T10:00:00Z",
    "SCREENING_SLOT_START": "2026-04-20T10:00:00Z",
    "SCREENING_SLOT_END": "2026-04-20T10:30:00Z",
}
