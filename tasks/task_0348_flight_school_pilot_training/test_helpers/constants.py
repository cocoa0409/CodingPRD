"""Domain thresholds — numeric constants the PRD states explicitly.

Only constants whose numeric value appears verbatim in PRD prose live here.
The PRD names INSTRUCTOR_BUFFER_MINUTES and NO_SHOW_SUSPEND_THRESHOLD only
symbolically (no numeric value), so they are deliberately absent — tests cannot
pin behaviour to an undisclosed number.

NON_EXISTENT_UUID comes from the framework barrel.
"""

# Complexity surcharge tiers (PRD §3.7 booking cost estimate).
COMPLEX_TIER1_HOURS = 2.0   # "the complex tier-one threshold of 2.0 hours"
COMPLEX_TIER1_PCT = 0.10    # at most 2.0h -> 10 percent
COMPLEX_TIER2_PCT = 0.15    # exceeds 2.0h -> 15 percent

# Flight charge meter-delta rounding (PRD §2.8 / §3.7).
HOURS_ROUNDING_PLACES = 1   # meter delta rounded half up to one decimal place

# A syntactically valid v4 UUID that no entity ever owns, for not-found probes.
RANDOM_UUID = "00000000-0000-4000-8000-000000000000"

# Convenience default test values reused across factories/fixtures.
TEST_DEFAULTS = {
    "RENTAL_RATE_CENTS_PER_HOUR": 15000,
    "CFI_RATE_CENTS_PER_HOUR": 6000,
    "REQUIRED_DUAL_HOURS": 40,
    "REQUIRED_SOLO_HOURS": 10,
    "STAGE_COUNT": 3,
    "MIN_DEPOSIT_CENTS": 50000,
}
