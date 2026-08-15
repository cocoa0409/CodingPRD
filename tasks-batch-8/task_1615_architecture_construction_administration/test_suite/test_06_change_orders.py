"""Change orders: tiered markup pricing, recommendation/decision chain, OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_change_order,
    recommend_change_order,
    decide_change_order,
    create_owner_accepted_change_order,
    set_clock,
    create_draft_invoice,
    make_firm_admin_headers,
    make_architect_headers,
    make_owner_headers,
)

SOV_AB = [
    {"line_code": "A", "description": "Concrete", "scheduled_value_cents": 6000000},
    {"line_code": "B", "description": "Metals", "scheduled_value_cents": 4000000},
]
SOV_A_ONLY = [{"line_code": "A", "description": "Concrete",
               "scheduled_value_cents": 10000000}]


class TestTieredMarkup:
    def test_three_tier_markup_allocation(self, api):
        """PRD 3.6: "The overhead-and-profit `markup_cents` is tiered against the
        net cost change: ten percent of the first 5,000,000 cents of net change,
        plus seven percent of the next 5,000,000 cents (the portion between
        5,000,000 and 10,000,000), plus four percent of any remainder above
        10,000,000 cents. Each tier's product is rounded half up to the cent
        before the tiers are summed."

        Design: Difficulty/combinatorial_formula/change_order_tiered_markup_mode_a
        """
        project = create_active_project(sov_lines=SOV_AB, grace_days=5)
        change_order = create_change_order(
            project["id"], title="Added steel canopy",
            net_cost_change_cents=12000000, time_extension_days=0,
        )
        # 0.10x5000000 + 0.07x5000000 + 0.04x2000000 = 500000+350000+80000
        assert change_order["markup_cents"] == 930000
        assert change_order["total_amount_cents"] == 12930000

    def test_deduct_and_zero_cost_changes_earn_no_markup(self, api):
        """PRD 3.6: "Deduct and zero-cost changes earn no markup — their
        `markup_cents` is zero. The change order's `total_amount_cents` is the
        net cost change plus the markup."

        Design: Difficulty/combinatorial_formula/change_order_tiered_markup_mode_a
        """
        project = create_active_project(sov_lines=SOV_AB, grace_days=5)
        deduct = create_change_order(
            project["id"], title="Deleted storefront",
            net_cost_change_cents=-4000000, time_extension_days=0,
        )
        assert deduct["markup_cents"] == 0
        assert deduct["total_amount_cents"] == -4000000
        time_only = create_change_order(
            project["id"], title="Weather time extension",
            net_cost_change_cents=0, time_extension_days=20,
        )
        assert time_only["markup_cents"] == 0
        assert time_only["total_amount_cents"] == 0


class TestMarkupTierBoundaryExactCap:
    def test_change_order_markup_tier_boundary_exact_cap(self, api):
        """PRD 3.6: "The overhead-and-profit `markup_cents` is tiered against the
        net cost change: ten percent of the first 5,000,000 cents of net change,
        plus seven percent of the next 5,000,000 cents (the portion between
        5,000,000 and 10,000,000), plus four percent of any remainder above
        10,000,000 cents."

        Design: Corner/calculations/change_order_markup_tier_boundary_exact_cap
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        change_order = create_change_order(
            project["id"], title="Exact-cap extra",
            net_cost_change_cents=5000000, time_extension_days=0,
        )
        # tier 1 fully consumed; tier 2 contributes exactly 0
        assert change_order["markup_cents"] == 500000
        assert change_order["total_amount_cents"] == 5500000


