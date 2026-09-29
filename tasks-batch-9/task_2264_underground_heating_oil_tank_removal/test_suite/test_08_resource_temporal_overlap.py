"""Two shared resources whose occupancy is decided by interval arithmetic."""
import pytest

from test_helpers import (
    fixtures as fx,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import custody_event_payload, work_order_payload
from test_helpers.test_users import (
    PROJECT_COORDINATOR,
    make_lab_analyst_headers,
)


class TestCrewSymmetricBuffer:
    #: The first booking on the crew's calendar ends here.
    FIRST_BOOKING_END = "2026-08-06T21:00:00Z"
    #: Sixty minutes after that end — inside the 90-minute allowance.
    TOO_SOON_START = "2026-08-06T22:00:00Z"
    TOO_SOON_END = "2026-08-07T02:00:00Z"
    #: Exactly ninety minutes after that end.
    JUST_LATE_ENOUGH_START = "2026-08-06T22:30:00Z"
    JUST_LATE_ENOUGH_END = "2026-08-07T02:30:00Z"
    #: The second project never had a sweep survey, so it has no recommendation and
    #: every method it books is an override that must be justified.
    OVERRIDE_REASON = "second site shares the crew for the same haul window"

    def _crew_holding_one_booking_and_a_second_site(self):
        ctx = fx.project_with_booked_work_order()
        other_property = fx.create_property(street_address="52 Quarry Ridge Road")
        ctx["other_property"] = other_property
        ctx["other_project"] = fx.create_project(other_property["id"])
        return ctx

    def _book_second_site(self, api, ctx, start, end):
        return api.create_work_order(
            work_order_payload(
                ctx["other_project"]["id"],
                ctx["crew"]["id"],
                scheduled_start_at=start,
                scheduled_end_at=end,
                method_override_reason=self.OVERRIDE_REASON,
            ),
            PROJECT_COORDINATOR,
        )

    def test_a_gap_shorter_than_the_buffer_collides_with_the_existing_booking(
        self, api
    ):
        """PRD §3.4: "The booking is refused with `ERR_CREW_BOOKING_CONFLICT` when, for any candidate, the requested start minus the buffer falls strictly before that candidate's end **and** that candidate's start falls strictly before the requested end plus the buffer."
        PRD §3.4: "That buffer is the travel-and-decontamination allowance the scheduler must leave on both ends of any booking the crew takes, and it is applied symmetrically."
        PRD §3.4: "The overlap test therefore compares the *requested* interval, expanded by the crew's `mobilization_buffer_minutes` on both ends, against the *raw* intervals of the crew's existing bookings."

        Design: Difficulty/resource_temporal_overlap/crew_symmetric_buffer_rejects_gap_below_ninety_minutes
        """
        ctx = self._crew_holding_one_booking_and_a_second_site()

        assert ctx["crew"]["mobilization_buffer_minutes"] == 90, (
            "the crew under test must carry the default allowance, got "
            f"{ctx['crew']['mobilization_buffer_minutes']}"
        )
        assert parse_instant(ctx["work_order"]["scheduled_end_at"]) == parse_instant(
            self.FIRST_BOOKING_END
        ), (
            "the existing booking must end where the arithmetic assumes, got "
            f"{ctx['work_order']['scheduled_end_at']}"
        )

        response = self._book_second_site(
            api, ctx, self.TOO_SOON_START, self.TOO_SOON_END
        )
        validate_error(response, ApiErrorId.ERR_CREW_BOOKING_CONFLICT.value, 409)

    def test_a_gap_of_exactly_the_buffer_is_accepted_and_the_crew_holds_both(
        self, api
    ):
        """PRD §3.4: "Both comparisons are strict, so with the default 90-minute buffer — an hour and a half of travel and decontamination — a new booking that begins exactly 90 minutes after an existing booking ends is accepted, while one beginning 89 minutes after is not."
        PRD §3.4: "A work order is created with `field_status` at `SCHEDULED` and `billing_status` at `UNBILLED`. Work orders may be listed with optional `tank_project_id`, `crew_id`, `field_status` and `billing_status` filters."

        Design: Difficulty/resource_temporal_overlap/crew_symmetric_buffer_rejects_gap_below_ninety_minutes
        """
        ctx = self._crew_holding_one_booking_and_a_second_site()
        self._book_second_site(api, ctx, self.TOO_SOON_START, self.TOO_SOON_END)

        accepted = validate_success(
            self._book_second_site(
                api, ctx, self.JUST_LATE_ENOUGH_START, self.JUST_LATE_ENOUGH_END
            ),
            201,
        )
        second = fx.read_work_order(accepted["id"])
        assert second["field_status"] == "SCHEDULED", (
            f"the accepted booking opens in SCHEDULED, got {second['field_status']}"
        )
        assert parse_instant(second["scheduled_start_at"]) == parse_instant(
            self.JUST_LATE_ENOUGH_START
        ), (
            "the booking must be stored at the requested start, got "
            f"{second['scheduled_start_at']}"
        )
        assert fx.read_work_order(ctx["work_order"]["id"])["field_status"] == "SCHEDULED", (
            "the original booking is untouched by the second site's request"
        )

        _, meta = validate_paginated(
            api.list_work_orders(
                PROJECT_COORDINATOR, params={"crew_id": ctx["crew"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            "the crew holds exactly the two accepted bookings, got "
            f"{meta['total_count']}"
        )


class TestLaboratoryClosedAnalysisWindow:
    #: Two aliquots are received here, so both windows run to the instant below.
    OCCUPIED_FROM = "2026-08-06T13:00:00Z"
    #: 72 hours later — still inside both windows, because the interval is closed.
    WINDOW_CLOSING_INSTANT = "2026-08-09T13:00:00Z"
    #: One second past the closing endpoint, so both slots are free.
    WINDOW_RELEASED_INSTANT = "2026-08-09T13:00:01Z"

    def _laboratory_at_capacity(self):
        ctx = fx.project_at_sampling()
        for key, point in (
            ("sample_a", "TANK_BOTTOM"),
            ("sample_b", "NORTH_SIDEWALL"),
            ("sample_c", "SOUTH_SIDEWALL"),
        ):
            ctx[key] = fx.create_sample(
                ctx["project"]["id"],
                ctx["work_order"]["id"],
                ctx["laboratory"]["id"],
                sample_point=point,
                depth_inches=96,
            )
            fx.dispatch_sample(ctx[key]["id"])
        ctx["sample_a"] = fx.receive_sample(
            ctx["sample_a"]["id"], ctx["laboratory"]["id"]
        )
        ctx["sample_b"] = fx.receive_sample(
            ctx["sample_b"]["id"], ctx["laboratory"]["id"]
        )
        return ctx

    def test_receipt_exactly_at_the_closing_endpoint_finds_both_slots_occupied(
        self, api
    ):
        """PRD §3.6: "Third, the lab's analysis capacity must be free. Count the lab's other samples — same `laboratory_id`, `status` at `AT_LAB` — whose analysis window contains the receipt instant, where a window runs from that sample's `received_at` to `received_at` plus the lab's `committed_turnaround_hours` and **both endpoints count as inside**."
        PRD §2.10: "In the one place where the convention runs the other way, it does so explicitly: the abandonment recommendation flips at a score of *at least* 55.00, and the laboratory analysis-window occupancy test uses a **closed** interval whose two endpoints both count as occupied."
        PRD §3.6: "`max_concurrent_analyses` defaults to 2 and is the aggregate number of overlapping analysis windows the lab can sustain; it must be at least 1, while the two hour figures must both be strictly greater than zero."

        Design: Difficulty/resource_temporal_overlap/laboratory_aggregate_capacity_uses_closed_analysis_window
        """
        ctx = self._laboratory_at_capacity()

        assert parse_instant(ctx["sample_a"]["received_at"]) == parse_instant(

            self.OCCUPIED_FROM

        ), (
            "the first window must open where the arithmetic assumes, got "
            f"{ctx['sample_a']['received_at']}"
        )
        assert fx.read_laboratory(ctx["laboratory"]["id"])[
            "committed_turnaround_hours"
        ] == pytest.approx(72.0, abs=0.01), (
            "the slot length under test is the default 72-hour commitment"
        )

        fx.set_clock(self.WINDOW_CLOSING_INSTANT)
        response = api.create_custody_event(
            ctx["sample_c"]["id"],
            custody_event_payload("RECEIVE"),
            make_lab_analyst_headers(ctx["laboratory"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED.value, 409)
        assert fx.read_sample(ctx["sample_c"]["id"])["status"] == "IN_TRANSIT", (
            "a refused receipt leaves the aliquot with the courier"
        )

    def test_receipt_one_second_after_the_endpoint_finds_the_slots_released(self, api):
        """PRD §3.6: "If that count has already reached `max_concurrent_analyses`, the receipt is refused with `ERR_LAB_CAPACITY_EXCEEDED`; it proceeds only while the count is strictly below capacity."
        PRD §3.6: "`committed_turnaround_hours` defaults to 72 and serves double duty — it is both the contractual turnaround the lab promises and the length of time each sample occupies one of the lab's analysis slots."
        PRD §3.6: "On success `received_at` is stamped from the logical clock, starting this sample's own analysis window."

        Design: Difficulty/resource_temporal_overlap/laboratory_aggregate_capacity_uses_closed_analysis_window
        """
        ctx = self._laboratory_at_capacity()
        fx.set_clock(self.WINDOW_CLOSING_INSTANT)
        api.create_custody_event(
            ctx["sample_c"]["id"],
            custody_event_payload("RECEIVE"),
            make_lab_analyst_headers(ctx["laboratory"]["id"]),
        )

        fx.set_clock(self.WINDOW_RELEASED_INSTANT)
        received = fx.receive_sample(ctx["sample_c"]["id"], ctx["laboratory"]["id"])
        assert received["status"] == "AT_LAB", (
            "past the closing endpoint the slots are free, got "
            f"{received['status']}"
        )
        assert parse_instant(received["received_at"]) == parse_instant(
            self.WINDOW_RELEASED_INSTANT
        ), (
            "the receipt instant is stamped from the logical clock, got "
            f"{received['received_at']}"
        )
        assert received["holding_time_elapsed_hours"] == pytest.approx(72.0, abs=0.01), (
            "72 hours and one second rounds half up to 72.0 hours, got "
            f"{received['holding_time_elapsed_hours']}"
        )

        assert fx.read_sample(ctx["sample_a"]["id"])["status"] == "AT_LAB", (
            "the two earlier aliquots are still awaiting their results"
        )
        assert parse_instant(fx.read_sample(ctx["sample_a"]["id"])["received_at"]) == parse_instant(
            self.OCCUPIED_FROM
        ), (
            "their own receipt instants are unchanged by the third receipt"
        )
        assert fx.read_sample(ctx["sample_b"]["id"])["status"] == "AT_LAB", (
            "the second aliquot likewise stays at the bench"
        )
