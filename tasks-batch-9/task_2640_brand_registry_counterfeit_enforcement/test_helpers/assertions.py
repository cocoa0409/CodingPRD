"""Domain assertion helpers and the pure arithmetic the PRD specifies.

Money is integer cents. Match, deviation and completeness values carry four
decimal places; strike and substantiation values carry two. All rounding is
exact decimal ROUND_HALF_UP.
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMPLETENESS_OPTIONAL_SATURATION,
    COMPLETENESS_WEIGHT_COVERAGE,
    COMPLETENESS_WEIGHT_OPTIONAL,
    CORROBORATION_BONUS,
    FLAG_THRESHOLD,
    MATCH_WEIGHT_IMAGE,
    MATCH_WEIGHT_PRICE_DEVIATION,
    MATCH_WEIGHT_TEXT,
    METRICS_KEYS,
    PRELIMINARY_DISCOUNT,
    REQUIRED_ITEM_TYPES_BY_VIOLATION,
    SELLER_HISTORY_DIVISOR,
    SERVICE_FEE_TIERS,
    STRIKE_DECAY_FACTOR,
    STRIKE_FRESH_MAX_AGE_DAYS,
    STRIKE_POINTS_CAP,
    SUBSTANTIATION_CAP,
    SUBSTANTIATION_WEIGHT_MATCH,
    SUBSTANTIATION_WEIGHT_REGISTRATION,
    SUBSTANTIATION_WEIGHT_SELLER_HISTORY,
    SWEEP_COUNTER_KEYS,
    VIOLATION_IMAGE_COPYRIGHT_THRESHOLD,
    VIOLATION_IMAGE_COUNTERFEIT_THRESHOLD,
    VIOLATION_PRICE_DEVIATION_COPYRIGHT_THRESHOLD,
    VIOLATION_TEXT_TRADEMARK_THRESHOLD,
    VIOLATION_TYPE_COPYRIGHT,
    VIOLATION_TYPE_COUNTERFEIT,
    VIOLATION_TYPE_NONE,
    VIOLATION_TYPE_TRADEMARK,
)

# --------------------------------------------------------------- arithmetic ---


def round_half_up(value, places: int) -> float:
    """Exact decimal ROUND_HALF_UP to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def price_deviation_factor(authorized_msrp_cents: int, price_cents: int) -> float:
    """(msrp - price) / msrp clamped into 0..1 and rounded to four places."""
    raw = (Decimal(authorized_msrp_cents) - Decimal(price_cents)) / Decimal(authorized_msrp_cents)
    clamped = min(Decimal(1), max(Decimal(0), raw))
    return round_half_up(clamped, 4)


def match_score(image_match_score: float, text_match_score: float,
                deviation_factor: float, risk_boost: float = 0.0) -> float:
    """Three weighted factors accumulated at full precision, boosted, rounded once."""
    weighted = (Decimal(str(MATCH_WEIGHT_IMAGE)) * Decimal(str(image_match_score))
                + Decimal(str(MATCH_WEIGHT_TEXT)) * Decimal(str(text_match_score))
                + Decimal(str(MATCH_WEIGHT_PRICE_DEVIATION)) * Decimal(str(deviation_factor)))
    total = min(Decimal("1.0000"), weighted + Decimal(str(risk_boost)))
    return round_half_up(total, 4)


def expected_violation_type(monitor_status_flagged: bool, image_match_score: float,
                            text_match_score: float, deviation_factor: float) -> str:
    """First satisfied branch of the violation ladder wins."""
    if not monitor_status_flagged:
        return VIOLATION_TYPE_NONE
    if image_match_score >= VIOLATION_IMAGE_COUNTERFEIT_THRESHOLD:
        return VIOLATION_TYPE_COUNTERFEIT
    if text_match_score >= VIOLATION_TEXT_TRADEMARK_THRESHOLD:
        return VIOLATION_TYPE_TRADEMARK
    if (image_match_score >= VIOLATION_IMAGE_COPYRIGHT_THRESHOLD
            and deviation_factor >= VIOLATION_PRICE_DEVIATION_COPYRIGHT_THRESHOLD):
        return VIOLATION_TYPE_COPYRIGHT
    return VIOLATION_TYPE_TRADEMARK


def is_flagged(score: float) -> bool:
    return score >= FLAG_THRESHOLD


def seller_history_term(standalone_strike_points: float) -> float:
    """min(1, standalone / 37.65) rounded to four places before weighting."""
    raw = Decimal(str(standalone_strike_points)) / Decimal(str(SELLER_HISTORY_DIVISOR))
    return round_half_up(min(Decimal(1), raw), 4)


