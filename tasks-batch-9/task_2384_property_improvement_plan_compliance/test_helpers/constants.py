"""Business constants stated by the specification, plus small pure-Python mirrors
of the pinned arithmetic so tests can express an expected integer in the same terms
the contract uses.

Nothing here re-implements a business rule the tests are meant to be checking; the
helpers exist only to keep literal expectations readable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

# ---------------------------------------------------------------------------
# The logical compliance clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Deadlines, escalation, contingency
# ---------------------------------------------------------------------------

DEADLINE_OFFSET_DAYS = {
    "LIFE_SAFETY": 90,
    "GUEST_FACING": 270,
    "BACK_OF_HOUSE": 450,
}

ESCALATION_FACTOR = {
    "LIFE_SAFETY": Decimal("1.00"),
    "GUEST_FACING": Decimal("1.075"),
    "BACK_OF_HOUSE": Decimal("1.035"),
}

DEFAULT_CONTINGENCY_PCT = Decimal("0.10")
MAX_CONTINGENCY_PCT = Decimal("0.50")

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

EXTENSION_CATEGORY_MAX_DAYS = {
    "LIFE_SAFETY": 30,
    "GUEST_FACING": 120,
    "BACK_OF_HOUSE": 180,
}

EXTENSION_MAX_ROUNDS = 3
PRESSURE_HORIZON_DAYS = 60
PRESSURE_CLAMP_THRESHOLD = Decimal("0.60")
PRESSURE_CLAMP_MULTIPLIER = Decimal("0.5")
MIN_JUSTIFICATION_CHARS = 40

# ---------------------------------------------------------------------------
# Phases, keys out of service and displacement
# ---------------------------------------------------------------------------

MAX_OOO_PCT = Decimal("0.25")
PHASE_CHANGEOVER_BUFFER_DAYS = 2

RECAPTURE_LOW = Decimal("0.30")  # ratio below 0.10
RECAPTURE_MID = Decimal("0.15")  # ratio at least 0.10 and below 0.25
RECAPTURE_HIGH = Decimal("0")  # ratio 0.25 or above

# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

RISK_SCORE_START = 100
OVERDUE_LIFE_SAFETY_PENALTY = 25
OVERDUE_LIFE_SAFETY_PENALTY_CAP = 50
OVERDUE_GUEST_FACING_PENALTY = 8
OVERDUE_BACK_OF_HOUSE_PENALTY = 3
OPEN_MAJOR_DEFECT_PENALTY = 5
OPEN_CRITICAL_DEFECT_PENALTY = 12
OPEN_MINOR_DEFECT_PENALTY = 0
FUNDING_GAP_PENALTY_SMALL = 10  # gap ratio greater than 0 and no more than 0.10
FUNDING_GAP_PENALTY_LARGE = 25  # gap ratio strictly greater than 0.10
PROJECTION_HORIZON_DAYS = 30
AT_RISK_SCORE_THRESHOLD = 80  # a score of exactly 80 is COMPLIANT

# ---------------------------------------------------------------------------
# Default notices
# ---------------------------------------------------------------------------

MIN_CURE_PERIOD_DAYS = 1
MAX_CURE_PERIOD_DAYS = 60
LIFE_SAFETY_MAX_CURE_PERIOD_DAYS = 10
PUNCH_CURE_WINDOW_DAYS = 14

LIQUIDATED_DAMAGES_RATE = {
    "LIFE_SAFETY": Decimal("0.15"),
    "GUEST_FACING": Decimal("0.08"),
    "BACK_OF_HOUSE": Decimal("0.03"),
}

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ---------------------------------------------------------------------------
# Small arithmetic helpers
# ---------------------------------------------------------------------------


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    """Round ``value`` half up to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value: Decimal) -> int:
    """Round an exact money expression half up to whole cents."""
    return int(round_half_up(Decimal(value), 0))


def item_funding_cents(approved_cost_cents: int, category: str, contingency: Decimal) -> int:
    """The per-item escalated, contingency-loaded figure, rounded to whole cents."""
    exact = (
        Decimal(approved_cost_cents)
        * (Decimal(1) + Decimal(contingency))
        * ESCALATION_FACTOR[category]
    )
    return round_cents(exact)


