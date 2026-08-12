"""Allowance lines, running contract price, and draw reservation tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_allowance_conservation,
    assert_allowance_line,
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


def _setup_project_with_line(api, budgeted=100000, base=5000000, line_name="FLOORING"):
    """INTAKE project carrying one unselected allowance line."""
    ctx = setup_intake_project(base_contract_cents=base)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    line = get_success_data(
        api.create_allowance_line(
            ctx["project"]["id"],
            create_allowance_line_payload(name=line_name, budgeted_cents=budgeted),
            ctr_h,
        )
    )
    ctx["line"] = line
    return ctx


class TestProvisionalVsFinalPrice:
    def test_unselected_line_makes_provisional_price_with_contingency(self, api):
        """PRD §3.5: "The `PROVISIONAL` price adds a contingency of 10 percent on each
        unselected line's budget-minus-drawn remainder, summed and rounded half up to
        whole cents — so with one unselected line budgeted at 100000 cents and no
        other activity, the provisional price reports the base plus 10000 cents of
        contingency"
        PRD §3.5: "`price_variant` is `FINAL` when the project has no allowance lines
        at all or every line is selected, and `PROVISIONAL` otherwise."

        Design: Difficulty/dual_variant_calc/project_price_provisional_vs_final
        """
        ctx = _setup_project_with_line(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["price_variant"] == "PROVISIONAL"
        assert proj["contract_price_cents"] == 5010000

    def test_selection_flips_to_final_and_reports_variance(self, api):
        """PRD §3.5: "selecting that line flips the variant to `FINAL` and reports the
        base plus the line's actual-minus-budgeted variance instead."
        PRD §3.5: "Two derived figures track the line thereafter: `remaining_cents` is
        always the budget minus the reserved, drawn, and actual amounts, and
        `variance_cents` is the actual plus the drawn minus the budgeted amount"

        Design: Difficulty/dual_variant_calc/project_price_provisional_vs_final
        """
        ctx = _setup_project_with_line(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        before = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        validate_success(
            api.select_allowance_line(
                ctx["line"]["id"], {"actual_cents": 112000}, ho_h
            ),
            200,
        )
        after = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert after["price_variant"] == "FINAL"
        assert after["contract_price_cents"] == 5012000
        assert after["contract_price_cents"] != before["contract_price_cents"]
        line = get_only_allowance_line(ctx["project"]["id"], ctr_h)
        assert line["variance_cents"] == 12000
        assert line["remaining_cents"] == -12000
        assert_allowance_conservation(line)


class TestDrawReservationConservation:
    def _create_draw_order(self, api, ctx):
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        co = create_change_order_fresh(
            ctx["project"]["id"], ctr_h,
            scope_description="add vanity fixture",
            kind="ADD",
            scope_items=[{"description": "vanity set", "qty": 20,
                          "unit_cost_cents": 1500}],
            allowance_draws=[{"allowance_line_id": ctx["line"]["id"],
                              "amount_cents": 30000}],
        )
        return co

    def test_draw_reservation_lowers_remaining(self, api):
        """PRD §3.5: "Each draw's amount is added to its line's `reserved_cents`,
        lowering `remaining_cents` by the same amount."
        PRD §3.5: "For an `ADD` order, `price_delta_cents` is the items total minus
        the draws total"

        Design: Difficulty/compensating_invariant/allowance_reserve_release_conservation
        """
        ctx = _setup_project_with_line(api, line_name="FIXTURES")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        assert ctx["line"]["remaining_cents"] == 100000

        co = self._create_draw_order(api, ctx)
        # round_half_up(20 * 1500 * 1.15) = 34500; 34500 - 30000 draw = 4500.
        assert co["price_delta_cents"] == 4500
        line = get_only_allowance_line(ctx["project"]["id"], ctr_h)
        assert line["reserved_cents"] == 30000
        assert line["remaining_cents"] == 70000
        assert_allowance_conservation(line)

    def test_reject_releases_reservation_and_restores_remaining(self, api):
        """PRD §3.5: "The owning homeowner rejects, optionally with a `reason`: all
        draws are released, restoring `remaining_cents`, and the project's `version`
        increments."

        Design: Difficulty/compensating_invariant/allowance_reserve_release_conservation
        """
        ctx = _setup_project_with_line(api, line_name="FIXTURES")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        co = self._create_draw_order(api, ctx)

        validate_success(
            api.reject_change_order(co["id"], {"reason": "too pricey"}, ho_h), 200
        )
        line = get_only_allowance_line(ctx["project"]["id"], ctr_h)
        assert line["reserved_cents"] == 0
        assert line["drawn_cents"] == 0
        assert line["actual_cents"] == 0
        assert line["remaining_cents"] == 100000, (
            "the compensating release restores the pre-reservation remaining"
        )
        assert_allowance_conservation(line)


class TestAllowanceCreationAndGuards:
    def test_allowance_remaining_equals_budget_at_creation(self, api):
        """PRD §3.5: "At creation `reserved_cents` and `drawn_cents` are zero,
        `selected` is false, `actual_cents` is zero, and `remaining_cents` equals the
        budget."

        Design: Corner/entities/allowance_remaining_equals_budget_at_creation
        """
        ctx = setup_intake_project()
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.create_allowance_line(
            ctx["project"]["id"],
            create_allowance_line_payload(name="LIGHTING", budgeted_cents=75000),
            ctr_h,
        )
        line = validate_success(res, 201)
        assert_allowance_line(line)
        assert line["remaining_cents"] == 75000
        assert line["reserved_cents"] == 0
        assert line["drawn_cents"] == 0
        assert line["selected"] is False
        assert line["actual_cents"] == 0

    def test_allowance_overdraw_rejected(self, api):
        """PRD §3.5: "each draw's `amount_cents` must be at least 1 and no more than
        the line's current `remaining_cents`; the draws in total must not exceed the
        items total; and a `CREDIT` order must carry an empty `allowance_draws` array
        — any breach is rejected with `ERR_ALLOWANCE_OVERDRAW`."

        Design: Corner/validations/allowance_overdraw_rejected
        """
        ctx = _setup_project_with_line(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        version = get_project_version(ctx["project"]["id"], ctr_h)
        res = api.create_change_order(
            ctx["project"]["id"],
            {
                "scope_description": "premium floor",
                "kind": "ADD",
                "scope_items": [{"description": "floor work", "qty": 20,
                                 "unit_cost_cents": 15000}],
                "allowance_draws": [{"allowance_line_id": ctx["line"]["id"],
                                     "amount_cents": 150000}],
                "expected_project_version": version,
            },
            ctr_h,
        )
        validate_error(res, ApiErrorId.ERR_ALLOWANCE_OVERDRAW)
        orders = api.list_change_orders(ctx["project"]["id"], ctr_h).json()["data"]
        assert orders == [], "a rejected creation must persist no change order"
        line = get_only_allowance_line(ctx["project"]["id"], ctr_h)
        assert line["reserved_cents"] == 0
        assert line["remaining_cents"] == 100000


class TestSelectionConsistency:
    def test_select_response_reflects_recompute_immediately(self, api):
        """PRD §3.5: "Each selection sets `selected` to true, stores `actual_cents`,
        recomputes `variance_cents` and `remaining_cents`, recomputes the project
        price, and increments the project's `version`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/select_response_reflects_recompute_immediately
        """
        ctx = _setup_project_with_line(api, base=4000000)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        res = api.select_allowance_line(
            ctx["line"]["id"], {"actual_cents": 90000}, ho_h
        )
        line = validate_success(res, 200)
        assert line["selected"] is True
        assert line["variance_cents"] == -10000
        assert line["remaining_cents"] == 10000
        proj = get_success_data(api.get_project(ctx["project"]["id"], ctr_h))
        assert proj["price_variant"] == "FINAL"
        assert proj["contract_price_cents"] == 3990000
