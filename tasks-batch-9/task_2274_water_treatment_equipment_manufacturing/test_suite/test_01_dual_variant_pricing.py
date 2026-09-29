"""Two prices for one package, and two money lines for one reserve draw."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_money,
    assert_pct,
    assert_project_state,
    assert_reserve_conserved,
    assert_settlement_variance,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_design_reviewer_headers,
)


class TestBudgetaryAndFirmPricingOfOnePackage:
    """The BUDGETARY and FIRM variants of the same package price differently."""

    def _package_awaiting_review(self, api):
        state = fixtures.scoped_single_stage_project(api)
        package = fixtures.add_draft_package(
            api, state["filtration_stage"]["id"], state["material_spec"]["id"]
        )
        api.submit_package_for_review(
            package["id"], make_application_engineer_headers()
        )
        state["package"] = package
        return state

    def test_approval_stamps_both_price_variants_on_the_same_package(self, api):
        """The budgetary price ignores the material cost index while the firm price applies it.

        The BUDGETARY variant "multiplies the base by a nominal material factor of
        exactly 1.0 -- the material is not yet committed, so the selected material's
        `cost_index` is deliberately ignored -- then by the pressure uplift, then by
        the code-stamp surcharge, and rounds the product half up to whole cents
        exactly once, at the end." The FIRM variant instead "multiplies by the
        *actual* selected material's `cost_index` instead of the nominal 1.0", so
        for a 240,000,000 cent base at 150 psig with an AWWA stamp the two prices
        stand apart by exactly the 1.10 cost index of stainless 316L.

        Design: Difficulty/dual_variant_calc/package_cost_budgetary_versus_firm_on_same_package
        """
        state = self._package_awaiting_review(api)

        response = api.decide_package_review(
            state["package"]["id"],
            {
                "decision": "APPROVE",
                "review_note": "Hydraulics and materials accepted",
            },
            make_design_reviewer_headers(),
        )
        package = validate_success(response)

        assert_money(package["budgetary_cost_cents"], 260832000, "budgetary_cost_cents")
        assert_money(package["firm_cost_cents"], 286915200, "firm_cost_cents")
        assert_money(
            package["firm_cost_cents"] - package["budgetary_cost_cents"],
            26083200,
            "firm minus budgetary",
        )
        assert package["status"] == "APPROVED"

    def test_approval_records_the_variance_fraction_and_leaves_the_flag_clear(self, api):
        """A ten percent design-to-release variance is stored as 0.1000 and raises no flag.

        The PRD says "`cost_variance_pct` is the firm price minus the budgetary
        price, divided by the budgetary price, rounded half up to four decimal
        places -- a fraction, not a percentage figure, so a fifteen-percent overrun
        is stored as 0.15" and that "`variance_flag` becomes true when that fraction
        is **strictly greater than** 0.15". Approval also cascades: "the parent
        stage transitions `SELECTED → ENGINEERED` and advances its own `version` by
        1, and the project's `delivery_posture` is recomputed -- becoming `AT_RISK`
        when the newly computed variance flag is set."

        Design: Difficulty/dual_variant_calc/package_cost_budgetary_versus_firm_on_same_package
        """
        state = self._package_awaiting_review(api)

        package = validate_success(
            api.decide_package_review(
                state["package"]["id"],
                {
                    "decision": "APPROVE",
                    "review_note": "Hydraulics and materials accepted",
                },
                make_design_reviewer_headers(),
            )
        )

        assert_pct(package["cost_variance_pct"], 0.1000, "cost_variance_pct")
        assert package["variance_flag"] is False

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "ENGINEERED"

        project = validate_success(
            api.get_project(
                state["project"]["id"], make_application_engineer_headers()
            )
        )
        assert_project_state(project, delivery_posture="ON_TRACK")


class TestAccrualAndSettledLinesOnAMembraneDraw:
    """One membrane replacement draw carries two independently computed amounts."""

    def _active_agreement(self, api):
        state = fixtures.service_active_project(api)
        state["agreement"] = fixtures.current_agreement(api, state["agreement"]["id"])
        return state

    def test_membrane_draw_computes_accrual_settled_and_warranty_credit_apart(self, api):
        """Catalog cost drives the accrual line while the invoiced cost drives the settled line.

        The PRD pins the accrual line as "`quantity` multiplied by
        `catalog_unit_cost_cents`, marked up by 22 percent, rounded half up to whole
        cents", and the settled line as starting "from `quantity` multiplied by
        `invoiced_unit_cost_cents`, uplifted by 6.5 percent freight, rounded half up
        to whole cents, and then has the warranty credit subtracted." For a
        MEMBRANE_REPLACEMENT draw "`warranty_credit_cents` is `quantity` multiplied
        by `invoiced_unit_cost_cents` multiplied by one percent per remaining month,
        rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/reserve_draw_accrual_versus_settled_on_membrane_replacement
        """
        state = self._active_agreement(api)

        response = api.create_consumable_draw(
            state["agreement"]["id"],
            factories.consumable_draw_payload(
                state["agreement"]["version"],
                draw_type="MEMBRANE_REPLACEMENT",
                item_code="MF-ELEM-8",
                quantity=2,
                catalog_unit_cost_cents=900000,
                invoiced_unit_cost_cents=1000000,
            ),
            make_contracts_administrator_headers(),
        )
        draw = validate_success(response, 201)

        assert_money(draw["accrual_amount_cents"], 2196000, "accrual_amount_cents")
        assert_money(draw["settled_amount_cents"], 930000, "settled_amount_cents")
        assert_money(draw["warranty_credit_cents"], 1200000, "warranty_credit_cents")

    def test_membrane_draw_moves_both_reserve_totals_and_reports_the_gap(self, api):
        """The agreement tracks the accrual and settled totals separately and reports their gap.

        The PRD says the agreement "adds the accrual line to
        `reserve_committed_accrual_cents`, adds the settled line to
        `reserve_committed_settled_cents`, decreases `reserve_available_cents` by
        the accrual line, recomputes `settlement_variance_cents` as the settled
        total minus the accrual total, and advances its `version` by 1." Because
        "the two lines use different unit costs and different rates, identical draw
        data yields two different numbers, and the gap between them is reported --
        never hidden -- as `settlement_variance_cents`."

        Design: Difficulty/dual_variant_calc/reserve_draw_accrual_versus_settled_on_membrane_replacement
        """
        state = self._active_agreement(api)

        api.create_consumable_draw(
            state["agreement"]["id"],
            factories.consumable_draw_payload(
                state["agreement"]["version"],
                draw_type="MEMBRANE_REPLACEMENT",
                item_code="MF-ELEM-8",
                quantity=2,
                catalog_unit_cost_cents=900000,
                invoiced_unit_cost_cents=1000000,
            ),
            make_contracts_administrator_headers(),
        )

        agreement = validate_success(
            api.get_service_agreement(
                state["agreement"]["id"],
                make_contracts_administrator_headers(),
            )
        )

        assert_money(
            agreement["reserve_committed_accrual_cents"],
            2196000,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_committed_settled_cents"],
            930000,
            "reserve_committed_settled_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 10004000, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"],
            -1266000,
            "settlement_variance_cents",
        )
        assert agreement["status"] == "ACTIVE"
        assert_reserve_conserved(agreement)
        assert_settlement_variance(agreement)
