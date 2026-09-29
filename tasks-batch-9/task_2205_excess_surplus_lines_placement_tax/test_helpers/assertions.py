"""Domain assertions for the Surplus Lines Placement Tax API.

These wrap the repetitive shape checks so that the tests themselves read as
statements about surplus lines rules rather than about dictionaries.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# System-managed properties (PRD 2.5)
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries `id`, `created_at`, `updated_at` and `version`."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO 8601: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO 8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    assert entity["version"] == expected, (
        f"expected version {expected}, got {entity['version']}"
    )


def assert_version_advanced_by(before: Dict[str, Any], after: Dict[str, Any], delta: int) -> None:
    """`version` increments by exactly `delta` across the two observations."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']} + {delta}, got {after['version']}"
    )


def assert_three_fraction_digits(timestamp: str) -> None:
    """Timestamps are ISO 8601 UTC with three fractional digits."""
    assert is_iso8601_timestamp(timestamp), f"not ISO 8601: {timestamp!r}"
    assert "." in timestamp, f"expected three fractional digits in {timestamp!r}"
    fraction = timestamp.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits in {timestamp!r}"


# ---------------------------------------------------------------------------
# Money (PRD 2.6 -- integer counts of cents, never floating point)
# ---------------------------------------------------------------------------
def assert_integer_cents(value: Any, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r}"
    )


def assert_money_equals(actual: Any, expected: int, label: str = "amount") -> None:
    assert_integer_cents(actual, label)
    assert actual == expected, f"{label}: expected {expected} cents, got {actual} cents"


# ---------------------------------------------------------------------------
# Policy state dimensions (PRD 2.8 / 3.5)
# ---------------------------------------------------------------------------
def assert_policy_dimensions(
    policy: Dict[str, Any],
    status: Optional[str] = None,
    compliance_status: Optional[str] = None,
    tax_status: Optional[str] = None,
    stamping_status: Optional[str] = None,
) -> None:
    """Check any subset of the policy's four independent state dimensions."""
    for field, expected in (
        ("status", status),
        ("compliance_status", compliance_status),
        ("tax_status", tax_status),
        ("stamping_status", stamping_status),
    ):
        if expected is not None:
            assert policy[field] == expected, (
                f"policy {field}: expected {expected}, got {policy[field]}"
            )


# ---------------------------------------------------------------------------
# Allocation rows (PRD 3.7)
# ---------------------------------------------------------------------------
def assert_allocation_row(
    row: Dict[str, Any],
    state_code: Optional[str] = None,
    allocated_premium_cents: Optional[int] = None,
    tax_cents: Optional[int] = None,
    stamping_fee_cents: Optional[int] = None,
    allocation_pct: Optional[float] = None,
    premium_tax_rate_applied: Optional[float] = None,
    stamping_fee_rate_applied: Optional[float] = None,
    allocation_basis: Optional[str] = None,
) -> None:
    if state_code is not None:
        assert row["state_code"] == state_code, (
            f"expected allocation row for {state_code}, got {row['state_code']}"
        )
    label = f"allocation[{row.get('state_code')}]"
    if allocated_premium_cents is not None:
        assert_money_equals(
            row["allocated_premium_cents"], allocated_premium_cents,
            f"{label}.allocated_premium_cents",
        )
    if tax_cents is not None:
        assert_money_equals(row["tax_cents"], tax_cents, f"{label}.tax_cents")
    if stamping_fee_cents is not None:
        assert_money_equals(
            row["stamping_fee_cents"], stamping_fee_cents, f"{label}.stamping_fee_cents"
        )
    if allocation_pct is not None:
        assert abs(float(row["allocation_pct"]) - allocation_pct) < 1e-9, (
            f"{label}.allocation_pct: expected {allocation_pct}, got {row['allocation_pct']}"
        )
    if premium_tax_rate_applied is not None:
        assert abs(float(row["premium_tax_rate_applied"]) - premium_tax_rate_applied) < 1e-9, (
            f"{label}.premium_tax_rate_applied: expected {premium_tax_rate_applied}, "
            f"got {row['premium_tax_rate_applied']}"
        )
    if stamping_fee_rate_applied is not None:
        assert abs(float(row["stamping_fee_rate_applied"]) - stamping_fee_rate_applied) < 1e-9, (
            f"{label}.stamping_fee_rate_applied: expected {stamping_fee_rate_applied}, "
            f"got {row['stamping_fee_rate_applied']}"
        )
    if allocation_basis is not None:
        assert row["allocation_basis"] == allocation_basis, (
            f"{label}.allocation_basis: expected {allocation_basis}, "
            f"got {row['allocation_basis']}"
        )


