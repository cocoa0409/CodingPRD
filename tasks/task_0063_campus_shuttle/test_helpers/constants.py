"""Domain thresholds and constants for the Campus Shuttle Dispatch API.

All numbers are derived from PRD prose (§2 system rules and §3 business
rules). The generic NON_EXISTENT_UUID is re-exported from the framework
via __init__.py.
"""
from __future__ import annotations
import math
from decimal import Decimal, ROUND_HALF_UP


# ===========================================================================
# Distance / duration constants (PRD §2.9, §3.2)
# ===========================================================================
EARTH_RADIUS_KM = 6371.0088
AVG_SPEED_KMH = 25
DWELL_MIN_PER_INTERMEDIATE = 1
PEAK_FACTOR = 1.25  # PEAK_ADJUSTED multiplier for travel-time minutes


# ===========================================================================
# Run-sheet occupation / window buffers (PRD §3.3, §3.4, §3.6)
# ===========================================================================
VEHICLE_OCCUPATION_BUFFER_MIN = 15      # closed-closed buffer (PRD §3.4)
BOARDING_WINDOW_MIN = 30                # +/- 30 min of scheduled_departure
CHECKIN_WINDOW_BEFORE_MIN = 30          # PRD §3.6 lower bound
CHECKIN_WINDOW_AFTER_MIN = 60           # PRD §3.6 upper bound
EMPLOYEE_CANCEL_LEAD_MIN = 15           # PRD §3.6 cancel window


# ===========================================================================
# Vehicle selection (PRD §3.4)
# ===========================================================================
MIN_VEHICLE_SEAT_CAPACITY = 20          # rotation-selector minimum-capacity floor
OVERFLOW_TOLERANCE_PCT = 10             # substitute selector overflow tolerance


# ===========================================================================
# Frequency window constraints (PRD §2.10)
# ===========================================================================
PEAK_FREQUENCY_MIN = 5
PEAK_FREQUENCY_MAX = 60
OFFPEAK_FREQUENCY_MIN = 5
OFFPEAK_FREQUENCY_MAX = 120


# ===========================================================================
# Fare calculation (PRD §3.6)
# ===========================================================================
BASE_FARE_CENTS = 200
FARE_TIER_BREAKS = (
    # (max_segments, additional cents)
    (2, 0),       # 1..2 segments  -> BASE_FARE_CENTS
    (5, 100),     # 3..5 segments  -> BASE_FARE_CENTS + 100
)
FARE_PLUS_FOR_6_OR_MORE = 200           # 6+ segments -> BASE_FARE_CENTS + 200
PEAK_FARE_MULTIPLIER = 1.5


# ===========================================================================
# No-show penalty (PRD §3.6)
# ===========================================================================
NO_SHOW_BASE_POINTS = 10
NO_SHOW_PEAK_BONUS = 5
NO_SHOW_DELAY_MITIGATION = 3            # subtracted if delay >= 30 min
NO_SHOW_REPEAT_FACTOR = 2
NO_SHOW_DELAY_THRESHOLD_MIN = 30
NO_SHOW_LOOKBACK_DAYS = 30


# ===========================================================================
# Delay thresholds (PRD §3.5)
# ===========================================================================
DELAY_NOTIFICATION_THRESHOLD_MIN = 30


# ===========================================================================
# Reservation limits (PRD §3.6)
# ===========================================================================
DAILY_RESERVATION_LIMIT = 3


