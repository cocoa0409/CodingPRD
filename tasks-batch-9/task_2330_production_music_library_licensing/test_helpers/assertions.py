"""Domain assertions for the production music library contract.

These wrap the shared framework validators with the vocabulary of this PRD:
integer-cent money, 2-decimal performance credits, the parallel status axes,
the credit-exposure triple, the append-only ledger and the pool invariant.
"""

from typing import Any, Dict, Iterable, List, Optional

import pytest
import requests
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_errors import expected_status_for
from .constants import MIN_PAYOUT_CENTS

JsonDict = Dict[str, Any]

CENT = 0.01
CREDIT = 0.005


# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------


def assert_created(response: requests.Response) -> JsonDict:
    """A request that creates a new resource returns 201 with the resource."""
    return validate_success(response, 201)


def assert_ok(response: requests.Response) -> JsonDict:
    """A read, a modification or a state transition returns 200."""
    return validate_success(response, 200)


def assert_declared_error(response: requests.Response, error_id: str) -> JsonDict:
    """Assert `error_id` together with the HTTP status the PRD declares for it."""
    return validate_error(response, error_id, expected_status_for(error_id))


def assert_page(response: requests.Response) -> tuple:
    """Validate a list response and return (rows, meta)."""
    return validate_paginated(response)


def assert_common_fields(data: JsonDict) -> None:
    """A living resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_thin_record_fields(data: JsonDict) -> None:
    """A fingerprint match or ledger entry carries only id and created_at."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"])
    assert "updated_at" not in data, "thin append-only record must have no updated_at"
    assert "version" not in data, "thin append-only record must have no version"


def assert_three_fraction_timestamp(value: str) -> None:
    """Timestamps are ISO 8601 UTC with exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert "." in value, f"timestamp has no fractional part: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits: {value!r}"


def assert_same_instant(actual: Optional[str], expected: str) -> None:
    """Compare two UTC instants written by the logical clock.

    The clock is set from values like `2026-08-01T00:00:00Z` while the service
    writes three fractional digits, so compare on the second.
    """
    assert actual is not None, f"expected instant {expected}, got null"
    assert _instant_key(actual) == _instant_key(expected), f"{actual!r} != {expected!r}"


def _instant_key(value: str) -> str:
    body = value.rstrip("Z")
    if "." in body:
        body = body.split(".")[0]
    return body


# ---------------------------------------------------------------------------
# Money and credits
# ---------------------------------------------------------------------------


def assert_integer_cents(value: Any, label: str = "amount") -> None:
    """Every monetary amount is an integer number of cents; no fractional cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_cents_equal(actual: Any, expected: int, label: str = "amount") -> None:
    assert_integer_cents(actual, label)
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_credits_equal(actual: Any, expected: float, label: str = "credits") -> None:
    """Performance credits are held at exactly 2 decimal places, rounded half up."""
    assert actual == pytest.approx(expected, abs=CREDIT), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_pct_equal(actual: Any, expected: float, label: str = "percentage") -> None:
    """Percentages are carried at 2 decimal places."""
    assert actual == pytest.approx(expected, abs=CENT), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Status axes
# ---------------------------------------------------------------------------


def assert_composition_axes(
    composition: JsonDict, catalog_status: str, availability_status: str
) -> None:
    """The catalogue axis and the rights axis are read independently."""
    assert composition["catalog_status"] == catalog_status, (
        f"catalog_status: expected {catalog_status}, got {composition['catalog_status']}"
    )
    assert composition["availability_status"] == availability_status, (
        f"availability_status: expected {availability_status}, "
        f"got {composition['availability_status']}"
    )


def assert_blanket_axes(
    agreement: JsonDict, coverage_status: str, reporting_status: str
) -> None:
    """The coverage axis and the reporting axis are read independently."""
    assert agreement["coverage_status"] == coverage_status, (
        f"coverage_status: expected {coverage_status}, got {agreement['coverage_status']}"
    )
    assert agreement["reporting_status"] == reporting_status, (
        f"reporting_status: expected {reporting_status}, got {agreement['reporting_status']}"
    )


def assert_status(row: JsonDict, expected: str, field: str = "status") -> None:
    assert row[field] == expected, f"{field}: expected {expected}, got {row[field]}"


# ---------------------------------------------------------------------------
# Credit exposure and composer money picture
# ---------------------------------------------------------------------------


