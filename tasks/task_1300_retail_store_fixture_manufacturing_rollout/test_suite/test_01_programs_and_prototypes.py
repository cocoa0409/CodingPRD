"""Program stand-up, prototype engineering, and the value-engineering loop."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_fixture_prototype,
    assert_rollout_program,
    create_active_program,
    create_program,
    create_prototype,
    is_valid_uuid,
    make_fixture_engineer_headers,
    make_hotline_agent_headers,
    make_program_manager_headers,
    make_store_manager_headers,
    submit_prototype,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_HEADERS_PM = make_program_manager_headers("pm-suite-1")
TEST_HEADERS_FE = make_fixture_engineer_headers("eng-suite-1")
TEST_HEADERS_SM = make_store_manager_headers("sm-suite-1")
TEST_HEADERS_HA = make_hotline_agent_headers("ha-suite-1")


class TestProgramCreation:

    def test_program_create_defaults_and_envelope(self):
        """PRD §3.1: "A new program is born in `DRAFT` status with its computed
        fields initialized: `remaining_budget_cents` equals `budget_total_cents`,
        while `contingency_spent_cents`, `fulfilled_kit_count`, and
        `closeout_recovery_cents` all start at zero, and
        `final_reconciliation_cents` stays null."
        PRD §3.1: "Two optional fields shape later behavior:
        `recalled_part_numbers`, a list of part numbers under recall hold that
        defaults to an empty list when omitted, and `attic_valuation_method`,
        which selects how leftover attic stock will be valued at disposition —
        `PROGRAM_AVERAGE` or `LIQUIDATION` — and defaults to `PROGRAM_AVERAGE`."
        PRD §2.4: "**`id` (string):** a unique, server-minted UUID with no type
        prefix, assigned at creation."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/program_create_defaults_and_envelope
        """
        resp = api_client.create_rollout_program(
            {
                "program_name": "P-CORNER",
                "retailer_code": "RTL-C",
                "budget_total_cents": 500_000,
                "contingency_budget_cents": 50_000,
            },
            TEST_HEADERS_PM,
        )
        body = resp.json()
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        assert body["meta"]["api_request_id"].startswith("req_"), \
            "api_request_id must start with req_"
        assert body["response_type"] == "object"
        data = body["data"]
        assert_rollout_program(data)
        assert data["status"] == "DRAFT"
        assert data["remaining_budget_cents"] == 500_000
        assert data["contingency_spent_cents"] == 0
        assert data["fulfilled_kit_count"] == 0
        assert data["closeout_recovery_cents"] == 0
        assert data["final_reconciliation_cents"] is None
        assert data["attic_valuation_method"] == "PROGRAM_AVERAGE"
        assert data["recalled_part_numbers"] == []
        assert is_valid_uuid(data["id"])

    def test_program_get_not_found_returns_404(self):
        """PRD §2.7: "Identifiers embedded in the URL are resolved strictly left
        to right; the first identifier that does not correspond to an existing
        resource produces that resource's not-found error —
        `ERR_PROGRAM_NOT_FOUND`, `ERR_PROTOTYPE_NOT_FOUND`,
        `ERR_KIT_CONFIG_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`,
        `ERR_RESERVATION_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`, or
        `ERR_LEDGER_NOT_FOUND` — and later path segments are never evaluated."

        Design: Corner/entities/program_not_found_returns_404
        """
        resp = api_client.get_rollout_program(NON_EXISTENT_UUID, TEST_HEADERS_PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)

    def test_program_create_ignores_client_supplied_computed_field(self):
        """PRD §3.1: "A new program is born in `DRAFT` status with its computed
        fields initialized: `remaining_budget_cents` equals
        `budget_total_cents`, while `contingency_spent_cents`,
        `fulfilled_kit_count`, and `closeout_recovery_cents` all start at zero,
        and `final_reconciliation_cents` stays null."
        PRD §2.9: "None of these aggregates is writable by clients; each
        changes only as a side effect of the workflows in §3, and each change
        is a mutation that refreshes the program's `updated_at` and increments
        its `version`."

        Design: Corner/entities/computed_field_input_ignored_on_program_create
        """
        resp = api_client.create_rollout_program(
            {
                "program_name": "P-IGN",
                "retailer_code": "RTL-C",
                "budget_total_cents": 500_000,
                "contingency_budget_cents": 50_000,
                "remaining_budget_cents": 1,
            },
            TEST_HEADERS_PM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["remaining_budget_cents"] == 500_000, (
            f"client-supplied remaining_budget_cents must be ignored; got "
            f"{data['remaining_budget_cents']}"
        )


class TestProgramActivation:

    def test_activate_active_program_returns_409(self):
        """PRD §3.1: "Activation requires the program to still be in `DRAFT` —
        attempting it from any other state fails with `ERR_PROGRAM_NOT_ACTIVE`
        — and requires `budget_total_cents` to be positive, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/activate_active_program_returns_409
        """
        program = create_active_program("P-SM1", 500_000, 50_000)
        assert program["status"] == "ACTIVE"
        resp = api_client.activate_program(program["id"], TEST_HEADERS_PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        after = validate_success(
            api_client.get_rollout_program(program["id"], TEST_HEADERS_PM))
        assert after["status"] == "ACTIVE"


class TestPrototypeCreation:

    def test_prototype_missing_required_field_returns_400(self):
        """PRD §3.2: "A `FixtureEngineer` creates it with the `program_id` of
        its program (an unknown program is rejected with
        `ERR_PROGRAM_NOT_FOUND`), a `fixture_code` such as a gondola model
        designation, a cost `target_cost_cents`, and the bill of materials
        `bom_lines`."
        PRD §2.7: "Required fields present and correctly typed, enum values
        drawn from their declared sets, quantities of at least 1, windows whose
        end is strictly after their start (`ERR_INVALID_WINDOW`), and the
        domain shape rules — value engineering only when the list-price
        estimate exceeds target (`ERR_VE_NOT_REQUIRED`), a non-empty kit at
        freeze (`ERR_KIT_EMPTY`), photo evidence present
        (`ERR_PHOTO_EVIDENCE_REQUIRED`), no second pending signoff for a
        delivery (`ERR_SIGNOFF_ALREADY_PENDING`), and no ledger adjustment that
        would drive stock below zero (`ERR_STOCK_UNDERFLOW`). Malformed or
        mistyped input in this category reports `ERR_INVALID_REQUEST`."

        Design: Corner/entities/prototype_missing_required_field_returns_400
        """
        program = create_program("P-REQ", 500_000, 50_000)
        resp = api_client.create_fixture_prototype(
            {
                "program_id": program["id"],
                "fixture_code": "GONDOLA-4FT",
                "bom_lines": [
                    {"part_number": "PN-1", "quantity": 1,
                     "list_unit_cost_cents": 100},
                ],
            },
            TEST_HEADERS_FE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        listed, meta = validate_paginated(api_client.list_fixture_prototypes(
            TEST_HEADERS_PM, params={"program_id": program["id"]}))
        assert meta["total_count"] == 0
        assert listed == []


class TestValueEngineeringGate:

    def test_ve_request_when_under_target_rejected(self):
        """PRD §3.2: "Requesting value engineering when the provisional
        estimate has not exceeded the target is rejected with
        `ERR_VE_NOT_REQUIRED`, and requesting it from any state other than
        `ENGINEERING_REVIEW` is rejected with `ERR_PROTOTYPE_INVALID_STATE`."

        Design: Corner/validations/ve_request_when_under_target_rejected
        """
        program = create_active_program("P-VAL5", 1_000_000, 100_000)
        proto = create_prototype(
            program["id"], fixture_code="GONDOLA-8FT",
            bom_lines=[{"part_number": "PN-300", "quantity": 5,
                        "list_unit_cost_cents": 9000}],
            target_cost_cents=50_000,
        )
        assert proto["provisional_cost_cents"] == 45_000
        submit_prototype(proto["id"], "eng-1")
        resp = api_client.request_value_engineering(proto["id"], TEST_HEADERS_PM)
        validate_error(resp, ApiErrorId.ERR_VE_NOT_REQUIRED)
        after = validate_success(
            api_client.get_fixture_prototype(proto["id"], TEST_HEADERS_PM))
        assert after["status"] == "ENGINEERING_REVIEW"
        assert after["ve_round_count"] == 0


class TestPrototypeApprovalSecurity:

    def test_prototype_self_approval_blocked_by_sod(self):
        """PRD §3.2: "Segregation of duties is enforced: the approving
        manager's `X-User-ID` must differ from the prototype's recorded
        `submitted_by_user_id`, and a violation is rejected with
        `ERR_PROTOTYPE_SELF_APPROVAL` (HTTP 403)."

        Design: Corner/rbac/prototype_self_approval_blocked_by_sod
        """
        program = create_active_program("P-RBAC4", 1_000_000, 100_000)
        proto = create_prototype(program["id"], fixture_code="ENDCAP")
        submit_prototype(proto["id"], "pm-dual")
        resp = api_client.approve_prototype(
            proto["id"], make_program_manager_headers("pm-dual"))
        validate_error(resp, ApiErrorId.ERR_PROTOTYPE_SELF_APPROVAL)
        after = validate_success(
            api_client.get_fixture_prototype(proto["id"], TEST_HEADERS_PM))
        assert after["status"] == "ENGINEERING_REVIEW"

    def test_engineer_cannot_approve_prototype_forbidden(self):
        """PRD §2.1: "When the role named in `X-User-Role` is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: the `/fixture-prototypes/{id}/approve` row authorizes only
        ProgramManager.

        Design: Corner/validations/engineer_cannot_approve_prototype_forbidden
        """
        program = create_active_program("P-VAL2", 1_000_000, 100_000)
        proto = create_prototype(program["id"], fixture_code="ENDCAP")
        submit_prototype(proto["id"], "eng-1")
        resp = api_client.approve_prototype(
            proto["id"], make_fixture_engineer_headers("eng-2"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(
            api_client.get_fixture_prototype(proto["id"], TEST_HEADERS_PM))
        assert after["status"] == "ENGINEERING_REVIEW"

    def test_store_manager_cannot_create_program_forbidden(self):
        """PRD §2.1: "When the role named in `X-User-Role` is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: the `/rollout-programs` creation row authorizes only
        ProgramManager.

        Design: Corner/rbac/store_manager_cannot_create_program_forbidden
        """
        resp = api_client.create_rollout_program(
            {
                "program_name": "P-RBAC1",
                "retailer_code": "RTL-C",
                "budget_total_cents": 500_000,
                "contingency_budget_cents": 50_000,
            },
            TEST_HEADERS_SM,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestAuthAndReadAccess:

    def test_missing_auth_headers_returns_400(self):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)
        before any other processing occurs."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api_client.list_rollout_programs(
            {"Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_any_role_can_read_lists(self):
        """PRD §2.1: "Read endpoints (single-resource retrieval and list
        retrieval) are available to any authenticated caller presenting one of
        the nine roles."

        Design: Corner/rbac/any_role_can_read_lists
        """
        create_program("P-RBAC5", 500_000, 50_000)
        data, meta = validate_paginated(
            api_client.list_rollout_programs(TEST_HEADERS_HA))
        assert meta["total_count"] == 1
        assert len(data) == 1


class TestPrototypeDualVariantEstimate:
    """The list-price (provisional) and negotiated-price (engineered) variants
    of the prototype cost estimate, and finalization at approval."""

    BOM = [
        {"part_number": "PN-100", "quantity": 10, "list_unit_cost_cents": 5000},
        {"part_number": "PN-200", "quantity": 4, "list_unit_cost_cents": 1250},
    ]
    BOM_VE = [
        {"part_number": "PN-100", "quantity": 10, "list_unit_cost_cents": 5000,
         "negotiated_unit_cost_cents": 4200},
        {"part_number": "PN-200", "quantity": 4, "list_unit_cost_cents": 1250},
    ]

    def test_provisional_vs_engineered_after_ve_and_approval(self):
        """PRD §3.2: "The `provisional_cost_cents` is the list-price basis: for
        each BOM line, the line's `quantity` multiplied by its
        `list_unit_cost_cents`, rounded half up to a whole cent, and then
        summed across lines. It is never rewritten by value-engineering
        activity."
        PRD §3.2: "Approval finalizes `final_cost_cents`: when the prototype
        has been through at least one value-engineering round —
        `ve_round_count` greater than zero — the final cost is the
        `engineered_cost_cents`; otherwise it is the `provisional_cost_cents`."

        Design: Difficulty/dual_variant_calc/prototype_estimate_provisional_vs_engineered
        """
        program = create_active_program("P-DUAL-PROTO", 1_000_000, 100_000)
        proto = create_prototype(
            program["id"], bom_lines=self.BOM, target_cost_cents=50_000)
        submit_prototype(proto["id"], "eng-1")
        api_client.request_value_engineering(proto["id"], TEST_HEADERS_PM)
        api_client.patch_fixture_prototype(
            proto["id"], {"bom_lines": self.BOM_VE}, TEST_HEADERS_FE)
        submit_prototype(proto["id"], "eng-1")
        approved = validate_success(api_client.approve_prototype(
            proto["id"], make_program_manager_headers("pm-1")))
        assert_fixture_prototype(approved)
        assert approved["provisional_cost_cents"] == 55_000
        assert approved["engineered_cost_cents"] == 47_000
        assert approved["final_cost_cents"] == 47_000
        assert approved["provisional_cost_cents"] \
            != approved["engineered_cost_cents"]
        assert approved["ve_round_count"] == 1
        assert approved["status"] == "APPROVED"

    def test_engineered_falls_back_to_list_until_negotiated_prices_exist(self):
        """PRD §3.2: "The `engineered_cost_cents` follows the same
        per-line-round-then-sum discipline but uses each line's
        `negotiated_unit_cost_cents` where one is present and falls back to
        `list_unit_cost_cents` where it is not; it therefore diverges from the
        provisional figure as soon as any negotiated price differs from list.
        A third figure, `final_cost_cents`, stays null until approval."
        PRD §3.2: "It is never rewritten by value-engineering activity."

        Design: Difficulty/dual_variant_calc/prototype_estimate_provisional_vs_engineered
        """
        program = create_active_program("P-DUAL-PROTO2", 1_000_000, 100_000)
        proto = create_prototype(
            program["id"], bom_lines=self.BOM, target_cost_cents=50_000)
        # No negotiated prices yet: the engineered variant falls back to list.
        assert proto["provisional_cost_cents"] == 55_000
        assert proto["engineered_cost_cents"] == 55_000
        assert proto["final_cost_cents"] is None
        submit_prototype(proto["id"], "eng-1")
        api_client.request_value_engineering(proto["id"], TEST_HEADERS_PM)
        patched = validate_success(api_client.patch_fixture_prototype(
            proto["id"], {"bom_lines": self.BOM_VE}, TEST_HEADERS_FE))
        # The provisional basis is never rewritten; only engineered moves.
        assert patched["provisional_cost_cents"] == 55_000
        assert patched["engineered_cost_cents"] == 47_000
        assert patched["final_cost_cents"] is None


class TestPrototypeValueEngineeringCycle:
    """The ENGINEERING_REVIEW -> VALUE_ENGINEERING -> ENGINEERING_REVIEW loop."""

    BOM = [
        {"part_number": "PN-100", "quantity": 10, "list_unit_cost_cents": 5000},
        {"part_number": "PN-200", "quantity": 4, "list_unit_cost_cents": 1250},
    ]

    def test_two_full_ve_rounds_before_approval(self):
        """PRD §3.2: "If the prototype's list-price estimate exceeds its cost
        target — that is, `provisional_cost_cents` is strictly greater than
        `target_cost_cents` — the manager may send it into a value-engineering
        round, moving it `ENGINEERING_REVIEW → VALUE_ENGINEERING` and
        incrementing `ve_round_count` by one."
        PRD §3.2: "Approval finalizes `final_cost_cents`: when the prototype
        has been through at least one value-engineering round —
        `ve_round_count` greater than zero — the final cost is the
        `engineered_cost_cents`; otherwise it is the `provisional_cost_cents`."

        Design: Difficulty/non_linear_state_machine/prototype_value_engineering_cycle
        """
        program = create_active_program("P-VE", 1_000_000, 100_000)
        proto = create_prototype(
            program["id"], bom_lines=self.BOM, target_cost_cents=50_000)
        submit_prototype(proto["id"], "eng-1")
        # Round 1: negotiated 4200 -> engineered 47000
        api_client.request_value_engineering(proto["id"], TEST_HEADERS_PM)
        api_client.patch_fixture_prototype(
            proto["id"],
            {"bom_lines": [
                {"part_number": "PN-100", "quantity": 10,
                 "list_unit_cost_cents": 5000,
                 "negotiated_unit_cost_cents": 4200},
                {"part_number": "PN-200", "quantity": 4,
                 "list_unit_cost_cents": 1250},
            ]},
            TEST_HEADERS_FE,
        )
        submit_prototype(proto["id"], "eng-1")
        # Round 2: negotiated 4000 -> engineered 45000
        api_client.request_value_engineering(proto["id"], TEST_HEADERS_PM)
        api_client.patch_fixture_prototype(
            proto["id"],
            {"bom_lines": [
                {"part_number": "PN-100", "quantity": 10,
                 "list_unit_cost_cents": 5000,
                 "negotiated_unit_cost_cents": 4000},
                {"part_number": "PN-200", "quantity": 4,
                 "list_unit_cost_cents": 1250},
            ]},
            TEST_HEADERS_FE,
        )
        submit_prototype(proto["id"], "eng-1")
        approved = validate_success(api_client.approve_prototype(
            proto["id"], make_program_manager_headers("pm-9")))
        assert approved["ve_round_count"] == 2
        assert approved["engineered_cost_cents"] == 45_000
        assert approved["provisional_cost_cents"] == 55_000
        assert approved["final_cost_cents"] == 45_000
        assert approved["status"] == "APPROVED"

    def test_resubmission_recomputes_engineered_and_refreshes_submitter(self):
        """PRD §3.2: "During the round the engineer patches negotiated prices
        into the BOM and then resubmits, moving `VALUE_ENGINEERING →
        ENGINEERING_REVIEW`; resubmission recomputes `engineered_cost_cents`
        from the current `bom_lines` and refreshes `submitted_by_user_id` with
        the resubmitting engineer's `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/prototype_value_engineering_cycle
        """
        program = create_active_program("P-VE2", 1_000_000, 100_000)
        proto = create_prototype(
            program["id"], bom_lines=self.BOM, target_cost_cents=50_000)
        submit_prototype(proto["id"], "eng-1")
        api_client.request_value_engineering(proto["id"], TEST_HEADERS_PM)
        api_client.patch_fixture_prototype(
            proto["id"],
            {"bom_lines": [
                {"part_number": "PN-100", "quantity": 10,
                 "list_unit_cost_cents": 5000,
                 "negotiated_unit_cost_cents": 4200},
                {"part_number": "PN-200", "quantity": 4,
                 "list_unit_cost_cents": 1250},
            ]},
            TEST_HEADERS_FE,
        )
        resubmitted = validate_success(api_client.submit_prototype_review(
            proto["id"], make_fixture_engineer_headers("eng-2")))
        assert resubmitted["status"] == "ENGINEERING_REVIEW"
        assert resubmitted["ve_round_count"] == 1
        assert resubmitted["engineered_cost_cents"] == 47_000
        assert resubmitted["provisional_cost_cents"] == 55_000
        assert resubmitted["submitted_by_user_id"] == "eng-2", \
            "resubmission must refresh submitted_by_user_id"
