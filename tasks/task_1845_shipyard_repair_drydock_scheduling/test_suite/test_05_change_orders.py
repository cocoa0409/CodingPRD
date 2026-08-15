"""Growth work: the change-order negotiation loop, approval cascades, credit
orders, budget discipline, segregation of duties, owner countersign, and OCC."""
from test_helpers import (
    COMM,
    COMM2,
    OWNER,
    PM,
    ApiErrorId,
    assert_contract_price_invariant,
    build_user_headers,
    create_change_order,
    create_change_order_payload,
    get_project,
    get_success_data,
    setup_contracted_project,
    setup_in_dock_project,
    validate_error,
    validate_paginated,
    validate_success,
)

# Base-spec line pricing to 99.8 x 500000 = 49900000 cents (tier-1 LD rate).
RIPPLE_ITEM = {
    "description": "Hull plate renewal", "trade_code": "HULL_STEEL",
    "duration_days": 14, "quantity": 99.8, "unit_price_cents": 500000,
}
GROWTH_SPEC = {
    "description": "Growth steel work", "trade_code": "HULL_STEEL",
    "pricing_mode": "LUMP_SUM", "duration_days": 2, "schedule_delta_days": 0,
    "quantity": 0.4, "unit_price_cents": 500000,
}


class TestNegotiationCycle:
    def test_reject_then_revise_reprices_and_reopens(self, api):
        """PRD §3.5: "the proposing `ProjectManager` may loop a `REJECTED`
        change order back to `UNDER_REVIEW` by revising any of `quantity`,
        `unit_price_cents`, `estimated_hours`, `hourly_rate_cents`,
        `materials_cost_cents`, `duration_days`, or `schedule_delta_days`. The
        revision reprices `proposed_cost_cents` under the same per-line rules —
        with the mode-conditional inputs again guarded by
        `ERR_PRICING_INPUT_INVALID` — recomputes `requires_owner_countersign`
        against the new price, and clears both `commercial_approved_by` and
        `owner_approved_by` so negotiation restarts from a clean sheet."

        Design: Difficulty/non_linear_state_machine/change_order_reject_revise_resubmit_cycle
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        assert co["proposed_cost_cents"] == 200000, (
            f"round_half_up(0.4 x 500000) = 200000, got {co['proposed_cost_cents']}"
        )

        rejected = validate_success(
            api.reject_change_order(co["id"], {"reason": "price too high"}, COMM)
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "price too high"

        revised = validate_success(
            api.revise_change_order(co["id"], {"quantity": 0.6}, PM)
        )
        assert revised["status"] == "UNDER_REVIEW"
        assert revised["proposed_cost_cents"] == 300000, (
            f"Repriced at 0.6 x 500000 = 300000, got "
            f"{revised['proposed_cost_cents']}"
        )
        assert revised["commercial_approved_by"] is None
        assert revised["owner_approved_by"] is None

    def test_reject_revise_approve_closes_cycle_and_reprices_contract(self, api):
        """PRD §3.5: "Second, the project's `contracted_price_cents` is
        recomputed as `awarded_price_cents` plus the sum of
        `proposed_cost_cents` over all of the project's `APPROVED` change
        orders — credit orders, whose proposed cost is negative, reduce the
        contract price — and the new contract price re-selects
        `ld_daily_rate_cents` from the tier table of §3.7."

        Design: Difficulty/non_linear_state_machine/change_order_reject_revise_resubmit_cycle
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        get_success_data(
            api.reject_change_order(co["id"], {"reason": "price too high"}, COMM)
        )
        get_success_data(api.revise_change_order(co["id"], {"quantity": 0.6}, PM))
        approved = validate_success(api.approve_change_order(co["id"], COMM))
        assert approved["status"] == "APPROVED"
        assert approved["approved_at_utc"] is not None

        project = get_project(ctx["project"]["id"])
        assert project["contracted_price_cents"] == 50200000, (
            f"49900000 + 300000 = 50200000, got "
            f"{project['contracted_price_cents']}"
        )


