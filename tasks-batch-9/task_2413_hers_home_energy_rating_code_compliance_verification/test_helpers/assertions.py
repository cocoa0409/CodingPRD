"""Domain assertion helpers for the HERS Rating & Code Compliance API."""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------- envelope (§2.2)
def assert_object_envelope(body: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §2.2: meta.api_request_id starts `req_`, response_type is `object`."""
    assert body["response_type"] == "object", body
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta
    return body["data"]


def assert_array_envelope(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """PRD §2.2: list responses carry `response_type` of `array`."""
    assert body["response_type"] == "array", body
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta
    return body["data"]


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    """PRD §2.2: error bodies carry `response_type` of `error` plus error_id."""
    assert body["response_type"] == "error", body
    assert body["data"]["error_id"] == expected_error_id, body
    assert isinstance(body["data"].get("message"), str), body


# --------------------------------------------------- common resource properties
def assert_common_fields(data: Dict[str, Any], *, expected_version: Optional[int] = None) -> None:
    """PRD §2.4: UUID `id`, `created_at`, `updated_at` and an integer `version`."""
    assert is_valid_uuid(data["id"]), data["id"]
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int)
    if expected_version is not None:
        assert data["version"] == expected_version, data


def assert_append_only_evidence(data: Dict[str, Any]) -> None:
    """PRD §2.4: a `DiagnosticTest` carries `id` and `created_at` only."""
    assert is_valid_uuid(data["id"]), data["id"]
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert "version" not in data, data
    assert "updated_at" not in data, data


# ---------------------------------------------------------------- numeric shape
def assert_normalized_value(actual, expected) -> None:
    """PRD §2.6: `normalized_value` is a two-decimal half-up figure."""
    assert actual == pytest.approx(float(expected), abs=0.005), (actual, expected)


def assert_index(actual, expected: int) -> None:
    """PRD §2.6: HERS index values are integers."""
    assert actual == expected, (actual, expected)


def assert_cents(actual, expected: int) -> None:
    """PRD §2.6: money is held in integer cents."""
    assert isinstance(actual, int), actual
    assert actual == expected, (actual, expected)


# --------------------------------------------------------------- rating (§3.2)
def assert_rating_dimensions(
    rating: Dict[str, Any],
    *,
    stage: Optional[str] = None,
    compliance_status: Optional[str] = None,
    qa_status: Optional[str] = None,
    registry_status: Optional[str] = None,
) -> None:
    """Check any subset of the four independent dimensions of PRD §3.2."""
    if stage is not None:
        assert rating["stage"] == stage, rating
    if compliance_status is not None:
        assert rating["compliance_status"] == compliance_status, rating
    if qa_status is not None:
        assert rating["qa_status"] == qa_status, rating
    if registry_status is not None:
        assert rating["registry_status"] == registry_status, rating


def assert_fresh_rating(rating: Dict[str, Any]) -> None:
    """PRD §3.2's opening values for a newly created rating file."""
    assert_rating_dimensions(
        rating,
        stage="PROJECTED",
        compliance_status="UNDETERMINED",
        qa_status="NOT_SELECTED",
        registry_status="NOT_SUBMITTED",
    )
    assert rating["file_locked"] is False, rating
    assert rating["compliance_path"] == "NONE", rating
    for field in (
        "confirmed_index",
        "confirmed_ach50",
        "confirmed_duct_leakage_cfm25_per_100sqft",
        "eri_target",
        "submitted_index",
        "registry_confirmation_number",
        "rejection_reason",
        "confirmed_at",
    ):
        assert rating[field] is None, (field, rating[field])


# -------------------------------------------------------------- ledgers (§2.10)
def assert_builder_ledger(
    builder: Dict[str, Any],
    *,
    certified_incentive_cents: Optional[int] = None,
    revoked_package_count: Optional[int] = None,
    open_corrective_action_count: Optional[int] = None,
    status: Optional[str] = None,
    sampling_eligible: Optional[bool] = None,
) -> None:
    if certified_incentive_cents is not None:
        assert_cents(builder["certified_incentive_cents"], certified_incentive_cents)
    if revoked_package_count is not None:
        assert builder["revoked_package_count"] == revoked_package_count, builder
    if open_corrective_action_count is not None:
        assert builder["open_corrective_action_count"] == open_corrective_action_count, builder
    if status is not None:
        assert builder["status"] == status, builder
    if sampling_eligible is not None:
        assert builder["sampling_eligible"] is sampling_eligible, builder


def assert_coverage_ledger(
    subdivision: Dict[str, Any],
    *,
    homes_count: Optional[int] = None,
    sampled_home_count: Optional[int] = None,
    unsampled_home_count: Optional[int] = None,
) -> None:
    """PRD §2.10: sampled + unsampled always sum to `homes_count`."""
    assert (
        subdivision["sampled_home_count"] + subdivision["unsampled_home_count"]
        == subdivision["homes_count"]
    ), subdivision
    if homes_count is not None:
        assert subdivision["homes_count"] == homes_count, subdivision
    if sampled_home_count is not None:
        assert subdivision["sampled_home_count"] == sampled_home_count, subdivision
    if unsampled_home_count is not None:
        assert subdivision["unsampled_home_count"] == unsampled_home_count, subdivision


def assert_sample_set_counters(
    sample_set: Dict[str, Any],
    *,
    status: Optional[str] = None,
    member_count: Optional[int] = None,
    tested_member_count: Optional[int] = None,
    represented_member_count: Optional[int] = None,
    tested_home_id: Optional[str] = ...,
    representative_index: Optional[int] = ...,
) -> None:
    if status is not None:
        assert sample_set["status"] == status, sample_set
    if member_count is not None:
        assert sample_set["member_count"] == member_count, sample_set
    if tested_member_count is not None:
        assert sample_set["tested_member_count"] == tested_member_count, sample_set
    if represented_member_count is not None:
        assert sample_set["represented_member_count"] == represented_member_count, sample_set
    if tested_home_id is not ...:
        assert sample_set["tested_home_id"] == tested_home_id, sample_set
    if representative_index is not ...:
        assert sample_set["representative_index"] == representative_index, sample_set


def assert_home_sampling_state(
    home: Dict[str, Any],
    *,
    sampling_role: Optional[str] = None,
    sample_set_id: Optional[str] = ...,
    individual_testing_required: Optional[bool] = None,
) -> None:
    if sampling_role is not None:
        assert home["sampling_role"] == sampling_role, home
    if sample_set_id is not ...:
        assert home["sample_set_id"] == sample_set_id, home
    if individual_testing_required is not None:
        assert home["individual_testing_required"] is individual_testing_required, home


# ------------------------------------------------------- rater standing (§2.11)
def assert_rater_standing(
    rater: Dict[str, Any],
    *,
    certification_status: Optional[str] = None,
    effective_certification_status: Optional[str] = None,
    qa_failure_count: Optional[int] = None,
    confirmed_rating_count: Optional[int] = None,
    qa_completed_count: Optional[int] = None,
    qa_files_owed: Optional[int] = None,
    registry_hold: Optional[bool] = None,
) -> None:
    if certification_status is not None:
        assert rater["certification_status"] == certification_status, rater
    if effective_certification_status is not None:
        assert (
            rater["effective_certification_status"] == effective_certification_status
        ), rater
    if qa_failure_count is not None:
        assert rater["qa_failure_count"] == qa_failure_count, rater
    if confirmed_rating_count is not None:
        assert rater["confirmed_rating_count"] == confirmed_rating_count, rater
    if qa_completed_count is not None:
        assert rater["qa_completed_count"] == qa_completed_count, rater
    if qa_files_owed is not None:
        assert rater["qa_files_owed"] == qa_files_owed, rater
    if registry_hold is not None:
        assert rater["registry_hold"] is registry_hold, rater


# ------------------------------------------------------------- packages (§3.9)
def assert_line_items(
    package: Dict[str, Any], expected: Sequence[Tuple[str, int]]
) -> None:
    """PRD §3.9: four `line_items` entries carrying `code` and `amount_cents`,
    recorded in the fixed ENVELOPE / DUCTS / AIR / INDEX order."""
    items = package["line_items"]
    assert [item["code"] for item in items] == [code for code, _ in expected], items
    assert [item["amount_cents"] for item in items] == [
        amount for _, amount in expected
    ], items


def assert_package_state(
    package: Dict[str, Any],
    *,
    status: Optional[str] = None,
    provisional_amount_cents: Optional[int] = None,
    certified_amount_cents: Optional[int] = ...,
    revocation_reason: Optional[str] = ...,
) -> None:
    if status is not None:
        assert package["status"] == status, package
    if provisional_amount_cents is not None:
        assert_cents(package["provisional_amount_cents"], provisional_amount_cents)
    if certified_amount_cents is not ...:
        assert package["certified_amount_cents"] == certified_amount_cents, package
    if revocation_reason is not ...:
        assert package["revocation_reason"] == revocation_reason, package


# ------------------------------------------------------------------ collections
def assert_ids(items: Iterable[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    assert [item["id"] for item in items] == list(expected_ids), items


def assert_count(items: Sequence[Any], expected: int) -> None:
    assert len(items) == expected, items
