"""
Domain assertion helpers.

These wrap the repeated shape and invariant checks the PRD pins: the common
field split between versioned collections and append-only audit rows, integer
cent arithmetic, four-decimal nondiscrimination ratios, the funding-batch net
identity, and normalized instant comparison for values stamped from the
logical clock.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ALLOCATION_TYPES,
    AMENDMENT_STATUSES,
    CERTIFICATION_STATUSES,
    EMPLOYMENT_STATUSES,
    FUNDING_BATCH_STATUSES,
    FUNDING_STATUSES,
    LOAN_ACCOUNT_STATUSES,
    PAYROLL_PERIOD_STATUSES,
    PLAN_YEAR_STATUSES,
    TEST_STATUSES,
    VESTING_STATUSES,
)

Resource = Dict[str, Any]


# ---------------------------------------------------------------------------
# Common-field shape (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_versioned_resource(resource: Resource, label: str = "resource") -> None:
    """Assert the full common-field set on a versioned collection member."""
    assert is_valid_uuid(resource["id"]), f"{label}.id is not a uuid: {resource.get('id')!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"{label}.created_at is not ISO 8601: {resource.get('created_at')!r}"
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"{label}.updated_at is not ISO 8601: {resource.get('updated_at')!r}"
    assert isinstance(resource["version"], int), f"{label}.version must be an integer"
    assert resource["version"] >= 1, f"{label}.version must start at 1"


def assert_append_only_row(resource: Resource, label: str = "resource") -> None:
    """
    Assert an append-only audit row's shape.

    Append-only rows carry only `id` and `created_at`; `updated_at` and
    `version` are absent from the resource entirely.
    """
    assert is_valid_uuid(resource["id"]), f"{label}.id is not a uuid: {resource.get('id')!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"{label}.created_at is not ISO 8601: {resource.get('created_at')!r}"
    assert "updated_at" not in resource, f"{label} must not expose updated_at"
    assert "version" not in resource, f"{label} must not expose version"


# ---------------------------------------------------------------------------
# Instants and money
# ---------------------------------------------------------------------------


def _parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 instants by value, tolerating fractional-second form."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert _parse_instant(actual) == _parse_instant(
        expected
    ), f"{label} is {actual}, expected {expected}"


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert an integer-cent money field: exact value, integral type."""
    assert isinstance(actual, int) and not isinstance(
        actual, bool
    ), f"{label} must be an integer number of cents, got {actual!r}"
    assert actual == expected, f"{label} is {actual}, expected {expected}"


def assert_ratio_4dp(actual: Any, expected: float, label: str = "ratio") -> None:
    """Assert a nondiscrimination ratio carried to four decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(
        actual, bool
    ), f"{label} must be numeric, got {actual!r}"
    assert round(float(actual), 4) == round(
        float(expected), 4
    ), f"{label} is {actual}, expected {expected}"
    assert (
        abs(float(actual) - round(float(actual), 4)) < 1e-9
    ), f"{label} carries more than four decimal places: {actual}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_plan_year_shape(plan_year: Resource) -> None:
    """Assert a plan year's shape, status vocabulary and derived rollups."""
    assert_versioned_resource(plan_year, "PlanYear")
    assert plan_year["status"] in PLAN_YEAR_STATUSES
    assert isinstance(plan_year["year"], int)
    for field in (
        "compensation_cap_cents",
        "annual_deferral_limit_cents",
        "hce_prior_comp_threshold_cents",
        "total_deferral_match_funded_cents",
        "total_qslp_match_funded_cents",
        "forfeiture_balance_cents",
    ):
        assert isinstance(plan_year[field], int), f"PlanYear.{field} must be integer cents"
    assert isinstance(plan_year["accepted_certification_count"], int)
    assert isinstance(plan_year["true_up_completed"], bool)
    assert isinstance(plan_year["reopened_count"], int)


def assert_amendment_shape(amendment: Resource) -> None:
    """Assert a plan amendment's shape and status vocabulary."""
    assert_versioned_resource(amendment, "PlanAmendment")
    assert amendment["status"] in AMENDMENT_STATUSES
    assert is_valid_uuid(amendment["plan_year_id"])
    assert is_iso8601_timestamp(amendment["effective_date"])


def assert_employee_shape(employee: Resource) -> None:
    """Assert an employee's shape, employment status and accumulators."""
    assert_versioned_resource(employee, "Employee")
    assert employee["employment_status"] in EMPLOYMENT_STATUSES
    assert isinstance(employee["hce_flag"], bool)
    for field in (
        "ytd_eligible_compensation_cents",
        "ytd_deferral_cents",
        "ytd_deferral_match_cents",
        "ytd_qslp_match_cents",
        "unpaid_leave_days_ytd",
        "vesting_service_months",
    ):
        assert isinstance(employee[field], int), f"Employee.{field} must be an integer"


def assert_payroll_period_shape(period: Resource) -> None:
    """Assert a payroll period's shape, status vocabulary and totals."""
    assert_versioned_resource(period, "PayrollPeriod")
    assert period["status"] in PAYROLL_PERIOD_STATUSES
    assert isinstance(period["period_number"], int)
    assert isinstance(period["reopen_count"], int)
    assert isinstance(period["total_eligible_compensation_cents"], int)
    assert isinstance(period["total_deferral_match_cents"], int)


