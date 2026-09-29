"""Domain assertion helpers.

The generic envelope checks live in the framework; what follows are the
entity-shaped assertions this specification keeps asking for — the common-field
quartet, the append-only evidence shape, the counter partition on a program, and
the pinned money arithmetic.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_FEE_PCT_HIGH,
    ADMIN_FEE_PCT_LOW,
    ADMIN_FEE_PCT_MID,
    ADMIN_FEE_TIER_HIGH_FLOOR,
    ADMIN_FEE_TIER_MID_FLOOR,
    CONTINUATION_COMPONENTS,
    CONTINUATION_LOAD_FACTOR,
)
from .types import Json

# --------------------------------------------------------------------- primitives
def assert_uuid(value: Any) -> None:
    """A server-minted identifier is a bare UUID string with no type prefix."""
    assert isinstance(value, str) and is_valid_uuid(value), value


def assert_timestamp(value: Any) -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), value


def assert_instant_equals(value: Any, expected_instant: str) -> None:
    """Compare a stamped instant to an expected UTC instant, format-tolerantly."""
    assert isinstance(value, str), value
    actual = datetime.fromisoformat(value.replace("Z", "+00:00"))
    expected = datetime.fromisoformat(expected_instant.replace("Z", "+00:00"))
    assert actual == expected, (value, expected_instant)


def assert_money(value: Any) -> None:
    """A money field holds whole integer cents, never a fractional value."""
    assert isinstance(value, int) and not isinstance(value, bool), value


def assert_pct(actual: Any, expected: float) -> None:
    """A two-decimal proportion such as 0.05 for five percent."""
    assert float(actual) == float(expected), (actual, expected)


def round_half_up(value: Decimal) -> int:
    """Round a computed cent amount half up, away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------- common fields
