"""
Domain assertions.

These wrap the generic format helpers with the rules the PRD states about this
API: the four common properties, the CounterFirm exception to them, the money
identities the PRD declares conserved, and the two-decimal accuracy figures.
"""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

PCT_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict) -> None:
    """Every entity except CounterFirm carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC timestamp: {data.get('updated_at')!r}"
    )
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_counter_firm_fields(data: dict) -> None:
    """CounterFirm is the declared exception: id and created_at only."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "CounterFirm must not carry updated_at"
    assert "version" not in data, "CounterFirm must not carry version"


def assert_field_absent(data: dict, field: str) -> None:
    assert field not in data, f"{field} must not be present, got {data.get(field)!r}"


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def assert_pct(actual, expected: float) -> None:
    """Percentages are carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"Expected percentage {expected}, got {actual}"
    )


def assert_two_decimal_places(value) -> None:
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"Value {value} carries more than two decimal places"
    )


def assert_bps(actual, expected: int) -> None:
    assert actual == expected, f"Expected {expected} bps, got {actual}"


# ---------------------------------------------------------------------------
# Entity-shaped assertions
# ---------------------------------------------------------------------------
def assert_position_snapshot(
    position: dict,
    *,
    on_hand_units=None,
    book_value_cents=None,
    promising_state=None,
    phantom_units=None,
    tag_integrity_hold=None,
    unit_accuracy_pct=None,
    value_accuracy_pct=None,
    negative_correction_count=None,
) -> None:
    if on_hand_units is not None:
        assert position["on_hand_units"] == on_hand_units, (
            f"on_hand_units expected {on_hand_units}, got {position['on_hand_units']}"
        )
    if book_value_cents is not None:
        assert position["book_value_cents"] == book_value_cents, (
            f"book_value_cents expected {book_value_cents}, "
            f"got {position['book_value_cents']}"
        )
    if promising_state is not None:
        assert position["promising_state"] == promising_state, (
            f"promising_state expected {promising_state}, "
            f"got {position['promising_state']}"
        )
    if phantom_units is not None:
        assert position["phantom_units"] == phantom_units
    if tag_integrity_hold is not None:
        assert position["tag_integrity_hold"] is tag_integrity_hold
    if unit_accuracy_pct is not None:
        assert_pct(position["unit_accuracy_pct"], unit_accuracy_pct)
    if value_accuracy_pct is not None:
        assert_pct(position["value_accuracy_pct"], value_accuracy_pct)
    if negative_correction_count is not None:
        assert position["negative_correction_count"] == negative_correction_count


def assert_adjustment_dimensions(
    adjustment: dict, *, approval_state: str, posting_state: str
) -> None:
    """The approval and posting dimensions of one adjustment row are independent."""
    assert adjustment["approval_state"] == approval_state, (
        f"approval_state expected {approval_state}, got {adjustment['approval_state']}"
    )
    assert adjustment["posting_state"] == posting_state, (
        f"posting_state expected {posting_state}, got {adjustment['posting_state']}"
    )


def assert_units_conserved(position: dict, posted_deltas) -> None:
    """on_hand_units == baseline_on_hand_units + sum of posted deltas."""
    expected = position["baseline_on_hand_units"] + sum(posted_deltas)
    assert position["on_hand_units"] == expected, (
        f"on_hand_units {position['on_hand_units']} does not equal "
        f"baseline {position['baseline_on_hand_units']} plus posted deltas "
        f"{list(posted_deltas)}"
    )


def assert_vendor_ledger_identity(vendor: dict) -> None:
    """lifetime_chargeback_gross_cents - credited_cents == chargeback_balance_cents."""
    gross = vendor["lifetime_chargeback_gross_cents"]
    credited = vendor["credited_cents"]
    balance = vendor["chargeback_balance_cents"]
    assert gross - credited == balance, (
        f"Vendor ledger identity broken: {gross} - {credited} != {balance}"
    )
    assert balance >= 0, f"chargeback_balance_cents went negative: {balance}"


def assert_attribution_buckets(
    attribution: dict,
    *,
    theft_cents=None,
    damage_cents=None,
    process_error_cents=None,
    vendor_shortage_cents=None,
    unresolved_cents=None,
) -> None:
    for field, expected in (
        ("theft_cents", theft_cents),
        ("damage_cents", damage_cents),
        ("process_error_cents", process_error_cents),
        ("vendor_shortage_cents", vendor_shortage_cents),
        ("unresolved_cents", unresolved_cents),
    ):
        if expected is not None:
            assert attribution[field] == expected, (
                f"{field} expected {expected}, got {attribution[field]}"
            )


def assert_buckets_sum_to(attribution: dict, total: int) -> None:
    """The five attribution buckets account for the whole amount with zero drift."""
    buckets = (
        attribution["theft_cents"]
        + attribution["damage_cents"]
        + attribution["process_error_cents"]
        + attribution["vendor_shortage_cents"]
        + attribution["unresolved_cents"]
    )
    assert buckets == total, f"Buckets sum to {buckets}, expected {total}"


def assert_store_posture(
    eligibility: dict,
    *,
    total_position_count=None,
    blocked_position_count=None,
    restricted_position_count=None,
    accuracy_index_bps=None,
    fulfillment_status=None,
) -> None:
    for field, expected in (
        ("total_position_count", total_position_count),
        ("blocked_position_count", blocked_position_count),
        ("restricted_position_count", restricted_position_count),
        ("accuracy_index_bps", accuracy_index_bps),
        ("fulfillment_status", fulfillment_status),
    ):
        if expected is not None:
            assert eligibility[field] == expected, (
                f"{field} expected {expected}, got {eligibility[field]}"
            )


def assert_tag_batch_counters_cleared(batch: dict) -> None:
    """A reworked batch starts its next pass from clean verification counters."""
    assert batch["sampled_units"] == 0
    assert batch["readable_units"] == 0
    assert batch["duplicate_epc_count"] == 0
    assert batch["unencoded_units"] == 0
    assert batch["read_rate_bps"] == 0
    assert batch["verification_outcome"] is None


# ---------------------------------------------------------------------------
# Logical-clock instants
# ---------------------------------------------------------------------------
def assert_clock_instant(actual, expected_instant: str) -> None:
    """
    A stamped instant must be the instant the logical clock was holding.

    The document describes UTC timestamps with three fractional digits while
    quoting the clock's own default without them, so both spellings of the same
    instant are accepted; what is asserted is the instant itself.
    """
    assert actual is not None, "Expected a stamped timestamp, got null"
    base = expected_instant[:-1] if expected_instant.endswith("Z") else expected_instant
    accepted = {f"{base}Z", f"{base}.000Z"}
    assert actual in accepted, (
        f"Expected the logical-clock instant {expected_instant}, got {actual!r}"
    )
