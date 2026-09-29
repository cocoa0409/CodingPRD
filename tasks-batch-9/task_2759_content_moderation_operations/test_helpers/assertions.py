"""Domain assertions for the Content Moderation Operations API.

Each helper encodes one rule the PRD states, so a failing test reports the
domain rule that broke rather than a bare dictionary comparison.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ACTION_WEIGHT,
    API_REQUEST_ID_PREFIX,
    CONGESTION_MULTIPLIER_HIGH,
    CONGESTION_MULTIPLIER_LOW,
    CONGESTION_MULTIPLIER_MID,
    CONGESTION_LOW_MAX_OPEN,
    CONGESTION_MID_MAX_OPEN,
    MEDIA_EXPOSURE_MULTIPLIER,
    RATE_DECIMAL_PLACES,
    REPEAT_BONUS_CAP_POINTS,
    REPEAT_BONUS_PER_POINT,
    REPEAT_MULTIPLIER_CAP_REMOVALS,
    REPEAT_MULTIPLIER_STEP,
    SEVERITY_POINTS,
    SEVERITY_SLA_DIVISOR,
    STANDING_BANNED_AT,
    STANDING_LIMITED_AT,
    STANDING_SUSPENDED_AT,
    TIER_CONFIDENCE_MULTIPLIER,
)

# ---------------------------------------------------------------------------
# Timestamp handling
# ---------------------------------------------------------------------------

_MILLIS_SUFFIX = ".000Z"


def normalize_instant(value: str) -> str:
    """Render an instant with exactly three fractional-second digits.

    Comparisons between an instant a test computed and an instant the server
    returned must not turn on fractional-digit width, so both sides pass
    through here first.
    """
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"instant {value!r} must end with Z"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Assert two instants denote the same moment, ignoring digit width."""
    assert actual is not None, f"{label} must not be null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label} should be {normalize_instant(expected)}, got {normalize_instant(actual)}"
    )


def assert_millisecond_timestamp(value: Optional[str], label: str = "timestamp") -> None:
    """Assert a timestamp is ISO 8601 UTC with exactly three fractional digits."""
    assert value is not None, f"{label} must not be null"
    assert is_iso8601_timestamp(value), f"{label} {value!r} is not an ISO 8601 UTC instant"
    assert value.endswith("Z"), f"{label} {value!r} must end with Z"
    body = value[:-1]
    assert "." in body, f"{label} {value!r} must carry fractional seconds"
    frac = body.split(".", 1)[1]
    assert len(frac) == 3, (
        f"{label} {value!r} must render exactly three fractional-second digits, got {len(frac)}"
    )


def add_minutes(instant: str, minutes: int) -> str:
    """Advance an instant by whole minutes, returning millisecond precision."""
    from datetime import datetime, timedelta, timezone

    text = normalize_instant(instant)
    moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    moved = moment + timedelta(minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}" + "Z"


def add_hours(instant: str, hours: int) -> str:
    """Advance an instant by whole hours, returning millisecond precision."""
    return add_minutes(instant, hours * 60)


# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------


def assert_request_id(meta: Dict[str, Any]) -> None:
    """Assert the envelope carries a request identifier of the documented shape."""
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id, "meta.api_request_id must be a non-empty string"
    assert request_id.startswith(API_REQUEST_ID_PREFIX), (
        f"meta.api_request_id should be prefixed {API_REQUEST_ID_PREFIX!r}, got {request_id!r}"
    )


def assert_bare_uuid(value: Optional[str], label: str = "id") -> None:
    """Assert an identifier is a bare UUID with no type prefix."""
    assert value is not None, f"{label} must not be null"
    assert is_valid_uuid(value), f"{label} {value!r} must be a bare UUID with no prefix"


def assert_versioned_resource(resource: Dict[str, Any], label: str = "resource") -> None:
    """Assert the four system-managed fields carried by ten of the resources."""
    assert_bare_uuid(resource.get("id"), f"{label}.id")
    assert_millisecond_timestamp(resource.get("created_at"), f"{label}.created_at")
    assert_millisecond_timestamp(resource.get("updated_at"), f"{label}.updated_at")
    version = resource.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version starts at 1, got {version}"


def assert_immutable_signal_shape(signal: Dict[str, Any]) -> None:
    """A detection signal carries id and created_at only, with no version fields."""
    assert_bare_uuid(signal.get("id"), "detection signal id")
    assert_millisecond_timestamp(signal.get("created_at"), "detection signal created_at")
    assert "updated_at" not in signal, (
        "a detection signal has no updated_at field, but the response carried one"
    )
    assert "version" not in signal, (
        "a detection signal has no version field, but the response carried one"
    )


def assert_fields_present(resource: Dict[str, Any], field_names: Iterable[str], label: str = "resource") -> None:
    """Assert every named field is present, counting an explicit null as present."""
    missing = [name for name in field_names if name not in resource]
    assert not missing, f"{label} is missing declared fields: {missing}"


def assert_nullable_fields_are_null(resource: Dict[str, Any], field_names: Iterable[str], label: str = "resource") -> None:
    """Assert each named field is present in the body carrying a JSON null."""
    for name in field_names:
        assert name in resource, f"{label}.{name} must be present in the body even while null"
        assert resource[name] is None, f"{label}.{name} should be null, got {resource[name]!r}"


# ---------------------------------------------------------------------------
# Rates and integer conversions
# ---------------------------------------------------------------------------


