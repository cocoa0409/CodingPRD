"""Domain assertion helpers.

These wrap the repeated shape checks: the two common-field profiles, the four
state dimensions of a correction case, the two dimensions of an agency notice,
the six figures of the exposure summary, and the pagination fields.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import EVIDENCE_COMMON_FIELDS, FULL_COMMON_FIELDS


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Mutable entities carry id, created_at, updated_at and version."""
    for field in FULL_COMMON_FIELDS:
        assert field in entity, f"Missing common field '{field}': {entity}"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_evidence_common_fields(entity: Dict[str, Any]) -> None:
    """Immutable evidence rows carry only id and created_at."""
    for field in EVIDENCE_COMMON_FIELDS:
        assert field in entity, f"Missing common field '{field}': {entity}"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "Immutable evidence rows must not carry updated_at"
    assert "version" not in entity, "Immutable evidence rows must not carry version"


def assert_case_dimensions(
    case: Dict[str, Any],
    status: Optional[str] = None,
    detection_status: Optional[str] = None,
    filing_status: Optional[str] = None,
    statement_status: Optional[str] = None,
) -> None:
    """Check any subset of the four independent case state dimensions."""
    if status is not None:
        assert case["status"] == status, f"case status {case['status']} != {status}"
    if detection_status is not None:
        assert case["detection_status"] == detection_status, (
            f"detection_status {case['detection_status']} != {detection_status}"
        )
    if filing_status is not None:
        assert case["filing_status"] == filing_status, (
            f"filing_status {case['filing_status']} != {filing_status}"
        )
    if statement_status is not None:
        assert case["statement_status"] == statement_status, (
            f"statement_status {case['statement_status']} != {statement_status}"
        )


def assert_notice_dimensions(
    notice: Dict[str, Any],
    response_status: Optional[str] = None,
    abatement_status: Optional[str] = None,
) -> None:
    """Check the two independent notice dimensions."""
    if response_status is not None:
        assert notice["response_status"] == response_status, (
            f"response_status {notice['response_status']} != {response_status}"
        )
    if abatement_status is not None:
        assert notice["abatement_status"] == abatement_status, (
            f"abatement_status {notice['abatement_status']} != {abatement_status}"
        )


def assert_case_rollups(
    case: Dict[str, Any],
    total_exposure_cents: Optional[int] = None,
    corrected_wage_base_cents: Optional[int] = None,
    repayment_recovered_cents: Optional[int] = None,
    open_discrepancy_count: Optional[int] = None,
    dominant_root_cause_code: Any = "__unset__",
) -> None:
    if total_exposure_cents is not None:
        assert case["total_exposure_cents"] == total_exposure_cents, (
            f"total_exposure_cents {case['total_exposure_cents']} != {total_exposure_cents}"
        )
    if corrected_wage_base_cents is not None:
        assert case["corrected_wage_base_cents"] == corrected_wage_base_cents, (
            f"corrected_wage_base_cents {case['corrected_wage_base_cents']} "
            f"!= {corrected_wage_base_cents}"
        )
    if repayment_recovered_cents is not None:
        assert case["repayment_recovered_cents"] == repayment_recovered_cents, (
            f"repayment_recovered_cents {case['repayment_recovered_cents']} "
            f"!= {repayment_recovered_cents}"
        )
    if open_discrepancy_count is not None:
        assert case["open_discrepancy_count"] == open_discrepancy_count, (
            f"open_discrepancy_count {case['open_discrepancy_count']} != {open_discrepancy_count}"
        )
    if dominant_root_cause_code != "__unset__":
        assert case["dominant_root_cause_code"] == dominant_root_cause_code, (
            f"dominant_root_cause_code {case['dominant_root_cause_code']} "
            f"!= {dominant_root_cause_code}"
        )


def assert_amendment_money(
    amended_return: Dict[str, Any],
    wage_delta_cents: Optional[int] = None,
    tax_delta_cents: Optional[int] = None,
    deposit_shortfall_cents: Optional[int] = None,
    days_late: Optional[int] = None,
    interest_cents: Optional[int] = None,
    penalty_cents: Optional[int] = None,
    interest_variant: Optional[str] = None,
    voluntary_reduction_applied: Optional[bool] = None,
) -> None:
    checks = {
        "wage_delta_cents": wage_delta_cents,
        "tax_delta_cents": tax_delta_cents,
        "deposit_shortfall_cents": deposit_shortfall_cents,
        "days_late": days_late,
        "interest_cents": interest_cents,
        "penalty_cents": penalty_cents,
        "interest_variant": interest_variant,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert amended_return[field] == expected, (
                f"{field} {amended_return[field]} != {expected}"
            )
    if voluntary_reduction_applied is not None:
        assert amended_return["voluntary_reduction_applied"] is voluntary_reduction_applied, (
            f"voluntary_reduction_applied {amended_return['voluntary_reduction_applied']} "
            f"!= {voluntary_reduction_applied}"
        )


def assert_exposure_summary(
    summary: Dict[str, Any],
    gross_exposure_cents: Optional[int] = None,
    waived_cents: Optional[int] = None,
    total_exposure_cents: Optional[int] = None,
    corrected_wage_base_cents: Optional[int] = None,
    repayment_recovered_cents: Optional[int] = None,
    dominant_root_cause_code: Any = "__unset__",
) -> None:
    for field in (
        "gross_exposure_cents",
        "waived_cents",
        "total_exposure_cents",
        "corrected_wage_base_cents",
        "repayment_recovered_cents",
        "dominant_root_cause_code",
    ):
        assert field in summary, f"exposure summary missing '{field}': {summary}"
    checks = {
        "gross_exposure_cents": gross_exposure_cents,
        "waived_cents": waived_cents,
        "total_exposure_cents": total_exposure_cents,
        "corrected_wage_base_cents": corrected_wage_base_cents,
        "repayment_recovered_cents": repayment_recovered_cents,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert summary[field] == expected, f"{field} {summary[field]} != {expected}"
    if dominant_root_cause_code != "__unset__":
        assert summary["dominant_root_cause_code"] == dominant_root_cause_code


def assert_pagination(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta["limit"] == limit, f"limit {meta['limit']} != {limit}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset {meta['offset']} != {offset}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count {meta['total_count']} != {total_count}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, f"has_more {meta['has_more']} != {has_more}"


def assert_error_body_is_minimal(response) -> None:
    """The error payload carries only error_id and message."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error payload must carry only error_id and message, got {sorted(body['data'].keys())}"
    )


def assert_envelope_meta(response) -> None:
    """Every response carries meta.api_request_id and meta.api_request_timestamp."""
    body = response.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        body["meta"]["api_request_timestamp"]
    )


def assert_response_type(response, expected: str) -> None:
    body = response.json()
    assert body["response_type"] == expected, (
        f"response_type {body['response_type']} != {expected}"
    )


def assert_period_ordinals(
    account: Dict[str, Any], from_period_ordinal: int, to_period_ordinal: int
) -> None:
    assert account["from_period_ordinal"] == from_period_ordinal, (
        f"from_period_ordinal {account['from_period_ordinal']} != {from_period_ordinal}"
    )
    assert account["to_period_ordinal"] == to_period_ordinal, (
        f"to_period_ordinal {account['to_period_ordinal']} != {to_period_ordinal}"
    )


def assert_nulls(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert entity[field] is None, f"{field} should be null, got {entity[field]!r}"


def assert_zeros(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert entity[field] == 0, f"{field} should be 0, got {entity[field]!r}"


def ids_of(rows) -> list:
    return [row["id"] for row in rows]
