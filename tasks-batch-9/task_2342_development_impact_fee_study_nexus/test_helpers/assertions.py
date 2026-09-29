"""Domain assertions layered on top of the shared assertion helpers."""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# Service demand units and level-of-service ratios are carried to four decimal
# places, so equality on them is checked at that scale.
FOUR_DECIMAL_TOLERANCE = 5e-5


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity carries a server-minted id, both audit stamps and a version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert "-" in entity["id"] and not entity["id"].startswith(
        ("prog_", "cat_", "study_", "comp_")
    ), f"id carries a type prefix: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_created_unmutated(entity: Dict[str, Any]) -> None:
    """A record that has never been mutated is at version 1 with equal stamps."""
    assert entity["version"] == 1, f"expected version 1, got {entity['version']}"
    assert entity["created_at"] == entity["updated_at"], (
        f"created_at {entity['created_at']} != updated_at {entity['updated_at']}"
    )


def assert_four_decimal_equals(actual: Any, expected: float, label: str = "value") -> None:
    """Compare a four-decimal quantity against its expected value."""
    assert actual is not None, f"{label} is null"
    assert abs(float(actual) - expected) < FOUR_DECIMAL_TOLERANCE, (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


def assert_whole_cents(value: Any, label: str = "amount") -> None:
    """No field in this service holds a fractional cent or a stringified amount."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} is not an integer number of cents: {value!r}"
    )


def assert_money_equals(actual: Any, expected: int, label: str = "amount") -> None:
    assert_whole_cents(actual, label)
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_fields_null(entity: Dict[str, Any], *field_names: str) -> None:
    for field_name in field_names:
        assert entity.get(field_name, None) is None, (
            f"expected {field_name} to be null, got {entity.get(field_name)!r}"
        )


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    for field_name, expected_value in expected.items():
        assert entity.get(field_name) == expected_value, (
            f"{field_name}: expected {expected_value!r}, got {entity.get(field_name)!r}"
        )


def assert_version_advanced_by(before: int, after: int, steps: int) -> None:
    """A version increments by one on every mutation, including derived-only ones."""
    assert after == before + steps, (
        f"expected version to advance from {before} by {steps}, got {after}"
    )


def line_for_code(lines: Iterable[Dict[str, Any]], code: str) -> Dict[str, Any]:
    """Pick one assessed line out of the ordered array by facility category code."""
    matches = [line for line in lines if line.get("facility_category_code") == code]
    assert len(matches) == 1, f"expected exactly one {code} line, got {len(matches)}"
    return matches[0]


def assert_line_codes_ascending(lines: List[Dict[str, Any]]) -> None:
    """Assessed lines come back in facility category code ascending order."""
    codes = [line["facility_category_code"] for line in lines]
    assert codes == sorted(codes), f"lines not ordered by code ascending: {codes}"


def assert_assessed_line(
    line: Dict[str, Any],
    *,
    demand_units: Optional[float] = None,
    line_gross_cents: Optional[int] = None,
    line_credit_cents: Optional[int] = None,
    line_admin_cents: Optional[int] = None,
    line_net_cents: Optional[int] = None,
) -> None:
    code = line.get("facility_category_code")
    if demand_units is not None:
        assert_four_decimal_equals(line["demand_units"], demand_units, f"{code} demand_units")
    if line_gross_cents is not None:
        assert_money_equals(line["line_gross_cents"], line_gross_cents, f"{code} line_gross_cents")
    if line_credit_cents is not None:
        assert_money_equals(
            line["line_credit_cents"], line_credit_cents, f"{code} line_credit_cents"
        )
    if line_admin_cents is not None:
        assert_money_equals(line["line_admin_cents"], line_admin_cents, f"{code} line_admin_cents")
    if line_net_cents is not None:
        assert_money_equals(line["line_net_cents"], line_net_cents, f"{code} line_net_cents")


def assert_application_totals(
    application: Dict[str, Any],
    *,
    gross_assessed_cents: Optional[int] = None,
    credit_applied_cents: Optional[int] = None,
    admin_charge_cents: Optional[int] = None,
    net_due_cents: Optional[int] = None,
    paid_cents: Optional[int] = None,
    default_penalty_cents: Optional[int] = None,
) -> None:
    expectations = {
        "gross_assessed_cents": gross_assessed_cents,
        "credit_applied_cents": credit_applied_cents,
        "admin_charge_cents": admin_charge_cents,
        "net_due_cents": net_due_cents,
        "paid_cents": paid_cents,
        "default_penalty_cents": default_penalty_cents,
    }
    for field_name, expected in expectations.items():
        if expected is not None:
            assert_money_equals(application[field_name], expected, field_name)


def assert_net_due_identity(application: Dict[str, Any]) -> None:
    """net_due_cents is gross less credit plus admin plus penalty."""
    expected = (
        application["gross_assessed_cents"]
        - application["credit_applied_cents"]
        + application["admin_charge_cents"]
        + application["default_penalty_cents"]
    )
    assert application["net_due_cents"] == expected, (
        f"net_due_cents {application['net_due_cents']} != {expected}"
    )


def assert_category_fund(
    category: Dict[str, Any],
    *,
    fund_balance_cents: Optional[int] = None,
    refund_due_cents: Optional[int] = None,
    fund_posture: Optional[str] = None,
    committed_demand_units: Optional[float] = None,
    deferred_receivable_cents: Optional[int] = None,
    oldest_unexpended_vintage_at: Optional[str] = None,
) -> None:
    if fund_balance_cents is not None:
        assert_money_equals(category["fund_balance_cents"], fund_balance_cents, "fund_balance_cents")
    if refund_due_cents is not None:
        assert_money_equals(category["refund_due_cents"], refund_due_cents, "refund_due_cents")
    if fund_posture is not None:
        assert category["fund_posture"] == fund_posture, (
            f"fund_posture: expected {fund_posture}, got {category['fund_posture']}"
        )
    if committed_demand_units is not None:
        assert_four_decimal_equals(
            category["committed_demand_units"], committed_demand_units, "committed_demand_units"
        )
    if deferred_receivable_cents is not None:
        assert_money_equals(
            category["deferred_receivable_cents"],
            deferred_receivable_cents,
            "deferred_receivable_cents",
        )
    if oldest_unexpended_vintage_at is not None:
        # oldest_unexpended_vintage_at is the earliest vintage_at instant among the
        # category's eligible COLLECTION rows, so the assertion is on the instant the
        # logical clock stamped, not on its fractional-second rendering.
        assert_timestamp_equals(
            category["oldest_unexpended_vintage_at"],
            oldest_unexpended_vintage_at,
            "oldest_unexpended_vintage_at",
        )


def assert_fund_cash_conserved(
    entries: List[Dict[str, Any]], fund_balance_cents: int
) -> None:
    """fund_balance_cents is collections less expenditures less refunds."""
    collections = sum(e["amount_cents"] for e in entries if e["kind"] == "COLLECTION")
    expenditures = sum(e["amount_cents"] for e in entries if e["kind"] == "EXPENDITURE")
    refunds = sum(e["amount_cents"] for e in entries if e["kind"] == "REFUND")
    expected = collections - expenditures - refunds
    assert fund_balance_cents == expected, (
        f"fund_balance_cents {fund_balance_cents} != {collections} - {expenditures} - {refunds}"
    )


def assert_timestamp_equals(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare a written timestamp against the logical clock instant it reads."""
    assert actual is not None, f"{label} is null"
    assert _normalize_instant(actual) == _normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def _normalize_instant(value: str) -> str:
    text = str(value).strip().replace("Z", "+00:00")
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
        if frac == "000":
            return head
        return f"{head}.{frac}"
    return text


def assert_entries_ordered_by_vintage(entries: List[Dict[str, Any]]) -> None:
    """The fund ledger comes back ordered by vintage then creation."""
    keys = [
        (_normalize_instant(e["vintage_at"]) if e.get("vintage_at") else "", _normalize_instant(e["created_at"]))
        for e in entries
    ]
    assert keys == sorted(keys), f"ledger rows not in vintage then creation order: {keys}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    for field_name in ("limit", "offset", "total_count", "has_more"):
        assert field_name in meta, f"meta is missing {field_name}"
    if limit is not None:
        assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more: expected {has_more}, got {meta['has_more']}"
        )
