"""Segregation of duties, the open-payable ceiling, contract liveness and the void guard."""

from test_helpers import (
    CONTROLLER_APPROVER_USER_ID,
    CONTROLLER_RELEASER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    make_controller_headers,
    open_settlement_payment,
    read_program,
    setup_pending_settlement,
    validate_error,
    validate_success,
)

SM = TEST_USERS["supplier_manager_headers"]

APPROVER = make_controller_headers(CONTROLLER_APPROVER_USER_ID)
RELEASER = make_controller_headers(CONTROLLER_RELEASER_USER_ID)


class TestSegregationOfDutiesOnRelease:
    def _settlement_approved_by_the_first_controller(self, api):
        """200,000 cents of approved cost against a 150,000-cent banked deposit."""
        ctx = setup_pending_settlement(
            actual_headcount=40,
            deliver_clock="2026-09-11T13:30:00Z",
            program_overrides={
                "client_name": "SoD Client",
                "group_name": "SoD Group",
                "guaranteed_count": 40,
                "markup_pct": 0.20,
            },
            element_overrides={"title": "SoD Element"},
            venue_overrides={"name": "SoD Venue"},
            supplier_overrides={"legal_name": "SoD Supplier"},
            contract_overrides={"contract_value_cents": 500_000, "deposit_pct": 0.3},
        )
        validate_success(api.approve_settlement_payment(ctx["payment"]["id"], APPROVER))
        return ctx

    def test_the_controller_who_approved_may_not_release(self, api):
        """PRD §2.10: "Releasing funds on a settlement payment requires that the acting
        `X-User-ID` differ from the `approved_by_user_id` recorded at approval. A `Controller`
        may not release a payment they themselves approved, and the attempt carries the same
        `ERR_SEGREGATION_OF_DUTIES` code."

        Design: Corner/errors/settlement_release_by_the_approving_controller_returns_403
        """
        ctx = self._settlement_approved_by_the_first_controller(api)

        response = api.release_settlement_payment(ctx["payment"]["id"], APPROVER)

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        stored = validate_success(
            api.get_settlement_payment(ctx["payment"]["id"], APPROVER)
        )
        assert stored["status"] == "APPROVED"
        assert stored["released_by_user_id"] is None
        assert stored["deposit_applied_cents"] == 150_000
        assert stored["net_payable_cents"] == 50_000

    def test_a_second_controller_releases_the_same_payment(self, api):
        """PRD §3.9: "The release is also the trigger for the programme's final bubble-up: if
        the programme's `settlement_status` is `CLIENT_INVOICED` and its
        `supplier_open_payable_cents` has reached zero, and at least one settlement payment of
        the programme is now `PAID`, then the programme advances `CLIENT_INVOICED` →
        `SETTLED`, every supplier contract of that programme still in `ACTIVE` is closed as
        described in §3.3, and the programme's `version` increments."

        Design: Corner/errors/settlement_release_by_the_approving_controller_returns_403
        """
        ctx = self._settlement_approved_by_the_first_controller(api)
        api.release_settlement_payment(ctx["payment"]["id"], APPROVER)

        released = validate_success(
            api.release_settlement_payment(ctx["payment"]["id"], RELEASER)
        )

        assert released["status"] == "PAID"
        assert released["released_by_user_id"] == CONTROLLER_RELEASER_USER_ID
        program = read_program(ctx["program"]["id"])
        assert program["supplier_settled_cents"] == 50_000
        assert program["supplier_open_payable_cents"] == 150_000
        # The deposit covered 150,000 cents of the gross, so the open bucket never
        # reaches zero and the bubble-up to SETTLED is withheld.
        assert program["settlement_status"] == "CLIENT_INVOICED"
        assert (
            validate_success(api.get_supplier_contract(ctx["contract"]["id"], SM))["status"]
            == "ACTIVE"
        )


