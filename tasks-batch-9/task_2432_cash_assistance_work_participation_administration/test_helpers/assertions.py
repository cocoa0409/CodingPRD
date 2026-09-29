"""Domain assertions for cash-assistance entities."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_FIELDS = ("id", "created_at")


def assert_rejected(response: Any, expected_error_id: str) -> Dict[str, Any]:
    """A rejected request carries exactly the expected identifier and status."""
    return validate_error(response, expected_error_id)


def assert_accepted(response: Any, expected_status: int = 200) -> Dict[str, Any]:
    """A successful request, returning its payload."""
    return validate_success(response, expected_status=expected_status)


def assert_page(
    response: Any,
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
    row_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Assert one page of a listing and return its rows."""
    data, meta = validate_paginated(response)
    expectations = {"total_count": total_count, "limit": limit, "offset": offset}
    for field, expected in expectations.items():
        if expected is not None:
            assert (
                meta[field] == expected
            ), f"meta.{field}: expected {expected}, got {meta[field]}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )
    if row_count is not None:
        assert len(data) == row_count, f"expected {row_count} rows, got {len(data)}"
    return data


def assert_audited_record(record: Dict[str, Any]) -> None:
    """A record that carries the full audit trail."""
    for field in AUDIT_FIELDS:
        assert field in record, f"missing audit field {field}: {record}"
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"created_at is not ISO 8601: {record['created_at']}"
    assert is_iso8601_timestamp(
        record["updated_at"]
    ), f"updated_at is not ISO 8601: {record['updated_at']}"
    assert isinstance(record["version"], int) and record["version"] >= 1


def assert_append_only_record(record: Dict[str, Any]) -> None:
    """An append-only ledger record: identifier and creation stamp only."""
    for field in APPEND_ONLY_FIELDS:
        assert field in record, f"missing field {field}: {record}"
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"created_at is not ISO 8601: {record['created_at']}"
    assert "updated_at" not in record, f"append-only record carries updated_at: {record}"
    assert "version" not in record, f"append-only record carries version: {record}"


def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """Money is an integer number of cents."""
    assert isinstance(actual, int) and not isinstance(
        actual, bool
    ), f"{label} must be integer cents, got {actual!r}"
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Percentages carry two decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(
        actual, bool
    ), f"{label} must be numeric, got {actual!r}"
    assert (
        abs(float(actual) - float(expected)) < 1e-9
    ), f"{label}: expected {expected}, got {actual}"


def assert_case_state(
    case: Dict[str, Any],
    benefit_status: Optional[str] = None,
    compliance_status: Optional[str] = None,
    closure_reason: Optional[str] = None,
    sanction_level: Optional[int] = None,
    sanction_pct: Optional[float] = None,
    benefit_amount_cents: Optional[int] = None,
) -> None:
    """Assert any subset of a case's two independent state dimensions."""
    if benefit_status is not None:
        assert (
            case["benefit_status"] == benefit_status
        ), f"benefit_status: expected {benefit_status}, got {case['benefit_status']}"
    if compliance_status is not None:
        assert case["compliance_status"] == compliance_status, (
            f"compliance_status: expected {compliance_status}, "
            f"got {case['compliance_status']}"
        )
    if closure_reason is not None:
        assert (
            case["closure_reason"] == closure_reason
        ), f"closure_reason: expected {closure_reason}, got {case['closure_reason']}"
    if sanction_level is not None:
        assert (
            case["sanction_level"] == sanction_level
        ), f"sanction_level: expected {sanction_level}, got {case['sanction_level']}"
    if sanction_pct is not None:
        assert_pct(case["sanction_pct"], sanction_pct, "sanction_pct")
    if benefit_amount_cents is not None:
        assert_money(
            case["benefit_amount_cents"], benefit_amount_cents, "benefit_amount_cents"
        )


