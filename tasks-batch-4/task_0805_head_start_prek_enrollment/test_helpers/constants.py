"""Domain thresholds — numeric constants from the PRD calculations (§2, §3)."""

# Federal Poverty Level threshold arithmetic (PRD §3.3).
FPL_BASE_CENTS = 1_508_000
FPL_INCREMENT_CENTS = 536_000

# Priority scoring cap (PRD §3.3).
MAX_PRIORITY_POINTS = 90

# Chronic-absence default threshold when a program omits it (PRD §3.1).
DEFAULT_ADA_CHRONIC_THRESHOLD_PCT = 0.10

# Offer window: offered_at + 10 days == offer_expires_at (PRD §3.4/§2.8;
# an offer created at the 2026-03-01 clock default expires 2026-03-11).
OFFER_WINDOW_DAYS = 10

# Logical clock startup default (PRD §2.8).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"


def fpl_for_household(household_size: int) -> int:
    """FPL threshold in cents for a household of the given size (PRD §3.3)."""
    return FPL_BASE_CENTS + FPL_INCREMENT_CENTS * (household_size - 1)
