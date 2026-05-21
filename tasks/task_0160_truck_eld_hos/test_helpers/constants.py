"""Domain thresholds — numeric constants from PRD calculations.

PRD §2.6: "All HOS minute computations ... are expressed as integer
minutes; any fractional minute that arises in intermediate arithmetic
is truncated toward zero."
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 11-hour driving — PRD §3.4
# ---------------------------------------------------------------------------
ELEVEN_HOUR_BASE_MINUTES: int = 660
ELEVEN_HOUR_EXTENDED_MINUTES: int = 780  # 660 + 120 adverse extension

# ---------------------------------------------------------------------------
# 14-hour on-duty window — PRD §3.4
# ---------------------------------------------------------------------------
FOURTEEN_HOUR_BASE_MINUTES: int = 840
FOURTEEN_HOUR_EXTENDED_MINUTES: int = 960  # 840 + 120 adverse extension

# ---------------------------------------------------------------------------
# Cycle — PRD §3.4
# ---------------------------------------------------------------------------
SEVENTY_HOUR_CAP_MINUTES: int = 4200
SIXTY_HOUR_CAP_MINUTES: int = 3600
RESTART_MIN_MINUTES: int = 2040  # 34h restart

# ---------------------------------------------------------------------------
# Qualifying break / sleeper-berth — PRD §3.5
# ---------------------------------------------------------------------------
QUALIFYING_BREAK_MINUTES: int = 600  # 10h
SLEEPER_LONG_LEG_MIN_MINUTES: int = 420  # 7h
SLEEPER_SHORT_LEG_MIN_MINUTES: int = 120  # 2h
SLEEPER_COMBINED_MIN_MINUTES: int = 600  # 10h combined

# ---------------------------------------------------------------------------
# Adverse-conditions exemption — PRD §3.6
# ---------------------------------------------------------------------------
ADVERSE_EXTRA_MINUTES: int = 120
ADVERSE_REASON_MIN_LEN: int = 10

# ---------------------------------------------------------------------------
# Annotation — PRD §3.3
# ---------------------------------------------------------------------------
ANNOTATION_MIN_LEN: int = 10

# ---------------------------------------------------------------------------
# Edit window — PRD §3.7
# ---------------------------------------------------------------------------
EDIT_WINDOW_DAYS: int = 8

# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Allowed enumeration sets
# ---------------------------------------------------------------------------
DUTY_STATUSES: set = {
    "OFF_DUTY", "SLEEPER_BERTH", "DRIVING",
    "ON_DUTY_NOT_DRIVING", "PERSONAL_CONVEYANCE", "YARD_MOVES",
}

CYCLE_TYPES: set = {"SEVENTY_HOUR_EIGHT_DAY", "SIXTY_HOUR_SEVEN_DAY"}

DAILY_LOG_STATUSES: set = {"UNCERTIFIED", "CERTIFIED", "RECERTIFIED"}

VIOLATION_STATUSES: set = {"OPEN", "ACKNOWLEDGED", "REPORTED", "RESOLVED"}

VIOLATION_RULE_CODES: set = {
    "ELEVEN_HOUR_DRIVING", "FOURTEEN_HOUR_WINDOW",
    "SEVENTY_HOUR_CYCLE", "SIXTY_HOUR_CYCLE",
}

EXEMPTION_STATUSES: set = {"ACTIVE", "CONSUMED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "CARRIER_LEGAL_NAME": "Acme Trucking Co.",
    "DRIVER_FULL_NAME": "Casey Test Driver",
    "DEFAULT_TIMEZONE": "UTC",
    "DEFAULT_FIRMWARE": "3.4.1",
    "DEFAULT_LAT": 37.774930,
    "DEFAULT_LON": -122.419416,
    "DEFAULT_REASON": (
        "Severe winter storm on I-80 reducing visibility below 100m."
    ),
    "DEFAULT_ANNOTATION": "Pre-trip inspection at yard.",
    "DEFAULT_PC_ANNOTATION": "Off-duty personal trip to dinner.",
    "DEFAULT_YM_ANNOTATION": "Repositioning trailer in yard.",
}


__all__ = [
    "ELEVEN_HOUR_BASE_MINUTES", "ELEVEN_HOUR_EXTENDED_MINUTES",
    "FOURTEEN_HOUR_BASE_MINUTES", "FOURTEEN_HOUR_EXTENDED_MINUTES",
    "SEVENTY_HOUR_CAP_MINUTES", "SIXTY_HOUR_CAP_MINUTES",
    "RESTART_MIN_MINUTES",
    "QUALIFYING_BREAK_MINUTES",
    "SLEEPER_LONG_LEG_MIN_MINUTES",
    "SLEEPER_SHORT_LEG_MIN_MINUTES",
    "SLEEPER_COMBINED_MIN_MINUTES",
    "ADVERSE_EXTRA_MINUTES", "ADVERSE_REASON_MIN_LEN",
    "ANNOTATION_MIN_LEN",
    "EDIT_WINDOW_DAYS",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_MIN_OFFSET",
    "DUTY_STATUSES", "CYCLE_TYPES", "DAILY_LOG_STATUSES",
    "VIOLATION_STATUSES", "VIOLATION_RULE_CODES", "EXEMPTION_STATUSES",
    "TEST_DEFAULTS",
]
