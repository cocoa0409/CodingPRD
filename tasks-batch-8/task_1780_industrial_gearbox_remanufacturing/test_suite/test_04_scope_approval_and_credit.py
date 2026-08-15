"""The SCOPE_APPROVAL revision loop, validation priority pairs, the customer
credit gate, and ownership checks on approval."""
from test_helpers import (
    ApiErrorId,
    add_decision,
    approve_scope,
    assert_credit_invariants,
    get_customer,
    get_order,
    make_customer,
    make_customer_headers,
    setup_order_in_scope_approval,
    setup_order_in_teardown,
    setup_unit_with_order,
    start_teardown,
    submit_scope,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRevisionLoop:
    def test_revision_loop_supersedes_and_recomputes(
            self, api, reman_engineer_headers):
        """PRD §3.3: "The revision cycle is a self-loop within
        `SCOPE_APPROVAL`: the engineer posts replacement decisions (each
        superseding its component's prior pending decision, per §3.2) and
        then re-presents the amended scope."
        PRD §3.2: "posting a new decision for a `component_code` that already
        has a `PENDING` decision on the same order flips the older one to
        `SUPERSEDED`, so at any moment each component has at most one pending
        decision."

        Design: Difficulty/non_linear_state_machine/reman_order_scope_approval_revision_loop
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-L1")
        order_id = ctx["order"]["id"]
        old_decision = ctx["decisions"][0]
        # Scope after submission: REGRIND 4.0h * 8500 + 12000 = 46000.
        assert ctx["order"]["approved_scope_cents"] == 46_000
        observed_version = get_order(order_id)["version"]

        new_decision = add_decision(order_id, component_code="PINION_1",
                                    action="REGRIND", labor_hours=2.665,
                                    material_cents=0)
        data = validate_success(
            api.revise_scope(order_id, observed_version,
                             reman_engineer_headers))
        assert data["status"] == "SCOPE_APPROVAL"  # looped into the same state
        # round_half_up(2.665 * 8500) = 22653.
        assert data["approved_scope_cents"] == 22_653

        decisions, _ = validate_paginated(
            api.list_decisions(order_id, reman_engineer_headers))
        by_id = {d["id"]: d for d in decisions}
        assert by_id[old_decision["id"]]["approval_status"] == "SUPERSEDED"
        assert by_id[new_decision["id"]]["approval_status"] == "PENDING"

    def test_revision_loop_increments_version_each_pass(
            self, api, reman_engineer_headers):
        """PRD §3.3: "The revision re-validates that every finding still has
        a `PENDING` decision (`ERR_DECISIONS_INCOMPLETE`), recomputes
        `approved_scope_cents` from the current pending set, and increments
        the order's `version` by one; the loop may repeat without bound, each
        pass advancing the version again."

        Design: Difficulty/non_linear_state_machine/reman_order_scope_approval_revision_loop
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-L2")
        order_id = ctx["order"]["id"]
        v0 = get_order(order_id)["version"]

        # First pass: REGRIND 2.665h/0 → 22653.
        add_decision(order_id, component_code="PINION_1", action="REGRIND",
                     labor_hours=2.665, material_cents=0)
        first = validate_success(
            api.revise_scope(order_id, v0, reman_engineer_headers))
        assert first["version"] == v0 + 1
        assert first["approved_scope_cents"] == 22_653

        # Second pass: REUSE_AS_IS 1.0h/0 → 2500.
        add_decision(order_id, component_code="PINION_1", action="REUSE_AS_IS",
                     labor_hours=1.0, material_cents=0)
        second = validate_success(
            api.revise_scope(order_id, v0 + 1, reman_engineer_headers))
        assert second["version"] == v0 + 2
        assert second["approved_scope_cents"] == 2_500
        assert second["status"] == "SCOPE_APPROVAL"


class TestStateVsFiscalPriority:
    def test_approve_scope_in_teardown_reports_state_not_fiscal(self, api):
        """PRD §2.11: "a request that would fail several checks surfaces the
        earliest one, so higher-priority rejections mask lower-priority ones"
        with "4. **State legality** — all action endpoints: the target
        resource must be in a state from which the requested transition
        exists, including terminal-state lockdown, else `ERR_INVALID_STATE`."
        ahead of "9. **Fiscal gates** — scope approval: the customer's credit
        headroom must cover the approved scope, else
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_approve_scope
        """
        ctx = setup_unit_with_order(serial_number="GBX-V1",
                                    quoted_estimate_cents=600_000,
                                    credit_limit_cents=1_000,
                                    legal_name="Broke Co")
        start_teardown(ctx["order"]["id"])

        resp = api.approve_scope(
            ctx["order"]["id"],
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_order(ctx["order"]["id"])["status"] == "TEARDOWN"

    def test_approve_scope_in_intake_reports_state_not_fiscal(self, api):
        """PRD §2.6: "Every action in this API exists only from specific
        states of its target resource; invoking an action from any other
        state is rejected with `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.11: "4. **State legality** ... else `ERR_INVALID_STATE`."
        precedes "9. **Fiscal gates** ... else `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_approve_scope
        """
        ctx = setup_unit_with_order(serial_number="GBX-V3",
                                    quoted_estimate_cents=600_000,
                                    credit_limit_cents=1_000,
                                    legal_name="Broke Two Co")
        resp = api.approve_scope(
            ctx["order"]["id"],
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_order(ctx["order"]["id"])["status"] == "INTAKE"


class TestStateVsReferentialPriority:
    def test_submit_scope_in_intake_reports_state_not_referential(
            self, api, reman_engineer_headers):
        """PRD §2.11: "4. **State legality** — all action endpoints: the
        target resource must be in a state from which the requested
        transition exists, including terminal-state lockdown, else
        `ERR_INVALID_STATE`." precedes "6. **Referential completeness** —
        scope submission, scope revision, assembly submission, and warranty
        review: findings must exist (`ERR_NO_FINDINGS`) ...".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_submit_scope
        """
        ctx = setup_unit_with_order(serial_number="GBX-V2",
                                    quoted_estimate_cents=600_000,
                                    legal_name="Prio Co")
        # INTAKE, zero findings: both the state and referential preconditions
        # of submit-scope are violated; state (priority 4) wins.
        resp = api.submit_scope(ctx["order"]["id"], reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_order(ctx["order"]["id"])["status"] == "INTAKE"

    def test_submit_scope_in_scope_approval_reports_state_despite_complete_scope(
            self, api, reman_engineer_headers):
        """PRD §2.6: "Every action in this API exists only from specific
        states of its target resource; invoking an action from any other
        state is rejected with `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.11: "a request that would fail several checks surfaces the
        earliest one, so higher-priority rejections mask lower-priority
        ones".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_submit_scope
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-V4")
        # Scope is referentially complete (finding + PENDING decision), but
        # submit-scope exists only from TEARDOWN.
        resp = api.submit_scope(ctx["order"]["id"], reman_engineer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_order(ctx["order"]["id"])["status"] == "SCOPE_APPROVAL"


class TestCreditGate:
    def test_credit_limit_exact_boundary(self, api):
        """PRD §2.10: "The customer's `credit_hold` flag is set to true
        whenever `outstanding_approved_cents` is strictly greater than
        `credit_limit_cents` — landing exactly on the limit is not a hold".
        PRD §3.3: "the credit gate of §2.10 is enforced at this moment:
        `credit_hold` must currently be false and the projected exposure —
        current `outstanding_approved_cents` plus this order's
        `approved_scope_cents` — must be at or below `credit_limit_cents`,
        landing exactly on the limit being acceptable
        (`ERR_CREDIT_LIMIT_EXCEEDED`)."

        Design: Corner/calculations/credit_hold_at_exactly_limit_is_not_a_hold
        """
        # Scope is REGRIND 2.0h * 8500 + 5000 = 22000 on both orders.
        ok_ctx = setup_order_in_teardown(
            serial_number="GBX-EX", legal_name="Exact Co",
            credit_limit_cents=22_000, quoted_estimate_cents=10_000,
            components=[("PINION_1", "REGRINDABLE", 2, "REGRIND", 2.0,
                         5_000)])
        submit_scope(ok_ctx["order"]["id"])

        bad_ctx = setup_order_in_teardown(
            serial_number="GBX-SH", legal_name="Short Co",
            credit_limit_cents=21_999, quoted_estimate_cents=10_000,
            components=[("PINION_1", "REGRINDABLE", 2, "REGRIND", 2.0,
                         5_000)])
        submit_scope(bad_ctx["order"]["id"])

        # Projected 22000 <= limit 22000: approval succeeds, no hold.
        data = validate_success(api.approve_scope(
            ok_ctx["order"]["id"],
            make_customer_headers(ok_ctx["customer"]["id"])))
        assert data["status"] == "APPROVED"
        customer = get_customer(ok_ctx["customer"]["id"])
        assert customer["outstanding_approved_cents"] == 22_000
        assert customer["credit_hold"] is False
        assert_credit_invariants(customer)

        # Projected 22000 > limit 21999: rejected, order unchanged.
        resp = api.approve_scope(
            bad_ctx["order"]["id"],
            make_customer_headers(bad_ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
        assert get_order(bad_ctx["order"]["id"])["status"] == "SCOPE_APPROVAL"

    def test_outstanding_reflects_approval_immediately(
            self, api, service_manager_headers):
        """PRD §2.10: "Each customer carries a running exposure figure,
        `outstanding_approved_cents`: the sum of `approved_scope_cents` over
        that customer's orders whose `status` is one of `APPROVED`,
        `IN_BUILD`, `ASSEMBLY`, `RUN_IN`, `READY_TO_SHIP`, or `SHIPPED`."
        PRD §3.3: "Approval moves the order `SCOPE_APPROVAL → APPROVED`,
        flips all pending decisions to `APPROVED`, and adds the scope to the
        customer's outstanding exposure with `credit_hold` recomputed."

        Design: Corner/cross_cutting_layers/derived_field_customer_outstanding_reconciles_on_cancel
        """
        ctx = setup_order_in_teardown(
            serial_number="GBX-DV", legal_name="Derived Co",
            quoted_estimate_cents=10_000,
            components=[("PINION_1", "REGRINDABLE", 2, "REGRIND", 2.0,
                         5_000)])
        submit_scope(ctx["order"]["id"])
        approve_scope(ctx["order"]["id"], ctx["customer"]["id"])

        customer = get_customer(ctx["customer"]["id"])
        assert customer["outstanding_approved_cents"] == 22_000
        assert customer["credit_hold"] is False
        assert get_order(ctx["order"]["id"])["status"] == "APPROVED"


class TestApprovalOwnership:
    def test_customer_cannot_approve_other_customers_scope(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the
        `id` of the acting `Customer` entity. Ownership checks on any
        resource reachable from that customer — an order, the gear unit it
        belongs to, or a claim filed under the order — compare the resource's
        owning chain (the order's gear unit, and that unit's `customer_id`)
        to `X-User-ID`."
        PRD §3.3: "The caller must be the customer who owns the gear unit
        (`ERR_FORBIDDEN` otherwise)".

        Design: Corner/roles/customer_cannot_approve_other_customers_scope
        """
        ctx = setup_order_in_scope_approval(serial_number="GBX-OWN",
                                            legal_name="Owner A")
        intruder = make_customer(legal_name="Intruder B")

        resp = api.approve_scope(ctx["order"]["id"],
                                 make_customer_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert get_order(ctx["order"]["id"])["status"] == "SCOPE_APPROVAL"