class TestApprovalCascade:
    def test_approval_materialises_growth_item_and_reprices_contract(self, api):
        """PRD §3.5: "First, the growth work materialises as a new work item
        built from the change order's own specification — its `description`,
        `trade_code`, pricing inputs, and `duration_days` — with an
        `origin_kind` of `CHANGE_ORDER`, the `origin_change_order_id` set to
        the change order's id, and status `PLANNED`."
        PRD §3.5: "Second, the project's `contracted_price_cents` is recomputed
        as `awarded_price_cents` plus the sum of `proposed_cost_cents` over all
        of the project's `APPROVED` change orders"

        Design: Difficulty/transitive_cascade/change_order_approval_price_ripple
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        pre = get_project(ctx["project"]["id"])
        assert pre["contracted_price_cents"] == 49900000
        assert pre["ld_daily_rate_cents"] == 200000
        assert pre["provisional_ld_cents"] == 400000, (
            f"Forecast 2026-08-15 vs contract 2026-08-10: 2 chargeable days x "
            f"200000 = 400000, got {pre['provisional_ld_cents']}"
        )

        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        approved = validate_success(api.approve_change_order(co["id"], COMM))
        assert approved["status"] == "APPROVED"

        growth_items, meta = validate_paginated(
            api.list_work_items(PM, params={"origin_change_order_id": co["id"]})
        )
        assert meta["total_count"] == 1
        growth = growth_items[0]
        assert growth["origin_kind"] == "CHANGE_ORDER"
        assert growth["origin_change_order_id"] == co["id"]
        assert growth["status"] == "PLANNED"
        assert growth["line_total_cents"] == 200000

        post = get_project(ctx["project"]["id"])
        assert post["contracted_price_cents"] == 50100000, (
            f"49900000 + 200000 = 50100000, got {post['contracted_price_cents']}"
        )

    def test_approval_reselects_tier_and_recomputes_provisional(self, api):
        """PRD §3.5: "and the new contract price re-selects
        `ld_daily_rate_cents` from the tier table of §3.7. Third, the change
        order's `schedule_delta_days` joins the approved-delta sum, so
        `forecast_delivery_utc` and `provisional_ld_cents` are recomputed."
        PRD §3.7: "A contracted price of at least 50000000 cents and at most
        200000000 cents ($2,000,000.00) selects 500000 cents per day
        ($5,000.00) — a contract priced at exactly 50000000 cents therefore
        falls in this middle tier."

        Design: Difficulty/transitive_cascade/change_order_approval_price_ripple
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        validate_success(api.approve_change_order(co["id"], COMM))

        post = get_project(ctx["project"]["id"])
        assert post["ld_daily_rate_cents"] == 500000, (
            f"50100000 crosses the 50000000 boundary into tier 2, got "
            f"{post['ld_daily_rate_cents']}"
        )
        assert post["provisional_ld_cents"] == 1000000, (
            f"2 chargeable days x 500000 = 1000000, got "
            f"{post['provisional_ld_cents']}"
        )


class TestCreditChangeOrder:
    def test_forward_change_order_raises_contract_price(self, api):
        """PRD §3.5: "Second, the project's `contracted_price_cents` is
        recomputed as `awarded_price_cents` plus the sum of
        `proposed_cost_cents` over all of the project's `APPROVED` change
        orders"

        Design: Difficulty/compensating_invariant/credit_change_order_restores_contract_price
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        validate_success(api.approve_change_order(co["id"], COMM))
        project = get_project(ctx["project"]["id"])
        assert project["contracted_price_cents"] == 50100000

    def test_credit_change_order_restores_contract_price(self, api):
        """PRD §3.5: "Unlike base-spec lines, a negative `unit_price_cents` is
        permitted here, producing a credit change order that reduces the
        contract price."
        PRD §3.5: "Second, the project's `contracted_price_cents` is recomputed
        as `awarded_price_cents` plus the sum of `proposed_cost_cents` over all
        of the project's `APPROVED` change orders — credit orders, whose
        proposed cost is negative, reduce the contract price"

        Design: Difficulty/compensating_invariant/credit_change_order_restores_contract_price
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        co1 = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        validate_success(api.approve_change_order(co1["id"], COMM))

        credit = create_change_order(
            ctx["project"]["id"],
            description="Credit: scope found sound on opening",
            trade_code="HULL_STEEL", pricing_mode="LUMP_SUM", duration_days=1,
            schedule_delta_days=0, quantity=0.4, unit_price_cents=-500000,
        )
        assert credit["proposed_cost_cents"] == -200000, (
            f"The credit is priced by the same formula, got "
            f"{credit['proposed_cost_cents']}"
        )
        validate_success(api.approve_change_order(credit["id"], COMM))

        project = get_project(ctx["project"]["id"])
        assert project["awarded_price_cents"] == 49900000
        assert project["contracted_price_cents"] == 49900000, (
            f"Zero drift: contracted == awarded + 200000 - 200000, got "
            f"{project['contracted_price_cents']}"
        )
        approved_cos, _ = validate_paginated(
            api.list_change_orders(PM, params={"project_id": ctx["project"]["id"]})
        )
        assert_contract_price_invariant(
            project, [c for c in approved_cos if c["status"] == "APPROVED"]
        )


