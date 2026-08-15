"""Domain thresholds and defaults — numeric constants from the PRD.

Sources: PRD §2.5 (logical clock startup), §2.6 (call window), §2.8 (fairness
points and equity band), §2.9 (moonlight cap / premium), §3.3 (rates and pay
multipliers), §3.4 (swap cutoff), §3.5 (credentialing lead time).
"""

# Logical clock startup default (PRD §2.5): before any set call the clock is
# exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Call window (PRD §2.6): 07:00 UTC to next-day 07:00 UTC, half-open.
CALL_WINDOW_START_HOUR = 7
CALL_HOURS = 24
ACTIVATION_GRACE_HOURS = 2  # activation allowed through window_end + 2h

# Moonlighting (PRD §2.9).
ROLLING_WINDOW_DAYS = 28
DEFAULT_MOONLIGHT_CAP_HOURS = 96
DEFAULT_MOONLIGHT_PREMIUM_THRESHOLD_HOURS = 40

# Rates and multipliers (PRD §3.3).
DEFAULT_PRIMARY_RATE_CENTS = 50_000
DEFAULT_BACKUP_RATE_CENTS = 20_000
DEFAULT_WEEKEND_MULTIPLIER = 1.25
DEFAULT_HOLIDAY_MULTIPLIER = 1.5
DEFAULT_BACKUP_ACTIVATION_MULTIPLIER = 2.0
DEFAULT_MOONLIGHT_PREMIUM_MULTIPLIER = 1.15

# Fairness points (PRD §2.8).
DEFAULT_WEEKDAY_CALL_POINTS = 1.0
DEFAULT_WEEKEND_CALL_POINTS = 2.0
DEFAULT_HOLIDAY_CALL_POINTS = 3.0
DEFAULT_BACKUP_POINT_MULTIPLIER = 0.5
DEFAULT_EQUITY_BAND_POINTS = 4.0

# Cutoffs and lead times.
DEFAULT_SWAP_CUTOFF_HOURS = 48  # PRD §3.4
DEFAULT_CREDENTIALING_LEAD_HOURS = 120  # PRD §3.5

# Credentialing checklist items (PRD §3.5), in a valid completion order
# (privileges_granting requires license_verification first).
CREDENTIALING_ITEMS = (
    "license_verification",
    "malpractice_verification",
    "privileges_granting",
    "health_screening",
    "orientation",
)