def assert_credit_exposure(
    licensee: JsonDict,
    committed_spend_cents: int,
    reserved_spend_cents: int,
    credit_available_cents: int,
) -> None:
    """committed, reserved and available are the licensee's derived exposure."""
    assert_cents_equal(
        licensee["committed_spend_cents"], committed_spend_cents, "committed_spend_cents"
    )
    assert_cents_equal(
        licensee["reserved_spend_cents"], reserved_spend_cents, "reserved_spend_cents"
    )
    assert_cents_equal(
        licensee["credit_available_cents"], credit_available_cents, "credit_available_cents"
    )
    assert (
        licensee["credit_available_cents"]
        == licensee["credit_limit_cents"]
        - licensee["committed_spend_cents"]
        - licensee["reserved_spend_cents"]
    ), "credit_available_cents must be the limit less committed less reserved"


def assert_composer_money(
    composer: JsonDict,
    accrued_unpaid_cents: Optional[int] = None,
    outstanding_advance_cents: Optional[int] = None,
    lifetime_paid_cents: Optional[int] = None,
) -> None:
    if accrued_unpaid_cents is not None:
        assert_cents_equal(
            composer["accrued_unpaid_cents"], accrued_unpaid_cents, "accrued_unpaid_cents"
        )
    if outstanding_advance_cents is not None:
        assert_cents_equal(
            composer["outstanding_advance_cents"],
            outstanding_advance_cents,
            "outstanding_advance_cents",
        )
    if lifetime_paid_cents is not None:
        assert_cents_equal(
            composer["lifetime_paid_cents"], lifetime_paid_cents, "lifetime_paid_cents"
        )


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------


def select_ledger_entries(
    entries: Iterable[JsonDict],
    source_type: Optional[str] = None,
    source_ref_id: Optional[str] = None,
    composer_id: Optional[str] = None,
) -> List[JsonDict]:
    """Filter a ledger page by origin, referenced row and owning composer."""
    selected = []
    for entry in entries:
        if source_type is not None and entry.get("source_type") != source_type:
            continue
        if source_ref_id is not None and entry.get("source_ref_id") != source_ref_id:
            continue
        if composer_id is not None and entry.get("composer_id") != composer_id:
            continue
        selected.append(entry)
    return selected


def assert_single_ledger_entry(
    entries: Iterable[JsonDict],
    source_type: str,
    amount_cents: int,
    source_ref_id: Optional[str] = None,
) -> JsonDict:
    """Exactly one entry of `source_type` exists and carries `amount_cents`."""
    matches = select_ledger_entries(entries, source_type=source_type, source_ref_id=source_ref_id)
    assert len(matches) == 1, (
        f"expected exactly one {source_type} entry, found {len(matches)}"
    )
    entry = matches[0]
    assert_cents_equal(entry["amount_cents"], amount_cents, f"{source_type} amount_cents")
    return entry


def assert_ledger_sum(entries: Iterable[JsonDict], expected: int) -> None:
    """The signed amounts of a set of entries sum to `expected`."""
    total = sum(entry["amount_cents"] for entry in entries)
    assert total == expected, f"ledger sum: expected {expected}, got {total}"


def assert_cash_unrecognized(entry: JsonDict) -> None:
    """Money promised but not collected leaves `cash_recognized_at` null."""
    assert entry["cash_recognized_at"] is None, (
        f"expected cash_recognized_at null, got {entry['cash_recognized_at']!r}"
    )


# ---------------------------------------------------------------------------
# Pricing and pool invariants
# ---------------------------------------------------------------------------


def assert_quote_figures(
    sync_request: JsonDict,
    quoted_spend_basis_cents: int,
    quoted_discount_pct: float,
    quoted_fee_cents: int,
) -> None:
    assert_cents_equal(
        sync_request["quoted_spend_basis_cents"],
        quoted_spend_basis_cents,
        "quoted_spend_basis_cents",
    )
    assert_pct_equal(
        sync_request["quoted_discount_pct"], quoted_discount_pct, "quoted_discount_pct"
    )
    assert_cents_equal(sync_request["quoted_fee_cents"], quoted_fee_cents, "quoted_fee_cents")