def assert_household_clocks(
    household: Dict[str, Any],
    state_clock_months_used: Optional[int] = None,
    federal_clock_months_used: Optional[int] = None,
    extension_months_used: Optional[int] = None,
    issued_countable_months: Optional[int] = None,
) -> None:
    """Assert any subset of the four household time-limit rollups."""
    expectations = {
        "state_clock_months_used": state_clock_months_used,
        "federal_clock_months_used": federal_clock_months_used,
        "extension_months_used": extension_months_used,
        "issued_countable_months": issued_countable_months,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert (
                household[field] == expected
            ), f"{field}: expected {expected}, got {household[field]}"


def assert_time_limit_month(
    row: Dict[str, Any],
    benefit_month: Optional[str] = None,
    assistance_issued: Optional[bool] = None,
    state_clock_countable: Optional[bool] = None,
    federal_clock_countable: Optional[bool] = None,
    non_countable_reason: Optional[str] = None,
) -> None:
    """Assert the countability flags of one time-limit ledger row."""
    expectations = {
        "benefit_month": benefit_month,
        "assistance_issued": assistance_issued,
        "state_clock_countable": state_clock_countable,
        "federal_clock_countable": federal_clock_countable,
        "non_countable_reason": non_countable_reason,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert (
                row[field] == expected
            ), f"{field}: expected {expected!r}, got {row[field]!r}"


def find_time_limit_month(rows: List[Dict[str, Any]], benefit_month: str) -> Dict[str, Any]:
    """Pick the ledger row for one benefit month."""
    matches = [row for row in rows if row["benefit_month"] == benefit_month]
    assert len(matches) == 1, (
        f"expected exactly one ledger row for {benefit_month}, got {len(matches)}: "
        f"{[row['benefit_month'] for row in rows]}"
    )
    return matches[0]


def find_by_id(rows: List[Dict[str, Any]], record_id: str) -> Dict[str, Any]:
    """Pick one row out of a listing by identifier."""
    matches = [row for row in rows if row["id"] == record_id]
    assert len(matches) == 1, f"expected exactly one row with id {record_id}"
    return matches[0]


def assert_report_credits(
    report: Dict[str, Any],
    status: Optional[str] = None,
    verified_hours: Optional[int] = None,
    core_hours_credited: Optional[int] = None,
    non_core_hours_credited: Optional[int] = None,
) -> None:
    """Assert a participation report's status and credited hour split."""
    expectations = {
        "status": status,
        "verified_hours": verified_hours,
        "core_hours_credited": core_hours_credited,
        "non_core_hours_credited": non_core_hours_credited,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert (
                report[field] == expected
            ), f"{field}: expected {expected!r}, got {report[field]!r}"


def assert_overpayment_ledger(
    overpayment: Dict[str, Any],
    status: Optional[str] = None,
    recoupment_status: Optional[str] = None,
    established_amount_cents: Optional[int] = None,
    total_recovered_cents: Optional[int] = None,
    balance_cents: Optional[int] = None,
    monthly_recoupment_cents: Optional[int] = None,
) -> None:
    """Assert the ledger figures of an overpayment claim."""
    if status is not None:
        assert overpayment["status"] == status, (
            f"status: expected {status}, got {overpayment['status']}"
        )
    if recoupment_status is not None:
        assert overpayment["recoupment_status"] == recoupment_status, (
            f"recoupment_status: expected {recoupment_status}, "
            f"got {overpayment['recoupment_status']}"
        )
    money_fields = {
        "established_amount_cents": established_amount_cents,
        "total_recovered_cents": total_recovered_cents,
        "balance_cents": balance_cents,
        "monthly_recoupment_cents": monthly_recoupment_cents,
    }
    for field, expected in money_fields.items():
        if expected is not None:
            assert_money(overpayment[field], expected, field)


def assert_authorization(
    authorization: Dict[str, Any],
    status: Optional[str] = None,
    authorized_amount_cents: Optional[int] = None,
    fiscal_year: Optional[int] = None,
    void_reason: Optional[str] = None,
) -> None:
    """Assert a supportive service authorization's award and status."""
    if status is not None:
        assert authorization["status"] == status, (
            f"status: expected {status}, got {authorization['status']}"
        )
    if authorized_amount_cents is not None:
        assert_money(
            authorization["authorized_amount_cents"],
            authorized_amount_cents,
            "authorized_amount_cents",
        )
    if fiscal_year is not None:
        assert (
            authorization["fiscal_year"] == fiscal_year
        ), f"fiscal_year: expected {fiscal_year}, got {authorization['fiscal_year']}"
    if void_reason is not None:
        assert (
            authorization["void_reason"] == void_reason
        ), f"void_reason: expected {void_reason}, got {authorization['void_reason']}"
