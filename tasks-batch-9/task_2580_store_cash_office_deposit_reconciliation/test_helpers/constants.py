"""Domain thresholds and derived-arithmetic constants named by the PRD."""

import math

#: Chain defaults every store policy parameter falls back to when omitted.
STORE_POLICY_DEFAULTS = {
    "safe_time_delay_minutes": 5,
    "safe_open_window_minutes": 10,
    "dual_control_required": True,
    "pickup_buffer_minutes": 30,
    "max_daily_pickups": 2,
    "single_event_variance_threshold_cents": 2500,
    "rolling_variance_threshold_cents": 10000,
    "rolling_window_days": 30,
    "theft_escalation_threshold_cents": 50000,
    "provisional_credit_cap_cents": 500000,
    "seasonal_profile": "BASELINE",
}

#: Accepted ranges for the store policy parameters.
STORE_POLICY_RANGES = {
    "safe_time_delay_minutes": (0, 120),
    "safe_open_window_minutes": (1, 240),
    "pickup_buffer_minutes": (0, 240),
    "max_daily_pickups": (1, 6),
    "rolling_window_days": (1, 365),
}

#: The coaching grace period: the breach instant plus three days, that is 72 hours.
COACHING_GRACE_HOURS = 72

#: The rolling-pattern escalation route looks back over the preceding 90 days.
ESCALATION_PATTERN_DAYS = 90

#: Only denominations of at least 500 cents earn smart-safe provisional credit.
VALIDATED_MIN_DENOMINATION_CENTS = 500

#: The armored-carrier fee: 1200 cents plus 35 cents per thousand-dollar increment.
CARRIER_BASE_FEE_CENTS = 1200
CARRIER_PER_THOUSAND_FEE_CENTS = 35
CARRIER_INCREMENT_CENTS = 100000

#: Card settlement pricing.
PER_TXN_FEE_CENTS = 12
TIER_1_RATE = 0.0250
TIER_2_RATE = 0.0220
TIER_3_RATE = 0.0195
TIER_2_FLOOR_CENTS = 5000000
TIER_3_FLOOR_CENTS = 20000000
AMEX_ADDER = 0.0035

#: Change-order seasonal demand multipliers.
SEASONAL_MULTIPLIER = {
    "BASELINE": 1.00,
    "BACK_TO_SCHOOL": 1.35,
    "HOLIDAY": 1.80,
}

#: The five denomination rows a change order always plans, in descending order.
DENOM_MIX = [
    {"denomination_cents": 2000, "mix_pct": 0.50, "strap_units": 25},
    {"denomination_cents": 1000, "mix_pct": 0.20, "strap_units": 25},
    {"denomination_cents": 500, "mix_pct": 0.15, "strap_units": 50},
    {"denomination_cents": 100, "mix_pct": 0.10, "strap_units": 50},
    {"denomination_cents": 25, "mix_pct": 0.05, "strap_units": 40},
]

#: Change order input bounds.
DAYS_COVERED_MIN = 1
DAYS_COVERED_MAX = 14
GROWTH_PCT_MIN = -0.50
GROWTH_PCT_MAX = 2.00

#: Register numbers run from 1 through 99 inclusive.
REGISTER_NUMBER_MIN = 1
REGISTER_NUMBER_MAX = 99

#: The logical clock reads exactly this instant on startup.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

#: Pagination contract.
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}


def denomination_value(lines) -> int:
    """The value of a set of denomination lines; an empty list is worth zero."""
    return sum(line["denomination_cents"] * line["quantity"] for line in lines)


def carrier_fee_cents(declared_total_cents: int) -> int:
    """1200 cents plus 35 cents per thousand-dollar increment, count rounded up."""
    increments = math.ceil(declared_total_cents / CARRIER_INCREMENT_CENTS)
    return CARRIER_BASE_FEE_CENTS + CARRIER_PER_THOUSAND_FEE_CENTS * increments
