"""Endpoint authorisation, per-record ownership, missing headers and the contracting desk."""

from test_helpers import (
    CONTRACT_SENDER_USER_ID,
    CONTRACT_SIGNER_USER_ID,
    CONTROLLER_APPROVER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    create_program,
    create_program_payload,
    create_sent_contract,
    create_settlement_payment_payload,
    create_supplier,
    draft_contract,
    make_controller_headers,
    make_supplier_headers,
    make_supplier_manager_headers,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
SM = TEST_USERS["supplier_manager_headers"]
PO = TEST_USERS["permit_officer_headers"]
CTRL = make_controller_headers(CONTROLLER_APPROVER_USER_ID)

SENDER = make_supplier_manager_headers(CONTRACT_SENDER_USER_ID)
SIGNER = make_supplier_manager_headers(CONTRACT_SIGNER_USER_ID)

NO_HEADERS = {}

ROLE_TEST_PROGRAM = {
    "client_name": "Role Test Client",
    "group_name": "Role Test Group",
    "guaranteed_count": 20,
}


class TestProgrammeIntakeIsTheDirectorsAlone:
    def test_the_same_payload_is_refused_for_the_coordinator_and_accepted_for_the_director(
        self, api
    ):
        """PRD §2.1: "If the headers are well-formed but the declared role is not among those
        authorised for the endpoint being called (see the authorisation column of §4), the
        request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/operations_coordinator_cannot_create_a_program
        """
        reset_clock()
        payload = create_program_payload(**ROLE_TEST_PROGRAM)

        refused = api.create_program(payload, OC)
        accepted = api.create_program(payload, PD)

        validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        program = validate_success(accepted, 201)
        items, meta = validate_paginated(
            api.list_programs(PD, params={"limit": 10, "offset": 0})
        )
        # Exactly one row: the refused attempt stored nothing.
        assert meta["total_count"] == 1
        assert [item["id"] for item in items] == [program["id"]]


class TestMoneyMovementIsTheControllersAlone:
    def test_the_permit_officer_cannot_open_a_supplier_settlement(self, api):
        """PRD §3.9: "A `Controller` opens a **settlement payment** by supplying the
        `program_id`, the `supplier_id` of the payee, the `contract_id` of the contract being
        discharged, and the `expected_contract_version` guard of §2.5."

        Design: Corner/rbac/permit_officer_cannot_approve_a_settlement
        """
        reset_clock()
        supplier = create_supplier(legal_name="Role Boundary Supplier")
        program = create_program(
            client_name="Role Boundary Client",
            group_name="Role Boundary Group",
            guaranteed_count=20,
        )
        contract = draft_contract(
            program["id"], supplier["id"], contract_value_cents=100_000
        )

        response = api.create_settlement_payment(
            create_settlement_payment_payload(
                program["id"], supplier["id"], contract["id"], contract["version"]
            ),
            PO,
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        _, meta = validate_paginated(
            api.list_settlement_payments(
                CTRL, params={"program_id": program["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0


class TestSupplierAuthorisationIsPerRecord:
    def _a_sent_contract_belonging_to_the_first_supplier(self):
        reset_clock()
        owner = create_supplier(legal_name="Owner Supplier")
        intruder = create_supplier(legal_name="Intruder Supplier")
        program = create_program(
            client_name="Ownership Client",
            group_name="Ownership Group",
            guaranteed_count=20,
        )
        contract = create_sent_contract(
            program["id"], owner["id"], contract_value_cents=300_000
        )
        return {"owner": owner, "intruder": intruder, "contract": contract}

    def test_only_the_named_supplier_may_counter_its_own_contract(self, api):
        """PRD §2.1: "When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting
        `Supplier`; ownership checks on any resource that references a `Supplier` compare the
        resource's foreign-key field to `X-User-ID`. A counter-offer on a contract therefore
        requires `X-User-ID` to equal that contract's `supplier_id`, and a supplier attempting
        to counter somebody else's contract receives `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/supplier_cannot_counter_another_suppliers_contract
        """
        ctx = self._a_sent_contract_belonging_to_the_first_supplier()

        intrusion = api.counter_supplier_contract(
            ctx["contract"]["id"],
            {"countered_value_cents": 260_000},
            make_supplier_headers(ctx["intruder"]["id"]),
        )

        validate_error(intrusion, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        # The intruder does hold the Supplier role, so the endpoint itself was open to them.
        assert (
            intrusion.json()["data"]["error_id"]
            != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        )
        assert (
            validate_success(api.get_supplier_contract(ctx["contract"]["id"], SM))["status"]
            == "SENT"
        )

        countered = validate_success(
            api.counter_supplier_contract(
                ctx["contract"]["id"],
                {"countered_value_cents": 330_000},
                make_supplier_headers(ctx["owner"]["id"]),
            )
        )

        assert countered["status"] == "COUNTERED"
        assert countered["contract_value_cents"] == 330_000
        # Only the send moved the counter, and there has been exactly one.
        assert countered["round_count"] == 1


class TestAuthenticationPrecedesAuthorisation:
    def test_a_request_with_no_role_header_at_all_is_unauthenticated(self, api):
        """PRD §2.1: "If either header is absent, empty or malformed, or if `X-User-Role` is
        not one of the six declared role names, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_missing_x_user_role_header_is_unauthenticated
        """
        reset_clock()

        response = api.create_program(
            create_program_payload(
                client_name="Anonymous Client",
                group_name="Anonymous Group",
                guaranteed_count=20,
            ),
            NO_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        # Authentication answers first, so the role verdict is never reached.
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        )
        _, meta = validate_paginated(
            api.list_programs(PD, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0


class TestTheCostSummaryIsASharedRead:
    def test_the_director_and_the_controller_see_the_same_zeroes_and_the_coordinator_none(
        self, api
    ):
        """PRD §3.9: "That read is restricted to a `ProgramDirector` or a `Controller`; the
        operational roles do not see the fee ladder."

        Design: Corner/rbac/controller_and_program_director_share_the_cost_summary_read
        """
        reset_clock()
        program = create_program(
            client_name="Shared Read Client",
            group_name="Shared Read Group",
            guaranteed_count=20,
        )

        as_director = validate_success(api.get_program_cost_summary(program["id"], PD))
        as_controller = validate_success(api.get_program_cost_summary(program["id"], CTRL))
        as_coordinator = api.get_program_cost_summary(program["id"], OC)

        assert as_director["program_id"] == program["id"]
        assert as_controller["program_id"] == program["id"]
        for field in (
            "final_subtotal_cents",
            "disclosed_markup_cents",
            "management_fee_cents",
            "final_client_total_cents",
        ):
            assert as_director[field] == 0, field
            assert as_controller[field] == as_director[field], field
        validate_error(as_coordinator, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)


class TestCountersignatureNeedsASecondManager:
    def _a_contract_sent_by_the_first_manager(self):
        reset_clock()
        supplier = create_supplier(legal_name="SoD Contract Supplier")
        program = create_program(
            client_name="SoD Contract Client",
            group_name="SoD Contract Group",
            guaranteed_count=20,
        )
        return create_sent_contract(
            program["id"], supplier["id"], contract_value_cents=300_000, deposit_pct=0.3
        )

    def test_the_sender_cannot_countersign_and_a_colleague_can(self, api):
        """PRD §2.10: "Countersigning a supplier contract requires that the acting
        `X-User-ID` differ from the `sent_by_user_id` recorded when the contract was last sent.
        A `SupplierManager` may not countersign a contract they themselves sent; the attempt is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/countersign_by_the_sending_user_is_segregation_of_duties
        """
        contract = self._a_contract_sent_by_the_first_manager()

        by_the_sender = api.countersign_supplier_contract(contract["id"], SENDER)

        validate_error(by_the_sender, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        assert (
            validate_success(api.get_supplier_contract(contract["id"], SM))["status"]
            == "SENT"
        )

        activated = validate_success(
            api.countersign_supplier_contract(contract["id"], SIGNER)
        )

        assert activated["status"] == "ACTIVE"
        # Three tenths of 300,000 cents, treated as banked at signature.
        assert activated["deposit_due_cents"] == 90_000
        assert activated["deposit_paid_cents"] == 90_000
