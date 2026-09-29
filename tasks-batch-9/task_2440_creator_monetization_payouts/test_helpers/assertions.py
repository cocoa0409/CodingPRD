"""Domain assertions shared by the test suite."""

import math
import re

from prd_bench_local_runner.testing import validate_paginated, validate_success

from .constants import (
    FEE_CAP_CENTS,
    FLAT_FEE_CENTS,
    PCT_FEE_BPS,
    VOLUME_TIERS,
)

_MS_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ------------------------------------------------------------- envelope ------
def assert_object_envelope(response, expected_status=200):
    """Validate an object response and additionally pin response_type."""
    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object', got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert meta["api_request_id"].strip(), "meta.api_request_id must be non-blank"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_ms_timestamp(meta["api_request_timestamp"])
    return validate_success(response, expected_status)


def assert_array_envelope(response):
    body = response.json()
    assert body["response_type"] == "array", (
        f"Expected response_type 'array', got {body['response_type']!r}"
    )
    return validate_paginated(response)


def assert_ms_timestamp(value):
    """Timestamps are rendered in UTC with exactly three fractional digits."""
    assert isinstance(value, str) and _MS_TIMESTAMP.match(value), (
        f"Expected an ISO-8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def assert_instant(value, iso_seconds):
    """Compare a rendered timestamp against a second-precision instant."""
    assert_ms_timestamp(value)
    expected = iso_seconds.replace("Z", ".000Z")
    assert value == expected, f"Expected {expected}, got {value}"


def total_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def assert_total_count(response, expected):
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}: {rows}"
    )
    return rows


def rows_of(response):
    rows, _ = validate_paginated(response)
    return rows


# --------------------------------------------------------------- money -------
def assert_cents(value):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"Monetary amounts are signed integer cents, got {value!r}"
    )


def assert_bps(value):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"Rates are integer basis points, got {value!r}"
    )


# -------------------------------------------------------------- ledger ------
def assert_append_only_shape(entry):
    """A ledger row carries a creation stamp only: it is never updated."""
    assert "id" in entry and "created_at" in entry
    assert "updated_at" not in entry, "A ledger row must not expose updated_at"
    assert "version" not in entry, "A ledger row must not expose version"


def assert_ledger_sequence(rows, expected):
    """Compare (entry_type, amount_cents) pairs positionally."""
    actual = [(r["entry_type"], r["amount_cents"]) for r in rows]
    assert actual == list(expected), f"Expected ledger sequence {expected}, got {actual}"


def assert_running_balance(rows):
    """balance_after_cents must be the running total of amount_cents."""
    running = 0
    for row in rows:
        running += row["amount_cents"]
        assert row["balance_after_cents"] == running, (
            f"Row {row['entry_type']} has balance_after_cents "
            f"{row['balance_after_cents']}, expected running total {running}"
        )
    return running


def assert_no_entry_of_type(rows, entry_type):
    offenders = [r for r in rows if r["entry_type"] == entry_type]
    assert not offenders, f"Expected no {entry_type} row, found {offenders}"


def assert_no_zero_amount_entries(rows):
    offenders = [r for r in rows if r["amount_cents"] == 0]
    assert not offenders, f"A zero-amount ledger row must never be written: {offenders}"


# ------------------------------------------------------------- creator ------
def assert_balances(
    creator,
    ledger_balance_cents=None,
    held_cents=None,
    statement_payable_cents=None,
    fund_credit_balance_cents=None,
    available_balance_cents=None,
    outstanding_clawback_cents=None,
):
    checks = {
        "ledger_balance_cents": ledger_balance_cents,
        "held_cents": held_cents,
        "statement_payable_cents": statement_payable_cents,
        "fund_credit_balance_cents": fund_credit_balance_cents,
        "available_balance_cents": available_balance_cents,
        "outstanding_clawback_cents": outstanding_clawback_cents,
    }
    for field, expected in checks.items():
        if expected is None:
            continue
        assert_cents(creator[field])
        assert creator[field] == expected, (
            f"Expected {field} {expected}, got {creator[field]}"
        )


def assert_available_balance_identity(creator):
    """available = statement payable + fund credit - held."""
    expected = (
        creator["statement_payable_cents"]
        + creator["fund_credit_balance_cents"]
        - creator["held_cents"]
    )
    assert creator["available_balance_cents"] == expected, (
        f"available_balance_cents {creator['available_balance_cents']} does not equal "
        f"statement_payable_cents + fund_credit_balance_cents - held_cents ({expected})"
    )


def assert_dimensions(creator, eligibility_status=None, payout_state=None):
    if eligibility_status is not None:
        assert creator["eligibility_status"] == eligibility_status, (
            f"Expected eligibility_status {eligibility_status}, "
            f"got {creator['eligibility_status']}"
        )
    if payout_state is not None:
        assert creator["payout_state"] == payout_state, (
            f"Expected payout_state {payout_state}, got {creator['payout_state']}"
        )


# ----------------------------------------------------------------- fees -----
def expected_payout_fee(method, payable_before_fee_cents):
    """Reference implementation of the documented fee formula."""
    flat = FLAT_FEE_CENTS[method]
    pct = math.ceil(payable_before_fee_cents * PCT_FEE_BPS[method] / 10000)
    raw = flat + pct
    multiplier = None
    for low, high, mult in VOLUME_TIERS:
        if payable_before_fee_cents >= low and (high is None or payable_before_fee_cents <= high):
            multiplier = mult
            break
    scaled = math.ceil(raw * multiplier / 10000)
    capped = min(scaled, FEE_CAP_CENTS[method])
    return min(capped, max(payable_before_fee_cents - 1, 0))


def assert_fund_pool_conserved(fund):
    """Allocated plus remainder always reconstitutes the declared pool."""
    assert (
        fund["allocated_cents"] + fund["unallocated_remainder_cents"]
        == fund["total_pool_cents"]
    ), (
        f"allocated_cents {fund['allocated_cents']} + unallocated_remainder_cents "
        f"{fund['unallocated_remainder_cents']} != total_pool_cents "
        f"{fund['total_pool_cents']}"
    )
