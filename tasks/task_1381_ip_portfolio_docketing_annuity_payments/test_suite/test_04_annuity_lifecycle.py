"""Annuity obligation lifecycle: confirmation-query cycle, terminal lockdown,
release gate on instruct-payment (PRD §3.5)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_world_with_granted_app,
    authorize_obligation,
    instruct_obligation,
    release_authorization,
    list_obligations,
)

MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]


class TestConfirmationQueryReinstructionCycle:
    def test_query_reinstruct_cycle_traversed_twice_then_confirmed(self):
        """PRD §3.5: "a `FinanceOfficer` may raise a confirmation query
        (`PAYMENT_INSTRUCTED → CONFIRMATION_QUERY`) and later reinstruct
        (`CONFIRMATION_QUERY → PAYMENT_INSTRUCTED`); the pair may cycle
        repeatedly."

        Design: Difficulty/non_linear_state_machine/annuity_confirmation_query_reinstruction_cycle
        """
        world = setup_world_with_granted_app(client_name="CycCo")
        obligation = world["obligations"][0]
        instruct_obligation(obligation["id"], 10000, world["contact"]["id"])

        q1 = validate_success(api_client.raise_confirmation_query(obligation["id"], FIN), 200)
        assert q1["status"] == "CONFIRMATION_QUERY"
        r1 = validate_success(api_client.reinstruct_payment(obligation["id"], FIN), 200)
        assert r1["status"] == "PAYMENT_INSTRUCTED"
        q2 = validate_success(api_client.raise_confirmation_query(obligation["id"], FIN), 200)
        assert q2["status"] == "CONFIRMATION_QUERY"
        r2 = validate_success(api_client.reinstruct_payment(obligation["id"], FIN), 200)
        assert r2["status"] == "PAYMENT_INSTRUCTED"
        # After the cycles the obligation can still be confirmed (due 2028-09-01).
        end = validate_success(
            api_client.confirm_payment(obligation["id"], {"paid_date": "2028-09-01"}, FIN), 200)
        assert end["status"] == "PAID_CONFIRMED"
        assert end["paid_amount_cents"] == 10000

    def test_single_cycle_preserves_committed_rollup(self):
        """PRD §3.5: "at all times it equals the sum of `authorized_amount_cents`
        over the family's obligations in `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or
        `CONFIRMATION_QUERY` status, plus the sum of `paid_amount_cents` over
        obligations in `PAID_CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/annuity_confirmation_query_reinstruction_cycle
        """
        from test_helpers import get_family
        world = setup_world_with_granted_app(client_name="CycCo")
        obligation = world["obligations"][0]
        instruct_obligation(obligation["id"], 10000, world["contact"]["id"])
        validate_success(api_client.raise_confirmation_query(obligation["id"], FIN), 200)
        # CONFIRMATION_QUERY is a committed state: the rollup still counts it.
        assert get_family(world["family"]["id"])["committed_forecast_cents"] == 10000
        validate_success(api_client.reinstruct_payment(obligation["id"], FIN), 200)
        assert get_family(world["family"]["id"])["committed_forecast_cents"] == 10000


class TestTerminalLockdownObligation:
    def _paid_obligation(self):
        world = setup_world_with_granted_app(client_name="TermCo")
        obligation = world["obligations"][0]
        instruct_obligation(obligation["id"], 10000, world["contact"]["id"])
        validate_success(
            api_client.confirm_payment(obligation["id"], {"paid_date": "2028-09-01"}, FIN), 200)
        return world, obligation

    def test_deauthorize_on_paid_confirmed_rejected(self):
        """PRD §3.5: "`PAID_CONFIRMED`, `LAPSED`, and `CANCELLED` are terminal
        for obligations"; PRD §2.9: "any transition attempted on a resource
        already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_lockdown_annuity_paid_confirmed
        """
        _, obligation = self._paid_obligation()
        validate_error(api_client.deauthorize_obligation(obligation["id"], MGR),
                       ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_raise_confirmation_query_on_paid_confirmed_rejected(self):
        """PRD §3.5: "`PAID_CONFIRMED`, `LAPSED`, and `CANCELLED` are terminal
        for obligations"; PRD §2.9: "any transition attempted on a resource
        already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_lockdown_annuity_paid_confirmed
        """
        _, obligation = self._paid_obligation()
        validate_error(api_client.raise_confirmation_query(obligation["id"], FIN),
                       ApiErrorId.ERR_ALREADY_TERMINAL)


class TestTerminalLockdownAuthorizationRejected:
    def _rejected_authorization(self):
        from test_helpers import request_authorization, make_client_approver_headers
        world = setup_world_with_granted_app(client_name="RejCo")
        obligation = world["obligations"][0]
        au, _ = request_authorization(obligation["id"], 10000)
        validate_success(
            api_client.reject_authorization(
                au["id"], make_client_approver_headers(world["contact"]["id"])),
            200)
        return world, obligation, au

    def test_approve_on_rejected_authorization_is_terminal(self):
        """PRD §3.5: "`RELEASED`, `REJECTED`, and `SUPERSEDED` are terminal for
        authorizations"; PRD §2.9: "any transition attempted on a resource
        already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_lockdown_authorization_rejected
        """
        from test_helpers import make_client_approver_headers
        world, _, au = self._rejected_authorization()
        validate_error(
            api_client.approve_authorization(au["id"], make_client_approver_headers(world["contact"]["id"])),
            ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_rejection_returns_obligation_to_scheduled_and_allows_fresh_request(self):
        """PRD §3.5: "Rejection records `decided_by_user_id`, marks the
        authorization `REJECTED`, and returns the obligation to `SCHEDULED`; a
        fresh authorization may then be requested, forming a revision loop."

        Design: Corner/state_machines/terminal_lockdown_authorization_rejected
        """
        from test_helpers import request_authorization, get_obligation
        world, obligation, au = self._rejected_authorization()
        assert validate_success(api_client.get_authorization(au["id"], TEST_USERS["any_headers"]), 200)["status"] == "REJECTED"
        assert get_obligation(obligation["id"])["status"] == "SCHEDULED"
        au2, _ = request_authorization(obligation["id"], 10000)
        assert au2["status"] == "REQUESTED"


class TestInstructPaymentRequiresReleasedAuthorization:
    def test_instruct_with_approved_but_unreleased_authorization_rejected(self):
        """PRD §3.5: "Instructing payment moves the obligation `AUTHORIZED →
        PAYMENT_INSTRUCTED` and is gated three ways: the current authorization
        must be `RELEASED` (`ERR_AUTHORIZATION_NOT_RELEASED`); when the
        jurisdiction rule enables `requires_recorded_assignment_for_payment`,
        a `RECORDED` assignment record must exist for the application
        (`ERR_ASSIGNMENT_RECORDATION_REQUIRED`); and when the rule enables
        `requires_confirmed_instruction_for_payment`, an outside counsel
        instruction of type `ANNUITY_PAYMENT` on the application must be
        `CONFIRMED` or `COMPLETED` (`ERR_COUNSEL_INSTRUCTION_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/instruct_payment_requires_authorization_released
        """
        world = setup_world_with_granted_app(client_name="GateCo")
        obligation = world["obligations"][0]
        au = authorize_obligation(obligation["id"], 10000, world["contact"]["id"])
        validate_error(api_client.instruct_payment(obligation["id"], FIN),
                       ApiErrorId.ERR_AUTHORIZATION_NOT_RELEASED)
        validate_success(api_client.release_authorization(au["id"], FIN), 200)
        data = validate_success(api_client.instruct_payment(obligation["id"], FIN), 200)
        assert data["status"] == "PAYMENT_INSTRUCTED"

    def test_instruct_while_obligation_not_authorized_is_invalid_state(self):
        """PRD §2.9: "an undefined transition is rejected with
        `ERR_INVALID_STATE`, and any transition attempted on a resource
        already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`";
        PRD §3.5: "Instructing payment moves the
        obligation `AUTHORIZED → PAYMENT_INSTRUCTED` and is gated three ways"

        Design: Difficulty/cross_entity_state_dependency/instruct_payment_requires_authorization_released
        """
        world = setup_world_with_granted_app(client_name="GateCo")
        obligation = world["obligations"][0]
        # Obligation is SCHEDULED (no authorization requested): the transition is undefined.
        validate_error(api_client.instruct_payment(obligation["id"], FIN),
                       ApiErrorId.ERR_INVALID_STATE)
