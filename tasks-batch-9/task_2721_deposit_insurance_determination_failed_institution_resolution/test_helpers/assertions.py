"""Domain assertion helpers.

Thin wrappers that keep the individual test bodies readable.  Nothing here
introduces an expectation of its own: every helper checks only what the caller
passes in, plus the envelope and arithmetic rules the PRD fixes globally.
"""
import re

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
# Envelope and common fields (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_audit_fields(row):
    """A full audit-bearing record exposes id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert_timestamp_format(row["created_at"])
    assert_timestamp_format(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1, row.get("version")


def assert_immutable_record_fields(row):
    """An ownership interest carries only `id` and `created_at` of the common set."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert_timestamp_format(row["created_at"])
    assert "updated_at" not in row, "an immutable record must not expose updated_at"
    assert "version" not in row, "an immutable record must not expose version"


def assert_fields_equal(row, expected):
    """Every key in `expected` is present on `row` with exactly that value."""
    for key, value in expected.items():
        assert key in row, f"missing field {key!r} in {sorted(row)}"
        assert row[key] == value, f"{key}: expected {value!r}, got {row[key]!r}"


def assert_cents(value):
    """A monetary amount is an integer count of cents, never a string or a float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "monetary value must be an integer count of cents, got "
        f"{type(value).__name__}: {value!r}"
    )


def assert_bps(value):
    """A rate, share or ratio is an integer count of basis points."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "basis-point value must be an integer, got "
        f"{type(value).__name__}: {value!r}"
    )


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
_FRACTION = re.compile(r"\.(\d+)(?=Z$)")


def canonical_instant(value):
    """The instant with any trailing zero fractional-second digits normalised away.

    `2026-08-03T09:00:00Z` and `2026-08-03T09:00:00.000Z` name the same instant,
    and the PRD's clock is set from the bare form while stamped audit fields are
    rendered with three fractional digits.
    """
    if value is None:
        return None
    match = _FRACTION.search(value)
    if match is None:
        return value
    if set(match.group(1)) <= {"0"}:
        return value[: match.start()] + "Z"
    return value


def assert_instant(actual, expected):
    """Two ISO 8601 instants name the same moment, whatever their rendering."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_clock_default(value):
    """The clock reads the instant the PRD says the service starts at."""
    assert_instant(value, C.CLOCK_DEFAULT)


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------
def created(response):
    """Assert HTTP 201 and return the created row."""
    return validate_success(response, 201)


def ok(response):
    """Assert HTTP 200 and return the affected row."""
    return validate_success(response, 200)


def data_of(response):
    return get_success_data(response)


# ---------------------------------------------------------------------------
# List helpers (PRD 2.3)
# ---------------------------------------------------------------------------
def assert_page(response, expected_total=None, expected_ids=None):
    """Validate a list envelope and, optionally, its total and exact id order."""
    data, meta = validate_paginated(response)
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"missing pagination field {key!r} in {sorted(meta)}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, meta
    if expected_ids is not None:
        assert [row["id"] for row in data] == list(expected_ids), [
            row["id"] for row in data
        ]
    return data, meta


def total_count(response):
    """The `total_count` a list response reports for its filters."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


def ids_of(rows):
    return [row["id"] for row in rows]


def assert_ordered_by(rows, key, descending=False):
    values = [row[key] for row in rows]
    assert values == sorted(values, reverse=descending), f"{key} not ordered: {values}"


# ---------------------------------------------------------------------------
# Readiness submissions (PRD 3.1)
# ---------------------------------------------------------------------------
def assert_submission_scored(submission, status, score_bps, variance_bps, rejection_reason):
    """Both basis-point diagnostics are written before either gate is applied."""
    assert_fields_equal(
        submission,
        {
            "status": status,
            "standardization_score_bps": score_bps,
            "deposit_total_variance_bps": variance_bps,
            "rejection_reason": rejection_reason,
        },
    )
    assert_bps(submission["standardization_score_bps"])
    assert_bps(submission["deposit_total_variance_bps"])


# ---------------------------------------------------------------------------
# Determinations (PRD 3.4, 3.5)
# ---------------------------------------------------------------------------
def assert_determination_amounts(determination, insured, uninsured, attributed):
    """The three headline figures of a determination, all in integer cents."""
    assert_fields_equal(
        determination,
        {
            "insured_amount_cents": insured,
            "uninsured_amount_cents": uninsured,
            "attributed_total_cents": attributed,
        },
    )
    for field in (
        "insured_amount_cents",
        "uninsured_amount_cents",
        "attributed_total_cents",
    ):
        assert_cents(determination[field])


