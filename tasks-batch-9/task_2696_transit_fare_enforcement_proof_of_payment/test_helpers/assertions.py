"""
Domain assertions layered on top of the framework's generic helpers.

The two families that matter most here are the four-decimal-place ratio
comparison (every ratio in this API is carried to exactly four places, rounded
half up) and the citation money identity, which every settlement test has to
hold true before and after the write under examination.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import (
    PAYMENT_SOURCE_DISMISSAL_REVERSAL,
    PAYMENT_SOURCE_DOWN_PAYMENT,
    PAYMENT_SOURCE_DIRECT,
    PAYMENT_SOURCE_PLAN_INSTALLMENT,
    PAYMENT_SOURCE_SERVICE_CREDIT,
    RATE_DECIMAL_PLACES,
    SETTLEMENT_SATISFIED,
    SETTLEMENT_WRITTEN_OFF,
)

_FOUR_PLACES = Decimal(1).scaleb(-RATE_DECIMAL_PLACES)  # Decimal("0.0001")


# ── Instants ─────────────────────────────────────────────────────────
# Timestamps are ISO 8601 UTC instants carried with three fractional digits, so
# the instant a field names is the contract while its textual spelling is not.

def as_instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants by the moment they name."""
    assert as_instant(actual) == as_instant(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


# ── Ratios carried to four decimal places ────────────────────────────

def as_rate(value: Any) -> Decimal:
    """Read a ratio field as an exact decimal, whatever its JSON rendering."""
    assert value is not None, "ratio field is unexpectedly empty"
    assert isinstance(value, (str, int, float)), (
        f"ratio field must be a number or a decimal string, got {value!r}"
    )
    return Decimal(str(value))


def quantize_rate(value: Any) -> Decimal:
    """Round a value half up to exactly four decimal places."""
    return as_rate(value).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def assert_rate_equals(actual: Any, expected: float, label: str = "ratio") -> None:
    """
    Assert a ratio field equals the expected figure at exactly four decimal
    places, and carries no precision beyond those four places.
    """
    actual_decimal = as_rate(actual)
    expected_decimal = Decimal(str(expected)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
    assert actual_decimal == actual_decimal.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP), (
        f"{label} carries more than {RATE_DECIMAL_PLACES} decimal places: {actual!r}"
    )
    assert actual_decimal == expected_decimal, (
        f"{label}: expected {expected_decimal}, got {actual_decimal} (raw {actual!r})"
    )


# ── Identity, timestamps and revision counters ───────────────────────

def assert_identity_fields(record: Dict[str, Any], label: str = "record") -> None:
    """Every persisted record is addressed by a server-minted UUID id."""
    assert is_valid_uuid(record.get("id", "")), (
        f"{label}.id must be a UUID, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC instant, got {record.get('created_at')!r}"
    )


def assert_versioned_record(
    record: Dict[str, Any], expected_version: Optional[int] = None, label: str = "record"
) -> None:
    """A record carrying the full identity set: id, created_at, updated_at, version."""
    assert_identity_fields(record, label)
    assert is_iso8601_timestamp(record.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC instant, got {record.get('updated_at')!r}"
    )
    version = record.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be an integer starting at 1, got {version!r}"
    )
    if expected_version is not None:
        assert version == expected_version, (
            f"{label}.version: expected {expected_version}, got {version}"
        )


def assert_immutable_record(record: Dict[str, Any], label: str = "record") -> None:
    """
    An immutable record carries only id and created_at: both updated_at and
    version are absent from its representation entirely.
    """
    assert_identity_fields(record, label)
    assert "updated_at" not in record, (
        f"{label} is immutable and must not carry updated_at, got {record.get('updated_at')!r}"
    )
    assert "version" not in record, (
        f"{label} is immutable and must not carry version, got {record.get('version')!r}"
    )


# ── The citation money identity ──────────────────────────────────────

def assert_citation_money_identity(citation: Dict[str, Any], label: str = "citation") -> None:
    """
    total_due = assessed_penalty + admin_fee, and outstanding_balance is
    total_due less amount_paid less service_credit floored at zero — except
    that it is unconditionally zero under SATISFIED or WRITTEN_OFF.
    """
    assessed = citation["assessed_penalty_cents"]
    fee = citation["admin_fee_cents"]
    total = citation["total_due_cents"]
    paid = citation["amount_paid_cents"]
    credit = citation["service_credit_cents"]
    outstanding = citation["outstanding_balance_cents"]

    for name, value in (
        ("assessed_penalty_cents", assessed),
        ("admin_fee_cents", fee),
        ("total_due_cents", total),
        ("amount_paid_cents", paid),
        ("service_credit_cents", credit),
        ("outstanding_balance_cents", outstanding),
    ):
        assert isinstance(value, int), f"{label}.{name} must be integer cents, got {value!r}"

    assert total == assessed + fee, (
        f"{label}: total_due {total} != assessed {assessed} + fee {fee}"
    )
    if citation["settlement_status"] in (SETTLEMENT_SATISFIED, SETTLEMENT_WRITTEN_OFF):
        assert outstanding == 0, (
            f"{label}: outstanding_balance must be 0 under "
            f"{citation['settlement_status']}, got {outstanding}"
        )
    else:
        assert outstanding == max(0, total - paid - credit), (
            f"{label}: outstanding_balance {outstanding} != max(0, {total} - {paid} - {credit})"
        )
    assert outstanding >= 0, f"{label}: outstanding_balance may never be negative"