def assert_contribution_record_shape(record: Resource) -> None:
    """Assert a payroll line's shape and its derived match and space fields."""
    assert_versioned_resource(record, "ContributionRecord")
    for field in (
        "eligible_compensation_cents",
        "elective_deferral_cents",
        "counted_compensation_cents",
        "deferral_match_cents",
        "qslp_space_tier1_cents",
        "qslp_space_tier2_cents",
    ):
        assert isinstance(record[field], int), f"ContributionRecord.{field} must be integer cents"


def assert_loan_account_shape(account: Resource) -> None:
    """Assert a loan account's shape and status vocabulary."""
    assert_versioned_resource(account, "LoanAccount")
    assert account["status"] in LOAN_ACCOUNT_STATUSES
    assert isinstance(account["account_last4"], str)


def assert_certification_shape(certification: Resource) -> None:
    """Assert a certification claim's shape, status and money totals."""
    assert_versioned_resource(certification, "LoanCertification")
    assert certification["status"] in CERTIFICATION_STATUSES
    assert isinstance(certification["return_count"], int)
    assert isinstance(certification["capped_by_statutory_room"], bool)
    for field in (
        "certified_total_cents",
        "eligible_total_cents",
        "matched_total_cents",
        "unmatched_eligible_cents",
    ):
        assert isinstance(certification[field], int), f"LoanCertification.{field} must be cents"


def assert_certification_line_shape(line: Resource) -> None:
    """Assert a certified payment line's append-only shape."""
    assert_append_only_row(line, "CertificationLine")
    assert isinstance(line["amount_cents"], int)
    assert is_iso8601_timestamp(line["payment_date"])
    assert is_iso8601_timestamp(line["covered_period_start"])
    assert is_iso8601_timestamp(line["covered_period_end"])


def assert_allocation_shape(allocation: Resource) -> None:
    """Assert a match allocation's shape and its two independent dimensions."""
    assert_versioned_resource(allocation, "MatchAllocation")
    assert allocation["allocation_type"] in ALLOCATION_TYPES
    assert allocation["funding_status"] in FUNDING_STATUSES
    assert allocation["vesting_status"] in VESTING_STATUSES
    for field in ("amount_cents", "tier1_applied_cents", "tier2_applied_cents", "vested_cents", "forfeited_cents"):
        assert isinstance(allocation[field], int), f"MatchAllocation.{field} must be cents"


def assert_funding_batch_shape(batch: Resource) -> None:
    """Assert a funding batch's shape, status vocabulary and totals."""
    assert_versioned_resource(batch, "FundingBatch")
    assert batch["status"] in FUNDING_BATCH_STATUSES
    assert isinstance(batch["allocation_count"], int)
    assert isinstance(batch["retransmit_count"], int)
    for field in ("total_allocated_cents", "forfeiture_offset_cents", "net_funding_cents"):
        assert isinstance(batch[field], int), f"FundingBatch.{field} must be integer cents"


def assert_batch_net_identity(batch: Resource) -> None:
    """Assert net funding equals the allocated total less the forfeiture offset."""
    expected = batch["total_allocated_cents"] - batch["forfeiture_offset_cents"]
    assert batch["net_funding_cents"] == expected, (
        "FundingBatch.net_funding_cents is "
        f"{batch['net_funding_cents']}, expected {expected}"
    )


def assert_forfeiture_record_shape(record: Resource) -> None:
    """Assert a forfeiture record's append-only shape."""
    assert_append_only_row(record, "ForfeitureRecord")
    assert isinstance(record["amount_cents"], int)
    assert isinstance(record["reason_code"], str)


def assert_correction_adjustment_shape(adjustment: Resource) -> None:
    """Assert a correction adjustment's append-only shape."""
    assert_append_only_row(adjustment, "CorrectionAdjustment")
    assert isinstance(adjustment["amount_cents"], int)
    assert isinstance(adjustment["reason_code"], str)


def assert_leave_event_shape(event: Resource) -> None:
    """Assert a leave interval's append-only shape and inclusive day count."""
    assert_append_only_row(event, "LeaveEvent")
    assert isinstance(event["day_count"], int)
    assert event["day_count"] >= 1


def assert_nondiscrimination_test_shape(test: Resource) -> None:
    """Assert an ACP test's shape, status vocabulary and ratio precision."""
    assert_versioned_resource(test, "NondiscriminationTest")
    assert test["status"] in TEST_STATUSES
    assert isinstance(test["hce_count"], int)
    assert isinstance(test["nhce_count"], int)
    assert isinstance(test["total_correction_cents"], int)
    for field in ("hce_acp", "nhce_acp", "limit_acp"):
        assert isinstance(test[field], (int, float)), f"NondiscriminationTest.{field} numeric"


def assert_audit_packet_shape(packet: Resource) -> None:
    """Assert the computed audit packet's shape."""
    for field in (
        "certification_count",
        "accepted_certified_cents",
        "deferral_match_cents",
        "qslp_match_cents",
        "forfeited_cents",
        "correction_cents",
        "remaining_space_cents",
    ):
        assert isinstance(packet[field], int), f"audit packet {field} must be an integer"


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def assert_collection_size(items: List[Resource], expected: int, label: str = "collection") -> None:
    """Assert an exact element count on a listing payload."""
    assert len(items) == expected, f"{label} holds {len(items)} rows, expected {expected}"


def assert_total_count(meta: Dict[str, Any], expected: int, label: str = "collection") -> None:
    """Assert the reported total row count of a paginated listing."""
    assert meta["total_count"] == expected, (
        f"{label} reports total_count {meta['total_count']}, expected {expected}"
    )


def only(items: List[Resource], label: str = "collection") -> Resource:
    """Return the single element of a listing, asserting there is exactly one."""
    assert_collection_size(items, 1, label)
    return items[0]