def assert_state_codes_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """Rows are emitted in ascending `state_code` order."""
    codes = [row["state_code"] for row in rows]
    assert codes == sorted(codes), f"expected ascending state_code order, got {codes}"


def assert_parts_sum_to(
    rows: Sequence[Dict[str, Any]], field: str, expected_total: int, label: str = "parts"
) -> None:
    """The apportioned parts sum exactly to the amount being apportioned."""
    total = sum(row[field] for row in rows)
    assert total == expected_total, (
        f"{label}: {[row[field] for row in rows]} sum to {total}, expected {expected_total}"
    )


def by_state(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index rows (allocations or filing lines) by their `state_code`."""
    return {row["state_code"]: row for row in rows}


# ---------------------------------------------------------------------------
# Tax filing lines (PRD 3.7 / 3.8)
# ---------------------------------------------------------------------------
def assert_filing_line(
    line: Dict[str, Any],
    line_type: Optional[str] = None,
    status: Optional[str] = None,
    taxable_premium_cents: Optional[int] = None,
    tax_cents: Optional[int] = None,
    stamping_fee_cents: Optional[int] = None,
    period_key: Optional[str] = None,
    policy_id: Optional[str] = None,
    source_endorsement_id: Optional[str] = None,
    source_cancellation_id: Optional[str] = None,
    filing_batch_id: Optional[str] = None,
) -> None:
    label = f"filing_line[{line.get('id')}]"
    for field, expected in (
        ("line_type", line_type),
        ("status", status),
        ("period_key", period_key),
        ("policy_id", policy_id),
    ):
        if expected is not None:
            assert line[field] == expected, (
                f"{label}.{field}: expected {expected}, got {line[field]}"
            )
    for field, expected in (
        ("taxable_premium_cents", taxable_premium_cents),
        ("tax_cents", tax_cents),
        ("stamping_fee_cents", stamping_fee_cents),
    ):
        if expected is not None:
            assert_money_equals(line[field], expected, f"{label}.{field}")
    if source_endorsement_id is not None:
        assert line["source_endorsement_id"] == source_endorsement_id
    if source_cancellation_id is not None:
        assert line["source_cancellation_id"] == source_cancellation_id
    if filing_batch_id is not None:
        assert line["filing_batch_id"] == filing_batch_id


def assert_ledger_reconciles(lines: Sequence[Dict[str, Any]], total_tax_cents: int) -> None:
    """The signed sum of the ledger's `tax_cents` equals the policy total."""
    total = sum(line["tax_cents"] for line in lines)
    assert total == total_tax_cents, (
        f"ledger sums to {total} but the policy reports total_tax_cents "
        f"{total_tax_cents}"
    )


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    for field, expected in (
        ("limit", limit),
        ("offset", offset),
        ("total_count", total_count),
        ("has_more", has_more),
    ):
        if expected is not None:
            assert meta.get(field) == expected, (
                f"meta.{field}: expected {expected}, got {meta.get(field)}"
            )


def assert_created_at_ascending(items: Sequence[Dict[str, Any]]) -> None:
    """List results are ordered by `created_at` ascending."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"expected created_at ascending, got {stamps}"


# ---------------------------------------------------------------------------
# Reference implementations of the PRD's arithmetic, used to justify the
# pinned expectations in the tests.
# ---------------------------------------------------------------------------
def round_half_up(numerator: int, denominator: int) -> int:
    """Round the exact rational value half up, with ties away from zero."""
    assert denominator > 0
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def largest_remainder(amount: int, weights: List[tuple]) -> Dict[str, int]:
    """Apportion `amount` across `(state_code, weight)` pairs.

    Each state first receives the floor of its exact share; the leftover cents
    are handed out one at a time in descending order of truncated fractional
    part, with ties broken by `state_code` in ascending ASCII order.
    """
    total_weight = sum(w for _, w in weights)
    floors: Dict[str, int] = {}
    remainders = []
    for code, weight in weights:
        numerator = amount * weight
        floors[code] = numerator // total_weight
        remainders.append((numerator % total_weight, code))
    leftover = amount - sum(floors.values())
    remainders.sort(key=lambda pair: (-pair[0], pair[1]))
    for _, code in remainders[:leftover]:
        floors[code] += 1
    return floors