# ===========================================================================
# Stop / vehicle constraints
# ===========================================================================
STOP_CAPACITY_MIN = 1
STOP_CAPACITY_MAX = 500
VEHICLE_SEAT_MIN = 8
VEHICLE_SEAT_MAX = 80
ROUTE_CODE_MIN_LEN = 3
ROUTE_CODE_MAX_LEN = 12


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ===========================================================================
# Helpers — exact-precision haversine and round-half-up arithmetic
# (PRD §2.9; tests compare implementation output against these helpers)
# ===========================================================================
def round_half_up(value: float, ndigits: int) -> float:
    """Round-half-up to `ndigits` decimal places (PRD §2.9)."""
    q = Decimal(10) ** (-ndigits)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def round_half_up_int(value: float) -> int:
    """Round-half-up to nearest integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km using PRD's Earth radius 6371.0088."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def expected_route_distance_km(stops_in_order: list) -> float:
    """Apply PRD §2.9 / §3.2: per-segment round to 4 dp, then sum, then round to 2 dp."""
    total = 0.0
    for i in range(len(stops_in_order) - 1):
        a = stops_in_order[i]
        b = stops_in_order[i + 1]
        raw = haversine_km(a["latitude"], a["longitude"],
                           b["latitude"], b["longitude"])
        total += round_half_up(raw, 4)
    return round_half_up(total, 2)


def expected_base_duration_minutes(distance_km: float,
                                   intermediate_count: int) -> int:
    """PRD §3.2 BASE variant: ceil((distance/25)*60 + 1*intermediate_count)."""
    minutes = (distance_km / AVG_SPEED_KMH) * 60.0 + DWELL_MIN_PER_INTERMEDIATE * intermediate_count
    return math.ceil(minutes)


def expected_peak_adjusted_duration_minutes(distance_km: float,
                                            intermediate_count: int) -> int:
    """PRD §3.4 PEAK_ADJUSTED variant: travel time multiplied by 1.25; dwell unaffected; ceil."""
    travel = (distance_km / AVG_SPEED_KMH) * 60.0 * PEAK_FACTOR
    dwell = DWELL_MIN_PER_INTERMEDIATE * intermediate_count
    return math.ceil(travel + dwell)


def fare_tier_cents(segment_count: int) -> int:
    """PRD §3.6 tier: 1..2 -> 200, 3..5 -> 300, 6+ -> 400."""
    if segment_count <= 2:
        return BASE_FARE_CENTS
    if segment_count <= 5:
        return BASE_FARE_CENTS + 100
    return BASE_FARE_CENTS + FARE_PLUS_FOR_6_OR_MORE


def expected_fare_cents(segment_count: int, is_peak: bool) -> int:
    """PRD §3.6: tier first, then peak multiplier, then round-half-up to int cents."""
    tier = fare_tier_cents(segment_count)
    raw = tier * PEAK_FARE_MULTIPLIER if is_peak else float(tier)
    return round_half_up_int(raw)


def expected_no_show_points(is_peak: bool, has_delay_mitigation: bool,
                            prior_no_show_count: int) -> int:
    """PRD §3.6 no-show formula. Floors at zero."""
    raw = (
        NO_SHOW_BASE_POINTS
        + (NO_SHOW_PEAK_BONUS if is_peak else 0)
        - (NO_SHOW_DELAY_MITIGATION if has_delay_mitigation else 0)
        + NO_SHOW_REPEAT_FACTOR * prior_no_show_count
    )
    return max(0, raw)


def expected_match_rate(actual: int, expected: int) -> float:
    """PRD §3.7: actual / max(expected, 1), rounded half-up to 4 dp."""
    denom = max(expected, 1)
    return round_half_up(actual / denom, 4)


__all__ = [
    "EARTH_RADIUS_KM",
    "AVG_SPEED_KMH",
    "DWELL_MIN_PER_INTERMEDIATE",
    "PEAK_FACTOR",
    "VEHICLE_OCCUPATION_BUFFER_MIN",
    "BOARDING_WINDOW_MIN",
    "CHECKIN_WINDOW_BEFORE_MIN",
    "CHECKIN_WINDOW_AFTER_MIN",
    "EMPLOYEE_CANCEL_LEAD_MIN",
    "MIN_VEHICLE_SEAT_CAPACITY",
    "OVERFLOW_TOLERANCE_PCT",
    "PEAK_FREQUENCY_MIN",
    "PEAK_FREQUENCY_MAX",
    "OFFPEAK_FREQUENCY_MIN",
    "OFFPEAK_FREQUENCY_MAX",
    "BASE_FARE_CENTS",
    "PEAK_FARE_MULTIPLIER",
    "NO_SHOW_BASE_POINTS",
    "NO_SHOW_PEAK_BONUS",
    "NO_SHOW_DELAY_MITIGATION",
    "NO_SHOW_REPEAT_FACTOR",
    "NO_SHOW_DELAY_THRESHOLD_MIN",
    "NO_SHOW_LOOKBACK_DAYS",
    "DELAY_NOTIFICATION_THRESHOLD_MIN",
    "DAILY_RESERVATION_LIMIT",
    "STOP_CAPACITY_MIN",
    "STOP_CAPACITY_MAX",
    "VEHICLE_SEAT_MIN",
    "VEHICLE_SEAT_MAX",
    "ROUTE_CODE_MIN_LEN",
    "ROUTE_CODE_MAX_LEN",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
    "round_half_up_int",
    "haversine_km",
    "expected_route_distance_km",
    "expected_base_duration_minutes",
    "expected_peak_adjusted_duration_minutes",
    "fare_tier_cents",
    "expected_fare_cents",
    "expected_no_show_points",
    "expected_match_rate",
]
