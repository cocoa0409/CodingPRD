"""Domain thresholds and shared literals from the PRD (§2.4, §3.2–§3.9)."""

# PRD §2.4: every picking container tares at exactly 4 ounces; 16 ounces per pound.
TARE_OZ_PER_CONTAINER = 4
OZ_PER_LB = 16

# PRD §3.3: staffing divides total window slots by 25 per staff member, rounded up.
STAFF_COVERAGE_SLOTS_PER_STAFF = 25

# PRD §3.9: offline sessions may overbook a window by an allowance of 10 extra slots.
OFFLINE_OVERBOOK_ALLOWANCE_SLOTS = 10

# PRD §3.2/§3.8: a picked-out field rests until the closing day's date plus seven days.
FIELD_REST_DAYS = 7

# Shared season window used across the suite (logical clock starts 2026-08-01).
SEASON_NAME = "2026 Harvest"
SEASON_START = "2026-08-01"
SEASON_END = "2026-08-31"
WAIVER_TEXT_V1 = "WAIVER-V1"
WAIVER_TEXT_V2 = "WAIVER-V2"

# Canonical operating days used by the fixtures.
WEEKDAY_DATE = "2026-08-04"
WEEKEND_DATE = "2026-08-08"
MONDAY_DATE = "2026-08-03"

# Baseline pricing policy ("policy A"): 650/person admission, 200/container,
# 12500 bps weekend surge (1.25x), 1000 bps bundle discount (10%), cap 1500.
POLICY_A = {
    "admission_per_person_cents": 650,
    "container_fee_cents": 200,
    "weekend_surge_bps": 12500,
    "bundle_discount_bps": 1000,
    "bundle_cap_cents": 1500,
}

# Alternate policy ("policy B") used for supersede scenarios.
POLICY_B = {
    "admission_per_person_cents": 800,
    "container_fee_cents": 200,
    "weekend_surge_bps": 12500,
    "bundle_discount_bps": 1000,
    "bundle_cap_cents": 1500,
}

# Standard window hours for an operating day.
DEFAULT_OPEN_TIME = "09:00"
DEFAULT_CLOSE_TIME = "17:00"


def round_half_up(numerator: int, denominator: int) -> int:
    """PRD §2.4: a fractional remainder of exactly one half rounds away from zero."""
    return (numerator * 2 + denominator) // (2 * denominator)
