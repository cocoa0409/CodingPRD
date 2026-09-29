"""The fifteen idle minutes a generator demands between two occupations."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TECHNICIAN_A_HEADERS

EXISTING_WINDOW = ("2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z")
INSIDE_BUFFER = ("2026-08-01T10:10:00Z", "2026-08-01T11:10:00Z")
AT_BUFFER_EDGE = ("2026-08-01T10:15:00Z", "2026-08-01T11:15:00Z")


def _generator_busy_until_ten(api):
    """One SCHEDULED surfacing window on a generator with a 15-minute buffer."""
    scenario = fixtures.surfaced_queued_job(api)
    assert scenario["machine"]["calibration_buffer_minutes"] == 15

    existing = fixtures.book_surfacing(api, scenario, *EXISTING_WINDOW)
    assert existing["status"] == "SCHEDULED"
    scenario["op_existing_id"] = existing["id"]
    scenario["job_version_after_first"] = fixtures.read_job(api, scenario["job_id"])[
        "version"
    ]
    return scenario


def _book(api, scenario, window, version=None):
    return api.create_lab_operation(
        f.create_surfacing_operation_payload(
            scenario["job_id"],
            version or scenario["job_version_after_first"],
            scenario["machine_id"],
            window[0],
            window[1],
        ),
        TECHNICIAN_A_HEADERS,
    )


def test_a_ten_minute_gap_falls_inside_the_buffer_and_conflicts(api):
    """10:10 is only ten minutes after a 10:00 end, so the machine is still idling.

    PRD 3.6: "The requested window conflicts with an existing occupation when the
    requested start is **strictly earlier** than the existing end advanced by the
    buffer, *and* the existing start is **strictly earlier** than the requested end
    advanced by the buffer."

    Design: Difficulty/resource_temporal_overlap/generator_buffer_rejects_a_ten_minute_gap_and_accepts_the_exact_fifteen_minute_boundary
    """
    scenario = _generator_busy_until_ten(api)

    validate_error(
        _book(api, scenario, INSIDE_BUFFER),
        ApiErrorId.MACHINE_WINDOW_CONFLICT.value,
        409,
    )


def test_a_start_exactly_at_the_buffered_edge_is_feasible(api):
    """10:15 is the buffered edge to the second and is therefore not a conflict.

    PRD 3.6: "Consequently a requested window that begins exactly at an existing
    window's end plus the buffer is feasible: the buffer is respected to the second,
    not to the second plus one."

    Design: Difficulty/resource_temporal_overlap/generator_buffer_rejects_a_ten_minute_gap_and_accepts_the_exact_fifteen_minute_boundary
    """
    scenario = _generator_busy_until_ten(api)
    validate_error(
        _book(api, scenario, INSIDE_BUFFER),
        ApiErrorId.MACHINE_WINDOW_CONFLICT.value,
        409,
    )

    boundary = fixtures.book_surfacing(api, scenario, *AT_BUFFER_EDGE)

    assert boundary["status"] == "SCHEDULED"
    assert boundary["window_start"] == "2026-08-01T10:15:00.000Z"
    assert boundary["machine_id"] == scenario["machine_id"]


def test_only_the_accepted_bookings_leave_rows_behind(api):
    """Two occupations exist: the original and the one at the buffered edge.

    PRD 3.6: "A booked occupation is created with `status` `SCHEDULED`, a null
    `performed_by_user_id`, a null `breakage_reason` and a null `cancel_reason`."

    Design: Difficulty/resource_temporal_overlap/generator_buffer_rejects_a_ten_minute_gap_and_accepts_the_exact_fifteen_minute_boundary
    """
    scenario = _generator_busy_until_ten(api)
    validate_error(
        _book(api, scenario, INSIDE_BUFFER),
        ApiErrorId.MACHINE_WINDOW_CONFLICT.value,
        409,
    )
    boundary = fixtures.book_surfacing(api, scenario, *AT_BUFFER_EDGE)

    operations, meta = validate_paginated(
        api.list_lab_operations(TECHNICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 2
    assert {op["id"] for op in operations} == {
        scenario["op_existing_id"],
        boundary["id"],
    }
