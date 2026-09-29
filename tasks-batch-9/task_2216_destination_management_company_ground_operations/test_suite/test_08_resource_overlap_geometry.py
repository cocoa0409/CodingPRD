"""Adjacency verdicts: half-open venue occupation versus closed staff shifts."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_assignment,
    create_program_element_payload,
    create_staff_member,
    propose_assignment,
    read_program,
    setup_locked_program_with_segment,
    setup_program_with_element,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]


class TestVenueHalfOpenOccupationWithForwardBuffer:
    INCUMBENT = {
        "element_type": "ACTIVITY",
        "title": "Incumbent Workshop",
        "starts_at": "2026-09-11T14:00:00Z",
        "ends_at": "2026-09-11T16:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 4_000,
    }
    FOUNDRY = {"name": "Foundry Studio", "turnover_buffer_minutes": 90}

    def _programme_with_an_incumbent_occupation(self):
        return setup_program_with_element(
            program_overrides={
                "client_name": "Ravel Apparel",
                "group_name": "Buyer Roadshow",
                "guaranteed_count": 30,
            },
            element_overrides=self.INCUMBENT,
            venue_overrides=self.FOUNDRY,
            supplier_overrides={"legal_name": "Foundry Creative Studio"},
        )

    def _candidate(self, ctx, title, starts_at, ends_at):
        return create_program_element_payload(
            ctx["program"]["id"],
            ctx["supplier"]["id"],
            read_program(ctx["program"]["id"])["version"],
            venue_id=ctx["venue"]["id"],
            element_type="ACTIVITY",
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            planned_headcount=30,
            guaranteed_headcount=30,
            per_person_cost_cents=4_000,
        )

    def test_a_candidate_ending_when_the_incumbent_begins_is_accepted(self, api):
        """PRD §3.2: "Two consequences are pinned by that geometry: a candidate that ends
        exactly when an incumbent begins is accepted, because no buffer is required in front
        of an incumbent; but a candidate that begins exactly when an incumbent ends is
        refused unless the full turnover buffer has already elapsed."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_with_forward_turnover_buffer
        """
        ctx = self._programme_with_an_incumbent_occupation()

        response = api.create_program_element(
            self._candidate(
                ctx,
                "Touching Predecessor",
                "2026-09-11T12:00:00Z",
                "2026-09-11T14:00:00Z",
            ),
            PD,
        )

        element = validate_success(response, 201)
        assert element["status"] == "PLANNED"

    def test_a_candidate_inside_the_forward_buffer_is_refused(self, api):
        """PRD §3.2: "The candidate is refused when its `starts_at` falls strictly before
        the incumbent's `ends_at` advanced by the venue's `turnover_buffer_minutes` **and**
        the incumbent's `starts_at` falls strictly before the candidate's `ends_at`."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_with_forward_turnover_buffer
        """
        ctx = self._programme_with_an_incumbent_occupation()

        response = api.create_program_element(
            self._candidate(
                ctx, "Inside Buffer", "2026-09-11T17:00:00Z", "2026-09-11T19:00:00Z"
            ),
            PD,
        )

        validate_error(response, ApiErrorId.ERR_VENUE_TURNOVER_CONFLICT.value, 409)

    def test_a_candidate_exactly_at_the_buffer_edge_is_accepted(self, api):
        """PRD §3.2: "An element occupies its venue over the **half-open** interval from
        `starts_at` inclusive to `ends_at` exclusive, and the venue's turnover buffer is
        attached **forward only**, to the tail of the incumbent occupation."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_interval_with_forward_turnover_buffer
        """
        ctx = self._programme_with_an_incumbent_occupation()
        validate_success(
            api.create_program_element(
                self._candidate(
                    ctx,
                    "Touching Predecessor",
                    "2026-09-11T12:00:00Z",
                    "2026-09-11T14:00:00Z",
                ),
                PD,
            ),
            201,
        )
        validate_error(
            api.create_program_element(
                self._candidate(
                    ctx, "Inside Buffer", "2026-09-11T17:00:00Z", "2026-09-11T19:00:00Z"
                ),
                PD,
            ),
            ApiErrorId.ERR_VENUE_TURNOVER_CONFLICT.value,
            409,
        )

        # 16:00Z plus the 90-minute buffer lands exactly on 17:30Z.
        response = api.create_program_element(
            self._candidate(
                ctx,
                "Exactly At Buffer Edge",
                "2026-09-11T17:30:00Z",
                "2026-09-11T19:30:00Z",
            ),
            PD,
        )

        validate_success(response, 201)
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["element_count"] == 3
        assert program["open_element_count"] == 3


class TestStaffClosedIntervalAdjacency:
    IRONBARK = {
        "client_name": "Ironbark Mining",
        "group_name": "Investor Site Visit",
        "guaranteed_count": 45,
    }
    SHUTTLE = {
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "SHUT-11",
        "origin": "Host Hotel",
        "destination": "Site Gate",
        "depart_at": "2026-09-11T08:00:00Z",
        "arrive_at": "2026-09-11T14:00:00Z",
        "seat_capacity": 45,
    }

    def _greeter_with_a_confirmed_morning_shift(self):
        """One confirmed 08:00-12:00 shift plus a touching and a one-minute-clear proposal."""
        ctx = setup_locked_program_with_segment(
            program_overrides=self.IRONBARK, segment_overrides=self.SHUTTLE
        )
        staff = create_staff_member(
            full_name="Rowan Keane",
            role_type="GREETER",
            pay_rate_cents_per_hour=3_000,
            min_rest_minutes=0,
            max_daily_minutes=720,
        )

        def propose(starts_at, ends_at):
            return propose_assignment(
                staff["id"],
                ctx["program"]["id"],
                target_type="SEGMENT",
                segment_id=ctx["segment"]["id"],
                role_type="GREETER",
                starts_at=starts_at,
                ends_at=ends_at,
            )

        incumbent = propose("2026-09-11T08:00:00Z", "2026-09-11T12:00:00Z")
        confirm_assignment(incumbent["id"])
        ctx.update(
            {
                "staff": staff,
                "incumbent": incumbent,
                "touching": propose(
                    "2026-09-11T12:00:00Z", "2026-09-11T14:00:00Z"
                ),
                "clear": propose("2026-09-11T12:01:00Z", "2026-09-11T14:00:00Z"),
            }
        )
        return ctx

    def test_a_shift_starting_when_another_ends_collides(self, api):
        """PRD §3.6: "A shift beginning at precisely the instant another ends therefore
        collides and is refused with `ERR_STAFF_ASSIGNMENT_OVERLAP`, where a venue booking in
        the same position would have been accepted."

        Design: Difficulty/resource_temporal_overlap/staff_closed_interval_touching_shifts_collide
        """
        ctx = self._greeter_with_a_confirmed_morning_shift()

        response = api.confirm_staff_assignment(ctx["touching"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_STAFF_ASSIGNMENT_OVERLAP.value, 409)
        touching = validate_success(api.get_staff_assignment(ctx["touching"]["id"], PD))
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        assert touching["status"] == "PROPOSED"
        assert staff["confirmed_minutes_total"] == 240

    def test_one_minute_of_clearance_is_enough(self, api):
        """PRD §3.6: "For the candidate shift and every incumbent shift of the same
        `staff_id` whose status is `CONFIRMED`, `CHECKED_IN` or `COMPLETED`, the candidate is
        refused when the candidate's `starts_at` is at or before the incumbent's `ends_at`
        **and** the incumbent's `starts_at` is at or before the candidate's `ends_at`."

        Design: Difficulty/resource_temporal_overlap/staff_closed_interval_touching_shifts_collide
        """
        ctx = self._greeter_with_a_confirmed_morning_shift()

        confirmed = validate_success(api.confirm_staff_assignment(ctx["clear"]["id"], PD))

        assert confirmed["status"] == "CONFIRMED"
        # 119 scheduled minutes, billed at the 240-minute call-out floor.
        assert confirmed["planned_labor_cost_cents"] == 12_000
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        assert staff["confirmed_minutes_total"] == 359
