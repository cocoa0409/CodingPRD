"""Domain assertion helpers.

Monetary amounts, ratios and scores are decimal quantities in this API, so the
helpers below compare them numerically after normalising through ``Decimal``.
That keeps a test insensitive to whether the server serialises ``23.19`` as a
JSON number or as the string ``"23.19"`` while still catching a genuinely wrong
value such as ``23.20``.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def to_decimal(value: Any) -> Decimal:
    """Normalise a JSON-carried decimal quantity into a `Decimal`."""
    assert value is not None, "expected a decimal quantity, got None"
    assert isinstance(
        value, (int, float, str, Decimal)
    ), f"expected a decimal quantity, got {type(value).__name__}: {value!r}"
    try:
        return Decimal(str(value))
    except InvalidOperation:  # pragma: no cover - defensive
        raise AssertionError(f"value {value!r} is not a decimal quantity")


def assert_money(actual: Any, expected: str, label: str = "amount") -> None:
    """Assert a monetary field equals `expected`, which is written to 2 decimals."""
    assert to_decimal(actual) == Decimal(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


def assert_decimal_equals(actual: Any, expected: str, label: str = "value") -> None:
    """Assert any decimal-carried field (score, ratio, variance) equals `expected`."""
    assert to_decimal(actual) == Decimal(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


def assert_bps(actual: Any, expected: int, label: str = "basis points") -> None:
    """Assert a basis-point field, which the PRD declares to be an integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: expected an integer, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_is_null(value: Any, label: str = "field") -> None:
    assert value is None, f"{label}: expected null, got {value!r}"


def assert_is_true(value: Any, label: str = "flag") -> None:
    """Assert a boolean field is the boolean `true`, not a truthy stand-in."""
    assert value is True, f"{label}: expected true, got {value!r}"


def assert_is_false(value: Any, label: str = "flag") -> None:
    assert value is False, f"{label}: expected false, got {value!r}"


def assert_common_fields(resource: dict, label: str = "resource") -> None:
    """Assert the four properties every resource in this system exposes (PRD 2.4)."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in resource, f"{label}: missing common property {field!r}"
    assert is_valid_uuid(resource["id"]), (
        f"{label}: id {resource['id']!r} is not a UUID"
    )
    assert is_iso8601_timestamp(resource["created_at"]), (
        f"{label}: created_at {resource['created_at']!r} is not an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(resource["updated_at"]), (
        f"{label}: updated_at {resource['updated_at']!r} is not an ISO 8601 timestamp"
    )
    assert isinstance(resource["version"], int) and not isinstance(
        resource["version"], bool
    ), f"{label}: version must be an integer, got {resource['version']!r}"
    assert resource["version"] >= 1, (
        f"{label}: version must start at 1, got {resource['version']}"
    )


def assert_version_at_least(resource: dict, minimum: int, label: str = "resource") -> None:
    assert resource["version"] >= minimum, (
        f"{label}: expected version >= {minimum}, got {resource['version']}"
    )


def assert_status(resource: dict, field: str, expected: str, label: str = "resource") -> None:
    assert resource.get(field) == expected, (
        f"{label}: expected {field} == {expected}, got {resource.get(field)!r}"
    )


def assert_date_equals(actual: Any, expected: str, label: str = "date") -> None:
    """Assert an ISO date field, tolerating a full timestamp carrying that date."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert str(actual)[:10] == expected, f"{label}: expected {expected}, got {actual!r}"


def assert_pool_conservation(cycle: dict) -> None:
    """`available_undesignated_pool` plus `awarded_total` always equals
    `opening_undesignated_pool` (PRD 3.8)."""
    available = to_decimal(cycle["available_undesignated_pool"])
    awarded = to_decimal(cycle["awarded_total"])
    opening = to_decimal(cycle["opening_undesignated_pool"])
    assert available + awarded == opening, (
        "cycle pool conservation violated: available "
        f"{available} + awarded {awarded} != opening {opening}"
    )


def assert_gross_decomposition(pledge: dict) -> None:
    """`undesignated_amount` is `gross_amount` minus `designated_amount_total`,
    and `net_designated_total` is `designated_amount_total` minus
    `designation_fee_total` (PRD 3.3)."""
    gross = to_decimal(pledge["gross_amount"])
    designated = to_decimal(pledge["designated_amount_total"])
    undesignated = to_decimal(pledge["undesignated_amount"])
    fee_total = to_decimal(pledge["designation_fee_total"])
    net_total = to_decimal(pledge["net_designated_total"])
    assert designated + undesignated == gross, (
        f"pledge decomposition violated: designated {designated} + undesignated "
        f"{undesignated} != gross {gross}"
    )
    assert designated - fee_total == net_total, (
        f"pledge net violated: designated {designated} - fees {fee_total} != net {net_total}"
    )


def find_by(items: list, field: str, value: Any) -> Optional[dict]:
    """Return the first element whose `field` equals `value`, else None."""
    for item in items:
        if item.get(field) == value:
            return item
    return None


def require_by(items: list, field: str, value: Any) -> dict:
    """Return the single element whose `field` equals `value`, asserting presence."""
    found = find_by(items, field, value)
    assert found is not None, f"no element with {field} == {value!r} in {len(items)} items"
    return found