def substantiation_base(match: float, registration_strength: float,
                        standalone_strike_points: float) -> Decimal:
    history = Decimal(str(seller_history_term(standalone_strike_points)))
    return (Decimal(SUBSTANTIATION_WEIGHT_MATCH) * Decimal(str(match))
            + Decimal(SUBSTANTIATION_WEIGHT_REGISTRATION) * Decimal(str(registration_strength))
            + Decimal(SUBSTANTIATION_WEIGHT_SELLER_HISTORY) * history)


def preliminary_score(match: float, registration_strength: float,
                      standalone_strike_points: float = 0.0) -> float:
    base = substantiation_base(match, registration_strength, standalone_strike_points)
    return round_half_up(base * Decimal(str(PRELIMINARY_DISCOUNT)), 2)


def full_substantiation_score(match: float, registration_strength: float,
                              standalone_strike_points: float = 0.0,
                              corroborated: bool = False) -> float:
    base = substantiation_base(match, registration_strength, standalone_strike_points)
    if corroborated:
        base = base + Decimal(str(CORROBORATION_BONUS))
    return round_half_up(min(Decimal(str(SUBSTANTIATION_CAP)), base), 2)


def service_fee_rate(subtotal_cents: int) -> float:
    """Inclusive-upper-bound ladder selected from the subtotal alone."""
    for upper, rate in SERVICE_FEE_TIERS:
        if upper is None or subtotal_cents <= upper:
            return rate
    raise AssertionError("fee ladder is total")


def test_buy_pricing(purchase_price_cents: int, shipping_cents: int, lab_fee_cents: int) -> Dict[str, Any]:
    subtotal = purchase_price_cents + shipping_cents + lab_fee_cents
    rate = service_fee_rate(subtotal)
    fee = int(round_half_up(Decimal(str(rate)) * Decimal(subtotal), 0))
    return {
        "subtotal_cents": subtotal,
        "service_fee_rate": rate,
        "service_fee_cents": fee,
        "billable_total_cents": subtotal + fee,
    }


# A domain helper, not a pytest case: the `test_buy_` prefix is the PRD's own
# vocabulary for the test-buy programme, so tell pytest not to collect it.
test_buy_pricing.__test__ = False


def strike_contribution(base_points: float, age_days: int) -> float:
    """A contribution is the full base while fresh and half of it once decayed."""
    value = Decimal(str(base_points))
    if age_days > STRIKE_FRESH_MAX_AGE_DAYS:
        value = value * Decimal(str(STRIKE_DECAY_FACTOR))
    return round_half_up(value, 2)


def strike_total(contributions: List[float]) -> float:
    """Round each contribution to two places before summing, then round the sum."""
    total = sum(Decimal(str(c)) for c in contributions) if contributions else Decimal(0)
    return min(STRIKE_POINTS_CAP, round_half_up(total, 2))


def completeness_score(covered_required: int, required_total: int, optional_count: int) -> float:
    coverage_term = Decimal(covered_required) / Decimal(required_total)
    optional_term = min(Decimal(1), Decimal(optional_count) / Decimal(COMPLETENESS_OPTIONAL_SATURATION))
    raw = (Decimal(str(COMPLETENESS_WEIGHT_COVERAGE)) * coverage_term
           + Decimal(str(COMPLETENESS_WEIGHT_OPTIONAL)) * optional_term)
    return round_half_up(raw, 4)


def required_types_for(claimed_violation_type: str) -> List[str]:
    return list(REQUIRED_ITEM_TYPES_BY_VIOLATION[claimed_violation_type])


def listing_removal_rate(removed_count: int, decided_count: int) -> float:
    if decided_count == 0:
        return 0.0
    return round_half_up(Decimal(removed_count) / Decimal(decided_count), 4)


# ------------------------------------------------------- logical clock walks ---

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_TS_FMT_FRACTIONAL = "%Y-%m-%dT%H:%M:%S.%fZ"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional seconds.

    PRD §2.4 fixes exactly three fractional digits for `created_at` and
    `updated_at`; for every other stamped instant and for client-supplied
    window bounds the PRD states no fractional-digit convention, so both
    renderings must be accepted and compared by value.
    """
    try:
        return datetime.strptime(value, _TS_FMT)
    except ValueError:
        return datetime.strptime(value, _TS_FMT_FRACTIONAL)


def format_instant(value: datetime) -> str:
    return value.strftime(_TS_FMT)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants by value, not by fractional-digit rendering."""
    assert isinstance(actual, str), f"{label} must be an ISO 8601 instant, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected {label} {expected}, got {actual}")


def add_business_days(instant: str, business_days: int) -> str:
    """Walk forward over Monday-to-Friday days only, preserving time of day.

    Day zero never counts and a weekend base is not snapped forward first.
    """
    current = parse_instant(instant)
    remaining = business_days
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return format_instant(current)


def add_days(instant: str, days: int) -> str:
    return format_instant(parse_instant(instant) + timedelta(days=days))


