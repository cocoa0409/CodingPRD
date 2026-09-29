"""Domain assertions and the integer arithmetic the PRD pins.

All money is an integer number of cents and all rates an integer number of basis
points, so every helper here works in exact integers.  ``round_half_up`` is the
single rounding primitive: the exact rational value is rounded to the nearest
integer and a value exactly halfway rounds away from zero.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

BPS_ONE = 10000


# ─── Integer arithmetic ───────────────────────────────

def round_half_up(numerator: int, denominator: int) -> int:
    """Divide two integers, rounding half away from zero to a whole number."""
    assert denominator != 0, "round_half_up: denominator must be non-zero"
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def bps_of(amount_cents: int, rate_bps: int) -> int:
    """`amount_cents * rate_bps / 10000`, rounded half up — the program's rate primitive."""
    return round_half_up(amount_cents * rate_bps, BPS_ONE)


def ratio_bps(part: int, whole: int) -> int:
    """`part * 10000 / whole`, rounded half up; whole must be non-zero."""
    return round_half_up(part * BPS_ONE, whole)


# ─── Envelope and common fields ───────────────────────

def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the id/created_at/updated_at/version quartet every mutable resource carries."""
    assert is_valid_uuid(data.get("id")), f"id is not a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at is not an ISO 8601 UTC instant: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at")), (
        f"updated_at is not an ISO 8601 UTC instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"version must be an integer, got {data.get('version')!r}"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_event_fields_only(data: Dict[str, Any]) -> None:
    """Assert an immutable event record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id")), f"id is not a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at is not an ISO 8601 UTC instant: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "An immutable event must not carry updated_at"
    assert "version" not in data, "An immutable event must not carry version"


def assert_millisecond_timestamp(value: str) -> None:
    """Assert an instant renders with exactly three fractional digits and a `Z`."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC instant: {value!r}"
    assert "." in value, f"Instant must carry fractional digits: {value!r}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"Instant must carry exactly three fractional digits: {value!r}"
    )


def assert_calendar_date(value: str) -> None:
    """Assert a value is a bare `YYYY-MM-DD` calendar date."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"Not a YYYY-MM-DD calendar date: {value!r}"
    )
    year, month, day = value.split("-")
    assert year.isdigit() and month.isdigit() and day.isdigit(), (
        f"Not a YYYY-MM-DD calendar date: {value!r}"
    )


def assert_integer_money(data: Dict[str, Any], *fields: str) -> None:
    """Assert every named `_cents`/`_bps` field is a non-negative integer, never a float."""
    for field in fields:
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer, got {value!r}"
        )
        assert value >= 0, f"{field} must not be negative, got {value}"


# ─── Field-level equality ─────────────────────────────

def assert_fields(data: Dict[str, Any], **expected: Any) -> None:
    """Assert each named field equals its expected value, reporting every mismatch."""
    mismatches = []
    for field, value in expected.items():
        actual = data.get(field, "<missing>")
        if actual != value:
            mismatches.append(f"{field}: expected {value!r}, got {actual!r}")
    assert not mismatches, "Field mismatches: " + "; ".join(mismatches)


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """Assert every named field holds the same value before and after an operation."""
    drifted = []
    for field in fields:
        if before.get(field) != after.get(field):
            drifted.append(f"{field}: {before.get(field)!r} -> {after.get(field)!r}")
    assert not drifted, "Fields moved that must not move: " + "; ".join(drifted)


def assert_empty(data: Dict[str, Any], *fields: str) -> None:
    """Assert every named field is empty: absent, null or the empty string."""
    populated = []
    for field in fields:
        value = data.get(field)
        if value not in (None, "", [], {}):
            populated.append(f"{field}={value!r}")
    assert not populated, "Fields should be empty: " + "; ".join(populated)


# ─── Derived-figure assertions ────────────────────────

def assert_provisional_economics(draw: Dict[str, Any], funded_amount_cents: int,
                                 plan_discount_bps: int, holdback_pct_bps: int) -> None:
    """Assert the write-time provisional view uses only plan and trade rates."""
    expected_discount = bps_of(funded_amount_cents, plan_discount_bps)
    expected_holdback = bps_of(funded_amount_cents, holdback_pct_bps)
    assert_fields(
        draw,
        funded_amount_cents=funded_amount_cents,
        provisional_discount_cents=expected_discount,
        provisional_holdback_cents=expected_holdback,
        provisional_net_settlement_cents=(
            funded_amount_cents - expected_discount - expected_holdback
        ),
    )


def component_wise_discount(funded_amount_cents: int, effective_discount_bps: int,
                            speed_surcharge_bps: int, volume_tier_credit_bps: int) -> int:
    """The pinned three-rounding composition of the final merchant discount."""
    base = bps_of(funded_amount_cents, effective_discount_bps)
    speed = bps_of(funded_amount_cents, speed_surcharge_bps)
    credit = bps_of(funded_amount_cents, volume_tier_credit_bps)
    return max(0, base + speed - credit)


def assert_reserve_coverage(merchant: Dict[str, Any]) -> None:
    """Assert `reserve_coverage_bps` agrees with reserve over target, 10000 when no target."""
    reserve = merchant["holdback_reserve_cents"]
    target = merchant["holdback_target_cents"]
    expected = BPS_ONE if target == 0 else ratio_bps(reserve, target)
    assert merchant["reserve_coverage_bps"] == expected, (
        f"reserve_coverage_bps should be {expected} for reserve {reserve} "
        f"over target {target}, got {merchant['reserve_coverage_bps']}"
    )


def assert_funded_pct(project: Dict[str, Any]) -> None:
    """Assert `funded_pct_bps` is settled funding over the contract, rounded half up."""
    expected = ratio_bps(
        project["settled_funded_cents"], project["contract_amount_cents"]
    )
    assert project["funded_pct_bps"] == expected, (
        f"funded_pct_bps should be {expected}, got {project['funded_pct_bps']}"
    )


def assert_chargeback_conserved(case: Dict[str, Any]) -> None:
    """Assert the three waterfall buckets re-sum to the chargeback amount exactly."""
    total = (
        case["chargeback_absorbed_from_reserve_cents"]
        + case["chargeback_receivable_cents"]
        + case["chargeback_write_off_cents"]
    )
    assert total == case["chargeback_amount_cents"], (
        "Chargeback buckets must re-sum to the claim exactly: "
        f"{case['chargeback_absorbed_from_reserve_cents']} + "
        f"{case['chargeback_receivable_cents']} + "
        f"{case['chargeback_write_off_cents']} = {total}, "
        f"expected {case['chargeback_amount_cents']}"
    )
    for field in (
        "chargeback_absorbed_from_reserve_cents",
        "chargeback_receivable_cents",
        "chargeback_write_off_cents",
    ):
        assert case[field] >= 0, f"{field} must never be negative, got {case[field]}"


def assert_reason_codes(data: Dict[str, Any], *expected: str) -> None:
    """Assert `decision_reason_codes` holds exactly the expected codes in order."""
    actual = data.get("decision_reason_codes")
    assert actual == list(expected), (
        f"Expected decision_reason_codes {list(expected)}, got {actual!r}"
    )


def assert_ordered_by(records: Sequence[Dict[str, Any]], field: str) -> None:
    """Assert a list page is ascending in the named field."""
    values = [record[field] for record in records]
    assert values == sorted(values), f"Records are not ascending in {field}: {values}"


def ids_of(records: Iterable[Dict[str, Any]]) -> List[str]:
    """The `id` of every record in a list page, in page order."""
    return [record["id"] for record in records]
