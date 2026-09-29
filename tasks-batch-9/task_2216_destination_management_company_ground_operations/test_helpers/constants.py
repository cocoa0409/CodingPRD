"""Domain thresholds and shared literals taken from the PRD's stated rules."""

# --- Attendance and billing (PRD §3.8, §3.9) ---
ATTRITION_FLOOR_PCT = 0.85          # "multiply it by 85 hundredths"
VARIANCE_TOLERANCE_PCT = 0.10       # "variance_pct exceeds 10 hundredths"
FEE_TIER_1_CEILING = 500_000        # base below 500,000 cents -> 12 hundredths
FEE_TIER_2_CEILING = 2_000_000      # base below 2,000,000 cents -> 9 hundredths
FEE_PCT_TIER_1 = 0.12
FEE_PCT_TIER_2 = 0.09
FEE_PCT_TIER_3 = 0.07
DEFAULT_MARKUP_PCT = 0.18           # "when omitted it defaults to 0.18"
MARKUP_PCT_MIN = 0.05
MARKUP_PCT_MAX = 0.35

# --- Labour cost ladder (PRD §3.6) ---
MIN_CALL_OUT_MINUTES = 240          # "four-hour call-out minimum of 240 minutes"
OT_THRESHOLD_MINUTES = 480          # "eight-hour overtime threshold of 480 minutes"
OT_MULTIPLIER = 1.5

# --- Credentials (PRD §3.6) ---
CREDENTIAL_EXPIRING_WINDOW_DAYS = 14
DEFAULT_MIN_REST_MINUTES = 600
DEFAULT_MAX_DAILY_MINUTES = 720

# --- Venue geometry (PRD §3.2) ---
DEFAULT_TURNOVER_BUFFER_MINUTES = 90

# --- Contracting (PRD §3.3) ---
DEFAULT_DEPOSIT_PCT = 0.3
MAX_NEGOTIATION_ROUNDS = 3

# --- Cancellation penalty ladders (PRD §3.7) ---
STANDARD_TIER_DAYS = [30, 15, 7]
STANDARD_TIER_PCTS = [0.00, 0.25, 0.50, 1.00]
STRICT_TIER_DAYS = [45, 30, 8]
STRICT_TIER_PCTS = [0.10, 0.35, 0.75, 1.00]

# --- Windows (PRD §3.5, §3.6) ---
MANIFEST_CHECKIN_WINDOW_MINUTES = 120   # opens two hours before depart_at
STAFF_CHECKIN_WINDOW_MINUTES = 60       # opens 60 minutes before starts_at

# --- Logical clock (PRD §2.4) ---
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Literals shared by the composite fixtures ---
TEST_DEFAULTS = {
    "ARRIVAL_DATE": "2026-09-10",
    "DEPARTURE_DATE": "2026-09-14",
    "INSURANCE_EXPIRES_ON": "2027-01-31",
    "INSURANCE_LIABILITY_LIMIT_CENTS": 500_000_000,
    "REQUIRED_LIABILITY_LIMIT_CENTS": 100_000_000,
    "BADGE_EXPIRES_ON": "2027-06-30",
    "FIRST_AID_EXPIRES_ON": "2027-12-31",
}

# Operator identifiers used where segregation of duties requires two humans
# (PRD §2.10).
CONTRACT_SENDER_USER_ID = "sm-sender-1"
CONTRACT_SIGNER_USER_ID = "sm-signer-2"
CONTROLLER_APPROVER_USER_ID = "ctrl-1"
CONTROLLER_RELEASER_USER_ID = "ctrl-2"