def assert_final_figures(
    license_row: JsonDict,
    final_spend_basis_cents: int,
    final_discount_pct: float,
    final_fee_cents: int,
) -> None:
    assert_cents_equal(
        license_row["final_spend_basis_cents"],
        final_spend_basis_cents,
        "final_spend_basis_cents",
    )
    assert_pct_equal(license_row["final_discount_pct"], final_discount_pct, "final_discount_pct")
    assert_cents_equal(license_row["final_fee_cents"], final_fee_cents, "final_fee_cents")


def assert_pool_conserves_cents(report: JsonDict) -> None:
    """Allocations sum to pool_distributable_cents exactly; no cent is created."""
    allocations = report["pool_allocations"]
    total = sum(item["allocation_cents"] for item in allocations)
    if allocations:
        assert total == report["pool_distributable_cents"], (
            f"allocations sum to {total} but pool_distributable_cents is "
            f"{report['pool_distributable_cents']}"
        )
    assert (
        report["pool_cents"] - report["pool_admin_fee_cents"]
        == report["pool_distributable_cents"]
    ), "pool_distributable_cents must be pool_cents less pool_admin_fee_cents"


def assert_allocation(
    report: JsonDict, composition_id: str, credits: float, allocation_cents: int
) -> JsonDict:
    """Find one entry of `pool_allocations` and check its credits and money."""
    matches = [a for a in report["pool_allocations"] if a["composition_id"] == composition_id]
    assert len(matches) == 1, (
        f"expected one allocation for {composition_id}, found {len(matches)}"
    )
    allocation = matches[0]
    assert_credits_equal(allocation["credits"], credits, "allocation credits")
    assert_cents_equal(allocation["allocation_cents"], allocation_cents, "allocation_cents")
    return allocation


# ---------------------------------------------------------------------------
# Statement figures
# ---------------------------------------------------------------------------


def assert_statement_figures(
    statement: JsonDict,
    gross_cents: int,
    recouped_cents: int,
    withholding_cents: int,
    net_payable_cents: int,
    payout_status: Optional[str] = None,
    line_count: Optional[int] = None,
) -> None:
    assert_cents_equal(statement["gross_cents"], gross_cents, "gross_cents")
    assert_cents_equal(statement["recouped_cents"], recouped_cents, "recouped_cents")
    assert_cents_equal(statement["withholding_cents"], withholding_cents, "withholding_cents")
    assert_cents_equal(statement["net_payable_cents"], net_payable_cents, "net_payable_cents")
    assert (
        statement["net_payable_cents"]
        == statement["gross_cents"] - statement["recouped_cents"] - statement["withholding_cents"]
    ), "net_payable_cents must be gross less recouped less withholding"
    if payout_status is not None:
        assert statement["payout_status"] == payout_status, (
            f"payout_status: expected {payout_status}, got {statement['payout_status']}"
        )
    if line_count is not None:
        assert statement["line_count"] == line_count, (
            f"line_count: expected {line_count}, got {statement['line_count']}"
        )


def assert_payout_status_follows_minimum(statement: JsonDict) -> None:
    """HELD_BELOW_MINIMUM applies strictly below 2500 cents; 2500 itself is PAYABLE."""
    net = statement["net_payable_cents"]
    if statement["gross_cents"] == 0:
        assert statement["payout_status"] == "NO_ACTIVITY"
    elif net < MIN_PAYOUT_CENTS:
        assert statement["payout_status"] == "HELD_BELOW_MINIMUM"
    else:
        assert statement["payout_status"] == "PAYABLE"


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------


def assert_sweep_lists(
    sweep: JsonDict,
    expired_license_ids: Optional[List[str]] = None,
    expired_blanket_agreement_ids: Optional[List[str]] = None,
    delinquent_blanket_agreement_ids: Optional[List[str]] = None,
) -> None:
    """The clock response reports the three arrays of identifiers it touched."""
    for key in (
        "current_utc",
        "expired_license_ids",
        "expired_blanket_agreement_ids",
        "delinquent_blanket_agreement_ids",
    ):
        assert key in sweep, f"clock response is missing {key}"
    if expired_license_ids is not None:
        assert sweep["expired_license_ids"] == expired_license_ids
    if expired_blanket_agreement_ids is not None:
        assert sweep["expired_blanket_agreement_ids"] == expired_blanket_agreement_ids
    if delinquent_blanket_agreement_ids is not None:
        assert sweep["delinquent_blanket_agreement_ids"] == delinquent_blanket_agreement_ids
