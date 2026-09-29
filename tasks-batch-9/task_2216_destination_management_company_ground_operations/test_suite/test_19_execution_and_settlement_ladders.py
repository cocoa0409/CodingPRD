"""Staff gates at proposal and confirmation, the on-site clocks, and the settlement ladder."""

from test_helpers import (
    CONTROLLER_APPROVER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_element,
    approve_line,
    confirm_assignment,
    confirm_program,
    create_active_contract,
    create_program,
    create_staff_assignment_payload,
    create_staff_member,
    create_supplier,
    create_venue,
    lock_design,
    make_controller_headers,
    make_operations_coordinator_headers,
    mark_ready,
    open_reconciliation,
    patch_line,
    propose_assignment,
    read_program,
    reset_clock,
    set_clock,
    setup_delivered_single_element_program,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
CTRL = make_controller_headers(CONTROLLER_APPROVER_USER_ID)

GREETER_SHIFT = {
    "target_type": "ELEMENT",
    "role_type": "GREETER",
    "starts_at": "2026-09-11T08:45:00Z",
    "ends_at": "2026-09-11T13:15:00Z",
}


class TestTheTwoStaffGatesFireAtDifferentMoments:
    ANCHOR = {
        "element_type": "ACTIVITY",
        "title": "Staff Gate Anchor",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 20,
        "guaranteed_headcount": 20,
        "per_person_cost_cents": 4_000,
    }
    CORA = {
        "full_name": "Cora Delacroix",
        "role_type": "COORDINATOR",
        "badge_expires_on": "2027-06-30",
        "first_aid_expires_on": "2027-06-30",
        "pay_rate_cents_per_hour": 5_000,
        "min_rest_minutes": 0,
        "max_daily_minutes": 480,
        "status": "ACTIVE",
    }
    GIL = {
        "full_name": "Gil Abarca",
        "role_type": "GREETER",
        "badge_expires_on": "2027-06-30",
        "first_aid_expires_on": "2027-06-30",
        "pay_rate_cents_per_hour": 4_000,
        "min_rest_minutes": 0,
        "max_daily_minutes": 480,
        "status": "INACTIVE",
    }

    def _a_coordinator_and_an_inactive_greeter(self):
        reset_clock()
        venue = create_venue(
            name="Staff Gate Garden", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Staff Gate Operator")
        program = create_program(
            client_name="Staff Gate Client",
            group_name="Staff Gate Group",
            guaranteed_count=20,
        )
        element = add_element(
            program["id"], supplier["id"], venue_id=venue["id"], **self.ANCHOR
        )
        # Confirmation is only open once the element set is frozen.
        lock_design(program["id"])
        return {
            "program": program,
            "element": element,
            "cora": create_staff_member(**self.CORA),
            "gil": create_staff_member(**self.GIL),
        }

    def _a_proposed_shift_for_the_inactive_greeter(self):
        ctx = self._a_coordinator_and_an_inactive_greeter()
        ctx["shift"] = propose_assignment(
            ctx["gil"]["id"],
            ctx["program"]["id"],
            element_id=ctx["element"]["id"],
            **GREETER_SHIFT,
        )
        return ctx

    def test_a_coordinator_cannot_be_proposed_onto_a_greeter_shift(self, api):
        """PRD §3.6: "The assignment's `role_type` must equal the staff member's own
        `role_type`; that requirement and the discriminator coherence requirement are both
        enforced as `ERR_STAFF_ROLE_MISMATCH`."

        Design: Corner/errors/staff_assignment_role_mismatch_and_inactive_confirm_rejected
        """
        ctx = self._a_coordinator_and_an_inactive_greeter()

        response = api.create_staff_assignment(
            create_staff_assignment_payload(
                ctx["cora"]["id"],
                ctx["program"]["id"],
                element_id=ctx["element"]["id"],
                **GREETER_SHIFT,
            ),
            PD,
        )

        validate_error(response, ApiErrorId.ERR_STAFF_ROLE_MISMATCH.value, 422)
        _, meta = validate_paginated(
            api.list_staff_assignments(
                PD, params={"staff_id": ctx["cora"]["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0

    def test_the_inactive_greeter_is_proposed_but_refused_at_confirmation(self, api):
        """PRD §3.6: "The staff member's `status` must be `ACTIVE`, otherwise
        `ERR_STAFF_INACTIVE`."

        Design: Corner/errors/staff_assignment_role_mismatch_and_inactive_confirm_rejected
        """
        ctx = self._a_proposed_shift_for_the_inactive_greeter()
        assert ctx["shift"]["status"] == "PROPOSED"

        response = api.confirm_staff_assignment(ctx["shift"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_STAFF_INACTIVE.value, 422)
        # Both documents run to 2027-06-30, so the credential gate is not what fired.
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_CREDENTIAL_EXPIRED.value
        )
        stored = validate_success(api.get_staff_assignment(ctx["shift"]["id"], PD))
        assert stored["status"] == "PROPOSED"
        assert stored["planned_labor_cost_cents"] == 0

    def test_repairing_the_roster_status_lets_the_same_shift_confirm(self, api):
        """PRD §3.6: "Otherwise the billable minutes are the larger of the minute basis and
        the DMC's four-hour call-out minimum of 240 minutes — a greeter called out for a
        90-minute airport meet is still paid for four hours."

        Design: Corner/errors/staff_assignment_role_mismatch_and_inactive_confirm_rejected
        """
        ctx = self._a_proposed_shift_for_the_inactive_greeter()
        api.confirm_staff_assignment(ctx["shift"]["id"], PD)

        reinstated = validate_success(
            api.patch_staff_member(ctx["gil"]["id"], {"status": "ACTIVE"}, PD)
        )
        confirmed = validate_success(
            api.confirm_staff_assignment(ctx["shift"]["id"], PD)
        )

        assert reinstated["status"] == "ACTIVE"
        assert confirmed["status"] == "CONFIRMED"
        # 270 scheduled minutes: past the call-out floor, short of the overtime threshold.
        assert confirmed["planned_labor_cost_cents"] == 18_000


class TestOnSiteExecutionIsGatedOnFourClocks:
    ELEMENT_A = {
        "element_type": "ACTIVITY",
        "title": "Sequence Element A",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 40,
        "guaranteed_headcount": 40,
        "per_person_cost_cents": 4_000,
    }
    ELEMENT_B = {
        "element_type": "ACTIVITY",
        "title": "Sequence Element B",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 40,
        "guaranteed_headcount": 40,
        "per_person_cost_cents": 4_000,
    }
    COORDINATOR = {
        "full_name": "Sequence Coordinator",
        "role_type": "COORDINATOR",
        "badge_expires_on": "2027-06-30",
        "first_aid_expires_on": "2027-06-30",
        "pay_rate_cents_per_hour": 5_000,
        "min_rest_minutes": 0,
        "max_daily_minutes": 480,
    }

    def _a_locked_programme_with_a_dependency_edge(self):
        """Element B waits on element A; each sits in its own venue."""
        reset_clock()
        venue_one = create_venue(
            name="Sequence Venue One", capacity_seated=100, capacity_reception=200
        )
        venue_two = create_venue(
            name="Sequence Venue Two", capacity_seated=100, capacity_reception=200
        )
        supplier = create_supplier(legal_name="Sequence Ground Handler")
        program = create_program(
            client_name="Sequence Client",
            group_name="Sequence Group",
            guaranteed_count=40,
            markup_pct=0.18,
        )
        first = add_element(
            program["id"], supplier["id"], venue_id=venue_one["id"], **self.ELEMENT_A
        )
        second = add_element(
            program["id"],
            supplier["id"],
            venue_id=venue_two["id"],
            predecessor_element_id=first["id"],
            **self.ELEMENT_B,
        )
        contract = create_active_contract(
            program["id"], supplier["id"], contract_value_cents=300_000, deposit_pct=0.3
        )
        lock_design(program["id"])
        staff = create_staff_member(**self.COORDINATOR)
        shift = propose_assignment(
            staff["id"],
            program["id"],
            element_id=first["id"],
            starts_at="2026-09-11T08:45:00Z",
            ends_at="2026-09-11T13:15:00Z",
        )
        confirm_assignment(shift["id"])
        return {
            "program": program,
            "first": first,
            "second": second,
            "contract": contract,
            "staff": staff,
            "shift": shift,
        }

    def _the_same_programme_in_execution(self):
        ctx = self._a_locked_programme_with_a_dependency_edge()
        confirm_program(ctx["program"]["id"])
        set_clock("2026-09-10T08:00:00Z")
        return ctx

    def test_execution_opens_neither_before_confirmation_nor_before_arrival(self, api):
        """PRD §3.1: "It requires that the logical clock have reached the programme's
        `arrival_date` — a clock strictly earlier than `arrival_date` is refused with
        `ERR_PROGRAM_WINDOW_NOT_OPEN` — and it is only legal from `CONFIRMED`, with any other
        source state refused as `ERR_PROGRAM_NOT_CONFIRMED`."

        Design: Corner/errors/execution_sequence_preconditions_rejected
        """
        ctx = self._a_locked_programme_with_a_dependency_edge()

        too_early_in_the_lifecycle = api.start_program_execution(ctx["program"]["id"], OC)
        confirmed = validate_success(api.confirm_program(ctx["program"]["id"], PD))
        too_early_on_the_calendar = api.start_program_execution(ctx["program"]["id"], OC)
        set_clock("2026-09-10T08:00:00Z")
        opened = validate_success(api.start_program_execution(ctx["program"]["id"], OC))

        validate_error(
            too_early_in_the_lifecycle, ApiErrorId.ERR_PROGRAM_NOT_CONFIRMED.value, 409
        )
        # Two 40-guest elements at 4,000 a head, marked up 18 hundredths, plus a 12 per
        # cent management fee on the 377,600-cent base.
        assert confirmed["estimated_client_total_cents"] == 422_912
        validate_error(
            too_early_on_the_calendar, ApiErrorId.ERR_PROGRAM_WINDOW_NOT_OPEN.value, 409
        )
        assert opened["execution_status"] == "IN_EXECUTION"

    def test_a_coordinator_cannot_check_in_a_day_ahead_of_the_shift(self, api):
        """PRD §3.6: "The programme must be `IN_EXECUTION`
        (`ERR_PROGRAM_NOT_IN_EXECUTION`), and the logical clock must lie within the window that
        opens 60 minutes before the shift's `starts_at` and closes at its `ends_at`; outside
        that window the attempt is refused with `ERR_CHECKIN_WINDOW_NOT_OPEN`."

        Design: Corner/errors/execution_sequence_preconditions_rejected
        """
        ctx = self._the_same_programme_in_execution()
        validate_success(api.start_program_execution(ctx["program"]["id"], OC))

        response = api.check_in_staff_assignment(
            ctx["shift"]["id"], make_operations_coordinator_headers(ctx["staff"]["id"])
        )

        validate_error(response, ApiErrorId.ERR_CHECKIN_WINDOW_NOT_OPEN.value, 409)
        # The programme is already open on site, so the lifecycle gate is not what fired.
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_PROGRAM_NOT_IN_EXECUTION.value
        )
        stored = validate_success(api.get_staff_assignment(ctx["shift"]["id"], PD))
        assert stored["status"] == "CONFIRMED"
        assert stored["check_in_at"] is None

    def test_an_element_cannot_be_delivered_before_it_starts(self, api):
        """PRD §3.7: "It requires the programme to be `IN_EXECUTION`
        (`ERR_PROGRAM_NOT_IN_EXECUTION`), the logical clock to have reached the element's
        `starts_at` (`ERR_ELEMENT_NOT_STARTED`), and an `actual_headcount` of at least 0 to be
        present in the request body (`ERR_INVALID_REQUEST` when it is missing)."

        Design: Corner/errors/execution_sequence_preconditions_rejected
        """
        ctx = self._the_same_programme_in_execution()
        validate_success(api.start_program_execution(ctx["program"]["id"], OC))
        mark_ready(ctx["first"]["id"])

        response = api.deliver_element(
            ctx["first"]["id"], {"actual_headcount": 40}, OC
        )

        validate_error(response, ApiErrorId.ERR_ELEMENT_NOT_STARTED.value, 409)
        stored = validate_success(api.get_program_element(ctx["first"]["id"], PD))
        assert stored["status"] == "READY"
        assert stored["actual_headcount"] is None

    def test_a_successor_cannot_be_made_ready_while_its_predecessor_only_is(self, api):
        """PRD §3.7: "And the production timeline must have caught up: either
        `predecessor_element_id` is null, or the element it names has reached `DELIVERED`;
        anything else is refused with `ERR_PREDECESSOR_NOT_DELIVERED`."

        Design: Corner/errors/execution_sequence_preconditions_rejected
        """
        ctx = self._the_same_programme_in_execution()
        validate_success(api.start_program_execution(ctx["program"]["id"], OC))
        assert mark_ready(ctx["first"]["id"])["status"] == "READY"

        response = api.mark_element_ready(ctx["second"]["id"], OC)

        validate_error(response, ApiErrorId.ERR_PREDECESSOR_NOT_DELIVERED.value, 409)
        # The programme carries an ACTIVE contract for this supplier, so cover is not the issue.
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_NO_ACTIVE_SUPPLIER_CONTRACT.value
        )
        assert (
            validate_success(api.get_program_element(ctx["second"]["id"], PD))["status"]
            == "PLANNED"
        )
        assert read_program(ctx["program"]["id"])["open_element_count"] == 2


class TestTheSettlementLadderIsOneWay:
    VARIANCE_REASON = (
        "Ten guests dropped after the client trimmed the agenda; attrition floor applied."
    )

    def _a_reconciling_programme_with_one_out_of_tolerance_line(self):
        """Forty guaranteed, thirty turned up: a quarter off the warranted count."""
        ctx = setup_delivered_single_element_program(
            actual_headcount=30,
            program_overrides={
                "client_name": "Ladder Client",
                "group_name": "Ladder Group",
                "guaranteed_count": 40,
                "markup_pct": 0.20,
            },
            element_overrides={"title": "Ladder Element"},
            venue_overrides={"name": "Ladder Venue"},
            supplier_overrides={"legal_name": "Ladder Supplier"},
            contract_overrides={"contract_value_cents": 300_000},
        )
        ctx["lines"] = open_reconciliation(ctx["program"]["id"])
        ctx["line"] = ctx["lines"][0]
        return ctx

    def test_reconciliation_cannot_be_opened_a_second_time(self, api):
        """PRD §3.8: "Three conditions gate it: `settlement_status` must still be
        `NOT_STARTED`, or the request is refused with `ERR_PROGRAM_ALREADY_RECONCILING`; the
        execution dimension must have reached a final state, either `COMPLETED` or `CANCELLED`,
        or the request is refused with `ERR_PROGRAM_NOT_EXECUTION_FINAL`; and at least one
        element of the programme must be in `DELIVERED` or `CANCELLED`, since there is nothing
        to reconcile otherwise, with the empty case refused as
        `ERR_NO_RECONCILABLE_ELEMENTS`."

        Design: Corner/errors/reconciliation_stage_transitions_rejected
        """
        ctx = self._a_reconciling_programme_with_one_out_of_tolerance_line()

        response = api.reconcile_program(ctx["program"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_PROGRAM_ALREADY_RECONCILING.value, 409)
        assert read_program(ctx["program"]["id"])["settlement_status"] == "RECONCILING"
        # The attrition floor of 34 outranks the turnout of 30, and the shortfall is a quarter.
        assert ctx["line"]["billed_headcount"] == 34
        assert ctx["line"]["variance_pct"] == 0.25
        _, meta = validate_paginated(
            api.list_reconciliation_lines(
                PD, params={"program_id": ctx["program"]["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1

    def test_the_invoice_waits_while_a_line_is_still_in_draft(self, api):
        """PRD §3.9: "Two conditions gate it: `settlement_status` must be `RECONCILING`,
        otherwise `ERR_PROGRAM_NOT_RECONCILING`; and every reconciliation line of the programme
        must already be `APPROVED`, with any line still in `DRAFT` blocking the invoice as
        `ERR_RECONCILIATION_LINES_PENDING`."

        Design: Corner/errors/reconciliation_stage_transitions_rejected
        """
        ctx = self._a_reconciling_programme_with_one_out_of_tolerance_line()

        response = api.issue_program_invoice(ctx["program"]["id"], CTRL)

        validate_error(response, ApiErrorId.ERR_RECONCILIATION_LINES_PENDING.value, 409)
        assert (
            validate_success(api.get_reconciliation_line(ctx["line"]["id"], PD))["status"]
            == "DRAFT"
        )
        program = read_program(ctx["program"]["id"])
        assert program["settlement_status"] == "RECONCILING"
        assert program["invoice_issued_at"] is None

    def test_an_out_of_tolerance_line_needs_a_written_reason_before_approval(self, api):
        """PRD §3.8: "And the DMC's variance-tolerance policy applies: a line whose
        `variance_pct` exceeds 10 hundredths may only be approved if `variance_reason` is
        present and non-empty, with the unexplained case refused as
        `ERR_VARIANCE_REASON_REQUIRED`; a line at or below the tolerance needs no explanation."

        Design: Corner/errors/reconciliation_stage_transitions_rejected
        """
        ctx = self._a_reconciling_programme_with_one_out_of_tolerance_line()

        unexplained = api.approve_reconciliation_line(ctx["line"]["id"], PD)

        validate_error(unexplained, ApiErrorId.ERR_VARIANCE_REASON_REQUIRED.value, 422)
        assert (
            validate_success(api.get_reconciliation_line(ctx["line"]["id"], PD))["status"]
            == "DRAFT"
        )

        patch_line(ctx["line"]["id"], variance_reason=self.VARIANCE_REASON)
        approved = approve_line(ctx["line"]["id"])

        assert approved["status"] == "APPROVED"
        assert approved["supplier_cost_cents"] == 170_000
        assert approved["markup_cents"] == 34_000
        assert approved["client_charge_cents"] == 204_000

    def test_once_the_invoice_is_issued_the_line_is_frozen(self, api):
        """PRD §3.8: "Patching increments the line's `version`, and it requires the
        programme's `settlement_status` to be `RECONCILING`, otherwise
        `ERR_PROGRAM_NOT_RECONCILING`."

        Design: Corner/errors/reconciliation_stage_transitions_rejected
        """
        ctx = self._a_reconciling_programme_with_one_out_of_tolerance_line()
        patch_line(ctx["line"]["id"], variance_reason=self.VARIANCE_REASON)
        approve_line(ctx["line"]["id"])

        invoiced = validate_success(
            api.issue_program_invoice(ctx["program"]["id"], CTRL)
        )
        response = api.patch_reconciliation_line(
            ctx["line"]["id"], {"actual_headcount": 35}, PD
        )

        assert invoiced["settlement_status"] == "CLIENT_INVOICED"
        assert invoiced["final_subtotal_cents"] == 170_000
        assert invoiced["disclosed_markup_cents"] == 34_000
        # A 204,000-cent base sits below the 500,000-cent ceiling, so the fee is 12 per cent.
        assert invoiced["management_fee_cents"] == 24_480
        assert invoiced["final_client_total_cents"] == 228_480
        validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_RECONCILING.value, 409)
        assert (
            validate_success(api.get_reconciliation_line(ctx["line"]["id"], PD))[
                "actual_headcount"
            ]
            == 30
        )