class TestBudgetAndStatePriority:
    def test_approve_rejected_over_budget_change_order_returns_state_error(self, api):
        """PRD §2.9: "Every request is validated against an ordered ladder of
        rungs; a request failing any rung is rejected without evaluating later
        rungs, while checks sharing a rung carry no relative order among
        themselves." (State preconditions — including
        `ERR_CHANGE_ORDER_NOT_REVIEWABLE` — are rung 5; fiscal checks — the
        change budget `ERR_CHANGE_BUDGET_EXCEEDED` — are rung 11.)

        Design: Difficulty/priority_pair_validation_conflict/approve_rejected_over_budget_change_order_returns_state_error
        """
        ctx = setup_in_dock_project(
            item_specs=[RIPPLE_ITEM], change_budget_cents=100000
        )
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        get_success_data(
            api.reject_change_order(co["id"], {"reason": "not justified"}, COMM)
        )
        resp = api.approve_change_order(co["id"], COMM2)
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_NOT_REVIEWABLE)

    def test_approve_rejected_change_order_returns_state_error(self, api):
        """PRD §3.5: "Approve, reject, owner-countersign, and withdraw are
        defined only from `UNDER_REVIEW`, and revise only from `REJECTED`;
        invoking any of them from any other state is rejected with
        `ERR_CHANGE_ORDER_NOT_REVIEWABLE`."

        Design: Difficulty/priority_pair_validation_conflict/approve_rejected_over_budget_change_order_returns_state_error
        """
        ctx = setup_in_dock_project(item_specs=[RIPPLE_ITEM])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        get_success_data(
            api.reject_change_order(co["id"], {"reason": "not justified"}, COMM)
        )
        resp = api.approve_change_order(co["id"], COMM)
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_NOT_REVIEWABLE)

    def test_change_budget_exceeded_on_clean_approval(self, api):
        """PRD §3.5: "If the project carries a `change_budget_cents` ceiling,
        approval is refused with `ERR_CHANGE_BUDGET_EXCEEDED` whenever the sum
        of `proposed_cost_cents` across the project's already-`APPROVED` change
        orders plus this proposal would exceed the ceiling; a project without
        the ceiling admits change orders of any size."

        Design: Corner/validations/change_budget_exceeded_on_clean_approval
        """
        ctx = setup_in_dock_project(
            item_specs=[{}], change_budget_cents=100000
        )
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        resp = api.approve_change_order(co["id"], COMM2)
        validate_error(resp, ApiErrorId.ERR_CHANGE_BUDGET_EXCEEDED)


class TestChangeOrderLifecycleGuards:
    def test_change_order_before_docking_returns_not_in_dock(self, api):
        """PRD §3.5: "Growth work — defects discovered only once the vessel is
        opened up in dock — enters the system as a change order proposed by the
        `ProjectManager` while the project is `IN_DOCK`; proposals against a
        project in any other state are rejected with
        `ERR_PROJECT_NOT_IN_DOCK`."

        Design: Corner/errors/change_order_before_docking_returns_not_in_dock
        """
        ctx = setup_contracted_project()
        resp = api.create_change_order(
            create_change_order_payload(
                ctx["project"]["id"],
                get_project(ctx["project"]["id"])["version"],
                description="Premature growth line",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_IN_DOCK)

    def test_withdraw_under_review_change_order_then_reject_fails(self, api):
        """PRD §3.5: "Alternatively, the `ProjectManager` may withdraw an
        `UNDER_REVIEW` proposal outright, moving it to the terminal `WITHDRAWN`
        state. Approve, reject, owner-countersign, and withdraw are defined
        only from `UNDER_REVIEW`, and revise only from `REJECTED`; invoking any
        of them from any other state is rejected with
        `ERR_CHANGE_ORDER_NOT_REVIEWABLE`."

        Design: Corner/state_machines/withdraw_under_review_change_order_then_reject_fails
        """
        ctx = setup_in_dock_project(item_specs=[{}])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        withdrawn = validate_success(api.withdraw_change_order(co["id"], PM))
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.reject_change_order(co["id"], {"reason": "too late"}, COMM)
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_NOT_REVIEWABLE)


