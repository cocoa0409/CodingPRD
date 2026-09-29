"""Exact boundaries: the last seat on a vehicle and the last day of a credential."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_manifest_entry_payload,
    create_staff_member,
    manifest_guest,
    propose_assignment,
    set_clock,
    setup_locked_program_with_segment,
    setup_program_with_seated_manifest,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]


class TestSeatCapacityExactFill:
    BRIGHTLINE = {
        "client_name": "Brightline Health",
        "group_name": "Nurse Leaders Forum",
        "guaranteed_count": 12,
    }
    MINIBUS = {
        "segment_type": "ARRIVAL_TRANSFER",
        "vehicle_code": "MINI-03",
        "origin": "Airport T2",
        "destination": "Host Hotel",
        "depart_at": "2026-09-10T14:00:00Z",
        "arrive_at": "2026-09-10T15:00:00Z",
        "wheelchair_accessible": True,
    }

    def _nine_of_twelve_seats_taken(self):
        ctx = setup_program_with_seated_manifest(
            [5, 4],
            seat_capacity=12,
            program_overrides=self.BRIGHTLINE,
            segment_overrides=self.MINIBUS,
        )
        assert ctx["segment"]["booked_seat_count"] == 9
        return ctx

    def test_filling_the_vehicle_to_exactly_its_capacity_succeeds(self, api):
        """PRD §3.5: "The capacity gate is generous at the boundary: a manifest write is
        refused only when the segment's current `booked_seat_count` plus the candidate's
        `seat_count` is **strictly greater** than the segment's `seat_capacity`, so filling
        a vehicle to exactly its capacity succeeds."

        Design: Difficulty/boundary_precision_check/segment_seat_capacity_exact_fill_then_single_seat_overflow
        """
        ctx = self._nine_of_twelve_seats_taken()

        entry = manifest_guest(
            ctx["segment"]["id"],
            guest_ref="G-103",
            guest_name="Party Okonkwo",
            seat_count=3,
        )

        assert entry["status"] == "ASSIGNED"
        segment = validate_success(api.get_transport_segment(ctx["segment"]["id"], OC))
        assert segment["booked_seat_count"] == 12
        assert segment["seat_capacity"] == 12

    def test_the_next_single_seat_overflows_and_is_refused(self, api):
        """PRD §3.5: "Exceeding it yields `ERR_SEGMENT_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/segment_seat_capacity_exact_fill_then_single_seat_overflow
        """
        ctx = self._nine_of_twelve_seats_taken()
        manifest_guest(
            ctx["segment"]["id"],
            guest_ref="G-103",
            guest_name="Party Okonkwo",
            seat_count=3,
        )

        response = api.create_manifest_entry(
            create_manifest_entry_payload(
                ctx["segment"]["id"],
                guest_ref="G-104",
                guest_name="Solo Traveller Hahn",
                seat_count=1,
            ),
            OC,
        )

        validate_error(response, ApiErrorId.ERR_SEGMENT_CAPACITY_EXCEEDED.value, 409)
        segment = validate_success(api.get_transport_segment(ctx["segment"]["id"], OC))
        assert segment["booked_seat_count"] == 12
        entries, meta = validate_paginated(
            api.list_manifest_entries(OC, params={"segment_id": ctx["segment"]["id"]})
        )
        assert meta["total_count"] == 3

    def test_the_programme_seat_ledger_follows_the_vehicle(self, api):
        """PRD §3.5: "Above the segment level, the programme's `seated_guest_count` is the
        sum of `booked_seat_count` across that programme's segments, and it is recomputed
        whenever any segment's occupancy changes."

        Design: Difficulty/boundary_precision_check/segment_seat_capacity_exact_fill_then_single_seat_overflow
        """
        ctx = self._nine_of_twelve_seats_taken()
        program_before = validate_success(api.get_program(ctx["program"]["id"], PD))
        manifest_guest(
            ctx["segment"]["id"],
            guest_ref="G-103",
            guest_name="Party Okonkwo",
            seat_count=3,
        )

        program_after = validate_success(api.get_program(ctx["program"]["id"], PD))

        assert program_before["seated_guest_count"] == 9
        assert program_after["seated_guest_count"] == 12


class TestCredentialExpiringWindowBoundary:
    CORDIS = {
        "client_name": "Cordis Analytics",
        "group_name": "User Conference",
        "guaranteed_count": 200,
    }
    SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "SHUT-09",
        "origin": "Host Hotel",
        "destination": "Conference Center",
        "depart_at": "2026-09-11T09:00:00Z",
        "arrive_at": "2026-09-11T13:00:00Z",
        "seat_capacity": 50,
    }
    GREETER = {
        "role_type": "GREETER",
        "pay_rate_cents_per_hour": 3_000,
        "first_aid_expires_on": "2027-12-31",
        "min_rest_minutes": 600,
        "max_daily_minutes": 720,
    }
    BADGES = {
        # Exactly the clock advanced by the 14-day window.
        "on_the_window_edge": "2026-09-15",
        # One day before the clock.
        "one_day_lapsed": "2026-08-31",
        # One day beyond the window.
        "clear_of_the_window": "2026-09-16",
    }

    def _three_greeters_around_the_window(self):
        ctx = setup_locked_program_with_segment(
            program_overrides=self.CORDIS, segment_overrides=self.SHUTTLE
        )
        staff, assignments = {}, {}
        for key, (badge, full_name) in {
            "on_the_window_edge": (self.BADGES["on_the_window_edge"], "Xenia Petrov"),
            "one_day_lapsed": (self.BADGES["one_day_lapsed"], "Yusuf Demir"),
            "clear_of_the_window": (
                self.BADGES["clear_of_the_window"],
                "Zola Mbeki",
            ),
        }.items():
            member = create_staff_member(
                full_name=full_name, badge_expires_on=badge, **self.GREETER
            )
            staff[key] = member
            assignments[key] = propose_assignment(
                member["id"],
                ctx["program"]["id"],
                target_type="SEGMENT",
                segment_id=ctx["segment"]["id"],
                role_type="GREETER",
                starts_at="2026-09-11T09:00:00Z",
                ends_at="2026-09-11T13:00:00Z",
            )
        set_clock("2026-09-01T00:00:00Z")
        ctx.update({"staff": staff, "assignments": assignments})
        return ctx

    def test_the_three_badges_derive_three_different_statuses(self, api):
        """PRD §3.6: "If that instant lies strictly before the logical clock, the status is
        `EXPIRED`. Otherwise, if it lies at or before the logical clock advanced by 14 days,
        the status is `EXPIRING`. Otherwise it is `VALID`."

        Design: Difficulty/boundary_precision_check/credential_expiring_window_inclusive_boundary_on_confirm
        """
        ctx = self._three_greeters_around_the_window()

        statuses = {
            key: validate_success(api.get_staff_member(member["id"], PD))[
                "credential_status"
            ]
            for key, member in ctx["staff"].items()
        }

        assert statuses["on_the_window_edge"] == "EXPIRING"
        assert statuses["one_day_lapsed"] == "EXPIRED"
        assert statuses["clear_of_the_window"] == "VALID"

    def test_only_a_badge_clear_of_the_window_may_be_confirmed(self, api):
        """PRD §3.6: "The member's derived `credential_status` must be exactly `VALID` — an
        `EXPIRING` member is refused just as an `EXPIRED` one is, because the earliest of
        the two documents must lie strictly beyond the clock plus the 14-day window — with
        `ERR_CREDENTIAL_EXPIRED` as the code."

        Design: Difficulty/boundary_precision_check/credential_expiring_window_inclusive_boundary_on_confirm
        """
        ctx = self._three_greeters_around_the_window()

        on_the_edge = api.confirm_staff_assignment(
            ctx["assignments"]["on_the_window_edge"]["id"], PD
        )
        lapsed = api.confirm_staff_assignment(
            ctx["assignments"]["one_day_lapsed"]["id"], PD
        )
        clear = api.confirm_staff_assignment(
            ctx["assignments"]["clear_of_the_window"]["id"], PD
        )

        validate_error(on_the_edge, ApiErrorId.ERR_CREDENTIAL_EXPIRED.value, 422)
        validate_error(lapsed, ApiErrorId.ERR_CREDENTIAL_EXPIRED.value, 422)
        confirmed = validate_success(clear)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["planned_labor_cost_cents"] == 12_000

    def test_the_refused_confirms_reserve_no_minutes(self, api):
        """PRD §3.6: "A new assignment lands in `PROPOSED` with `check_in_at`,
        `completed_at` null and `planned_labor_cost_cents`, `actual_labor_cost_cents` both
        zero, and — importantly — **no credential, overlap, rest or daily check runs at
        proposal time**."

        Design: Difficulty/boundary_precision_check/credential_expiring_window_inclusive_boundary_on_confirm
        """
        ctx = self._three_greeters_around_the_window()
        for key in ("on_the_window_edge", "one_day_lapsed", "clear_of_the_window"):
            api.confirm_staff_assignment(ctx["assignments"][key]["id"], PD)

        minutes = {
            key: validate_success(api.get_staff_member(member["id"], PD))[
                "confirmed_minutes_total"
            ]
            for key, member in ctx["staff"].items()
        }
        statuses = {
            key: validate_success(api.get_staff_assignment(assignment["id"], PD))[
                "status"
            ]
            for key, assignment in ctx["assignments"].items()
        }

        assert minutes["on_the_window_edge"] == 0
        assert minutes["one_day_lapsed"] == 0
        assert minutes["clear_of_the_window"] == 240
        assert statuses["on_the_window_edge"] == "PROPOSED"
        assert statuses["one_day_lapsed"] == "PROPOSED"
        assert statuses["clear_of_the_window"] == "CONFIRMED"