def assert_category_breakdown(
    determination, category, attributed, limit, insured, uninsured
):
    """One `category_breakdown` entry, which exists only for a non-zero attribution."""
    breakdown = determination["category_breakdown"]
    assert category in breakdown, (
        f"expected a {category} entry in category_breakdown, got {sorted(breakdown)}"
    )
    assert_fields_equal(
        breakdown[category],
        {
            "attributed_cents": attributed,
            "limit_cents": limit,
            "insured_cents": insured,
            "uninsured_cents": uninsured,
        },
    )
    return breakdown[category]


def assert_breakdown_categories(determination, categories):
    """`category_breakdown` holds exactly the categories with a non-zero attribution."""
    assert sorted(determination["category_breakdown"]) == sorted(categories), (
        f"expected breakdown for {sorted(categories)}, got "
        f"{sorted(determination['category_breakdown'])}"
    )


# ---------------------------------------------------------------------------
# Deposit accounts: three independent dimensions (PRD 2.7, 3.6)
# ---------------------------------------------------------------------------
def assert_account_dimensions(
    account,
    insurance_status,
    hold_status,
    transition_status,
    held_amount_cents=None,
    attributed_amount_cents=None,
):
    """All three dimensions of one account, each advancing under its own triggers."""
    expected = {
        "insurance_status": insurance_status,
        "hold_status": hold_status,
        "transition_status": transition_status,
    }
    if held_amount_cents is not None:
        expected["held_amount_cents"] = held_amount_cents
    if attributed_amount_cents is not None:
        expected["attributed_amount_cents"] = attributed_amount_cents
    assert_fields_equal(account, expected)
    assert_cents(account["held_amount_cents"])
    assert_cents(account["attributed_amount_cents"])


# ---------------------------------------------------------------------------
# Certificates (PRD 3.6, 3.9)
# ---------------------------------------------------------------------------
def assert_certificate(
    certificate,
    status,
    face_amount_cents,
    cumulative_dividends_cents=None,
    last_dividend_amount_cents=None,
    last_dividend_round=None,
):
    """A receivership certificate's status and its dividend history."""
    expected = {"status": status, "face_amount_cents": face_amount_cents}
    if cumulative_dividends_cents is not None:
        expected["cumulative_dividends_cents"] = cumulative_dividends_cents
    if last_dividend_amount_cents is not None:
        expected["last_dividend_amount_cents"] = last_dividend_amount_cents
    if last_dividend_round is not None:
        expected["last_dividend_round"] = last_dividend_round
    assert_fields_equal(certificate, expected)
    assert_cents(certificate["face_amount_cents"])
    assert_cents(certificate["cumulative_dividends_cents"])


# ---------------------------------------------------------------------------
# Bids (PRD 3.8)
# ---------------------------------------------------------------------------
def assert_bid_costs(
    bid,
    assumed_deposit_base_cents,
    pre_fee_cost_cents,
    loss_share_fee_cents,
    expected_loss_share_reimbursement_cents,
    evaluated_cost_cents,
):
    """The five cost fields a conforming bid receives from the pricing steps."""
    assert_fields_equal(
        bid,
        {
            "assumed_deposit_base_cents": assumed_deposit_base_cents,
            "pre_fee_cost_cents": pre_fee_cost_cents,
            "loss_share_fee_cents": loss_share_fee_cents,
            "expected_loss_share_reimbursement_cents": (
                expected_loss_share_reimbursement_cents
            ),
            "evaluated_cost_cents": evaluated_cost_cents,
        },
    )
    for field in (
        "assumed_deposit_base_cents",
        "pre_fee_cost_cents",
        "loss_share_fee_cents",
        "expected_loss_share_reimbursement_cents",
        "evaluated_cost_cents",
    ):
        assert_cents(bid[field])


def assert_no_cost_calculation(bid):
    """A non-conforming bid has no cost calculation run at all."""
    assert bid["evaluated_cost_cents"] is None, (
        f"evaluated_cost_cents must stay unset, got {bid['evaluated_cost_cents']!r}"
    )


# ---------------------------------------------------------------------------
# Institution aggregates and the two conservation identities (PRD 2.7, 2.8)
# ---------------------------------------------------------------------------
def assert_institution_aggregates(institution, **expected):
    """Any subset of the institution's recomputed-from-scratch aggregates."""
    assert_fields_equal(institution, expected)


def assert_conservation_identities_hold(summary):
    """Both signed deltas the insurance summary exposes must read zero."""
    assert_fields_equal(
        summary, {"conservation_delta_cents": 0, "cash_conservation_delta_cents": 0}
    )


def assert_summary(summary, **expected):
    """Any subset of the recomputed insurance-summary read."""
    assert_fields_equal(summary, expected)