class TestChangeOrderOcc:
    def test_occ_stale_version_on_change_order_create(self, api):
        """PRD §2.8: "Two creation endpoints carry optimistic concurrency
        control on the parent repair project: proposing a change order and
        booking a dock reservation both require the client to supply
        `expected_project_version`, carrying the `version` of the repair
        project as last observed by the client."
        PRD §2.8: "the request is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and nothing is created. Both of these creations themselves increment
        the parent project's `version` by one, which is exactly what makes a
        second write against an unrefreshed copy fail: the client must re-read
        the project and resubmit with the current version."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_change_order_create
        """
        ctx = setup_in_dock_project(item_specs=[{}])
        project_id = ctx["project"]["id"]
        observed = get_project(project_id)["version"]

        first = validate_success(api.create_change_order(
            create_change_order_payload(project_id, observed, description="Growth A"),
            PM,
        ), 201)
        assert first["status"] == "UNDER_REVIEW"

        stale = api.create_change_order(
            create_change_order_payload(project_id, observed, description="Growth B"),
            PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        refreshed = get_project(project_id)["version"]
        assert refreshed == observed + 1, (
            f"Each successful creation bumps the project version by one "
            f"({observed} -> {refreshed})"
        )
        retried = validate_success(api.create_change_order(
            create_change_order_payload(project_id, refreshed, description="Growth B"),
            PM,
        ), 201)
        assert retried["status"] == "UNDER_REVIEW"


class TestSegregationOfDuties:
    def test_proposer_cannot_approve_own_change_order(self, api):
        """PRD §3.5: "Commercial approval is a `CommercialApprover` act guarded
        by segregation of duties: the approver's `X-User-ID` is compared
        against the change order's `proposed_by_user_id`, and a match is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/proposer_cannot_approve_own_change_order
        """
        ctx = setup_in_dock_project(item_specs=[{}])
        co = create_change_order(ctx["project"]["id"], **GROWTH_SPEC)
        assert co["proposed_by_user_id"] == "pm_1"

        resp = api.approve_change_order(
            co["id"], build_user_headers("pm_1", "CommercialApprover")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(api.approve_change_order(co["id"], COMM))
        assert approved["status"] == "APPROVED", (
            "The failed attempt left the order UNDER_REVIEW for an independent "
            "approver"
        )


class TestOwnerCountersign:
    def test_owner_countersign_two_phase_flow(self, api):
        """PRD §3.5: "computes `requires_owner_countersign`: true exactly when
        `proposed_cost_cents` is strictly greater than 5000000 cents (that is,
        $50,000.00) — a proposal priced exactly at that amount does not require
        the countersign."
        PRD §3.5: "When `requires_owner_countersign` is true and
        `owner_approved_by` is still null, the change order stays in
        `UNDER_REVIEW` and none of the cascade effects fire; when no
        countersign is required, or the countersign is already recorded, the
        approval becomes final."
        PRD §3.5: "The two approvals may arrive in either order — whichever
        lands last completes the transition to `APPROVED`."

        Design: Corner/rbac/owner_countersign_two_phase_flow
        """
        ctx = setup_in_dock_project(item_specs=[{
            "description": "Hull plate renewal", "trade_code": "HULL_STEEL",
            "duration_days": 14, "quantity": 100, "unit_price_cents": 600000,
        }])
        co = create_change_order(
            ctx["project"]["id"],
            description="Engine room piping growth", trade_code="PIPING",
            pricing_mode="TIME_AND_MATERIALS", duration_days=5,
            schedule_delta_days=2, estimated_hours=520, hourly_rate_cents=9600,
            materials_cost_cents=100000,
        )
        assert co["proposed_cost_cents"] == 5107000, (
            f"520 x 9600 + round_half_up(100000 x 1.15) = 4992000 + 115000 = "
            f"5107000, got {co['proposed_cost_cents']}"
        )
        assert co["requires_owner_countersign"] is True

        mid = validate_success(api.approve_change_order(co["id"], COMM))
        assert mid["status"] == "UNDER_REVIEW", (
            "Commercial approval alone does not fire the cascade while the "
            "countersign is outstanding"
        )
        assert mid["commercial_approved_by"] == "comm_1"
        project_mid = get_project(ctx["project"]["id"])
        assert project_mid["contracted_price_cents"] == 60000000

        final = validate_success(api.owner_approve_change_order(co["id"], OWNER))
        assert final["status"] == "APPROVED"
        assert final["owner_approved_by"] == "owner_9"
        project_end = get_project(ctx["project"]["id"])
        assert project_end["contracted_price_cents"] == 65107000, (
            f"60000000 + 5107000 = 65107000, got "
            f"{project_end['contracted_price_cents']}"
        )
