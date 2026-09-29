"""Domain assertion helpers.

Thin wrappers that keep the individual test bodies readable.  Nothing here
introduces an expectation of its own — every helper only checks what the caller
passes in, plus the envelope and precision rules the PRD fixes globally.
"""
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from . import constants as C


# ---------------------------------------------------------------------------
# Envelope / common properties
# ---------------------------------------------------------------------------
def assert_audit_fields(row):
    """A full audit-bearing record exposes id, created_at, updated_at, version."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert_timestamp_format(row["created_at"])
    assert_timestamp_format(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1, row.get("version")


def assert_lean_record_fields(row):
    """A reference record exposes only id and created_at of the common set."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert_timestamp_format(row["created_at"])
    assert "updated_at" not in row, "reference record must not expose updated_at"
    assert "version" not in row, "reference record must not expose version"


def assert_fields_equal(row, expected):
    """Every key in `expected` is present on `row` with exactly that value."""
    for key, value in expected.items():
        assert key in row, f"missing field {key!r} in {sorted(row)}"
        assert row[key] == value, f"{key}: expected {value!r}, got {row[key]!r}"


def assert_two_dp(value):
    """A percentage or weighted figure carries at most two decimal places."""
    assert isinstance(value, (int, float)), value
    assert round(float(value), 2) == float(value), f"{value} is not 2-decimal rounded"


def assert_cents(value):
    """A monetary amount is an integer number of cents, never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"monetary value must be an integer of cents, got {type(value).__name__}: {value!r}"
    )


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------
def assert_page(response, expected_total=None, expected_ids=None):
    """Validate a list envelope and, optionally, its total and exact id order."""
    data, meta = validate_paginated(response)
    assert set(["limit", "offset", "total_count", "has_more"]).issubset(meta), sorted(meta)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, meta
    if expected_ids is not None:
        assert [row["id"] for row in data] == list(expected_ids), [r["id"] for r in data]
    return data, meta


def ids_of(rows):
    return [row["id"] for row in rows]


def assert_ordered_by(rows, key, descending=False):
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"{key} not ordered: {values}"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def assert_clock_default(value):
    assert value == C.CLOCK_DEFAULT, f"expected {C.CLOCK_DEFAULT}, got {value!r}"


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------
def created(response):
    """Assert HTTP 201 and return the created row."""
    return validate_success(response, 201)


def ok(response):
    """Assert HTTP 200 and return the row."""
    return validate_success(response, 200)


def data_of(response):
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Search-firm ledger
# ---------------------------------------------------------------------------
def assert_firm_ledger(
    firm, placed_nominee_count, committed_fee_cents, retainer_credit_applied_cents, net_payable_cents
):
    assert_fields_equal(
        firm,
        {
            "placed_nominee_count": placed_nominee_count,
            "committed_fee_cents": committed_fee_cents,
            "retainer_credit_applied_cents": retainer_credit_applied_cents,
            "net_payable_cents": net_payable_cents,
        },
    )
    for field in (
        "committed_fee_cents",
        "retainer_credit_applied_cents",
        "net_payable_cents",
    ):
        assert_cents(firm[field])


# ---------------------------------------------------------------------------
# Committee seat ledger
# ---------------------------------------------------------------------------
def assert_committee_ledger(committee, filled_seats, status):
    assert_fields_equal(committee, {"filled_seats": filled_seats, "status": status})


# ---------------------------------------------------------------------------
# Onboarding rollup
# ---------------------------------------------------------------------------
def assert_onboarding_rollup(director, onboarding_status, completion_pct):
    assert_fields_equal(
        director,
        {
            "onboarding_status": onboarding_status,
            "onboarding_completion_pct": completion_pct,
        },
    )
    assert_two_dp(director["onboarding_completion_pct"])


# ---------------------------------------------------------------------------
# Slate tallies
# ---------------------------------------------------------------------------
def assert_slate_tallies(
    slate, votes_for, votes_against, votes_abstain, votes_recused, approval_pct, quorum_met
):
    assert_fields_equal(
        slate,
        {
            "votes_for": votes_for,
            "votes_against": votes_against,
            "votes_abstain": votes_abstain,
            "votes_recused": votes_recused,
            "approval_pct": approval_pct,
            "quorum_met": quorum_met,
        },
    )
    assert_two_dp(slate["approval_pct"])


def assert_slate_independence(slate, independent_nominee_count, independent_nominee_pct, shortfall):
    assert_fields_equal(
        slate,
        {
            "independent_nominee_count": independent_nominee_count,
            "independent_nominee_pct": independent_nominee_pct,
            "independence_shortfall": shortfall,
        },
    )
    assert_two_dp(slate["independent_nominee_pct"])


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------
def gap_row(analysis, code):
    matches = [row for row in analysis["categories"] if row["code"] == code]
    assert len(matches) == 1, f"expected exactly one {code} row, got {len(matches)}"
    return matches[0]


def assert_gap_row(analysis, code, covered_director_count, gap, weighted_gap, severity):
    row = gap_row(analysis, code)
    assert_fields_equal(
        row,
        {
            "covered_director_count": covered_director_count,
            "gap": gap,
            "weighted_gap": weighted_gap,
            "severity": severity,
        },
    )
    assert_two_dp(row["weighted_gap"])
    return row
