"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Cadence cap (PRD §3.5): trailing 7-day window, max 7 cadence-counting attempts.
WINDOW_DAYS = 7
MAX_ATTEMPTS_PER_WINDOW = 7

# Post-conversation cooldown buffer (PRD §3.5): 7 days forward from last_conversation_at.
COOLDOWN_DAYS = 7

# Validation / dispute window (PRD §3.3): validation_deadline = sent + 30 days.
VALIDATION_WINDOW_DAYS = 30

# e-OSCAR investigation deadline (PRD §3.11): opened_at + 30 days.
INVESTIGATION_DEADLINE_DAYS = 30

# Calling window (PRD §3.5): local time must be in [08:00:00, 21:00:00).
CALL_WINDOW_START_HOUR = 8
CALL_WINDOW_END_HOUR = 21

# Payoff admin fee (PRD §3.10): 50 cents per whole day under GOOD_THROUGH.
ADMIN_FEE_PER_DAY_CENTS = 50

# Settlement floor (PRD §3.6) — age buckets in whole days and resulting bps floors.
FRESH_AGE_DAYS = 180          # age < 180 -> 7000 bps
AGED_AGE_DAYS = 730           # 180 <= age < 730 -> 5000 bps; age >= 730 -> 3000 bps
AGE_FLOOR_FRESH_BPS = 7000
AGE_FLOOR_MID_BPS = 5000
AGE_FLOOR_OLD_BPS = 3000

# Balance tier (PRD §3.6): balance >= 1,000,000 cents -> 4000 bps; else 6000 bps.
HIGH_BALANCE_CENTS = 1_000_000
BALANCE_FLOOR_HIGH_BPS = 4000
BALANCE_FLOOR_LOW_BPS = 6000

# Verified-dispute bump (PRD §3.6): +1000 bps, capped at 10000.
VERIFIED_FLOOR_BUMP_BPS = 1000
MAX_BPS = 10000

# Basis points denominator (PRD §2.6): 10000 bps = 100%.
BPS_DENOMINATOR = 10000

# Server startup default clock (PRD §2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


THRESHOLDS = {
    "WINDOW_DAYS": WINDOW_DAYS,
    "MAX_ATTEMPTS_PER_WINDOW": MAX_ATTEMPTS_PER_WINDOW,
    "COOLDOWN_DAYS": COOLDOWN_DAYS,
    "VALIDATION_WINDOW_DAYS": VALIDATION_WINDOW_DAYS,
    "ADMIN_FEE_PER_DAY_CENTS": ADMIN_FEE_PER_DAY_CENTS,
    "HIGH_BALANCE_CENTS": HIGH_BALANCE_CENTS,
    "MAX_BPS": MAX_BPS,
    "BPS_DENOMINATOR": BPS_DENOMINATOR,
}