def funding_requirement_cents(items: Iterable[tuple], contingency: Decimal) -> int:
    """Round each ``(approved_cost_cents, category)`` pair first, then sum."""
    return sum(item_funding_cents(cost, category, contingency) for cost, category in items)


def liquidated_damages_cents(items: Iterable[tuple]) -> int:
    """Sum the exact per-item products of ``(approved_cost_cents, category)`` and round once."""
    exact = sum(
        (Decimal(cost) * LIQUIDATED_DAMAGES_RATE[category] for cost, category in items),
        Decimal(0),
    )
    return round_cents(exact)


def recapture_fraction(ooo_ratio: Decimal) -> Decimal:
    """Compression-recapture fraction for a phase's own out-of-service ratio."""
    ratio = Decimal(ooo_ratio)
    if ratio < Decimal("0.10"):
        return RECAPTURE_LOW
    if ratio < MAX_OOO_PCT:
        return RECAPTURE_MID
    return RECAPTURE_HIGH


def displacement_revenue_impact_cents(
    rooms_out_of_service: int,
    nights: int,
    room_count: int,
    adr_baseline_cents: int,
    occupancy_baseline_pct: str,
) -> int:
    """Round the gross figure first, then apply the recapture and round again."""
    displaced_room_nights = Decimal(rooms_out_of_service) * Decimal(nights)
    gross = round_cents(
        displaced_room_nights * Decimal(adr_baseline_cents) * Decimal(occupancy_baseline_pct)
    )
    ratio = Decimal(rooms_out_of_service) / Decimal(room_count)
    return round_cents(Decimal(gross) * (Decimal(1) - recapture_fraction(ratio)))


def add_days(iso_date: str, days: int) -> str:
    """Whole-calendar-day arithmetic on a UTC date string."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def clock_date(iso_instant: str) -> str:
    """The calendar date in UTC of a logical-clock instant."""
    return datetime.fromisoformat(iso_instant.replace("Z", "+00:00")).date().isoformat()


def nights_inclusive(start_date: str, end_date: str) -> int:
    """Closed-interval night count: the difference between the dates plus one."""
    return (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1


__all__ = [
    "DEFAULT_CLOCK_UTC",
    "DEFAULT_CLOCK_DATE",
    "DEADLINE_OFFSET_DAYS",
    "ESCALATION_FACTOR",
    "DEFAULT_CONTINGENCY_PCT",
    "MAX_CONTINGENCY_PCT",
    "EXTENSION_CATEGORY_MAX_DAYS",
    "EXTENSION_MAX_ROUNDS",
    "PRESSURE_HORIZON_DAYS",
    "PRESSURE_CLAMP_THRESHOLD",
    "PRESSURE_CLAMP_MULTIPLIER",
    "MIN_JUSTIFICATION_CHARS",
    "MAX_OOO_PCT",
    "PHASE_CHANGEOVER_BUFFER_DAYS",
    "RECAPTURE_LOW",
    "RECAPTURE_MID",
    "RECAPTURE_HIGH",
    "RISK_SCORE_START",
    "OVERDUE_LIFE_SAFETY_PENALTY",
    "OVERDUE_LIFE_SAFETY_PENALTY_CAP",
    "OVERDUE_GUEST_FACING_PENALTY",
    "OVERDUE_BACK_OF_HOUSE_PENALTY",
    "OPEN_MAJOR_DEFECT_PENALTY",
    "OPEN_CRITICAL_DEFECT_PENALTY",
    "OPEN_MINOR_DEFECT_PENALTY",
    "FUNDING_GAP_PENALTY_SMALL",
    "FUNDING_GAP_PENALTY_LARGE",
    "PROJECTION_HORIZON_DAYS",
    "AT_RISK_SCORE_THRESHOLD",
    "MIN_CURE_PERIOD_DAYS",
    "MAX_CURE_PERIOD_DAYS",
    "LIFE_SAFETY_MAX_CURE_PERIOD_DAYS",
    "PUNCH_CURE_WINDOW_DAYS",
    "LIQUIDATED_DAMAGES_RATE",
    "DEFAULT_PAGE_LIMIT",
    "MIN_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "round_half_up",
    "round_cents",
    "item_funding_cents",
    "funding_requirement_cents",
    "liquidated_damages_cents",
    "recapture_fraction",
    "displacement_revenue_impact_cents",
    "add_days",
    "clock_date",
    "nights_inclusive",
]
