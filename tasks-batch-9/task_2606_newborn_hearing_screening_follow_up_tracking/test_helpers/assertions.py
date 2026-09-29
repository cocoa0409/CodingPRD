"""Domain assertions shared across the suite."""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from . import clock
from .types import JsonDict


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------


def assert_envelope(response, expected_response_type: str) -> JsonDict:
    """Assert the shared envelope is present and well formed."""
    body = response.json()
    assert "meta" in body, "response is missing meta"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), meta
    assert body.get("response_type") == expected_response_type, body.get("response_type")
    return body


def assert_error_envelope(response, expected_error_id: str) -> JsonDict:
    """Assert an error response carries the error envelope and the expected id."""
    body = response.json()
    assert body.get("response_type") == "error", body
    data = validate_error(response, expected_error_id)
    assert isinstance(data.get("message"), str) and data["message"], data
    return data


def assert_created(response) -> JsonDict:
    """Assert a creation succeeded with HTTP 201 and return its data object."""
    return validate_success(response, 201)


def assert_ok(response) -> JsonDict:
    """Assert a non-creation operation succeeded with HTTP 200."""
    return validate_success(response, 200)


def assert_total_count(response, expected: int) -> List[JsonDict]:
    """Assert a list response reports ``expected`` matching rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, "total_count {0} != {1}".format(
        meta["total_count"], expected
    )
    return rows


def assert_page(response, expected_rows: int, total_count: int, has_more: bool):
    rows, meta = validate_paginated(response)
    assert len(rows) == expected_rows, "page carried {0} rows".format(len(rows))
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta
    return rows, meta


def assert_created_at_ascending(rows: List[JsonDict]) -> None:
    """Assert rows arrive in ascending ``created_at`` order."""
    stamps = [clock.parse(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "rows are not in ascending created_at order"


# ---------------------------------------------------------------------------
# record properties
# ---------------------------------------------------------------------------


def assert_record_identity(row: JsonDict) -> None:
    """Every record carries a UUID ``id`` and an ISO 8601 ``created_at``."""
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]


def assert_versioned(row: JsonDict, expected_version: int) -> None:
    assert row["version"] == expected_version, "version {0} != {1}".format(
        row["version"], expected_version
    )
    assert is_iso8601_timestamp(row["updated_at"]), row


def assert_append_only(row: JsonDict) -> None:
    """An append-only record carries neither ``updated_at`` nor ``version``."""
    assert "version" not in row, "append-only record exposes a version field"
    assert "updated_at" not in row, "append-only record exposes an updated_at field"


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    assert actual is not None, "expected an instant, found null"
    assert clock.same_instant(actual, expected), "{0} != {1}".format(actual, expected)


def assert_nulls(row: JsonDict, field_names: List[str]) -> None:
    for field in field_names:
        assert row.get(field, None) is None, "{0} should be null, found {1!r}".format(
            field, row.get(field)
        )


# ---------------------------------------------------------------------------
# domain-specific
# ---------------------------------------------------------------------------


def assert_risk(row: JsonDict, score: int, band: str) -> None:
    """Assert the stored loss-to-follow-up score and its band."""
    assert row["ltf_risk_score"] == score, "ltf_risk_score {0} != {1}".format(
        row["ltf_risk_score"], score
    )
    assert row["priority_band"] == band, "priority_band {0} != {1}".format(
        row["priority_band"], band
    )


def assert_slot_capacity(
    slot: JsonDict, booked_count: int, remaining_capacity: int, status: str
) -> None:
    assert slot["booked_count"] == booked_count, slot
    assert slot["remaining_capacity"] == remaining_capacity, slot
    assert slot["status"] == status, slot
    assert slot["remaining_capacity"] >= 0, slot


def assert_episode_state(
    episode: JsonDict,
    status: str,
    closure_reason: Optional[str] = None,
    benchmark_days: Optional[int] = None,
    attempt_count: Optional[int] = None,
    timeliness_status: Optional[str] = None,
) -> None:
    assert episode["status"] == status, "episode status {0} != {1}".format(
        episode["status"], status
    )
    if closure_reason is not None:
        assert episode["closure_reason"] == closure_reason, episode
    if timeliness_status is not None:
        assert episode["timeliness_status"] == timeliness_status, (
            "episode timeliness_status {0} != {1}".format(
                episode.get("timeliness_status"), timeliness_status
            )
        )
    if benchmark_days is not None:
        assert episode["benchmark_days"] == benchmark_days, episode
    if attempt_count is not None:
        assert episode["attempt_count"] == attempt_count, episode


def assert_infant_dimensions(
    infant: JsonDict, screening_status: str, intervention_status: str
) -> None:
    assert infant["screening_status"] == screening_status, infant["screening_status"]
    assert infant["intervention_status"] == intervention_status, infant["intervention_status"]


def assert_facility_ledger(
    facility: JsonDict,
    penalty_points_balance: Optional[int] = None,
    reporting_compliance_status: Optional[str] = None,
    navigation_budget_units_remaining: Optional[int] = None,
    manual_adjustment_points_total: Optional[int] = None,
) -> None:
    if penalty_points_balance is not None:
        assert facility["penalty_points_balance"] == penalty_points_balance, facility
    if reporting_compliance_status is not None:
        assert facility["reporting_compliance_status"] == reporting_compliance_status, facility
    if navigation_budget_units_remaining is not None:
        assert (
            facility["navigation_budget_units_remaining"] == navigation_budget_units_remaining
        ), facility
    if manual_adjustment_points_total is not None:
        assert facility["manual_adjustment_points_total"] == manual_adjustment_points_total, facility


def assert_budget_conservation(facility: JsonDict, tasks: List[JsonDict]) -> None:
    """Remaining budget plus every live reservation equals the total budget."""
    live = [t for t in tasks if t["status"] in ("UNASSIGNED", "OPEN", "COMPLETED")]
    reserved = sum(task["units_reserved"] for task in live)
    assert (
        facility["navigation_budget_units_remaining"] + reserved
        == facility["navigation_budget_units_total"]
    ), "remaining {0} + reserved {1} != total {2}".format(
        facility["navigation_budget_units_remaining"],
        reserved,
        facility["navigation_budget_units_total"],
    )


def assert_rate(actual: Optional[float], expected: Optional[float]) -> None:
    """Compare a four-decimal component rate, or assert both sides are null."""
    if expected is None:
        assert actual is None, "expected a null rate, found {0!r}".format(actual)
        return
    assert actual is not None, "expected {0}, found null".format(expected)
    assert actual == pytest.approx(expected, abs=0.00005), "{0} != {1}".format(actual, expected)


def assert_score(actual: Optional[float], expected: Optional[float]) -> None:
    """Compare a two-decimal published score, or assert both sides are null."""
    if expected is None:
        assert actual is None, "expected a null score, found {0!r}".format(actual)
        return
    assert actual is not None, "expected {0}, found null".format(expected)
    assert actual == pytest.approx(expected, abs=0.01), "{0} != {1}".format(actual, expected)


def assert_timeliness_panel(panel: JsonDict, **expected: Any) -> None:
    """Assert the named fields of the timeliness panel."""
    for field, value in expected.items():
        assert field in panel, "timeliness panel is missing {0}".format(field)
        assert panel[field] == value, "{0} {1} != {2}".format(field, panel[field], value)
