"""Domain assertion helpers.

Each helper encodes an invariant the PRD states in prose, so a test can name the
invariant once instead of restating the arithmetic.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from prd_bench_local_runner.testing import validate_paginated, validate_success

from .constants import (
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_SUBSIDY_RESTRICTED,
    PROGRAM_STATUS_SUSPENDED,
)


# --- Envelope ---------------------------------------------------------------
def assert_error_envelope_shape(response) -> Dict[str, Any]:
    """The error envelope carries exactly the two documented data keys.

    The PRD pins both halves: "The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`" and the error `data`
    object holds `error_id` and `message`.
    """
    body = response.json()
    assert body["response_type"] == "error", body
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, meta
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_"), meta
    data = body["data"]
    assert set(data.keys()) == {"error_id", "message"}, data
    assert isinstance(data["error_id"], str) and data["error_id"], data
    assert isinstance(data["message"], str) and data["message"], data
    return data


def assert_object_envelope(response, expected_status: int = 200) -> Dict[str, Any]:
    """A single-resource response: `response_type` of "object" plus request meta."""
    body = response.json()
    assert response.status_code == expected_status, (response.status_code, body)
    assert body["response_type"] == "object", body
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
    assert isinstance(body["data"], dict), body
    return body["data"]


def assert_list_window(response, expected_total: int) -> List[Dict[str, Any]]:
    """A list response whose `total_count` counts matching rows before windowing."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (meta, rows)
    return rows


def assert_pagination_meta(
    response, expected_limit: int, expected_offset: int, expected_total: int, expected_has_more: bool
) -> List[Dict[str, Any]]:
    rows, meta = validate_paginated(response)
    assert meta["limit"] == expected_limit, meta
    assert meta["offset"] == expected_offset, meta
    assert meta["total_count"] == expected_total, meta
    assert meta["has_more"] is expected_has_more, meta
    return rows


# --- Identity and versioning ----------------------------------------------
def assert_append_only_row(row: Dict[str, Any]) -> None:
    """A cost entry "carries `id` and `created_at` only".

    It has neither `updated_at` nor `version`, which is also why it can never be
    guarded by optimistic concurrency.
    """
    assert "id" in row, row
    assert "created_at" in row, row
    assert "updated_at" not in row, row
    assert "version" not in row, row


def assert_version_bumped_by(before: int, after: int, expected_bumps: int) -> None:
    """`version` "increases by exactly 1 on every accepted mutation of that row"."""
    assert after == before + expected_bumps, (before, after, expected_bumps)


# --- The conserved subsidy pool -------------------------------------------
def assert_pool_identity(program: Dict[str, Any]) -> None:
    """Pool equals available plus committed plus disbursed, with no rounding."""
    assert (
        program["subsidy_pool_cents"]
        == program["subsidy_available_cents"]
        + program["subsidy_committed_cents"]
        + program["subsidy_disbursed_cents"]
    ), program


def assert_posture(program: Dict[str, Any]) -> None:
    """`program_posture` is derived, never supplied."""
    if program["status"] == PROGRAM_STATUS_SUSPENDED:
        expected = POSTURE_FROZEN
    elif program["subsidy_available_cents"] == 0:
        expected = POSTURE_SUBSIDY_RESTRICTED
    else:
        expected = POSTURE_OPEN
    assert program["program_posture"] == expected, program


def assert_pool_state(
    program: Dict[str, Any],
    pool_cents: Optional[int] = None,
    committed_cents: Optional[int] = None,
    disbursed_cents: Optional[int] = None,
    available_cents: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    """Assert the named pool buckets, then the identity and the derived posture."""
    if pool_cents is not None:
        assert program["subsidy_pool_cents"] == pool_cents, program
    if committed_cents is not None:
        assert program["subsidy_committed_cents"] == committed_cents, program
    if disbursed_cents is not None:
        assert program["subsidy_disbursed_cents"] == disbursed_cents, program
    if available_cents is not None:
        assert program["subsidy_available_cents"] == available_cents, program
    if posture is not None:
        assert program["program_posture"] == posture, program
    assert_pool_identity(program)
    assert_posture(program)


# --- The sweat equity ledger ----------------------------------------------
def assert_hours_equal(actual: Any, expected: float) -> None:
    """Hours are decimal numbers carried to two decimal places."""
    assert actual is not None, "expected an hour figure, found null"
    assert abs(float(actual) - expected) < 1e-9, (actual, expected)


def assert_ledger_matches_entries(household: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> None:
    """The household ledger equals the sum of `hours_credited` over CREDITED and
    REVERSED entries."""
    total = 0.0
    for entry in entries:
        if entry["status"] in ("CREDITED", "REVERSED"):
            total += float(entry["hours_credited"] or 0.0)
    assert_hours_equal(household["sweat_equity_credited_hours"], round(total + 0.0, 2))


def assert_two_state_dimensions(
    household: Dict[str, Any], selection_status: str, partnership_readiness: str
) -> None:
    """The two dimensions of a household move on their own schedules."""
    assert household["selection_status"] == selection_status, household
    assert household["partnership_readiness"] == partnership_readiness, household


def assert_application_dimensions(application: Dict[str, Any], status: str, lien_status: str) -> None:
    assert application["status"] == status, application
    assert application["lien_status"] == lien_status, application


# --- Volunteer committed hours -------------------------------------------
def assert_committed_hours(volunteer: Dict[str, Any], expected: float, strikes: Optional[int] = None) -> None:
    """Committed volunteer hours are a conserved quantity."""
    assert_hours_equal(volunteer["assigned_hours_committed"], expected)
    if strikes is not None:
        assert volunteer["no_show_strikes"] == strikes, volunteer


# --- Read-back helper ----------------------------------------------------
def read_version(response) -> Tuple[str, int]:
    """Return the (id, version) pair of a single-resource response."""
    data = validate_success(response)
    return data["id"], data["version"]