def assert_mutable_common_fields(row: Json) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert_uuid(row["id"])
    assert_timestamp(row["created_at"])
    assert_timestamp(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1, row.get("version")


def assert_evidence_common_fields(row: Json) -> None:
    """An append-only evidence row carries only id and created_at."""
    assert_uuid(row["id"])
    assert_timestamp(row["created_at"])
    assert "updated_at" not in row, row
    assert "version" not in row, row


# ---------------------------------------------------------------- field compare
def assert_fields(row: Json, **expected: Any) -> None:
    """Every named field on ``row`` equals the expected value."""
    for field, value in expected.items():
        assert field in row, f"missing field {field!r} on {sorted(row)}"
        assert row[field] == value, (field, row[field], value)


assert_program = assert_fields
assert_case = assert_fields
assert_dependent = assert_fields
assert_submission = assert_fields
assert_notice = assert_fields
assert_recovery = assert_fields
assert_appeal = assert_fields


# ------------------------------------------------------------ program invariants
PARTITION_COUNTERS = (
    "pending_dependent_count",
    "verified_dependent_count",
    "amnesty_removed_count",
    "termination_pending_count",
    "terminated_dependent_count",
)


def assert_counter_partition(program: Json) -> None:
    """The five coverage-status counters partition the in-scope population."""
    parts = {name: program[name] for name in PARTITION_COUNTERS}
    assert program["in_scope_dependent_count"] == sum(parts.values()), (
        program["in_scope_dependent_count"],
        parts,
    )


def assert_program_ledgers_are_money(program: Json) -> None:
    for field in (
        "provisional_annual_savings_cents",
        "audited_annual_savings_cents",
        "recovery_ledger_cents",
        "recovered_total_cents",
        "refund_due_total_cents",
    ):
        assert_money(program[field])


def assert_program_starts_at_zero(program: Json) -> None:
    """A freshly created program has every counter and every ledger at zero."""
    for field in (
        "in_scope_case_count",
        "in_scope_dependent_count",
        "pending_dependent_count",
        "verified_dependent_count",
        "amnesty_removed_count",
        "termination_pending_count",
        "terminated_dependent_count",
        "responded_case_count",
        "non_responsive_case_count",
        "provisional_annual_savings_cents",
        "audited_annual_savings_cents",
        "recovery_ledger_cents",
        "recovered_total_cents",
        "refund_due_total_cents",
    ):
        assert program[field] == 0, (field, program[field])


# ------------------------------------------------------------------- pagination
def assert_page_meta(
    meta: Json, *, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, meta
    assert meta["offset"] == offset, meta
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta


def assert_no_pagination_fields(body: Json) -> None:
    """A single-resource response omits all four pagination fields."""
    meta = body["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (field, meta)


def assert_ordered_by_created_at(rows: Sequence[Json]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), stamps


def ids_of(rows: Iterable[Json]) -> List[str]:
    return [row["id"] for row in rows]


# ---------------------------------------------------------- pinned money formulas
def expected_continuation_premium(relationship_type: str) -> int:
    """Load each component individually, round each half up, then add."""
    components = CONTINUATION_COMPONENTS[relationship_type]
    factor = Decimal(str(CONTINUATION_LOAD_FACTOR))
    return sum(
        round_half_up(Decimal(components[name]) * factor)
        for name in ("medical", "dental", "vision")
    )


def naive_continuation_premium(relationship_type: str) -> int:
    """The forbidden alternative: add the raw components, load once, round once."""
    components = CONTINUATION_COMPONENTS[relationship_type]
    raw = sum(components[name] for name in ("medical", "dental", "vision"))
    return round_half_up(Decimal(raw) * Decimal(str(CONTINUATION_LOAD_FACTOR)))


def expected_admin_fee_pct(subtotal_cents: int) -> float:
    """The fee rate is selected from the subtotal, never a fee-inclusive figure."""
    if subtotal_cents >= ADMIN_FEE_TIER_HIGH_FLOOR:
        return ADMIN_FEE_PCT_HIGH
    if subtotal_cents >= ADMIN_FEE_TIER_MID_FLOOR:
        return ADMIN_FEE_PCT_MID
    return ADMIN_FEE_PCT_LOW


def expected_admin_fee_cents(subtotal_cents: int) -> int:
    """One rounding step, applied before any waiver credit is considered."""
    pct = Decimal(str(expected_admin_fee_pct(subtotal_cents)))
    return round_half_up(Decimal(subtotal_cents) * pct)


def expected_net_demand_cents(subtotal_cents: int, waiver_credit_cents: int = 0) -> int:
    return (
        subtotal_cents + expected_admin_fee_cents(subtotal_cents) - waiver_credit_cents
    )


def assert_demand_pricing(
    recovery: Json, *, subtotal_cents: int, waiver_credit_cents: int = 0
) -> None:
    """The whole pinned demand arithmetic in one assertion."""
    assert_fields(
        recovery,
        recoverable_subtotal_cents=subtotal_cents,
        admin_fee_cents=expected_admin_fee_cents(subtotal_cents),
        waiver_credit_cents=waiver_credit_cents,
        net_demand_cents=expected_net_demand_cents(subtotal_cents, waiver_credit_cents),
    )
    assert_pct(recovery["admin_fee_pct"], expected_admin_fee_pct(subtotal_cents))


def assert_priority_score(
    case: Json,
    *,
    unverified: int,
    in_scope: int,
    sensitive: bool,
    reminders: int,
    max_reminders: int,
    silent: bool,
) -> None:
    """Recompute the weighted triage blend and compare it to the stored score."""
    unverified_ratio = Decimal(unverified) / Decimal(in_scope if in_scope else 1)
    reminder_ratio = Decimal(reminders) / Decimal(max_reminders if max_reminders else 1)
    raw = (
        Decimal(40) * unverified_ratio
        + Decimal(25 if sensitive else 0)
        + Decimal(20) * reminder_ratio
        + Decimal(15 if silent else 0)
    )
    expected = min(100, round_half_up(raw))
    assert case["priority_score"] == expected, (case["priority_score"], expected)


def counters(program: Json, *names: str) -> Dict[str, Any]:
    """A named subset of a program's counters, for readable diffs."""
    return {name: program[name] for name in names}
