"""Crew reservations, aggregate per-day capacity and the installation handoff.

PRD §3.8 counts booking days on a half-open interval, allows two bookings to share
a day within the crew's limit, and stamps every warranty clock at handoff.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

INDIANA_CREW = {
    "crew_code": "CRW-IN-1",
    "contractor_name": "Hoosier Refrigeration",
    "service_region_codes": ["IN"],
    "daily_case_capacity": 6,
}


class TestBookingIntervals:
    """PRD §3.8 — day counts and the delivery-and-remodel envelope."""

    def test_01_a_single_day_booking_counts_exactly_one_day(self, api):
        """A booking from the 17th to the 18th occupies only the 17th.

        PRD §3.8: "Its `day_count` is the number of whole UTC days that fall at
        or after `start_date` and strictly before `end_date`; because the
        exclusive end must be strictly later than the start, `day_count` is
        always at least 1."

        Design: Corner/calculations/install_booking_half_open_single_day_counts_one_day
        """
        ctx = setup_booked_shipment(create_booking=False)

        booking = validate_success(
            book_crew(
                ctx,
                start_date="2026-09-17",
                end_date="2026-09-18",
                cases_committed=1,
            ),
            expected_status=201,
        )
        assert_install_booking(booking)
        assert booking["status"] == "BOOKED"
        assert booking["day_count"] == 1
        assert booking["cases_committed"] == 1

        crew = validate_success(
            api.get_install_crew(
                ctx["install_crew"]["id"], TEST_USERS["logistics_coordinator_headers"]
            )
        )
        assert crew["committed_case_days"] == 1

    def test_02_booking_a_crew_that_does_not_serve_the_region_is_rejected(self, api):
        """An Indiana-only crew cannot be reserved for an Ohio store.

        PRD §3.8: "At rank 31 the `region_code` of the shipment's plan must be a
        member of the crew's `service_region_codes`, else
        `ERR_CREW_REGION_NOT_SERVED` (HTTP 422)."

        Design: Corner/validations/install_booking_for_crew_not_serving_region_rejected
        """
        ctx = setup_booked_shipment(create_booking=False, crew_overrides=INDIANA_CREW)
        assert ctx["store_plan"]["region_code"] == "OH"

        response = book_crew(ctx)
        validate_error(response, ApiErrorId.ERR_CREW_REGION_NOT_SERVED.value)

        crew = validate_success(
            api.get_install_crew(
                ctx["install_crew"]["id"], TEST_USERS["logistics_coordinator_headers"]
            )
        )
        assert crew["committed_case_days"] == 0

    def test_03_booking_end_one_day_past_the_remodel_window_is_accepted(self, api):
        """The exclusive end may equal the day after the window's last day.

        PRD §3.8: "the exclusive end is allowed to equal the day after the
        window's last day precisely so that a crew can work the final remodel
        day."

        Design: Difficulty/boundary_precision_check/booking_end_date_exactly_one_day_past_remodel_window_end_accepted
        """
        ctx = setup_booked_shipment(create_booking=False)
        assert ctx["store_plan"]["remodel_window_end"].startswith("2026-09-27")

        accepted = validate_success(
            book_crew(
                ctx,
                start_date="2026-09-17",
                end_date="2026-09-28",
                cases_committed=1,
            ),
            expected_status=201,
        )
        assert accepted["day_count"] == 11
        assert accepted["status"] == "BOOKED"
        assert validate_success(
            api.get_install_crew(
                ctx["install_crew"]["id"], TEST_USERS["logistics_coordinator_headers"]
            )
        )["committed_case_days"] == 11

        rejected = book_crew(
            ctx,
            start_date="2026-09-17",
            end_date="2026-09-29",
            cases_committed=1,
        )
        validate_error(rejected, ApiErrorId.ERR_BOOKING_OUTSIDE_REMODEL_WINDOW.value)

        assert validate_success(
            api.get_install_crew(
                ctx["install_crew"]["id"], TEST_USERS["logistics_coordinator_headers"]
            )
        )["committed_case_days"] == 11, "the rejected booking committed nothing"

    def test_04_booking_start_before_the_delivery_date_is_rejected(self, api):
        """A crew cannot start the day before the trailer arrives.

        PRD §3.8: "At rank 30 the booking must sit inside the
        delivery-and-remodel envelope: `start_date` must be at or after the
        shipment's `delivery_date`, and `end_date` must be at or before the day
        following the plan's `remodel_window_end`"

        Design: Difficulty/boundary_precision_check/booking_end_date_exactly_one_day_past_remodel_window_end_accepted
        """
        ctx = setup_booked_shipment(create_booking=False)
        assert ctx["shipment"]["delivery_date"].startswith("2026-09-17")

        rejected = book_crew(ctx, start_date="2026-09-16", end_date="2026-09-19")
        validate_error(rejected, ApiErrorId.ERR_BOOKING_OUTSIDE_REMODEL_WINDOW.value)

        accepted = validate_success(
            book_crew(ctx, start_date="2026-09-17", end_date="2026-09-19"),
            expected_status=201,
        )
        assert accepted["day_count"] == 2


class TestCrewCapacity:
    """PRD §3.8 — capacity is an aggregate per-day constraint, not exclusivity."""

    def test_05_aggregate_per_day_capacity_rejects_only_the_overlapping_day(self, api):
        """Two cases a day is full on the 18th but free again on the 19th.

        PRD §3.8: "If any single day's load strictly exceeds the crew's
        `daily_case_capacity`, the booking is rejected with
        `ERR_CREW_DAILY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_aggregate_per_day_case_capacity_overlap
        """
        ctx = setup_booked_shipment(
            line_overrides={"quantity": 2},
            crew_overrides={"daily_case_capacity": 2},
            booking_overrides={
                "start_date": "2026-09-17",
                "end_date": "2026-09-19",
                "cases_committed": 2,
            },
        )
        assert ctx["shipment"]["unit_count"] == 2
        assert ctx["shipment"]["linear_feet"] == 16

        overlapping = book_crew(
            ctx,
            start_date="2026-09-18",
            end_date="2026-09-20",
            cases_committed=1,
        )
        validate_error(overlapping, ApiErrorId.ERR_CREW_DAILY_CAPACITY_EXCEEDED.value)

        accepted = validate_success(
            book_crew(
                ctx,
                start_date="2026-09-19",
                end_date="2026-09-20",
                cases_committed=2,
            ),
            expected_status=201,
        )
        assert accepted["day_count"] == 1

        assert refresh_install_booking(ctx)["day_count"] == 2
        assert refresh_install_crew(ctx)["committed_case_days"] == 6

        _rows, meta = validate_paginated(
            api.list_install_bookings(
                TEST_USERS["logistics_coordinator_headers"],
                params={"shipment_id": ctx["shipment"]["id"]},
            )
        )
        assert meta["total_count"] == 2

    def test_06_a_released_booking_frees_its_days_for_the_next_candidate(self, api):
        """The same candidate that was refused is accepted once the day is freed.

        PRD §3.8: "Bookings whose status is `RELEASED` or `COMPLETED` are
        excluded from the scan and free their days entirely."

        Design: Difficulty/resource_temporal_overlap/crew_aggregate_per_day_case_capacity_overlap
        """
        ctx = setup_booked_shipment(
            line_overrides={"quantity": 2},
            crew_overrides={"daily_case_capacity": 2},
            booking_overrides={
                "start_date": "2026-09-17",
                "end_date": "2026-09-19",
                "cases_committed": 2,
            },
        )

        blocked = book_crew(
            ctx,
            start_date="2026-09-18",
            end_date="2026-09-19",
            cases_committed=1,
        )
        validate_error(blocked, ApiErrorId.ERR_CREW_DAILY_CAPACITY_EXCEEDED.value)

        validate_success(
            api.release_install_booking(
                ctx["install_booking"]["id"],
                {"release_reason": "Crew reassigned to the neighbouring store"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )

        accepted = validate_success(
            book_crew(
                ctx,
                start_date="2026-09-18",
                end_date="2026-09-19",
                cases_committed=1,
            ),
            expected_status=201,
        )
        assert accepted["day_count"] == 1
        assert refresh_install_crew(ctx)["committed_case_days"] == 1


class TestBookingRelease:
    """PRD §3.8 — release restores exactly what the booking committed."""

    def test_07_releasing_a_booking_fully_restores_the_committed_case_days(self, api):
        """Two committed case-days come back in full and nothing else moves.

        PRD §3.8: "Releasing a booking requires a `release_reason`, moves it
        `BOOKED → RELEASED`, decreases the crew's `committed_case_days` by that
        booking's `cases_committed` multiplied by its `day_count`, and increments
        the booking's `version` by 1."

        Design: Difficulty/compensating_invariant/crew_committed_case_days_fully_restored_on_booking_release
        """
        ctx = setup_booked_shipment()
        assert ctx["install_crew"]["committed_case_days"] == 2

        released = validate_success(
            api.release_install_booking(
                ctx["install_booking"]["id"],
                {"release_reason": "Store pushed the install crew to a later week"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )
        assert released["status"] == "RELEASED"
        assert released["day_count"] == 2
        assert released["cases_committed"] == 1

        assert refresh_install_crew(ctx)["committed_case_days"] == 0
        assert refresh_shipment(ctx)["status"] == "STAGED"

        plan = refresh_store_plan(ctx)
        assert plan["production_status"] == "COMPLETE"
        assert plan["units_shipped_count"] == 1

    def test_08_releasing_one_booking_leaves_the_other_commitment_intact(self, api):
        """The counter always equals the sum over the crew's BOOKED bookings.

        PRD §3.8: "that counter is always the sum of `cases_committed` multiplied
        by `day_count` over the crew's `BOOKED` bookings."

        Design: Difficulty/compensating_invariant/crew_committed_case_days_fully_restored_on_booking_release
        """
        ctx = setup_booked_shipment()
        second = validate_success(
            book_crew(
                ctx,
                start_date="2026-09-19",
                end_date="2026-09-21",
                cases_committed=2,
            ),
            expected_status=201,
        )
        assert second["day_count"] == 2
        assert refresh_install_crew(ctx)["committed_case_days"] == 6

        validate_success(
            api.release_install_booking(
                ctx["install_booking"]["id"],
                {"release_reason": "Store pushed the install crew to a later week"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )
        assert refresh_install_crew(ctx)["committed_case_days"] == 4, (
            "only the released booking's contribution is returned"
        )


class TestHandoff:
    """PRD §3.8 — the handoff needs a BOOKED booking and a clock inside it."""

    def test_09_handoff_inside_the_booking_window_completes_the_booking(self, api):
        """The signature completes the booking and starts the warranty clock.

        PRD §3.8: "And every work order whose `shipment_id` is this shipment has
        its `warranty_start_date` set to that same logical instant — which is the
        only way a `warranty_start_date` is ever stamped, and therefore the only
        way a unit becomes eligible for warranty coverage at all."

        Design: Corner/endpoints/shipment_handoff_inside_booking_window_completes_booking
        """
        ctx = setup_handed_off_shipment()

        assert ctx["shipment"]["status"] == "HANDED_OFF"
        assert_instant_equals(
            ctx["shipment"]["handoff_at"], "2026-09-17T14:00:00Z", "handoff_at"
        )
        assert ctx["shipment"]["received_by_name"] == "Dana Ruiz"

        booking = refresh_install_booking(ctx)
        assert booking["status"] == "COMPLETED"
        assert booking["day_count"] == 2

        assert refresh_install_crew(ctx)["committed_case_days"] == 0

        unit = refresh_work_orders(ctx)[0]
        assert_instant_equals(
            unit["warranty_start_date"], "2026-09-17T14:00:00Z", "warranty_start_date"
        )

    def test_10_handoff_outside_the_booking_window_is_rejected(self, api):
        """A clock one day past the exclusive end is too late to sign.

        PRD §3.8: "At rank 34, the current logical clock instant must fall at or
        after that booking's `start_date` and strictly before its `end_date`,
        else `ERR_HANDOFF_OUTSIDE_BOOKING_WINDOW` (HTTP 422)."

        Design: Corner/validations/handoff_outside_booking_window_rejected
        """
        ctx = setup_delivered_shipment()
        set_logical_clock("2026-09-20T10:00:00Z")

        response = api.handoff_shipment(
            ctx["shipment"]["id"],
            {"received_by_name": "Dana Ruiz"},
            make_install_contractor_headers(ctx["install_crew"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_HANDOFF_OUTSIDE_BOOKING_WINDOW.value)

        assert refresh_shipment(ctx)["status"] == "DELIVERED"
        unit = refresh_work_orders(ctx)[0]
        assert unit["status"] == "SHIPPED"
        assert unit.get("warranty_start_date") is None

    def test_11_handoff_is_blocked_when_the_only_booking_has_been_released(self, api):
        """The identity test passes at rank 3 and the readiness test still refuses.

        PRD §3.8: "At rank 33, an install booking with status exactly `BOOKED`
        must exist for this shipment, else `ERR_INSTALL_BOOKING_NOT_READY` (HTTP
        409) — which is why a contractor whose only booking on the shipment is
        `RELEASED` passes the identity test at rank 3 and still cannot complete
        the handoff."

        Design: Difficulty/cross_entity_state_dependency/shipment_handoff_blocked_by_released_install_booking
        """
        ctx = setup_delivered_shipment()
        validate_success(
            api.release_install_booking(
                ctx["install_booking"]["id"],
                {"release_reason": "Contractor reassigned to another remodel"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )
        set_logical_clock("2026-09-17T14:00:00Z")

        response = api.handoff_shipment(
            ctx["shipment"]["id"],
            {"received_by_name": "J. Ruiz"},
            make_install_contractor_headers(ctx["install_crew"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSTALL_BOOKING_NOT_READY.value)

        shipment = refresh_shipment(ctx)
        assert shipment["status"] == "DELIVERED"
        assert shipment.get("handoff_at") is None

        assert refresh_install_booking(ctx)["status"] == "RELEASED"
        assert refresh_work_orders(ctx)[0].get("warranty_start_date") is None
        assert refresh_install_crew(ctx)["committed_case_days"] == 0

    def test_12_a_fresh_booking_restores_the_handoff_readiness(self, api):
        """Rebooking the same crew makes the identical handoff succeed.

        PRD §2.1: "satisfying rank 3 with a `RELEASED` booking does not make the
        handoff legal, it only proves the caller is one of the crews that has at
        some point been assigned to that shipment."

        Design: Difficulty/cross_entity_state_dependency/shipment_handoff_blocked_by_released_install_booking
        """
        ctx = setup_delivered_shipment()
        validate_success(
            api.release_install_booking(
                ctx["install_booking"]["id"],
                {"release_reason": "Contractor reassigned to another remodel"},
                TEST_USERS["logistics_coordinator_headers"],
            )
        )
        contractor_headers = make_install_contractor_headers(ctx["install_crew"]["id"])
        set_logical_clock("2026-09-17T14:00:00Z")
        validate_error(
            api.handoff_shipment(
                ctx["shipment"]["id"],
                {"received_by_name": "J. Ruiz"},
                contractor_headers,
            ),
            ApiErrorId.ERR_INSTALL_BOOKING_NOT_READY.value,
        )

        replacement = validate_success(
            book_crew(ctx, start_date="2026-09-17", end_date="2026-09-19"),
            expected_status=201,
        )
        assert replacement["status"] == "BOOKED"

        handed_off = validate_success(
            api.handoff_shipment(
                ctx["shipment"]["id"],
                {"received_by_name": "J. Ruiz"},
                contractor_headers,
            )
        )
        assert handed_off["status"] == "HANDED_OFF"
        assert handed_off["received_by_name"] == "J. Ruiz"
        assert_instant_equals(
            handed_off["handoff_at"], "2026-09-17T14:00:00Z", "handoff_at"
        )

        ctx["install_booking"] = replacement
        assert refresh_install_booking(ctx)["status"] == "COMPLETED"
