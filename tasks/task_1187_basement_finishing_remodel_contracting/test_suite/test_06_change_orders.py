"""Change-order pricing, supersede, terminal lockdown, and OCC tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_allowance_line_payload,
    create_change_order_fresh,
    get_only_allowance_line,
    get_project_version,
    get_success_data,
    make_contractor_headers,
    make_homeowner_headers,
    setup_intake_project,
    validate_error,
    validate_success,
)

POT_LIGHT = {"description": "pot light", "qty": 1, "unit_cost_cents": 101}
OUTLET = {"description": "outlet", "qty": 1, "unit_cost_cents": 103}


class TestPerItemMarkupRounding:
    def test_per_item_rounding_pinned_over_sum_first(self, api):
        """PRD §3.5: "The alternative order — summing quantities times unit costs
        first, then applying the markup and rounding once — is forbidden because it
        produces different cents: two one-unit items priced at 101 and 103 cents yield
        234 cents under the pinned per-line order but 235 under sum-first."

        Design: Difficulty/combinatorial_formula/change_order_per_item_markup_rounding
        """
        ctx = setup_intake_project(base_contract_cents=5000000, address="5 E St",
                                   basement_sqft=700)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        co = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="add pot lights + outlet",
            kind="ADD",
            scope_items=[POT_LIGHT, OUTLET],
            allowance_draws=[],
        )
        # round_half_up(101 * 1.15) = 116 and round_half_up(103 * 1.15) = 118.
        assert co["price_delta_cents"] == 234
        assert co["status"] == "PROPOSED"

    def test_change_order_creation_increments_project_version(self, api):
        """PRD §3.5: "Creation ripples outward. Each draw's amount is added to its
        line's `reserved_cents`, lowering `remaining_cents` by the same amount. Every
        existing `PROPOSED` change order on the same project moves to `SUPERSEDED`,
        and its draws are released back to their lines. The project's `version`
        increments."

        Design: Difficulty/combinatorial_formula/change_order_per_item_markup_rounding
        """
        ctx = setup_intake_project(base_contract_cents=5000000, address="5 E St",
                                   basement_sqft=700)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        v0 = ctx["project"]["version"]
        create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="add pot lights + outlet",
            kind="ADD",
            scope_items=[POT_LIGHT, OUTLET],
            allowance_draws=[],
        )
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["version"] == v0 + 1


class TestDebitCreditConservation:
    def _create_add_order(self, api, ctx):
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        return create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="add pot light + outlet",
            kind="ADD",
            scope_items=[POT_LIGHT, OUTLET],
            allowance_draws=[],
        )

    def test_approved_add_order_raises_price_by_delta(self, api):
        """PRD §3.5: "The `FINAL` price is `base_contract_cents` plus the summed
        `price_delta_cents` of all `APPROVED` change orders plus the summed
        `variance_cents` of all selected lines."
        PRD §3.5: "`price_variant` is `FINAL` when the project has no allowance lines
        at all or every line is selected, and `PROVISIONAL` otherwise."

        Design: Difficulty/compensating_invariant/contract_price_debit_credit_conservation
        """
        ctx = setup_intake_project(base_contract_cents=5000000, address="20 T St",
                                   basement_sqft=780)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        co1 = self._create_add_order(api, ctx)
        assert co1["price_delta_cents"] == 234
        validate_success(api.approve_change_order(co1["id"], ho_h), 200)
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["contract_price_cents"] == 5000234
        assert proj["price_variant"] == "FINAL"

    def test_approved_credit_order_nets_price_back_to_base(self, api):
        """PRD §3.5: "For an `ADD` order, `price_delta_cents` is the items total minus
        the draws total; for a `CREDIT` order it is the negated items total."
        PRD §3.5: "The `FINAL` price is `base_contract_cents` plus the summed
        `price_delta_cents` of all `APPROVED` change orders plus the summed
        `variance_cents` of all selected lines."

        Design: Difficulty/compensating_invariant/contract_price_debit_credit_conservation
        """
        ctx = setup_intake_project(base_contract_cents=5000000, address="20 T St",
                                   basement_sqft=780)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        co1 = self._create_add_order(api, ctx)
        validate_success(api.approve_change_order(co1["id"], ho_h), 200)

        co2 = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="remove pot light + outlet",
            kind="CREDIT",
            scope_items=[
                {"description": "pot light removal", "qty": 1,
                 "unit_cost_cents": 101},
                {"description": "outlet removal", "qty": 1,
                 "unit_cost_cents": 103},
            ],
            allowance_draws=[],
        )
        assert co2["price_delta_cents"] == -234
        validate_success(api.approve_change_order(co2["id"], ho_h), 200)
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["contract_price_cents"] == 5000000, (
            "forward ADD (+234) and compensating CREDIT (-234) net to the base"
        )
        assert proj["price_variant"] == "FINAL"


class TestSupersedeAndTerminal:
    def test_new_change_order_supersedes_proposed_and_releases_draws(self, api):
        """PRD §3.5: "Every existing `PROPOSED` change order on the same project moves
        to `SUPERSEDED`, and its draws are released back to their lines."

        Design: Corner/endpoints/change_order_supersede_releases_draws
        """
        ctx = setup_intake_project(address="E1 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        line = get_success_data(
            api.create_allowance_line(
                ctx["project"]["id"],
                create_allowance_line_payload(name="FIXTURES",
                                              budgeted_cents=100000),
                ctr_h,
            )
        )
        co1 = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="vanity", kind="ADD",
            scope_items=[{"description": "vanity", "qty": 20,
                          "unit_cost_cents": 1500}],
            allowance_draws=[{"allowance_line_id": line["id"],
                              "amount_cents": 30000}],
        )
        co2 = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="vanity plus mirror", kind="ADD",
            scope_items=[{"description": "mirror", "qty": 1,
                          "unit_cost_cents": 5000}],
            allowance_draws=[],
        )
        assert co2["status"] == "PROPOSED"
        orders = api.list_change_orders(ctx["project"]["id"], ctr_h).json()["data"]
        by_id = {o["id"]: o for o in orders}
        assert by_id[co1["id"]]["status"] == "SUPERSEDED"
        assert by_id[co2["id"]]["status"] == "PROPOSED"
        proposed = [o for o in orders if o["status"] == "PROPOSED"]
        assert len(proposed) == 1
        line_after = get_only_allowance_line(ctx["project"]["id"], ctr_h)
        assert line_after["reserved_cents"] == 0
        assert line_after["remaining_cents"] == 100000

    def test_approved_change_order_refuses_withdraw(self, api):
        """PRD §2.6: "Terminal guard: an entity in a terminal state — a `COMPLETED` or
        `CANCELLED` project, an `APPROVED` or `SUPERSEDED` package, a `CLOSED` or
        `EXPIRED` permit, a change order in any of its four end states, a `PASSED`,
        `FAILED`, or `CANCELLED` inspection, a decided claim — refuses every further
        mutation (`ERR_ALREADY_TERMINAL`)."

        Design: Corner/state_machines/change_order_approve_then_withdraw_terminal_lockdown
        """
        ctx = setup_intake_project(address="12 Corner Way")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        co = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="add shelf", kind="ADD",
            scope_items=[{"description": "shelf", "qty": 1,
                          "unit_cost_cents": 10000}],
            allowance_draws=[],
        )
        assert co["price_delta_cents"] == 11500
        validate_success(api.approve_change_order(co["id"], ho_h), 200)

        res = api.withdraw_change_order(co["id"], ctr_h)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        orders = api.list_change_orders(ctx["project"]["id"], ctr_h).json()["data"]
        assert orders[0]["status"] == "APPROVED"
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["contract_price_cents"] == 4000000 + 11500, (
            "the approved order's price impact is not rolled back"
        )


class TestOptimisticConcurrency:
    def test_stale_version_rejected_then_fresh_accepted(self, api):
        """PRD §2.8: "If that value does not equal the project's current `version` —
        for example because another writer has since created a change order on the
        project, an act that legitimately supersedes every `PROPOSED` change order
        and leaves the current writer's view of the project stale — the creation is
        rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), preventing the client
        from building on a project state it has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_then_fresh_accepted
        """
        ctx = setup_intake_project(address="X1 St")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        v0 = ctx["project"]["version"]
        co1 = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="first", kind="ADD",
            scope_items=[{"description": "a", "qty": 1, "unit_cost_cents": 1000}],
            allowance_draws=[],
        )
        assert co1["status"] == "PROPOSED"

        stale_res = api.create_change_order(
            ctx["project"]["id"],
            {
                "scope_description": "second-stale",
                "kind": "ADD",
                "scope_items": [{"description": "b", "qty": 1,
                                 "unit_cost_cents": 2000}],
                "allowance_draws": [],
                "expected_project_version": v0,
            },
            ctr_h,
        )
        validate_error(stale_res, ApiErrorId.ERR_STALE_PROJECT_VERSION)

        v_fresh = get_project_version(ctx["project"]["id"], ctr_h)
        assert v_fresh == v0 + 1, "one successful create advances the version by 1"
        co2 = validate_success(
            api.create_change_order(
                ctx["project"]["id"],
                {
                    "scope_description": "second-fresh",
                    "kind": "ADD",
                    "scope_items": [{"description": "b", "qty": 1,
                                     "unit_cost_cents": 2000}],
                    "allowance_draws": [],
                    "expected_project_version": v_fresh,
                },
                ctr_h,
            ),
            201,
        )
        assert co2["status"] == "PROPOSED"
        orders = api.list_change_orders(ctx["project"]["id"], ctr_h).json()["data"]
        by_id = {o["id"]: o for o in orders}
        assert by_id[co1["id"]]["status"] == "SUPERSEDED"
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["version"] == v_fresh + 1
