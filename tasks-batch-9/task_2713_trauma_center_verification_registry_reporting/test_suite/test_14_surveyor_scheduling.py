"""Surveyor bookings as an exclusive resource with a travel buffer around each window.

Two windows on the same surveyor do not merely have to avoid touching: they have to be a
full travel buffer apart, which makes a twenty-three hour gap a conflict.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiClient
from test_helpers import ApiErrorId as E
from test_helpers import (
    CycleStatus,
    CycleType,
    DEFAULT_TRAVEL_BUFFER_HOURS,
    DesignationLevel,
    SURVEYOR_1,
    assert_surveyor_booking,
    factories as f,
    fixtures as fx,
    make_verification_reviewer_headers,
)

SURVEYOR_7 = "u_surveyor_7"


def _submitted_cycle_with_one_booking(api: ApiClient):
    """A submitted national cycle already holding one full-day surveyor window."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Lakeshore Trauma",
        state_code="MI",
        designation_level=DesignationLevel.LEVEL_I,
    )
    cycle = fx.cycle_submitted(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-09-10T13:00:00Z",
    )
    first = fx.book_surveyor(
        api,
        cycle,
        surveyor_user_id=SURVEYOR_1,
        window_start="2026-09-10T08:00:00Z",
        window_end="2026-09-10T17:00:00Z",
    )
    return cycle, first


class TestSurveyorTravelBuffer:
    """The buffer is measured from the end of one window to the start of the next."""

    def test_a_twenty_three_hour_gap_conflicts_with_the_existing_window(
        self, api: ApiClient
    ) -> None:
        """The windows do not intersect, yet the buffer is short by an hour.

        Design: Difficulty/resource_temporal_overlap/surveyor_booking_buffer_rejects_twenty_three_hour_gap
        """
        cycle, first = _submitted_cycle_with_one_booking(api)
        assert_surveyor_booking(first, cycle["id"])

        refused = api.create_surveyor_booking(
            cycle["id"],
            f.surveyor_booking_payload(
                surveyor_user_id=SURVEYOR_1,
                window_start="2026-09-11T16:00:00Z",
                window_end="2026-09-11T20:00:00Z",
            ),
            make_verification_reviewer_headers(),
        )
        validate_error(refused, E.SURVEYOR_WINDOW_CONFLICT, 409)

        bookings = get_success_data(
            api.list_surveyor_bookings(
                cycle["id"],
                make_verification_reviewer_headers(),
                {"surveyor_user_id": SURVEYOR_1},
            )
        )
        assert [row["id"] for row in bookings] == [first["id"]]

    def test_a_twenty_four_hour_gap_is_accepted_on_the_same_surveyor(
        self, api: ApiClient
    ) -> None:
        """Moving the request one hour later satisfies the buffer exactly.

        Design: Difficulty/resource_temporal_overlap/surveyor_booking_buffer_rejects_twenty_three_hour_gap
        """
        cycle, first = _submitted_cycle_with_one_booking(api)

        accepted = api.create_surveyor_booking(
            cycle["id"],
            f.surveyor_booking_payload(
                surveyor_user_id=SURVEYOR_1,
                window_start="2026-09-11T17:00:00Z",
                window_end="2026-09-11T20:00:00Z",
            ),
            make_verification_reviewer_headers(),
        )
        second = validate_success(accepted, 201)
        assert_surveyor_booking(second, cycle["id"])
        assert second["travel_buffer_hours"] == DEFAULT_TRAVEL_BUFFER_HOURS

        bookings = get_success_data(
            api.list_surveyor_bookings(
                cycle["id"],
                make_verification_reviewer_headers(),
                {"surveyor_user_id": SURVEYOR_1},
            )
        )
        assert {row["id"] for row in bookings} == {first["id"], second["id"]}


class TestSurveyorWindowInterval:
    """A window is an interval, so its end cannot precede its start."""

    def test_a_window_ending_before_it_starts_is_an_invalid_interval(
        self, api: ApiClient
    ) -> None:
        """Interval sanity is checked before any conflict search runs.

        Design: Corner/validations/surveyor_window_end_before_start_returns_invalid_interval_dates
        """
        fx.anchor_clock(api)
        center = fx.create_center(
            api,
            name="Windrow Trauma",
            state_code="SD",
            designation_level=DesignationLevel.LEVEL_III,
        )
        cycle = fx.cycle_submitted(
            api,
            center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-11-18T13:00:00Z",
        )

        refused = api.create_surveyor_booking(
            cycle["id"],
            f.surveyor_booking_payload(
                surveyor_user_id=SURVEYOR_7,
                window_start="2026-11-18T17:00:00Z",
                window_end="2026-11-18T08:00:00Z",
            ),
            make_verification_reviewer_headers(),
        )
        validate_error(refused, E.INVALID_INTERVAL_DATES, 422)
        assert refused.json()["data"]["error_id"] != E.SURVEYOR_WINDOW_CONFLICT, (
            "there is nothing to conflict with: the cycle holds no bookings at all"
        )

        assert (
            get_success_data(
                api.list_surveyor_bookings(
                    cycle["id"], make_verification_reviewer_headers()
                )
            )
            == []
        )
        assert fx.get_cycle(api, cycle["id"])["status"] == CycleStatus.SUBMITTED