def add_seconds(instant: str, seconds: int) -> str:
    return format_instant(parse_instant(instant) + timedelta(seconds=seconds))


# ------------------------------------------------------------- shape asserts ---


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource family carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id must be a uuid, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at {row.get('created_at')!r}"
    assert is_iso8601_timestamp(row["updated_at"]), f"bad updated_at {row.get('updated_at')!r}"
    assert isinstance(row["version"], int), f"version must be an integer, got {row.get('version')!r}"
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}")


def assert_score_4dp(actual: Any, expected: Any, label: str = "score") -> None:
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}")
    # `expected` may arrive as a Decimal from the exact-arithmetic helpers above.
    expected = float(expected)
    assert abs(float(actual) - expected) < 5e-5, f"Expected {label} {expected:.4f}, got {actual}"


def assert_score_2dp(actual: Any, expected: Any, label: str = "score") -> None:
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}")
    expected = float(expected)
    assert abs(float(actual) - expected) < 5e-3, f"Expected {label} {expected:.2f}, got {actual}"


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}")
    assert actual == expected, f"Expected {label} {expected}, got {actual}"


def assert_listing_screening(listing: Dict[str, Any], image: float, text: float,
                             deviation: float, expected_match: float,
                             expected_monitor: str, expected_violation: str) -> None:
    assert_score_4dp(listing["image_match_score"], image, "image_match_score")
    assert_score_4dp(listing["text_match_score"], text, "text_match_score")
    assert_score_4dp(listing["price_deviation_factor"], deviation, "price_deviation_factor")
    assert_score_4dp(listing["match_score"], expected_match, "match_score")
    assert listing["monitor_status"] == expected_monitor, (
        f"Expected monitor_status {expected_monitor}, got {listing['monitor_status']}")
    assert listing["violation_type"] == expected_violation, (
        f"Expected violation_type {expected_violation}, got {listing['violation_type']}")


def assert_seller_strikes(seller: Dict[str, Any], standalone: float, cluster: float,
                          status: Optional[str] = None) -> None:
    assert_score_2dp(seller["standalone_strike_points"], standalone, "standalone_strike_points")
    assert_score_2dp(seller["cluster_strike_points"], cluster, "cluster_strike_points")
    if status is not None:
        assert seller["status"] == status, (
            f"Expected seller status {status}, got {seller['status']} at "
            f"cluster {seller['cluster_strike_points']}")


def assert_test_buy_pricing(test_buy: Dict[str, Any], purchase_price_cents: int,
                            shipping_cents: int, lab_fee_cents: int) -> None:
    expected = test_buy_pricing(purchase_price_cents, shipping_cents, lab_fee_cents)
    assert_cents(test_buy["subtotal_cents"], expected["subtotal_cents"], "subtotal_cents")
    assert_score_2dp(test_buy["service_fee_rate"], expected["service_fee_rate"], "service_fee_rate")
    assert_cents(test_buy["service_fee_cents"], expected["service_fee_cents"], "service_fee_cents")
    assert_cents(test_buy["billable_total_cents"], expected["billable_total_cents"],
                 "billable_total_cents")


def assert_package_derivations(package: Dict[str, Any], item_count: int,
                              coverage: int, completeness: float) -> None:
    assert package["item_count"] == item_count, (
        f"Expected item_count {item_count}, got {package['item_count']}")
    assert package["required_type_coverage"] == coverage, (
        f"Expected required_type_coverage {coverage}, got {package['required_type_coverage']}")
    assert_score_4dp(package["completeness_score"], completeness, "completeness_score")


def assert_metrics(metrics: Dict[str, Any], **expected) -> None:
    for key in METRICS_KEYS:
        assert key in metrics, f"metrics response is missing {key}"
    for key, value in expected.items():
        if key == "listing_removal_rate":
            assert_score_4dp(metrics[key], value, key)
        else:
            assert metrics[key] == value, f"Expected {key} {value}, got {metrics[key]}"


def assert_sweep_counts(result: Dict[str, Any], **expected) -> None:
    for key in SWEEP_COUNTER_KEYS:
        assert key in result, f"sweep response is missing {key}"
        assert isinstance(result[key], int), f"{key} must be an integer, got {result[key]!r}"
    for key, value in expected.items():
        assert result[key] == value, f"Expected {key} {value}, got {result[key]}"


def assert_all_sweep_counts_zero(result: Dict[str, Any]) -> None:
    for key in SWEEP_COUNTER_KEYS:
        assert result[key] == 0, f"Expected {key} 0 on an idempotent sweep, got {result[key]}"


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A request that changes nothing leaves version and updated_at untouched."""
    assert after["version"] == before["version"], (
        f"Expected version to stay {before['version']}, got {after['version']}")
    assert after["updated_at"] == before["updated_at"], (
        f"Expected updated_at to stay {before['updated_at']}, got {after['updated_at']}")
