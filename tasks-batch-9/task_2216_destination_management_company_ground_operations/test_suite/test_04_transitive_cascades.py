"""Single writes that propagate several links deep: permit denial and segment cancellation."""

from test_helpers import (
    TEST_USERS,
    confirm_assignment,
    create_permit,
    create_staff_member,
    lock_design,
    propose_assignment,
    record_permit_decision,
    setup_program_with_contracted_element,
    setup_program_with_seated_manifest,
    submit_permit,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
PO = TEST_USERS["permit_officer_headers"]

DENIAL_NOTE = "Street-adjacent load-in plan not acceptable to the board."
SCRUB_REASON = "Restaurant lost power; leg scrubbed."


class TestPermitDenialCascade:
    GALA = {
        "element_type": "OFF_PREMISE_EVENT",
        "title": "Warehouse Gala",
        "starts_at": "2026-09-11T08:00:00Z",
        "ends_at": "2026-09-11T14:00:00Z",
        "planned_headcount": 60,
        "guaranteed_headcount": 60,
        "per_person_cost_cents": 9_000,
    }

    def _denied_permit_on_a_staffed_element(self):
        """A staffed off-premise event whose alcohol permit has just been refused."""
        ctx = setup_program_with_contracted_element(
            program_overrides={
                "client_name": "Orbit Semiconductors",
                "group_name": "Supplier Days",
                "guaranteed_count": 60,
            },
            element_overrides=self.GALA,
            venue_overrides={
                "name": "Riverside Warehouse",
                "capacity_reception": 400,
                "requires_special_venue_permit": True,
            },
            supplier_overrides={"legal_name": "Rivergate Production House"},
            contract_overrides={"contract_value_cents": 540_000},
        )
        staff = create_staff_member(
            full_name="Priya Raman", pay_rate_cents_per_hour=4_000
        )
        assignment = propose_assignment(
            staff["id"],
            ctx["program"]["id"],
            target_type="ELEMENT",
            element_id=ctx["element"]["id"],
            role_type="COORDINATOR",
            starts_at="2026-09-11T08:00:00Z",
            ends_at="2026-09-11T14:00:00Z",
        )
        lock_design(ctx["program"]["id"])
        ctx["staff"] = staff
        ctx["assignment"] = confirm_assignment(assignment["id"])
        assert ctx["assignment"]["status"] == "CONFIRMED"

        permit = create_permit(
            ctx["element"]["id"],
            permit_type="OFF_PREMISE_ALCOHOL",
            authority_name="City Alcohol Beverage Board",
            lead_time_days_required=30,
        )
        submit_permit(permit["id"])
        ctx["permit"] = record_permit_decision(
            permit["id"], "DENIED", conditions_note=DENIAL_NOTE
        )
        return ctx

    def test_denial_blocks_the_element_it_authorised(self, api):
        """PRD §3.4: "First, the element identified by `element_id`, if its status is
        `PLANNED` or `READY`, moves to `PERMIT_BLOCKED`, with its own `version`
        incremented; the programme's `open_element_count` is recomputed and is unchanged by
        this, because `PERMIT_BLOCKED` is still an open status."

        Design: Difficulty/transitive_cascade/permit_denial_cascade_depth_four
        """
        ctx = self._denied_permit_on_a_staffed_element()
        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))
        program = validate_success(api.get_program(ctx["program"]["id"], PD))

        assert ctx["permit"]["status"] == "DENIED"
        assert ctx["permit"]["decision_at"].startswith("2026-08-01T00:00:00")
        assert element["status"] == "PERMIT_BLOCKED"
        assert program["element_count"] == 1
        assert program["open_element_count"] == 1

    def test_blocking_the_element_releases_its_confirmed_shift(self, api):
        """PRD §3.4: "Second, caused by that block, every staff assignment against that
        element whose status is `PROPOSED` or `CONFIRMED` moves to `RELEASED`."

        Design: Difficulty/transitive_cascade/permit_denial_cascade_depth_four
        """
        ctx = self._denied_permit_on_a_staffed_element()

        assignment = validate_success(
            api.get_staff_assignment(ctx["assignment"]["id"], PD)
        )

        assert assignment["status"] == "RELEASED"

    def test_the_release_reaches_the_minute_ledger_and_the_gap_counter(self, api):
        """PRD §3.4: "Third, caused by each of those releases, the assignment's staff
        member has `confirmed_minutes_total` decremented by that assignment's scheduled
        minutes and the programme's `staffing_gap_count` is incremented by one."

        Design: Difficulty/transitive_cascade/permit_denial_cascade_depth_four
        """
        ctx = self._denied_permit_on_a_staffed_element()
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        program = validate_success(api.get_program(ctx["program"]["id"], PD))

        # The 360 scheduled minutes the confirmation had reserved are given back.
        assert staff["confirmed_minutes_total"] == 0
        assert program["staffing_gap_count"] == 1
        assert program["execution_status"] == "DESIGN_LOCKED"


class TestSegmentCancellationCascade:
    FENWICK = {
        "client_name": "Fenwick Legal",
        "group_name": "Partner Dine-Around",
        "guaranteed_count": 24,
        "markup_pct": 0.22,
    }
    DINE_AROUND_LEG = {
        "segment_type": "DINE_AROUND_LEG",
        "vehicle_code": "VAN-07",
        "origin": "Host Hotel",
        "destination": "Trattoria Nine",
        "depart_at": "2026-09-12T18:00:00Z",
        "arrive_at": "2026-09-12T18:40:00Z",
        "wheelchair_accessible": True,
    }

    def _cancelled_leg(self, api):
        ctx = setup_program_with_seated_manifest(
            [2, 1, 1],
            seat_capacity=20,
            program_overrides=self.FENWICK,
            segment_overrides=self.DINE_AROUND_LEG,
        )
        assert ctx["segment"]["booked_seat_count"] == 4
        ctx["segment"] = validate_success(
            api.cancel_transport_segment(
                ctx["segment"]["id"], OC, {"cancel_reason": SCRUB_REASON}
            )
        )
        return ctx

    def test_cancelling_the_leg_releases_every_seated_guest(self, api):
        """PRD §3.7: "Every entry of the segment in `ASSIGNED` or `CHECKED_IN` moves to
        `RELEASED`; caused by each such release, the segment's `booked_seat_count` is
        decremented by that entry's `seat_count` and the programme's
        `unseated_guest_count` is incremented by one; and caused by that, the programme's
        `seated_guest_count` is recomputed as the sum of `booked_seat_count` across the
        programme's segments."

        Design: Difficulty/transitive_cascade/segment_cancellation_cascade_depth_three
        """
        ctx = self._cancelled_leg(api)

        assert ctx["segment"]["status"] == "CANCELLED"
        assert ctx["segment"]["booked_seat_count"] == 0
        for entry in ctx["entries"]:
            reread = validate_success(api.get_manifest_entry(entry["id"], OC))
            assert reread["status"] == "RELEASED"

    def test_seat_counters_move_in_opposite_directions(self, api):
        """PRD §2.7: "`unseated_guest_count` behaves the same way for guests displaced by
        a segment cancellation."

        Design: Difficulty/transitive_cascade/segment_cancellation_cascade_depth_three
        """
        ctx = self._cancelled_leg(api)
        program = validate_success(api.get_program(ctx["program"]["id"], PD))

        # Four seats vacated, but three guest parties displaced.
        assert program["seated_guest_count"] == 0
        assert program["unseated_guest_count"] == 3
        assert program["staffing_gap_count"] == 0
