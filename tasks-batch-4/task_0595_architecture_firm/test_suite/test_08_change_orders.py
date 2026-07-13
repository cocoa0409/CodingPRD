"""Change orders: the client fork, the four-hop execution cascade, its guards and its mirror."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_change_order, assert_contract, assert_phase_allocation_sums_to_total,
    assert_contract_wip_identity,
    state_payload, create_change_order_payload,
    setup_executed_project,
    activate_and_complete_phase, create_change_order, create_submitted_change_order,
    create_client_approved_change_order, create_executed_change_order,
    get_contract_version, read_contract, read_phase, read_all_phases,
    PRINCIPAL, PRINCIPAL_B,
)


class TestClientDecisionFork:

    def test_client_rejection_is_terminal_and_leaves_the_contract_fee_untouched(self, api):
        """PRD §3.8: "Driving it instead to `CLIENT_REJECTED` is terminal and equally inert: the
        contract's `total_fee_cents`, every phase's `fee_allocation_cents`, and the contract's
        `version` are all left exactly as they were, and no fee cascade will ever fire for that
        order."

        Design: Difficulty/non_linear_state_machine/change_order_fork_reject_branch_leaves_contract_fee_untouched
        """
        bundle = setup_executed_project(project_number="FRK-001", name="Fork Field",
                                        with_architect=False)
        order = create_submitted_change_order(
            bundle, title="Extra rendering package",
            co_type="ADDITIONAL_SERVICE", fee_delta_cents=2_000_000,
        )
        before = read_contract(bundle)

        rejected = validate_success(
            api.set_change_order_state(
                order["id"], state_payload("CLIENT_REJECTED"), bundle["client_headers"]
            )
        )
        assert_change_order(rejected)
        assert rejected["status"] == "CLIENT_REJECTED"

        after = read_contract(bundle)
        assert_contract(after)
        assert after["total_fee_cents"] == 10_000_000
        assert after["base_fee_cents"] == 10_000_000
        assert after["earned_to_date_cents"] == 0
        assert after["version"] == before["version"], (
            "the rejected branch must not bump Contract.version"
        )

    def test_client_approval_alone_moves_no_fee(self, api):
        """PRD §3.8: "Driving the order to `CLIENT_APPROVED` records nothing but the new status: no
        fee moves, `total_fee_cents` is untouched, and the contract's `version` does not change."
        PRD §3.8: "**Execution** is reserved for a `PrincipalArchitect` and is the only operation
        that actually moves the contract's fee."

        Design: Difficulty/non_linear_state_machine/change_order_fork_reject_branch_leaves_contract_fee_untouched
        """
        bundle = setup_executed_project(project_number="FRK-002", name="Fork Farm",
                                        with_architect=False)
        before = read_contract(bundle)

        approved = create_client_approved_change_order(
            bundle, title="Extra rendering package",
            co_type="ADDITIONAL_SERVICE", fee_delta_cents=2_000_000,
        )
        assert_change_order(approved)
        assert approved["status"] == "CLIENT_APPROVED"

        after = read_contract(bundle)
        assert after["total_fee_cents"] == 10_000_000, "approval unlocks execution; it books nothing"
        assert after["version"] == before["version"]
        assert read_phase(bundle, "SD")["fee_allocation_cents"] == 2_000_000


class TestExecutionCascade:

    def test_execution_rewrites_the_total_fee_and_reallocates_every_phase(self, api):
        """PRD §3.8: "On success the order becomes `EXECUTED`, `executed_by_user_id` records the
        actor and `executed_at` is stamped from the logical clock, and the fee cascade runs in four
        hops: the contract's `total_fee_cents` is recomputed as `base_fee_cents` plus the sum of
        `fee_delta_cents` over all of that contract's `EXECUTED` change orders (which, for this one
        order, means it moves by exactly this order's delta); every phase's `fee_allocation_cents` is
        re-allocated from the new total by the pinned procedure of §3.3; every phase's `earned_cents`
        is recomputed from its new allocation and its existing `percent_complete`; and the contract's
        `earned_to_date_cents` and `wip_balance_cents` are recomputed."

        Design: Difficulty/transitive_cascade/change_order_execute_cascades_contract_fee_to_phase_allocation_to_earned_to_wip
        """
        bundle = setup_executed_project(project_number="CAS-001", name="Cascade Campus",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        order = create_client_approved_change_order(
            bundle, title="Additional lobby study",
            co_type="ADDITIONAL_SERVICE", fee_delta_cents=2_000_000,
        )
        version = get_contract_version(bundle)

        executed = validate_success(
            api.execute_change_order(
                order["id"], {"expected_contract_version": version}, PRINCIPAL_B
            )
        )
        assert_change_order(executed)
        assert executed["status"] == "EXECUTED"

        contract = read_contract(bundle)
        assert contract["total_fee_cents"] == 12_000_000  # 10_000_000 + 2_000_000

        phases = read_all_phases(bundle)
        allocations = {p["phase_code"]: p["fee_allocation_cents"] for p in phases}
        assert allocations["SD"] == 2_400_000
        assert allocations["DD"] == 2_400_000
        assert allocations["CD"] == 4_800_000
        assert allocations["CA"] == 2_400_000
        assert_phase_allocation_sums_to_total(phases, contract["total_fee_cents"])

    def test_the_reallocation_propagates_into_earned_value_and_the_wip_balance(self, api):
        """PRD §2.9: "When a change order is executed, the contract's `total_fee_cents` moves;
        because it moved, every phase's `fee_allocation_cents` is re-allocated; because those moved,
        every phase's `earned_cents` is recomputed; because those moved, the contract's
        `earned_to_date_cents` is recomputed and `wip_balance_cents` follows."
        PRD §3.3: "All four phases are re-allocated every time, regardless of status — a `COMPLETED`
        phase is re-allocated too, and its earned value recomputed at a percent complete of 100."

        Design: Difficulty/transitive_cascade/change_order_execute_cascades_contract_fee_to_phase_allocation_to_earned_to_wip
        """
        bundle = setup_executed_project(project_number="CAS-002", name="Cascade Court",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")

        before = read_contract(bundle)
        assert before["earned_to_date_cents"] == 2_000_000
        assert before["wip_balance_cents"] == 2_000_000

        create_executed_change_order(
            bundle, title="Additional lobby study",
            co_type="ADDITIONAL_SERVICE", fee_delta_cents=2_000_000,
        )

        sd = read_phase(bundle, "SD")
        assert sd["status"] == "COMPLETED"
        assert sd["percent_complete"] == 100
        assert sd["fee_allocation_cents"] == 2_400_000
        assert sd["earned_cents"] == 2_400_000, (
            "the COMPLETED phase's earned value follows its re-allocated fee"
        )

        contract = read_contract(bundle)
        assert contract["earned_to_date_cents"] == 2_400_000
        assert contract["wip_balance_cents"] == 2_400_000
        assert_contract_wip_identity(contract)


class TestChangeOrderGuards:

    def test_fee_delta_sign_must_agree_with_the_change_order_type(self, api):
        """PRD §3.8: "The sign of the delta must agree with the type: `fee_delta_cents` must be
        strictly greater than zero for an `ADDITIONAL_SERVICE` and strictly less than zero for a
        `SCOPE_REDUCTION`. A mismatch — including a delta of exactly zero, which satisfies neither —
        is rejected with `ERR_FEE_DELTA_SIGN`."
        PRD §3.8: "Change orders begin in `DRAFT` with `submitted_by_user_id`,
        `executed_by_user_id` and `executed_at` all null, and have no fee effect whatsoever."

        Design: Corner/validations/change_order_fee_delta_sign_must_match_type
        """
        bundle = setup_executed_project(
            project_number="SGN-001", name="Sign Studio",
            weights=(2500, 2500, 2500, 2500), with_architect=False, labor_budget_cents=500_000,
        )

        response = api.create_change_order(
            create_change_order_payload(
                bundle["contract_id"], title="Backwards add",
                co_type="ADDITIONAL_SERVICE", fee_delta_cents=-500_000,
            ),
            bundle["pm_headers"],
        )
        validate_error(response, ApiErrorId.ERR_FEE_DELTA_SIGN.value)

        accepted = validate_success(
            api.create_change_order(
                create_change_order_payload(
                    bundle["contract_id"], title="Drop the canopy",
                    co_type="SCOPE_REDUCTION", fee_delta_cents=-500_000,
                ),
                bundle["pm_headers"],
            ),
            201,
        )
        assert_change_order(accepted)
        assert accepted["status"] == "DRAFT"

        rows, _ = validate_paginated(
            api.list_contract_change_orders(bundle["contract_id"], bundle["pm_headers"])
        )
        assert len(rows) == 1, "the sign-violating order must not have been persisted"

    def test_the_submitter_of_a_change_order_may_not_execute_it(self, api):
        """PRD §2.1: "Executing a change order whose `submitted_by_user_id` equals the executor's
        `X-User-ID` is forbidden."
        PRD §3.8: "and it requires the executor's `X-User-ID` to differ from the order's
        `submitted_by_user_id` — the principal who drafted and submitted an additional service may
        not also be the one who books it."

        Design: Corner/rbac/change_order_submitter_cannot_execute_it
        """
        bundle = setup_executed_project(
            project_number="SOD-002", name="Executor Elsewhere",
            weights=(2500, 2500, 2500, 2500), with_architect=False, labor_budget_cents=500_000,
        )
        order = create_client_approved_change_order(
            bundle, headers=PRINCIPAL,  # submitted by principal-alice
            title="Additional site survey", co_type="ADDITIONAL_SERVICE",
            fee_delta_cents=1_000_000,
        )
        assert order["submitted_by_user_id"] == "principal-alice"

        version = get_contract_version(bundle)
        response = api.execute_change_order(
            order["id"], {"expected_contract_version": version}, PRINCIPAL
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        rows, _ = validate_paginated(
            api.list_contract_change_orders(bundle["contract_id"], bundle["pm_headers"])
        )
        assert rows[0]["status"] == "CLIENT_APPROVED"

        fresh_version = get_contract_version(bundle)
        executed = validate_success(
            api.execute_change_order(
                order["id"], {"expected_contract_version": fresh_version}, PRINCIPAL_B
            )
        )
        assert executed["status"] == "EXECUTED"
        assert executed["executed_by_user_id"] == "principal-bob"
        assert read_contract(bundle)["total_fee_cents"] == 11_000_000

    def test_a_client_rep_from_another_project_cannot_decide_the_change_order(self, api):
        """PRD §2.1: "A `ClientRep` rendering a decision on a change order whose project carries a
        different `client_rep_user_id` is rejected with `ERR_NOT_OWNER`."
        PRD §3.8: "The client then decides, and only the `ClientRep` whose `X-User-ID` matches the
        project's `client_rep_user_id` may do so."

        Design: Corner/rbac/wrong_client_rep_cannot_decide_a_change_order
        """
        from test_helpers import make_client_rep_headers

        bundle = setup_executed_project(
            project_number="CLI-001", name="Client Scope",
            weights=(2500, 2500, 2500, 2500), with_architect=False, labor_budget_cents=500_000,
        )
        order = create_submitted_change_order(
            bundle, title="Extra survey", co_type="ADDITIONAL_SERVICE",
            fee_delta_cents=1_000_000,
        )

        response = api.set_change_order_state(
            order["id"], state_payload("CLIENT_APPROVED"), make_client_rep_headers("client-9")
        )
        validate_error(response, ApiErrorId.ERR_NOT_OWNER.value)

        rows, _ = validate_paginated(
            api.list_contract_change_orders(bundle["contract_id"], bundle["pm_headers"])
        )
        assert rows[0]["status"] == "SUBMITTED"

        approved = validate_success(
            api.set_change_order_state(
                order["id"], state_payload("CLIENT_APPROVED"), make_client_rep_headers("client-1")
            )
        )
        assert approved["status"] == "CLIENT_APPROVED"
        assert read_contract(bundle)["total_fee_cents"] == 10_000_000

    def test_execution_with_a_stale_contract_version_is_rejected(self, api):
        """PRD §2.5: "Executing a client-approved change order likewise requires a non-optional
        `expected_contract_version` field carrying the client's last observed contract `version`."
        PRD §2.5: "Again, a mismatch against the contract's current `version` is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/change_order_execute_with_stale_contract_version_returns_412
        """
        bundle = setup_executed_project(
            project_number="OCC-002", name="OCC Orchard",
            weights=(2500, 2500, 2500, 2500), with_architect=False, labor_budget_cents=500_000,
        )
        order_a = create_client_approved_change_order(
            bundle, title="CO A", co_type="ADDITIONAL_SERVICE", fee_delta_cents=1_000_000
        )
        order_b = create_client_approved_change_order(
            bundle, title="CO B", co_type="ADDITIONAL_SERVICE", fee_delta_cents=1_000_000
        )
        observed_version = get_contract_version(bundle)

        validate_success(
            api.execute_change_order(
                order_a["id"], {"expected_contract_version": observed_version}, PRINCIPAL_B
            )
        )
        assert read_contract(bundle)["total_fee_cents"] == 11_000_000

        # Executing CO A bumped Contract.version, so the version we still hold is stale.
        response = api.execute_change_order(
            order_b["id"], {"expected_contract_version": observed_version}, PRINCIPAL_B
        )
        validate_error(response, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value)

        rows, _ = validate_paginated(
            api.list_contract_change_orders(bundle["contract_id"], bundle["pm_headers"])
        )
        blocked = next(row for row in rows if row["id"] == order_b["id"])
        assert blocked["status"] == "CLIENT_APPROVED"
        assert read_contract(bundle)["total_fee_cents"] == 11_000_000


class TestChangeOrderVoid:

    def test_voiding_an_executed_change_order_replays_the_cascade_backwards(self, api):
        """PRD §3.8: "The void runs the compensating cascade: the order's delta drops out of
        `total_fee_cents`, phase allocations and earned values are recomputed, and the contract's
        earned and WIP figures follow, with `Contract.version` incrementing again."
        PRD §2.9: "the contract's `total_fee_cents` always equals its `base_fee_cents` plus the sum
        of `fee_delta_cents` over that contract's change orders in status `EXECUTED`, and the four
        phases' `fee_allocation_cents` always sum to exactly `total_fee_cents`, with no cent lost to
        rounding."

        Design: Corner/cross_cutting_complexity_layers/change_order_void_compensates_the_fee_cascade_end_to_end
        """
        bundle = setup_executed_project(project_number="VOI-001", name="Void Village",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        order = create_executed_change_order(
            bundle, title="Lobby study", co_type="ADDITIONAL_SERVICE",
            fee_delta_cents=2_000_000,
        )

        assert read_contract(bundle)["total_fee_cents"] == 12_000_000
        assert read_phase(bundle, "SD")["fee_allocation_cents"] == 2_400_000

        voided = validate_success(
            api.set_change_order_state(order["id"], state_payload("VOID"), PRINCIPAL)
        )
        assert voided["status"] == "VOID"

        contract = read_contract(bundle)
        assert contract["total_fee_cents"] == 10_000_000

        sd = read_phase(bundle, "SD")
        assert sd["fee_allocation_cents"] == 2_000_000
        assert sd["earned_cents"] == 2_000_000
        assert read_phase(bundle, "CA")["fee_allocation_cents"] == 2_000_000

        assert contract["earned_to_date_cents"] == 2_000_000
        assert contract["wip_balance_cents"] == 2_000_000
        assert_phase_allocation_sums_to_total(read_all_phases(bundle), contract["total_fee_cents"])