class TestOwnerOverridesRecommendation:
    def test_owner_accepts_reject_recommended_change_order(self, api):
        """PRD 3.6: "The `Owner` then renders the decision with `decision` —
        `ACCEPT` or `REJECT` — against a change order in either recommended state:
        `ACCEPT` moves it to `OWNER_ACCEPTED` and `REJECT` moves it to
        `OWNER_REJECTED`, and the owner may override the CA recommendation in
        either direction."

        Design: Corner/state_machines/owner_accepts_reject_recommended_change_order
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        change_order = create_change_order(
            project["id"], title="Owner-requested upgrade",
            net_cost_change_cents=3000000, time_extension_days=0,
        )
        recommend_change_order(change_order["id"], "REJECT")
        decided = decide_change_order(change_order["id"], "ACCEPT", project)
        assert decided["status"] == "OWNER_ACCEPTED"
        assert decided["recommendation"] == "REJECT"
        assert decided["markup_cents"] == 300000
        assert decided["total_amount_cents"] == 3300000


class TestOwnerDecisionInvalidState:
    def test_owner_decision_on_unrecommended_change_order_returns_invalid_state(self, api):
        """PRD 3.6: "Recommending against a change order that is not `SUBMITTED`,
        or rendering an owner decision against one that is not in
        `RECOMMEND_ACCEPTANCE` or `RECOMMEND_REJECTION`, fails with
        `ERR_CHANGE_ORDER_INVALID_STATE` (HTTP 409)."

        Design: Corner/validations/owner_decision_on_unrecommended_change_order_returns_invalid_state
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        change_order = create_change_order(
            project["id"], title="Panel substitution",
            net_cost_change_cents=250000, time_extension_days=0,
        )
        resp = api.decide_change_order(
            change_order["id"], {"decision": "ACCEPT"},
            make_owner_headers(project["owner_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE, 409)
        current = get_success_data(
            api.get_change_order(change_order["id"], make_firm_admin_headers()))
        assert current["status"] == "SUBMITTED"


class TestOccIncorporateStaleProjectVersion:
    def _two_accepted_change_orders(self, api):
        project = create_active_project(sov_lines=SOV_A_ONLY)
        co1 = create_owner_accepted_change_order(
            project, title="CO1", net_cost_change_cents=1000000, time_extension_days=0,
        )
        co2 = create_owner_accepted_change_order(
            project, title="CO2", net_cost_change_cents=2000000, time_extension_days=0,
        )
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        return project, co1, co2

    def test_incorporation_with_stale_project_version_rejected(self, api):
        """PRD 3.6: "The request carries `expected_project_version`, the OCC
        handshake of Section 2.9: if the project's current `version` differs,
        incorporation is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting
        the financial baseline from unobserved drift."

        Design: Corner/cross_cutting_layers/occ_incorporate_stale_project_version
        """
        project, co1, co2 = self._two_accepted_change_orders(api)
        observed_version = project["version"]
        owner_headers = make_owner_headers(project["owner_user_id"])
        first = api.incorporate_change_order(
            co1["id"], {"expected_project_version": observed_version}, owner_headers,
        )
        validate_success(first, 200)
        stale = api.incorporate_change_order(
            co2["id"], {"expected_project_version": observed_version}, owner_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_stale_incorporation_leaves_change_order_and_sum_unchanged(self, api):
        """PRD 3.6: "A successful incorporation moves the change order to
        `INCORPORATED` and then mutates the project: `adjusted_contract_sum_cents`
        increases by the change order's `total_amount_cents`".

        Design: Corner/cross_cutting_layers/occ_incorporate_stale_project_version
        """
        project, co1, co2 = self._two_accepted_change_orders(api)
        observed_version = project["version"]
        owner_headers = make_owner_headers(project["owner_user_id"])
        api.incorporate_change_order(
            co1["id"], {"expected_project_version": observed_version}, owner_headers,
        )
        api.incorporate_change_order(
            co2["id"], {"expected_project_version": observed_version}, owner_headers,
        )
        co2_current = get_success_data(api.get_change_order(co2["id"], make_firm_admin_headers()))
        assert co2_current["status"] == "OWNER_ACCEPTED"
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        # CO1 net 1000000 + markup 100000 = 1100000 applied; CO2 not applied
        assert project["adjusted_contract_sum_cents"] == 11100000


class TestIncorporationCascadesToInvoiceRecompute:
    def _setup(self, api):
        """ACTIVE project; clock 2026-11-05; DRAFT invoice 2026-10-01..2026-11-30;
        time-only change order (20 days) OWNER_ACCEPTED; version captured."""
        project = create_active_project(sov_lines=SOV_AB, grace_days=5)
        set_clock("2026-11-05T09:00:00Z")
        invoice = create_draft_invoice(project["id"], "2026-10-01", "2026-11-30")
        change_order = create_owner_accepted_change_order(
            project, title="Weather extension",
            net_cost_change_cents=0, time_extension_days=20,
        )
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        return project, invoice, change_order

    def test_incorporation_moves_completion_date_and_bumps_version(self, api):
        """PRD 3.6: "`adjusted_substantial_completion_date` moves out by
        `time_extension_days` calendar days, and the project's `version`
        increments by one."

        Design: Difficulty/transitive_cascade/change_order_incorporation_cascades_to_invoice_recompute
        """
        project, invoice, change_order = self._setup(api)
        observed_version = project["version"]
        owner_headers = make_owner_headers(project["owner_user_id"])
        incorporated = validate_success(api.incorporate_change_order(
            change_order["id"], {"expected_project_version": observed_version},
            owner_headers,
        ), 200)
        assert incorporated["status"] == "INCORPORATED"
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        assert project["adjusted_substantial_completion_date"] == "2026-10-20"
        assert project["version"] == observed_version + 1

    def test_draft_invoice_recomputes_against_new_horizon(self, api):
        """PRD 3.8: "On any change to the project's `excusable_delay_days` or
        `adjusted_substantial_completion_date`, and again when substantial
        completion is achieved (which fixes the horizon end to
        `substantial_completion_actual_date`), every invoice of the project still
        in `DRAFT` recomputes its `horizon_start_date`, `horizon_end_date`,
        `billable_days`, and `amount_cents`".

        Design: Difficulty/transitive_cascade/change_order_incorporation_cascades_to_invoice_recompute
        """
        project, invoice, change_order = self._setup(api)
        assert invoice["billable_days"] == 31
        assert invoice["amount_cents"] == 3720000
        owner_headers = make_owner_headers(project["owner_user_id"])
        api.incorporate_change_order(
            change_order["id"], {"expected_project_version": project["version"]},
            owner_headers,
        )
        invoice = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        # new horizon_start = 2026-10-20 + 0 + 5 = 2026-10-25
        assert invoice["horizon_start_date"] == "2026-10-25"
        # dates 2026-10-26..2026-11-05 within the period -> 11 billable days
        assert invoice["billable_days"] == 11
        assert invoice["amount_cents"] == 1320000
        assert invoice["status"] == "DRAFT"
