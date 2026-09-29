"""One entity's state gating another's transition: contract coverage and execution phase."""

from test_helpers import (
    CONTRACT_SIGNER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    confirm_assignment,
    confirm_program,
    create_sent_contract,
    create_staff_member,
    lock_design,
    make_operations_coordinator_headers,
    make_supplier_manager_headers,
    mark_ready,
    propose_assignment,
    set_clock,
    setup_program_with_contracted_element,
    setup_program_with_element,
    start_execution,
    validate_error,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]


class TestActiveContractCoverageGate:
    BRUNCH = {
        "element_type": "ACTIVITY",
        "title": "Conservatory Brunch",
        "starts_at": "2026-09-12T09:00:00Z",
        "ends_at": "2026-09-12T12:00:00Z",
        "planned_headcount": 35,
        "guaranteed_headcount": 35,
        "per_person_cost_cents": 6_000,
    }

    def _locked_programme_with_an_unsigned_contract(self):
        ctx = setup_program_with_element(
            program_overrides={
                "client_name": "Wexford Energy",
                "group_name": "Board Retreat",
                "guaranteed_count": 35,
            },
            element_overrides=self.BRUNCH,
            venue_overrides={"name": "Botanical Conservatory"},
            supplier_overrides={"legal_name": "Conservatory Events Co"},
        )
        ctx["contract"] = create_sent_contract(
            ctx["program"]["id"], ctx["supplier"]["id"], contract_value_cents=800_000
        )
        assert ctx["contract"]["status"] == "SENT"
        lock_design(ctx["program"]["id"])
        return ctx

    def _countersign(self, api, contract_id):
        return validate_success(
            api.countersign_supplier_contract(
                contract_id, make_supplier_manager_headers(CONTRACT_SIGNER_USER_ID)
            )
        )

    def test_an_element_covered_only_by_an_unsigned_contract_blocks_confirmation(self, api):
        """PRD §3.1: "Confirmation requires that no element of the programme sit in
        `PERMIT_BLOCKED` — otherwise `ERR_PERMIT_NOT_APPROVED` — and that every element of
        the programme still in `PLANNED` or `READY` be covered by a supplier contract for
        the same programme and the same supplier whose `status` is `ACTIVE`; an uncovered
        element yields `ERR_NO_ACTIVE_SUPPLIER_CONTRACT`."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_active_supplier_contract
        """
        ctx = self._locked_programme_with_an_unsigned_contract()

        response = api.confirm_program(ctx["program"]["id"], PD)

        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_SUPPLIER_CONTRACT.value, 409)
        element = validate_success(api.get_program_element(ctx["element"]["id"], PD))
        program = validate_success(api.get_program(ctx["program"]["id"], PD))
        assert element["status"] == "PLANNED"
        assert program["execution_status"] == "DESIGN_LOCKED"

    def test_countersignature_activates_the_contract_and_banks_the_deposit(self, api):
        """PRD §3.3: "On success it stamps `countersigned_by_user_id` with the acting
        `X-User-ID`, computes `deposit_due_cents` as the contract value multiplied by
        `deposit_pct` and rounded half up to whole cents, sets `deposit_paid_cents` equal to
        `deposit_due_cents` — the deposit is treated as banked at signature — and increments
        the contract's `version`."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_active_supplier_contract
        """
        ctx = self._locked_programme_with_an_unsigned_contract()

        contract = self._countersign(api, ctx["contract"]["id"])

        assert contract["status"] == "ACTIVE"
        assert contract["deposit_due_cents"] == 240_000
        assert contract["deposit_paid_cents"] == 240_000

    def test_mark_ready_goes_through_once_the_contract_is_active(self, api):
        """PRD §3.7: "A supplier contract for this element's programme and supplier with
        status `ACTIVE` must exist, otherwise `ERR_NO_ACTIVE_SUPPLIER_CONTRACT`."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_active_supplier_contract
        """
        ctx = self._locked_programme_with_an_unsigned_contract()
        self._countersign(api, ctx["contract"]["id"])
        program = confirm_program(ctx["program"]["id"])

        element = mark_ready(ctx["element"]["id"])

        assert program["execution_status"] == "CONFIRMED"
        # Nothing about the element itself changed; only its contract cover did.
        assert element["status"] == "READY"


class TestExecutionPhaseGateOnStaffCheckIn:
    TOUR = {
        "element_type": "ACTIVITY",
        "title": "Museum Private Tour",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 25,
        "guaranteed_headcount": 25,
        "per_person_cost_cents": 7_000,
    }

    def _confirmed_programme_inside_the_check_in_window(self):
        ctx = setup_program_with_contracted_element(
            program_overrides={
                "client_name": "Larkspur Ventures",
                "group_name": "LP Weekend",
                "guaranteed_count": 25,
            },
            element_overrides=self.TOUR,
            venue_overrides={"name": "Maritime Museum Hall"},
            supplier_overrides={"legal_name": "Maritime Programs Inc"},
        )
        staff = create_staff_member(
            full_name="Nadia Farouk", pay_rate_cents_per_hour=3_600
        )
        assignment = propose_assignment(
            staff["id"],
            ctx["program"]["id"],
            target_type="ELEMENT",
            element_id=ctx["element"]["id"],
            role_type="COORDINATOR",
            starts_at="2026-09-11T09:00:00Z",
            ends_at="2026-09-11T13:00:00Z",
        )
        lock_design(ctx["program"]["id"])
        ctx["assignment"] = confirm_assignment(assignment["id"])
        ctx["program"] = confirm_program(ctx["program"]["id"])
        ctx["staff"] = staff
        # Half an hour into the shift, so the 60-minute window is wide open.
        set_clock("2026-09-11T09:30:00Z")
        return ctx

    def test_check_in_is_refused_while_the_programme_is_merely_confirmed(self, api):
        """PRD §3.6: "The programme must be `IN_EXECUTION`
        (`ERR_PROGRAM_NOT_IN_EXECUTION`), and the logical clock must lie within the window
        that opens 60 minutes before the shift's `starts_at` and closes at its `ends_at`;
        outside that window the attempt is refused with `ERR_CHECKIN_WINDOW_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/staff_check_in_blocked_until_program_in_execution
        """
        ctx = self._confirmed_programme_inside_the_check_in_window()

        response = api.check_in_staff_assignment(
            ctx["assignment"]["id"],
            make_operations_coordinator_headers(ctx["staff"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_IN_EXECUTION.value, 409)
        assignment = validate_success(
            api.get_staff_assignment(ctx["assignment"]["id"], PD)
        )
        assert assignment["status"] == "CONFIRMED"
        assert assignment["check_in_at"] is None

    def test_the_same_call_goes_through_once_execution_opens(self, api):
        """PRD §3.6: "On-site check-in advances the assignment `CONFIRMED` → `CHECKED_IN`
        and stamps `check_in_at` from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/staff_check_in_blocked_until_program_in_execution
        """
        ctx = self._confirmed_programme_inside_the_check_in_window()
        program = start_execution(ctx["program"]["id"], clock=None)

        assignment = validate_success(
            api.check_in_staff_assignment(
                ctx["assignment"]["id"],
                make_operations_coordinator_headers(ctx["staff"]["id"]),
            )
        )

        assert program["execution_status"] == "IN_EXECUTION"
        assert assignment["status"] == "CHECKED_IN"
        assert assignment["check_in_at"].startswith("2026-09-11T09:30:00")
