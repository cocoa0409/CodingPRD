"""Domain thresholds — numeric constants from PRD §3.x.

Field names mirror PRD prose exactly. Generic NON_EXISTENT_UUID comes from
the framework.
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Reservation hold + no-show penalty (PRD §3.3)
# ---------------------------------------------------------------------------
# PRD §3.3: 'The system computes hold_expires_at as the reservation's
# created_at plus fifteen minutes ...'
RESERVATION_HOLD_MINUTES = 15

# PRD §3.3: 'multiply five hundred cents by two raised to the power of prior
# strikes, then cap the result at five thousand cents'.
NO_SHOW_BASE_PENALTY_CENTS = 500
NO_SHOW_STRIKE_MULTIPLIER = 2
NO_SHOW_MAX_PENALTY_CENTS = 5000

# PRD §3.3: 'A driver whose no_show_strikes has reached three or more is
# barred from reserving.'
MAX_STRIKES_FOR_RESERVATION = 3


# ---------------------------------------------------------------------------
# Wallet / session start (PRD §3.4)
# ---------------------------------------------------------------------------
# PRD §3.4: 'The driver's wallet_balance_cents must be at least one thousand
# cents (the minimum authentication hold)'.
MIN_AUTH_HOLD_CENTS = 1000


# ---------------------------------------------------------------------------
# Operator-settlement waterfall (PRD §3.6)
# ---------------------------------------------------------------------------
# PRD §3.6: 'the platform's allocation is that remainder multiplied by five
# hundred basis points (five percent)'.
PLATFORM_BASE_FEE_BPS = 500

# PRD §3.6: 'the roaming partner's allocation is net_cents multiplied by
# fifteen hundred basis points (fifteen percent)'.
ROAMING_PARTNER_BPS = 1500


# ---------------------------------------------------------------------------
# Energy units (PRD §2.6)
# ---------------------------------------------------------------------------
# PRD §2.6: 'one kilowatt-hour equals one thousand units in
# cumulative_energy_milli'.
MILLI_PER_KWH = 1000


# ---------------------------------------------------------------------------
# Availability ranking (PRD §3.6)
# ---------------------------------------------------------------------------
# PRD §3.6: 'five times the pile's rated_power_kw plus twenty-five times the
# member's tier rank minus one hundred times the haversine distance ...'.
POWER_WEIGHT = 5
TIER_BONUS_PER_LEVEL = 25
DISTANCE_WEIGHT = 100


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding utility (PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up(value: float) -> int:
    """PRD §2.6: 'conversions from any computed quantity to cents always
    round half up.'"""
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


def no_show_penalty_for_prior_strikes(prior_strikes: int) -> int:
    """PRD §3.3: 'read the prior strikes count, multiply five hundred cents
    by two raised to the power of prior strikes, then cap the result at five
    thousand cents'."""
    raw = NO_SHOW_BASE_PENALTY_CENTS * (
        NO_SHOW_STRIKE_MULTIPLIER ** prior_strikes
    )
    return min(raw, NO_SHOW_MAX_PENALTY_CENTS)


__all__ = [
    "RESERVATION_HOLD_MINUTES",
    "NO_SHOW_BASE_PENALTY_CENTS",
    "NO_SHOW_STRIKE_MULTIPLIER",
    "NO_SHOW_MAX_PENALTY_CENTS",
    "MAX_STRIKES_FOR_RESERVATION",
    "MIN_AUTH_HOLD_CENTS",
    "PLATFORM_BASE_FEE_BPS",
    "ROAMING_PARTNER_BPS",
    "MILLI_PER_KWH",
    "POWER_WEIGHT",
    "TIER_BONUS_PER_LEVEL",
    "DISTANCE_WEIGHT",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
    "no_show_penalty_for_prior_strikes",
]