class TestSettlementMayNotOverdrawTheOpenPayable:
    def _first_settlement_consumes_the_whole_payable(self, api):
        """With no deposit every settlement's net equals its gross of 200,000 cents."""
        ctx = setup_pending_settlement(
            actual_headcount=40,
            deliver_clock="2026-09-11T13:30:00Z",
            program_overrides={
                "client_name": "Overdraw Client",
                "group_name": "Overdraw Group",
                "guaranteed_count": 40,
                "markup_pct": 0.20,
            },
            element_overrides={"title": "Overdraw Element"},
            venue_overrides={"name": "Overdraw Venue"},
            supplier_overrides={"legal_name": "Overdraw Supplier"},
            contract_overrides={"contract_value_cents": 200_000, "deposit_pct": 0},
        )
        validate_success(api.approve_settlement_payment(ctx["payment"]["id"], APPROVER))
        ctx["second"] = open_settlement_payment(
            ctx["program"]["id"], ctx["supplier"]["id"], ctx["contract"]["id"]
        )
        return ctx

    def test_a_second_settlement_for_the_same_gross_cannot_be_approved(self, api):
        """PRD §3.9: "And the payment's `net_payable_cents` may not exceed the programme's
        `supplier_open_payable_cents`, since the DMC will not commit more than it owes; an
        over-commitment is refused with `ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE`."

        Design: Corner/errors/second_settlement_exceeding_open_payable_rejected
        """
        ctx = self._first_settlement_consumes_the_whole_payable(api)

        response = api.approve_settlement_payment(ctx["second"]["id"], APPROVER)

        validate_error(
            response, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_OPEN_PAYABLE.value, 422
        )
        first = validate_success(
            api.get_settlement_payment(ctx["payment"]["id"], APPROVER)
        )
        second = validate_success(
            api.get_settlement_payment(ctx["second"]["id"], APPROVER)
        )
        assert first["status"] == "APPROVED"
        assert first["net_payable_cents"] == 200_000
        assert second["status"] == "PENDING"
        assert second["net_payable_cents"] == 200_000
        program = read_program(ctx["program"]["id"])
        assert program["supplier_settled_cents"] == 200_000
        assert program["supplier_open_payable_cents"] == 0


class TestContractLivenessAndTheVoidGuard:
    def _pending_settlement_against_an_active_contract(self):
        return setup_pending_settlement(
            actual_headcount=40,
            deliver_clock="2026-09-11T13:30:00Z",
            program_overrides={
                "client_name": "Void Path Client",
                "group_name": "Void Path Group",
                "guaranteed_count": 40,
                "markup_pct": 0.18,
            },
            element_overrides={"title": "Void Path Element"},
            venue_overrides={"name": "Void Path Venue"},
            supplier_overrides={"legal_name": "Void Path Coach Company"},
            contract_overrides={"contract_value_cents": 300_000, "deposit_pct": 0},
        )

    def test_a_contract_terminated_after_the_open_blocks_the_approval(self, api):
        """PRD §3.9: "The contract named by `contract_id` must still be `ACTIVE`, otherwise
        `ERR_CONTRACT_NOT_ACTIVE`."

        Design: Corner/errors/settlement_against_a_non_active_contract_and_double_void_rejected
        """
        ctx = self._pending_settlement_against_an_active_contract()
        # A pending payment has committed nothing, so termination is still open.
        validate_success(
            api.terminate_supplier_contract(
                ctx["contract"]["id"],
                SM,
                {"termination_note": "Coach company lost its operating licence."},
            )
        )

        response = api.approve_settlement_payment(ctx["payment"]["id"], APPROVER)

        validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)
        assert (
            validate_success(api.get_supplier_contract(ctx["contract"]["id"], SM))["status"]
            == "TERMINATED"
        )
        assert (
            validate_success(api.get_settlement_payment(ctx["payment"]["id"], APPROVER))[
                "status"
            ]
            == "PENDING"
        )
        assert read_program(ctx["program"]["id"])["supplier_settled_cents"] == 0

    def test_voiding_an_already_void_payment_is_refused(self, api):
        """PRD §3.9: "Attempting to void a payment that has already reached `PAID` or `VOID`
        is refused with `ERR_SETTLEMENT_ALREADY_PAID`."

        Design: Corner/errors/settlement_against_a_non_active_contract_and_double_void_rejected
        """
        ctx = self._pending_settlement_against_an_active_contract()

        voided = validate_success(
            api.void_settlement_payment(
                ctx["payment"]["id"],
                APPROVER,
                {"void_reason": "Opened against the wrong cost centre."},
            )
        )
        response = api.void_settlement_payment(
            ctx["payment"]["id"], APPROVER, {"void_reason": "Duplicate void attempt."}
        )

        assert voided["status"] == "VOID"
        validate_error(response, ApiErrorId.ERR_SETTLEMENT_ALREADY_PAID.value, 409)
        assert (
            validate_success(api.get_settlement_payment(ctx["payment"]["id"], APPROVER))[
                "status"
            ]
            == "VOID"
        )
        program = read_program(ctx["program"]["id"])
        # Voiding from PENDING moves no programme money.
        assert program["supplier_settled_cents"] == 0
        assert program["supplier_open_payable_cents"] == 200_000
