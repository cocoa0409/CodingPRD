"""Temporal overlap on two resources: the buffered room and the additive render pool."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RENDER_CAPACITY_EXCEEDED,
    ERR_ROOM_SEAT_CAPACITY_EXCEEDED,
    ERR_ROOM_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_cents, assert_two_decimal
from test_helpers.constants import (
    JOB_RESERVED,
    SESSION_CANCELLED,
    SESSION_DIRECTOR_REVIEW,
    SESSION_SCHEDULED,
)
from test_helpers.test_users import DIRECTOR_HEADERS, PRODUCTION_MANAGER_HEADERS


def _active_show(client):
    return fx.active_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        master_color_space="ACEScg",
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )


def _stage_one_with_a_two_hour_incumbent(client):
    """STAGE-1 calibrated, 12 seats, 30-minute buffer, holding 09:00 -> 11:00."""
    production = _active_show(client)
    room = fx.calibrated_room(
        client,
        name="STAGE-1",
        seat_capacity=12,
        room_color_space="ACEScg",
        turnover_buffer_minutes=30,
        calibration_valid_days=30,
    )
    incumbent = fx.book_session(
        client,
        production["id"],
        room["id"],
        session_type=SESSION_DIRECTOR_REVIEW,
        window_start="2026-08-20T09:00:00Z",
        window_end="2026-08-20T11:00:00Z",
        attendee_count=6,
    )
    assert incumbent["status"] == SESSION_SCHEDULED
    return production, room, incumbent


def _sessions_in_room(client, room_id):
    """Every session stored against a room, through the published collection read."""
    return validate_paginated(
        client.list_review_sessions(
            PRODUCTION_MANAGER_HEADERS, {"screening_room_id": room_id, "limit": 100}
        )
    )


def _booking(production_id, room_id, start, end, attendee_count=4):
    return {
        "production_id": production_id,
        "screening_room_id": room_id,
        "session_type": SESSION_DIRECTOR_REVIEW,
        "window_start": start,
        "window_end": end,
        "attendee_count": attendee_count,
    }


class TestScreeningRoomTurnoverBuffer:
    def test_a_zero_gap_booking_conflicts_while_a_thirty_minute_gap_is_admitted(
        self, client
    ):
        """Against a stored 09:00 -> 11:00 session in a room with a 30-minute buffer, an
        11:00 start is refused because the requested side alone is expanded to 10:30 ->
        12:30, while an 11:30 start whose buffered window opens exactly at 11:00 is booked.

        PRD: "The **requested** window is expanded by `turnover_buffer_minutes` at both
        ends, and that expanded interval is tested against the **stored, unexpanded**
        windows of every `SCHEDULED` or `IN_PROGRESS` session already booked in the same
        room."
        PRD: "All intervals are half-open, so a session that ends exactly when another
        begins does not overlap."
        PRD: "Consequently a gap between two sessions exactly equal to
        `turnover_buffer_minutes` is legal, and any smaller gap conflicts and is refused
        with `ERR_ROOM_WINDOW_CONFLICT`."
        PRD: "The session collection read may be filtered by `production_id`,
        `screening_room_id`, `session_type` and `status`."

        Design: Difficulty/resource_temporal_overlap/screening_room_turnover_buffer_rejects_zero_gap_booking
        """
        production, room, incumbent = _stage_one_with_a_two_hour_incumbent(client)
        assert room["turnover_buffer_minutes"] == 30

        validate_error(
            client.create_review_session(
                _booking(
                    production["id"],
                    room["id"],
                    "2026-08-20T11:00:00Z",
                    "2026-08-20T12:00:00Z",
                ),
                DIRECTOR_HEADERS,
            ),
            ERR_ROOM_WINDOW_CONFLICT,
        )

        gapped = validate_success(
            client.create_review_session(
                _booking(
                    production["id"],
                    room["id"],
                    "2026-08-20T11:30:00Z",
                    "2026-08-20T12:30:00Z",
                ),
                DIRECTOR_HEADERS,
            ),
            201,
        )
        assert gapped["status"] == SESSION_SCHEDULED, (
            "a gap of exactly turnover_buffer_minutes must be admitted"
        )

        held, meta = _sessions_in_room(client, room["id"])
        assert meta["total_count"] == 2, (
            "the refused booking must not have been stored in the room"
        )
        assert sorted(row["window_start"] for row in held) == sorted(
            [incumbent["window_start"], gapped["window_start"]]
        )

    def test_cancelling_the_incumbent_frees_its_buffer_and_seats_bite_separately(
        self, client
    ):
        """Once the 09:00 -> 11:00 session is cancelled its buffer stops reserving the room,
        so a 09:00 -> 10:30 booking succeeds; the seat ceiling is an unrelated limit that a
        13th attendee trips in a window nobody else holds.

        PRD: "Sessions that are `CLOSED` or `CANCELLED` are ignored entirely by this test,
        which is why cancelling a session frees the room."
        PRD: "It accepts an optional `reason`, moves the session to `CANCELLED`, stamps
        `closed_at`, and moves **every** note of the session that is still `OPEN` to
        `WAIVED` — regardless of severity, and issuing no retake whatsoever."
        PRD: "And `attendee_count` may not exceed the room's `seat_capacity`, otherwise
        `ERR_ROOM_SEAT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/screening_room_turnover_buffer_rejects_zero_gap_booking
        """
        production, room, incumbent = _stage_one_with_a_two_hour_incumbent(client)
        validate_success(
            client.create_review_session(
                _booking(
                    production["id"],
                    room["id"],
                    "2026-08-20T11:30:00Z",
                    "2026-08-20T12:30:00Z",
                ),
                DIRECTOR_HEADERS,
            ),
            201,
        )

        cancelled = validate_success(
            client.cancel_review_session(
                incumbent["id"],
                {"reason": "Director travelling."},
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        assert cancelled["status"] == SESSION_CANCELLED
        assert cancelled["closed_at"] is not None, "cancelling stamps closed_at"

        released = validate_success(
            client.create_review_session(
                _booking(
                    production["id"],
                    room["id"],
                    "2026-08-20T09:00:00Z",
                    "2026-08-20T10:30:00Z",
                ),
                DIRECTOR_HEADERS,
            ),
            201,
        )
        assert released["status"] == SESSION_SCHEDULED, (
            "a CANCELLED session no longer reserves its buffered window"
        )

        validate_error(
            client.create_review_session(
                _booking(
                    production["id"],
                    room["id"],
                    "2026-08-21T09:00:00Z",
                    "2026-08-21T10:00:00Z",
                    attendee_count=13,
                ),
                DIRECTOR_HEADERS,
            ),
            ERR_ROOM_SEAT_CAPACITY_EXCEEDED,
        )
        _, meta = _sessions_in_room(client, room["id"])
        assert meta["total_count"] == 3, (
            "only the three accepted bookings exist in the room"
        )


FARM_START = "2026-08-10T00:00:00Z"
FARM_MID = "2026-08-10T06:00:00Z"
FARM_END = "2026-08-10T12:00:00Z"
STRADDLE_START = "2026-08-10T03:00:00Z"
STRADDLE_END = "2026-08-10T09:00:00Z"


def _reservation(pool_id, task_id, version, cores, start, end):
    return {
        "render_pool_id": pool_id,
        "shot_stage_task_id": task_id,
        "priority": "NORMAL",
        "requested_cores": cores,
        "window_start": start,
        "window_end": end,
        "frame_count": 120,
        "seconds_per_frame": 50,
        "expected_render_pool_version": version,
    }


def _farm_with_two_adjacent_reservations(client):
    """FARM-A holding 60 cores over 00:00 -> 06:00 and 60 more over 06:00 -> 12:00."""
    production = _active_show(client)
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
    fx.assign_task(client, layout["id"])
    pool = fx.create_pool(
        client, name="FARM-A", total_cores=100, cost_per_core_hour_cents=175
    )
    first = validate_success(
        client.create_render_job(
            _reservation(pool["id"], layout["id"], pool["version"], 60, FARM_START, FARM_MID),
            PRODUCTION_MANAGER_HEADERS,
        ),
        201,
    )
    after_first = fx.read_pool(client, pool["id"])
    second = validate_success(
        client.create_render_job(
            _reservation(
                pool["id"], layout["id"], after_first["version"], 60, FARM_MID, FARM_END
            ),
            PRODUCTION_MANAGER_HEADERS,
        ),
        201,
    )
    return production, shot, layout, pool, first, after_first, second


class TestRenderPoolAggregateCapacity:
    def test_a_job_starting_exactly_when_another_ends_gets_the_full_sixty_cores(
        self, client
    ):
        """Two 60-core six-hour reservations on a 100-core pool coexist because the second
        window only touches the first, so the pool carries 720.00 committed core-hours and
        the show carries both estimates.

        PRD: "A job that merely touches the request — one whose `window_end` equals the
        request's `window_start` — does not intersect, and jobs that are `COMPLETED`,
        `FAILED`, `CANCELLED` or `PREEMPTED` are excluded entirely."
        PRD: "The job's `committed_core_hours` is its `requested_cores` multiplied by the
        length of its window expressed in hours, carried to two decimal places."
        PRD: "Both computed figures are derived from the pool's reservations:
        `committed_core_hours` is the sum of `committed_core_hours` over the pool's jobs
        whose `status` is `RESERVED`, carried to two decimal places, and
        `reserved_job_count` is the count of those same jobs."

        Design: Difficulty/resource_temporal_overlap/render_pool_aggregate_capacity_allows_adjacent_windows
        """
        production, _, _, pool, first, after_first, second = (
            _farm_with_two_adjacent_reservations(client)
        )

        assert first["status"] == JOB_RESERVED
        assert_cents(first["estimated_cost_cents"], 17520, "estimated_cost_cents")
        assert_two_decimal(first["committed_core_hours"], 360.00, "committed_core_hours")
        assert_two_decimal(
            after_first["committed_core_hours"], 360.00, "pool committed_core_hours"
        )
        assert after_first["reserved_job_count"] == 1
        assert after_first["version"] > pool["version"]

        assert second["status"] == JOB_RESERVED, (
            "the windows touch at 06:00, so the full 60 cores are free again"
        )
        assert_cents(second["estimated_cost_cents"], 17520, "estimated_cost_cents")
        assert second["preempted_by_render_job_id"] is None, (
            "an admission that fits never displaces anything"
        )

        after_second = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            after_second["committed_core_hours"], 720.00, "pool committed_core_hours"
        )
        assert after_second["reserved_job_count"] == 2
        assert after_second["version"] > after_first["version"]

        assert_cents(
            fx.read_production(client, production["id"])["render_committed_cents"],
            35040,
            "render_committed_cents",
        )

    def test_the_straddling_request_is_measured_against_peak_and_refused(self, client):
        """A 03:00 -> 09:00 request intersects both reservations, so peak usage is 60 against
        a NORMAL ceiling of 90 and only 30 cores are available: 60 is refused and leaves no
        trace, while exactly 30 is admitted.

        PRD: "At each such instant the system sums the `requested_cores` of every candidate
        job whose interval covers that instant — that is, whose `window_start` is at or
        before the instant and whose `window_end` is strictly after it — and the peak usage
        is the largest of those sums."
        PRD: "Third, available capacity is the usable ceiling minus that peak usage."
        PRD: "If not, and the request's `priority` is anything other than `CRITICAL`, the
        reservation is refused with `ERR_RENDER_CAPACITY_EXCEEDED`."
        PRD: "A hundred-core pool therefore keeps 10 cores free from a `NORMAL` request and
        20 from a `LOW` one, while a `HIGH` or `CRITICAL` request may use all 100."

        Design: Difficulty/resource_temporal_overlap/render_pool_aggregate_capacity_allows_adjacent_windows
        """
        production, shot, layout, pool, _, _, _ = _farm_with_two_adjacent_reservations(
            client
        )
        before = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            before["committed_core_hours"], 720.00, "pool committed_core_hours"
        )

        validate_error(
            client.create_render_job(
                _reservation(
                    pool["id"],
                    layout["id"],
                    before["version"],
                    60,
                    STRADDLE_START,
                    STRADDLE_END,
                ),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_RENDER_CAPACITY_EXCEEDED,
        )

        after_refusal = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            after_refusal["committed_core_hours"], 720.00, "pool committed_core_hours"
        )
        assert after_refusal["reserved_job_count"] == 2
        assert after_refusal["version"] == before["version"], (
            "a refused reservation is not a write and must not advance the pool version"
        )
        assert_cents(
            fx.read_production(client, production["id"])["render_committed_cents"],
            35040,
            "render_committed_cents",
        )

        fitting = validate_success(
            client.create_render_job(
                _reservation(
                    pool["id"],
                    layout["id"],
                    after_refusal["version"],
                    30,
                    STRADDLE_START,
                    STRADDLE_END,
                ),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert fitting["status"] == JOB_RESERVED, (
            "exactly the available 30 cores must be admitted over the same window"
        )
        assert_cents(fitting["estimated_cost_cents"], 8760, "estimated_cost_cents")
        assert_two_decimal(fitting["committed_core_hours"], 180.00, "committed_core_hours")

        settled_pool = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            settled_pool["committed_core_hours"], 900.00, "pool committed_core_hours"
        )
        assert settled_pool["reserved_job_count"] == 3
        assert_cents(
            fx.read_shot(client, shot["id"])["render_cost_committed_cents"],
            43800,
            "render_cost_committed_cents",
        )