def assert_rate_precision(value: Optional[float], label: str = "rate") -> None:
    """Assert a decimal fraction sits in range and carries at most four places."""
    assert value is not None, f"{label} must not be null"
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert 0.0 <= float(value) <= 1.0, f"{label} must lie between 0.0000 and 1.0000, got {value}"
    quantized = Decimal(str(value)).normalize()
    exponent = -quantized.as_tuple().exponent
    assert exponent <= RATE_DECIMAL_PLACES, (
        f"{label} carries more than four decimal places: {value}"
    )


def round_half_up_4(value: float) -> float:
    """Round to four decimal places, half away from zero."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def assert_rate_equals(actual: Optional[float], expected: float, label: str = "rate") -> None:
    """Assert a four-decimal rate matches the expected value exactly."""
    assert actual is not None, f"{label} must not be null"
    assert round_half_up_4(float(actual)) == round_half_up_4(expected), (
        f"{label} should be {round_half_up_4(expected):.4f}, got {actual}"
    )


def ceil_once(value: float) -> int:
    """Take the ceiling of a single already-completed product or quotient."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Derived quantities the PRD specifies as formulas
# ---------------------------------------------------------------------------


def expected_effective_confidence(
    classifier_confidence: float,
    account_tier: str,
    account_strike_points: int,
) -> float:
    """Dampen by tier, add the repeat bonus, clamp, then round once."""
    dampened = Decimal(str(classifier_confidence)) * Decimal(str(TIER_CONFIDENCE_MULTIPLIER[account_tier]))
    counted_points = min(account_strike_points, REPEAT_BONUS_CAP_POINTS)
    boosted = dampened + Decimal(str(REPEAT_BONUS_PER_POINT)) * counted_points
    clamped = min(boosted, Decimal("1.0"))
    return float(clamped.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def expected_strike_points(
    severity_tier: str,
    outcome: str,
    prior_removed_count: int,
) -> int:
    """Base points times outcome weight times repeat multiplier, ceiled once."""
    base = Decimal(SEVERITY_POINTS[severity_tier])
    weight = Decimal(str(ACTION_WEIGHT[outcome]))
    removals = min(prior_removed_count, REPEAT_MULTIPLIER_CAP_REMOVALS)
    multiplier = Decimal("1") + Decimal(str(REPEAT_MULTIPLIER_STEP)) * removals
    product = base * weight * multiplier
    return int(product.quantize(Decimal("1"), rounding=ROUND_CEILING))


def congestion_multiplier(open_case_count: int) -> float:
    """Convert a queue's post-increment depth into its congestion multiplier."""
    if open_case_count <= CONGESTION_LOW_MAX_OPEN:
        return CONGESTION_MULTIPLIER_LOW
    if open_case_count <= CONGESTION_MID_MAX_OPEN:
        return CONGESTION_MULTIPLIER_MID
    return CONGESTION_MULTIPLIER_HIGH


def expected_sla_minutes(review_sla_minutes: int, open_case_count: int, severity_tier: str) -> int:
    """Base allowance times congestion, divided by the severity divisor, ceiled once."""
    numerator = Decimal(str(review_sla_minutes)) * Decimal(str(congestion_multiplier(open_case_count)))
    quotient = numerator / Decimal(SEVERITY_SLA_DIVISOR[severity_tier])
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_CEILING))


def expected_exposure_charge(graphic_weight: int, media_kind: str) -> int:
    """Graphic weight times the media multiplier."""
    return graphic_weight * MEDIA_EXPOSURE_MULTIPLIER[media_kind]


def expected_standing(strike_points: int) -> str:
    """Recompute the posture from the ledger by the inclusive breakpoints."""
    if strike_points >= STANDING_BANNED_AT:
        return "BANNED"
    if strike_points >= STANDING_SUSPENDED_AT:
        return "SUSPENDED"
    if strike_points >= STANDING_LIMITED_AT:
        return "LIMITED"
    return "GOOD_STANDING"


# ---------------------------------------------------------------------------
# Field-level convenience assertions
# ---------------------------------------------------------------------------


def assert_field(resource: Dict[str, Any], field: str, expected: Any, label: str = "resource") -> None:
    """Assert one field equals the expected value, naming the field on failure."""
    assert field in resource, f"{label}.{field} is missing from the response"
    assert resource[field] == expected, (
        f"{label}.{field} should be {expected!r}, got {resource[field]!r}"
    )


def assert_fields(resource: Dict[str, Any], expected: Dict[str, Any], label: str = "resource") -> None:
    """Assert a whole set of fields at once."""
    for field, value in expected.items():
        assert_field(resource, field, value, label)


def assert_version_bumped_by(new_version: int, old_version: int, steps: int, label: str = "resource") -> None:
    """Assert a record's counter advanced by exactly the expected number of steps."""
    assert new_version == old_version + steps, (
        f"{label}.version should have advanced from {old_version} by {steps} to "
        f"{old_version + steps}, got {new_version}"
    )


def assert_version_unchanged(new_version: int, old_version: int, label: str = "resource") -> None:
    """Assert a rejected operation left the record's counter alone."""
    assert new_version == old_version, (
        f"{label}.version should still be {old_version} after a rejected request, got {new_version}"
    )


def assert_ordered_by_created_at_ascending(rows: List[Dict[str, Any]], label: str = "collection") -> None:
    """Assert a collection is ordered oldest first."""
    stamps = [normalize_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"{label} must be ordered by created_at ascending, got {stamps}"


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str], label: str = "collection") -> None:
    """Assert the collection holds exactly these ids in exactly this order."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"{label} should hold {expected_ids} in order, got {actual}"


def assert_codes_in_order(rows: List[Dict[str, Any]], key: str, expected: List[Any], label: str = "collection") -> None:
    """Assert a projected column matches an expected ordered list."""
    actual = [row.get(key) for row in rows]
    assert actual == expected, f"{label}.{key} should read {expected} in order, got {actual}"
