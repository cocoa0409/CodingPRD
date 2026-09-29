"""Initial states, terminal lockdown, one-shot triggers, cycles and cascades."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_element,
    advance_to_in_execution,
    confirm_assignment,
    create_active_contract,
    create_permit,
    create_program,
    create_staff_member,
    create_supplier,
    create_venue,
    mark_ready,
    propose_assignment,
    read_program,
    set_clock,
    setup_delivered_single_element_program,
    setup_multi_element_program,
    setup_program_with_element,
    submit_permit,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
SM = TEST_USERS["supplier_manager_headers"]
PO = TEST_USERS["permit_officer_headers"]

IDEM_ELEMENT = {
    "element_type": "ACTIVITY",
    "title": "Idem Element",
    "starts_at": "2026-09-11T09:00:00Z",
    "ends_at": "2026-09-11T11:00:00Z",
    "planned_headcount": 20,
    "guaranteed_headcount": 20,
    "per_person_cost_cents": 4_000,
}


def _delivered_element_program():
    """One element delivered with an actual head count of 18, programme COMPLETED."""
    return setup_delivered_single_element_program(
        actual_headcount=18,
        deliver_clock="2026-09-11T11:30:00Z",
        program_overrides={
            "client_name": "Idem Client",
            "group_name": "Idem Group",
            "guaranteed_count": 20,
        },
        element_overrides=IDEM_ELEMENT,
        venue_overrides={"name": "Idem Venue"},
        supplier_overrides={"legal_name": "Idem Supplier"},
        contract_overrides={"contract_value_cents": 80_000},
    )


class TestElementInitialState:
    FRESH = {
        "element_type": "ACTIVITY",
        "title": "Fresh Element",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }

    def test_a_freshly_curated_element_is_planned_and_undelivered(self, api):
        """PRD §3.2: "A new element lands in `PLANNED`, and the create recomputes the
        programme's `element_count` and `open_element_count` and increments the programme's
        `version`." Delivery is what stamps `delivered_at` and `actual_headcount`, and
        cancellation is what stamps a penalty, so none of the three carries a figure yet.

        Design: Corner/state_machines/new_program_element_starts_in_planned
        """
        venue = create_venue(name="Initial State Venue")
        supplier = create_supplier(legal_name="Initial State Supplier")
        program = create_program(
            client_name="Initial Client", group_name="Initial Group", guaranteed_count=20
        )

        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.FRESH
        )

        assert element["status"] == "PLANNED"
        assert element["delivered_at"] is None
        assert element["actual_headcount"] is None
        assert element["cancellation_penalty_cents"] == 0
        stored = validate_success(api.get_program(program["id"], PD))
        assert stored["element_count"] == 1
        assert stored["open_element_count"] == 1
        assert stored["version"] == program["version"] + 1


class TestOneShotTriggers:
    def test_delivering_the_same_element_twice_is_refused_and_keeps_the_head_count(
        self, api
    ):
        """PRD §2.9: "Transition legality: the target row's current status must be a
        declared source state of the requested transition. Every second application of a
        one-shot trigger fails here with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/deliver_same_element_twice_returns_409_invalid_state
        """
        ctx = _delivered_element_program()

        response = api.deliver_element(
            ctx["element"]["id"], {"actual_headcount": 5}, OC
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))
        assert element["actual_headcount"] == 18
        assert element["status"] == "DELIVERED"
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["actual_attendance_total"] == 18
        assert program["execution_status"] == "COMPLETED"

    def test_marking_a_delivered_element_ready_again_reports_the_transition_not_a_gate(
        self, api
    ):
        """PRD §3.7: "`DELIVERED`, `WEATHER_SWITCHED` and `CANCELLED` are all terminal for
        an element."

        Design: Corner/state_machines/mark_ready_from_delivered_returns_409_invalid_state
        """
        ctx = _delivered_element_program()

        response = api.mark_element_ready(ctx["element"]["id"], OC)

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        error_id = response.json()["data"]["error_id"]
        assert error_id != ApiErrorId.ERR_NO_ACTIVE_SUPPLIER_CONTRACT.value
        assert error_id != ApiErrorId.ERR_PERMIT_NOT_APPROVED.value
        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))
        assert element["status"] == "DELIVERED"


class TestCancelledProgramIsTerminal:
    ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Terminal Element",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }

    def test_neither_lock_nor_confirm_may_follow_a_cancellation(self, api):
        """PRD §3.1: "The **execution dimension** runs `DRAFT` → `DESIGN_LOCKED` →
        `CONFIRMED` → `IN_EXECUTION` → `COMPLETED`, with `CANCELLED` reachable from any of
        the first four and with `COMPLETED` and `CANCELLED` both terminal."

        Design: Corner/state_machines/cancelled_program_rejects_further_transitions
        """
        ctx = setup_program_with_element(
            program_overrides={
                "client_name": "Terminal Client",
                "group_name": "Terminal Group",
                "guaranteed_count": 20,
            },
            element_overrides=self.ELEMENT,
            venue_overrides={"name": "Terminal Venue"},
            supplier_overrides={"legal_name": "Terminal Supplier"},
        )
        validate_success(
            api.cancel_program(
                ctx["program"]["id"], PD, {"cancel_reason": "Client pulled the program."}
            )
        )

        locked = api.lock_program_design(ctx["program"]["id"], PD)
        confirmed = api.confirm_program(ctx["program"]["id"], PD)

        validate_error(locked, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        validate_error(confirmed, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["execution_status"] == "CANCELLED"
        # The settlement dimension never moved: no money was ever in flight.
        assert program["settlement_status"] == "NOT_STARTED"


class TestPermitResubmissionCycle:
    BLOCK_PARTY = {
        "element_type": "OFF_PREMISE_EVENT",
        "title": "Block Party",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T12:00:00Z",
        "planned_headcount": 100,
        "guaranteed_headcount": 100,
        "per_person_cost_cents": 3_000,
    }
    CONDITIONS = "Provide a certified traffic-control plan and a noise variance."

    def _submitted_street_closure_permit(self):
        venue = create_venue(
            name="Street Closure Block",
            capacity_seated=100,
            capacity_reception=300,
            requires_special_venue_permit=True,
        )
        supplier = create_supplier(legal_name="Street Fest Productions")
        program = create_program(
            client_name="Permit Cycle Client",
            group_name="Permit Cycle Group",
            guaranteed_count=100,
        )
        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.BLOCK_PARTY
        )
        permit = create_permit(
            element["id"],
            permit_type="STREET_CLOSURE",
            authority_name="Department of Transportation",
            lead_time_days_required=20,
        )
        submit_permit(permit["id"])
        return {"program": program, "element": element, "permit": permit}

    def test_a_conditions_round_returns_the_permit_and_counts_the_resubmission(self, api):
        """PRD §3.4: "From `CONDITIONS_REQUESTED` the officer may submit again, which
        advances `CONDITIONS_REQUESTED` → `SUBMITTED`, re-stamps `submitted_at`, adds one to
        `resubmission_count`, and applies exactly the same lead-time test as a first
        submission — with the clock having moved on, a revision that took too long to
        prepare will fail with `ERR_PERMIT_LEAD_TIME_INSUFFICIENT` even though the original
        submission passed."

        Design: Corner/state_machines/permit_conditions_requested_resubmission_cycle_increments_counter
        """
        ctx = self._submitted_street_closure_permit()

        returned = validate_success(
            api.record_permit_decision(
                ctx["permit"]["id"],
                {"decision": "CONDITIONS_REQUESTED", "conditions_note": self.CONDITIONS},
                PO,
            )
        )
        resubmitted = validate_success(api.submit_permit(ctx["permit"]["id"], PO))

        assert returned["status"] == "CONDITIONS_REQUESTED"
        assert returned["conditions_note"] == self.CONDITIONS
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["resubmission_count"] == 1

    def test_the_second_round_can_still_be_approved_and_the_element_never_blocks(self, api):
        """PRD §3.4: "The authority's answer is recorded as a `decision` of `APPROVED`,
        `DENIED` or `CONDITIONS_REQUESTED`, always from `SUBMITTED`, and all three branches
        stamp `decision_at` with the logical clock instant and increment the permit's
        `version`."

        Design: Corner/state_machines/permit_conditions_requested_resubmission_cycle_increments_counter
        """
        ctx = self._submitted_street_closure_permit()
        validate_success(
            api.record_permit_decision(
                ctx["permit"]["id"],
                {"decision": "CONDITIONS_REQUESTED", "conditions_note": self.CONDITIONS},
                PO,
            )
        )
        validate_success(api.submit_permit(ctx["permit"]["id"], PO))

        approved = validate_success(
            api.record_permit_decision(
                ctx["permit"]["id"], {"decision": "APPROVED"}, PO
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["decision_at"].startswith("2026-08-01T00:00:00")
        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))
        assert element["status"] == "PLANNED"
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["staffing_gap_count"] == 0


class TestContractTerminationCascade:
    ELEMENT = {
        "element_type": "ACTIVITY",
        "title": "Terminate Element",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T12:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 6_000,
    }
    NOTE = "Supplier lost its operating licence."

    def _active_contract_ten_days_before_service(self):
        venue = create_venue(
            name="Terminate Venue", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Terminate Supplier")
        program = create_program(
            client_name="Terminate Client",
            group_name="Terminate Group",
            guaranteed_count=30,
        )
        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.ELEMENT
        )
        contract = create_active_contract(
            program["id"],
            supplier["id"],
            contract_value_cents=180_000,
            deposit_pct=0.3,
            cancellation_tier="STANDARD",
        )
        # Exactly ten whole days before the element starts.
        set_clock("2026-09-01T09:00:00Z")
        return {
            "program": program,
            "element": element,
            "contract": contract,
        }

    def test_termination_unbanks_the_deposit_but_leaves_the_amount_due_on_record(self, api):
        """PRD §3.3: "A successful termination resets `deposit_paid_cents` to zero, cascades
        into the operational plan by moving every element of the same programme and the same
        supplier that is still in `PLANNED`, `PERMIT_BLOCKED` or `READY` to `CANCELLED` —
        with each of those element transitions computing and stamping its own cancellation
        penalty and running its own staff-release cascade — and increments the contract's
        `version`."

        Design: Corner/state_machines/contract_terminate_cascades_element_cancellation_with_penalty
        """
        ctx = self._active_contract_ten_days_before_service()

        terminated = validate_success(
            api.terminate_supplier_contract(
                ctx["contract"]["id"], SM, {"termination_note": self.NOTE}
            )
        )

        assert terminated["status"] == "TERMINATED"
        assert terminated["deposit_paid_cents"] == 0
        assert terminated["deposit_due_cents"] == 54_000

    def test_the_cancelled_element_carries_the_standard_ten_day_penalty(self, api):
        """PRD §3.7: "On the `STANDARD` schedule, a cancellation at 30 or more whole days
        out costs nothing; at 15 to 29 days it costs a quarter of the element's planned
        value; at 7 to 14 days it costs half; and inside 7 days it costs the whole planned
        value."

        Design: Corner/state_machines/contract_terminate_cascades_element_cancellation_with_penalty
        """
        ctx = self._active_contract_ten_days_before_service()

        validate_success(
            api.terminate_supplier_contract(
                ctx["contract"]["id"], SM, {"termination_note": self.NOTE}
            )
        )

        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))
        assert element["status"] == "CANCELLED"
        # Half of 30 guests at 6,000 cents each.
        assert element["cancellation_penalty_cents"] == 90_000
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert program["open_element_count"] == 0
        assert program["element_count"] == 1
        assert program["execution_status"] == "DRAFT"


class TestWeatherSwitch:
    PRIMARY = {
        "element_type": "ACTIVITY",
        "title": "Lawn Games",
        "starts_at": "2026-09-11T14:00:00Z",
        "ends_at": "2026-09-11T17:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 4_000,
        "is_weather_dependent": True,
    }
    STAND_IN = {
        "element_type": "ACTIVITY",
        "title": "Atrium Games",
        "starts_at": "2026-09-11T14:00:00Z",
        "ends_at": "2026-09-11T17:00:00Z",
        "planned_headcount": 30,
        "guaranteed_headcount": 30,
        "per_person_cost_cents": 4_000,
        "is_weather_dependent": False,
    }

    def _rained_out_primary_with_one_confirmed_shift(self):
        outdoor = create_venue(
            name="Outdoor Lawn", capacity_seated=100, capacity_reception=200
        )
        indoor = create_venue(
            name="Indoor Atrium", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="All Weather Events")
        program = create_program(
            client_name="Rainplan Client",
            group_name="Rainplan Group",
            guaranteed_count=30,
        )
        primary = add_element(
            program["id"], supplier["id"], venue_id=outdoor["id"], **self.PRIMARY
        )
        stand_in = add_element(
            program["id"],
            supplier["id"],
            venue_id=indoor["id"],
            alternative_for_element_id=primary["id"],
            **self.STAND_IN,
        )
        create_active_contract(
            program["id"], supplier["id"], contract_value_cents=120_000
        )
        staff = create_staff_member(
            full_name="Iris Tanaka", pay_rate_cents_per_hour=3_600
        )
        assignment = propose_assignment(
            staff["id"],
            program["id"],
            target_type="ELEMENT",
            element_id=primary["id"],
            role_type="COORDINATOR",
            starts_at="2026-09-11T14:00:00Z",
            ends_at="2026-09-11T18:00:00Z",
        )
        advance_to_in_execution(program["id"])
        confirmed = confirm_assignment(assignment["id"])
        mark_ready(primary["id"])
        # An hour before the outdoor start, when the forecast finally settles it.
        set_clock("2026-09-11T13:00:00Z")
        return {
            "program": program,
            "primary": primary,
            "stand_in": stand_in,
            "staff": staff,
            "assignment": confirmed,
        }

    def test_the_stand_in_is_promoted_as_the_primary_is_switched_away(self, api):
        """PRD §3.7: "On success the selected alternative advances `PLANNED` → `READY`;
        every staff assignment against the switched-away element in `PROPOSED` or
        `CONFIRMED` moves to `RELEASED`, each such release decrementing its member's
        `confirmed_minutes_total` when the prior status was `CONFIRMED` and incrementing the
        programme's `staffing_gap_count`; the programme's `open_element_count` is
        recomputed; and the element's `version` increments."

        Design: Corner/state_machines/weather_switch_promotes_alternative_and_releases_staff
        """
        ctx = self._rained_out_primary_with_one_confirmed_shift()

        switched = validate_success(
            api.weather_switch_element(ctx["primary"]["id"], OC)
        )

        assert switched["status"] == "WEATHER_SWITCHED"
        stand_in = validate_success(api.get_program_element(ctx["stand_in"]["id"], PD))
        assert stand_in["status"] == "READY"

    def test_the_switch_hands_back_the_shift_and_opens_a_staffing_gap(self, api):
        """PRD §3.7: "Because the switch resolves one open element while opening another,
        the bubble-up to `COMPLETED` described above is re-evaluated here too."

        Design: Corner/state_machines/weather_switch_promotes_alternative_and_releases_staff
        """
        ctx = self._rained_out_primary_with_one_confirmed_shift()
        assert ctx["assignment"]["status"] == "CONFIRMED"

        validate_success(api.weather_switch_element(ctx["primary"]["id"], OC))

        assignment = validate_success(
            api.get_staff_assignment(ctx["assignment"]["id"], PD)
        )
        staff = validate_success(api.get_staff_member(ctx["staff"]["id"], PD))
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert assignment["status"] == "RELEASED"
        assert staff["confirmed_minutes_total"] == 0
        assert program["staffing_gap_count"] == 1
        # The stand-in is now the one open element, so no bubble-up fires.
        assert program["open_element_count"] == 1
        assert program["execution_status"] == "IN_EXECUTION"


class TestProgramBubbleUp:
    FIRST = {
        "element_type": "ACTIVITY",
        "title": "Bubble E1",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T11:00:00Z",
        "planned_headcount": 15,
        "guaranteed_headcount": 15,
        "per_person_cost_cents": 3_000,
    }
    SECOND = {
        "element_type": "ACTIVITY",
        "title": "Bubble E2",
        # 12:30Z clears the venue's 90-minute turnover buffer after E1.
        "starts_at": "2026-09-11T12:30:00Z",
        "ends_at": "2026-09-11T14:30:00Z",
        "planned_headcount": 15,
        "guaranteed_headcount": 15,
        "per_person_cost_cents": 3_000,
    }

    def test_the_programme_completes_only_on_the_last_delivery(self, api):
        """PRD §3.7: "Finally, if `open_element_count` has reached zero while the programme
        is `IN_EXECUTION`, the programme itself advances `IN_EXECUTION` → `COMPLETED`,
        recomputing `actual_attendance_total` and incrementing the programme's `version`."

        Design: Corner/state_machines/program_completes_by_bubble_up_when_last_element_delivered
        """
        ctx = setup_multi_element_program(
            [self.FIRST, self.SECOND],
            program_overrides={
                "client_name": "Bubble Client",
                "group_name": "Bubble Group",
                "guaranteed_count": 30,
            },
            venue_overrides={"name": "Bubble Venue"},
            supplier_overrides={"legal_name": "Bubble Supplier"},
            contract_overrides={"contract_value_cents": 90_000},
        )
        first, second = ctx["elements"]
        advance_to_in_execution(ctx["program"]["id"])
        mark_ready(first["id"])
        mark_ready(second["id"])
        set_clock("2026-09-11T14:45:00Z")

        validate_success(api.deliver_element(first["id"], {"actual_headcount": 12}, OC))
        after_first = read_program(ctx["program"]["id"])
        validate_success(api.deliver_element(second["id"], {"actual_headcount": 9}, OC))
        after_second = read_program(ctx["program"]["id"])

        assert after_first["open_element_count"] == 1
        assert after_first["execution_status"] == "IN_EXECUTION"
        assert after_second["open_element_count"] == 0
        assert after_second["execution_status"] == "COMPLETED"
        assert after_second["actual_attendance_total"] == 21
