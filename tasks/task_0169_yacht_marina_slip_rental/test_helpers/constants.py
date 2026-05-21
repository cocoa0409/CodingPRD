"""Domain thresholds — numeric constants from PRD calculations.

All monetary values are integer cents per PRD §2.8:
"All monetary values are stored as integer cents — never floating-point
dollars."
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pricing constants — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "a liveaboard surcharge of 1500 cents per night (fifteen
# dollars per day)"
LIVEABOARD_SURCHARGE_CENTS: int = 1500

# PRD §3.5 season multipliers (peak Jun-Aug, shoulder Apr-May/Sep-Oct,
# off-season otherwise).
SEASON_PEAK_MULTIPLIER: float = 1.50
SEASON_SHOULDER_MULTIPLIER: float = 1.20
SEASON_OFF_MULTIPLIER: float = 1.00

SEASON_PEAK_MONTHS: tuple = (6, 7, 8)
SEASON_SHOULDER_MONTHS: tuple = (4, 5, 9, 10)


# ---------------------------------------------------------------------------
# Utility settlement — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "a kilowatt-hour rate of 18 cents, and a water rate of 4 cents
# per gallon."
KWH_RATE_CENTS: int = 18
WATER_RATE_CENTS_PER_GAL: int = 4

# PRD §3.6: "a flat sewage charge of 2500 cents (twenty-five dollars) is
# added"
SEWAGE_FLAT_CENTS: int = 2500


# ---------------------------------------------------------------------------
# Tow contracts — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "`charge_cents` is set to 25000 cents (a flat
# two-hundred-fifty-dollar fee)"
TOW_FLAT_FEE_CENTS: int = 25000

# PRD §3.2 / §3.8: BASIC starts at 2, PREMIUM at -1 sentinel.
BASIC_TOWS_INITIAL: int = 2
PREMIUM_TOWS_SENTINEL: int = -1


# ---------------------------------------------------------------------------
# Size-match — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "The slip's `beam_feet` must be at least two feet greater
# than the vessel's `beam_feet`, reserving a two-foot buffer ..."
BEAM_BUFFER_FEET: float = 2.0


# ---------------------------------------------------------------------------
# Transfer offer expiry — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "on success the system sets `offer_expires_at` to the
# marina's `current_date` plus twenty-four hours."
OFFER_EXPIRES_HOURS: int = 24


# ---------------------------------------------------------------------------
# Approval expiry threshold — PRD §3.4 / §2.7
# ---------------------------------------------------------------------------
# PRD §3.4: "If the marina clock advances and an `APPROVED` reservation
# has not been checked in by a full day past its `check_in_date`, the
# next ops sweep transitions the reservation to `EXPIRED`."
APPROVAL_EXPIRY_DAYS: int = 1


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Initial marina clock — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "At creation the marina's `current_date` is initialized to
# `1970-01-01T00:00:00.000Z`"
INITIAL_MARINA_CLOCK: str = "1970-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Test defaults — values used by factories when no override is given.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "MARINA_NAME": "Test Marina",
    "MARINA_TIMEZONE": "America/New_York",
    "BASE_DAILY_RATE_CENTS": 500,         # 5.00 dollars per LOA-foot
    "LIVEABOARD_QUOTA": 5,
    "BOATER_NAME": "Test Boater",
    "VESSEL_NAME": "Test Vessel",
    "VESSEL_LOA_FEET": 30.0,
    "VESSEL_BEAM_FEET": 10.0,
    "VESSEL_DRAFT_FEET": 4.0,
    "VESSEL_HOLDING_TANK": 40,
    "SLIP_LENGTH_FEET": 40.0,
    "SLIP_BEAM_FEET": 14.0,
    "SLIP_DEPTH_FEET": 6.0,
    "SLIP_FLAT_DAILY_CHARGE_CENTS": 2000,
    "INSURANCE_CARRIER": "Test Marine Ins.",
    "INSURANCE_LIABILITY_LIMIT_CENTS": 1_000_000,
    "INSURANCE_EFFECTIVE_DATE": "2024-01-01T00:00:00.000Z",
    "INSURANCE_EXPIRATION_DATE": "2025-01-01T00:00:00.000Z",
}


__all__ = [
    "LIVEABOARD_SURCHARGE_CENTS",
    "SEASON_PEAK_MULTIPLIER",
    "SEASON_SHOULDER_MULTIPLIER",
    "SEASON_OFF_MULTIPLIER",
    "SEASON_PEAK_MONTHS",
    "SEASON_SHOULDER_MONTHS",
    "KWH_RATE_CENTS",
    "WATER_RATE_CENTS_PER_GAL",
    "SEWAGE_FLAT_CENTS",
    "TOW_FLAT_FEE_CENTS",
    "BASIC_TOWS_INITIAL",
    "PREMIUM_TOWS_SENTINEL",
    "BEAM_BUFFER_FEET",
    "OFFER_EXPIRES_HOURS",
    "APPROVAL_EXPIRY_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "INITIAL_MARINA_CLOCK",
    "TEST_DEFAULTS",
]