def assert_installment_schedule(plan: Dict[str, Any], label: str = "plan") -> None:
    """
    The base amount is the financed total divided by the installment count
    rounded down, the whole remainder sits in the final installment, and the
    schedule sums to the financed total exactly.
    """
    financed = plan["financed_cents"]
    count = plan["installment_count"]
    base = plan["base_installment_cents"]
    final = plan["final_installment_cents"]

    assert base == financed // count, (
        f"{label}: base_installment {base} != floor({financed} / {count})"
    )
    assert final == base + (financed - base * count), (
        f"{label}: final_installment {final} does not absorb the whole remainder"
    )
    assert base * (count - 1) + final == financed, (
        f"{label}: schedule {base} x {count - 1} + {final} does not sum to {financed}"
    )


# ── Ledger helpers ───────────────────────────────────────────────────

def rows_with_source(rows: Iterable[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    """Every ledger row carrying the given source."""
    return [row for row in rows if row.get("source") == source]


def sole_row_with_source(rows: Iterable[Dict[str, Any]], source: str) -> Dict[str, Any]:
    """The single ledger row carrying the given source; fails if there is not exactly one."""
    matches = rows_with_source(rows, source)
    assert len(matches) == 1, (
        f"expected exactly one {source} ledger row, found {len(matches)}"
    )
    return matches[0]


def ledger_sources(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """The source of every ledger row, in the order returned."""
    return [row.get("source") for row in rows]


def assert_ledger_row(
    row: Dict[str, Any],
    source: str,
    amount_cents: int,
    plan_id: Optional[str] = None,
    hours_credited: int = 0,
    applied_at: Optional[str] = None,
    label: str = "ledger row",
) -> None:
    """A single append-only ledger row, including the fields that are empty on it."""
    assert_immutable_record(row, label)
    assert row["source"] == source, f"{label}.source: expected {source}, got {row['source']!r}"
    assert row["amount_cents"] == amount_cents, (
        f"{label}.amount_cents: expected {amount_cents}, got {row['amount_cents']!r}"
    )
    assert row["amount_cents"] > 0, f"{label}.amount_cents is always strictly positive"
    assert row.get("hours_credited", 0) == hours_credited, (
        f"{label}.hours_credited: expected {hours_credited}, got {row.get('hours_credited')!r}"
    )
    if plan_id is None:
        assert not row.get("plan_id"), (
            f"{label}.plan_id must be empty, got {row.get('plan_id')!r}"
        )
    else:
        assert row.get("plan_id") == plan_id, (
            f"{label}.plan_id: expected {plan_id}, got {row.get('plan_id')!r}"
        )
    if applied_at is not None:
        assert_instant_equals(row.get("applied_at"), applied_at, f"{label}.applied_at")


def cash_paid_from_ledger(rows: Sequence[Dict[str, Any]]) -> int:
    """amount_paid as the ledger defines it: cash sources less dismissal reversals."""
    positive = sum(
        row["amount_cents"]
        for row in rows
        if row.get("source")
        in (PAYMENT_SOURCE_DOWN_PAYMENT, PAYMENT_SOURCE_PLAN_INSTALLMENT, PAYMENT_SOURCE_DIRECT)
    )
    reversed_amount = sum(
        row["amount_cents"]
        for row in rows
        if row.get("source") == PAYMENT_SOURCE_DISMISSAL_REVERSAL
    )
    return positive - reversed_amount


def service_credit_from_ledger(rows: Sequence[Dict[str, Any]]) -> int:
    """service_credit as the ledger defines it: the sum of the service-credit rows."""
    return sum(
        row["amount_cents"]
        for row in rows
        if row.get("source") == PAYMENT_SOURCE_SERVICE_CREDIT
    )


# ── Pagination ───────────────────────────────────────────────────────

def assert_collection(
    response,
    expected_total_count: Optional[int] = None,
    expected_row_count: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
    label: str = "collection",
):
    """Validate a list envelope and pin its page window figures."""
    rows, meta = validate_paginated(response)
    if expected_total_count is not None:
        assert meta["total_count"] == expected_total_count, (
            f"{label}: expected total_count {expected_total_count}, got {meta['total_count']}"
        )
    if expected_row_count is not None:
        assert len(rows) == expected_row_count, (
            f"{label}: expected {expected_row_count} rows on the page, got {len(rows)}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"{label}: expected has_more {expected_has_more}, got {meta['has_more']}"
        )
    return rows, meta


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    """The ids of a collection page, in the order returned."""
    return [row["id"] for row in rows]
