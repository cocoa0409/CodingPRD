"""A generator that is both down and already busy for the requested window."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import MANAGER_A_HEADERS, TECHNICIAN_A_HEADERS

CONFLICTING_START = "2026-08-01T09:30:00Z"
CONFLICTING_END = "2026-08-01T10:30:00Z"


def _down_generator_with_a_scheduled_window(api):
    """GEN-1 occupied from 09:00 to 10:00 and then taken out of service."""
    scenario = fixtures.surfaced_queued_job(api)
    first = fixtures.book_surfacing(api, scenario)
    scenario["op_first_id"] = first["id"]
    assert first["status"] == "SCHEDULED"

    scenario["job_version_before_rejections"] = fixtures.read_job(
        api, scenario["job_id"]
    )["version"]

    machine = validate_success(
        api.patch_lab_machine_status(
            scenario["machine_id"], {"status": "DOWN"}, MANAGER_A_HEADERS
        )
    )
    assert machine["status"] == "DOWN"
    return scenario


def _conflicting_booking(api, scenario):
    return api.create_lab_operation(
        f.create_surfacing_operation_payload(
            scenario["job_id"],
            scenario["job_version_before_rejections"],
            scenario["machine_id"],
            CONFLICTING_START,
            CONFLICTING_END,
        ),
        TECHNICIAN_A_HEADERS,
    )


def test_the_standing_answer_is_given_before_the_calendar_answer(api):
    """A down machine is reported as down, never as busy.

    PRD 3.6: "Checking availability before the calendar in both cases means a down
    machine is reported as down rather than as busy."

    Design: Difficulty/priority_pair_validation_conflict/down_machine_with_a_conflicting_window_reports_machine_not_available
    """
    scenario = _down_generator_with_a_scheduled_window(api)

    error = validate_error(
        _conflicting_booking(api, scenario),
        ApiErrorId.MACHINE_NOT_AVAILABLE.value,
        409,
    )

    assert error["error_id"] != ApiErrorId.MACHINE_WINDOW_CONFLICT.value


def test_the_calendar_answer_surfaces_once_the_machine_is_back_in_service(api):
    """The very same window was already conflicting while the machine was down.

    PRD 3.6: "For surfacing, the machine's `status` must be `AVAILABLE`, and a
    machine on `CALIBRATION_HOLD` or `DOWN` yields `ERR_MACHINE_NOT_AVAILABLE`; only
    if the machine is available is its calendar consulted, and a conflicting window
    yields `ERR_MACHINE_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/down_machine_with_a_conflicting_window_reports_machine_not_available
    """
    scenario = _down_generator_with_a_scheduled_window(api)
    validate_error(
        _conflicting_booking(api, scenario),
        ApiErrorId.MACHINE_NOT_AVAILABLE.value,
        409,
    )

    machine = validate_success(
        api.patch_lab_machine_status(
            scenario["machine_id"], {"status": "AVAILABLE"}, MANAGER_A_HEADERS
        )
    )
    assert machine["status"] == "AVAILABLE"

    validate_error(
        _conflicting_booking(api, scenario),
        ApiErrorId.MACHINE_WINDOW_CONFLICT.value,
        409,
    )


def test_neither_rejected_booking_creates_a_row_or_touches_the_job(api):
    """One occupation exists throughout and the job's version never moves.

    PRD 3.6: "Booking increments the job's `version` by 1 — which is precisely why a
    client that books two occupations back to back must re-read the job between
    them."

    Design: Difficulty/priority_pair_validation_conflict/down_machine_with_a_conflicting_window_reports_machine_not_available
    """
    scenario = _down_generator_with_a_scheduled_window(api)
    validate_error(
        _conflicting_booking(api, scenario),
        ApiErrorId.MACHINE_NOT_AVAILABLE.value,
        409,
    )
    validate_success(
        api.patch_lab_machine_status(
            scenario["machine_id"], {"status": "AVAILABLE"}, MANAGER_A_HEADERS
        )
    )
    validate_error(
        _conflicting_booking(api, scenario),
        ApiErrorId.MACHINE_WINDOW_CONFLICT.value,
        409,
    )

    operations, meta = validate_paginated(
        api.list_lab_operations(TECHNICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 1
    assert operations[0]["id"] == scenario["op_first_id"]

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["version"] == scenario["job_version_before_rejections"]
