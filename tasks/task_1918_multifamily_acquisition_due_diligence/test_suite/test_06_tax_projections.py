"""Tax reassessment projections: dual methods, pinned evaluation, revise loop."""
from test_helpers import (
    TEST_USERS,
    create_acquisition,
    get_acquisition_version,
    get_success_data,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]


class TestTaxProjectionMethodsDiverge:
    def test_price_anchored_vs_income_approach_on_same_acquisition(self, api):
        """PRD §3.6: "Under `PURCHASE_PRICE_ANCHORED` the `projected_value_cents`
        is simply the acquisition's `agreed_purchase_price_cents`. Under
        `INCOME_APPROACH` the `projected_value_cents` is `noi_t12_cents`
        divided by `cap_rate`, rounded half up to integer cents. The
        `projected_assessed_value_cents` is the `projected_value_cents`
        multiplied by the acquisition's `assessment_ratio`, rounded half up.
        The `projected_annual_tax_cents` is the `projected_assessed_value_cents`
        multiplied by the acquisition's `millage_rate` and divided by 1000 —
        millage being mills per dollar of assessed value — rounded half up. The
        `delta_vs_prior_cents` is the `projected_annual_tax_cents` minus the
        acquisition's `prior_year_tax_cents`, so a positive delta is new tax
        burden the buyer underwrites. The two methods produce different values
        and taxes for identical acquisition data."

        Design: Difficulty/dual_variant_calc/tax_projection_methods_diverge
        """
        acq = create_acquisition(property_name="Harbor View")
        proj_p = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "PURCHASE_PRICE_ANCHORED",
                        "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        get_success_data(api.compute_tax_projection(proj_p["id"], ANALYST))

        proj_i = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "INCOME_APPROACH", "cap_rate": 0.055,
                        "noi_t12_cents": 16_500_000,
                        "expected_acquisition_version":
                            get_acquisition_version(acq["id"])},
            ANALYST), 201)
        get_success_data(api.compute_tax_projection(proj_i["id"], ANALYST))

        p = get_success_data(api.get_tax_projection(proj_p["id"], ANALYST))
        i = get_success_data(api.get_tax_projection(proj_i["id"], ANALYST))
        assert p["projected_assessed_value_cents"] == 80_000_000
        assert p["projected_annual_tax_cents"] == 2_000_000
        assert p["delta_vs_prior_cents"] == 200_000
        assert i["projected_value_cents"] == 300_000_000
        assert i["projected_assessed_value_cents"] == 120_000_000
        assert i["projected_annual_tax_cents"] == 3_000_000
        assert i["delta_vs_prior_cents"] == 1_200_000
        assert i["projected_annual_tax_cents"] - p["projected_annual_tax_cents"] == 1_000_000

    def test_identical_acquisition_data_drives_divergent_tax(self, api):
        """PRD §3.6: "The two methods produce different values and taxes for
        identical acquisition data."
        PRD §3.6: "Computing a `DRAFT` projection runs a pinned one-pass
        evaluation in a fixed order — value conclusion first, then assessed
        value, then projected tax — and lands the projection in `COMPUTED`."

        Design: Difficulty/dual_variant_calc/tax_projection_methods_diverge
        """
        acq = create_acquisition(property_name="Diverge Deal")
        proj_p = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "PURCHASE_PRICE_ANCHORED",
                        "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        computed_p = get_success_data(api.compute_tax_projection(proj_p["id"], ANALYST))
        assert computed_p["status"] == "COMPUTED"
        assert computed_p["projected_annual_tax_cents"] == 2_000_000

        proj_i = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "INCOME_APPROACH", "cap_rate": 0.055,
                        "noi_t12_cents": 16_500_000,
                        "expected_acquisition_version":
                            get_acquisition_version(acq["id"])},
            ANALYST), 201)
        computed_i = get_success_data(api.compute_tax_projection(proj_i["id"], ANALYST))
        assert computed_i["projected_annual_tax_cents"] == 3_000_000
        assert computed_i["projected_value_cents"] == 300_000_000, (
            "INCOME_APPROACH: round_half_up(16500000 / 0.055)"
        )


class TestIncomeApproachPinnedEvaluationOrder:
    def test_income_approach_computes_in_one_pass(self, api):
        """PRD §3.6: "The income approach additionally requires a `cap_rate`
        and a `noi_t12_cents` giving trailing-twelve-month net operating income
        computed with prior-year taxes, which breaks the circularity between
        tax and NOI: the projected tax computed here must never feed back into
        the NOI."
        PRD §3.6: "Computing a `DRAFT` projection runs a pinned one-pass
        evaluation in a fixed order — value conclusion first, then assessed
        value, then projected tax — and lands the projection in `COMPUTED`."

        Design: Difficulty/combinatorial_formula/tax_income_approach_pinned_evaluation_order_mode_c
        """
        acq = create_acquisition(property_name="Circular Deal")
        proj = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "INCOME_APPROACH", "cap_rate": 0.055,
                        "noi_t12_cents": 16_500_000,
                        "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        computed = validate_success(api.compute_tax_projection(proj["id"], ANALYST))
        assert computed["projected_value_cents"] == 300_000_000
        assert computed["projected_assessed_value_cents"] == 120_000_000
        assert computed["projected_annual_tax_cents"] == 3_000_000
        assert computed["delta_vs_prior_cents"] == 1_200_000

    def test_pinned_order_uses_prior_year_tax_in_noi(self, api):
        """PRD §3.6: "The `projected_annual_tax_cents` is the
        `projected_assessed_value_cents` multiplied by the acquisition's
        `millage_rate` and divided by 1000 — millage being mills per dollar of
        assessed value — rounded half up. The `delta_vs_prior_cents` is the
        `projected_annual_tax_cents` minus the acquisition's
        `prior_year_tax_cents`, so a positive delta is new tax burden the buyer
        underwrites."

        Design: Difficulty/combinatorial_formula/tax_income_approach_pinned_evaluation_order_mode_c
        """
        acq = create_acquisition(property_name="Circular Deal Two")
        proj = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "INCOME_APPROACH", "cap_rate": 0.055,
                        "noi_t12_cents": 16_500_000,
                        "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        computed = get_success_data(api.compute_tax_projection(proj["id"], ANALYST))
        # The one-pass chain: value 300000000 -> assessed 120000000 -> tax 3000000.
        # A feedback implementation (re-solving NOI with the projected tax)
        # would conclude a lower value; the pinned order forbids it.
        assert computed["projected_value_cents"] == 300_000_000
        assert computed["projected_assessed_value_cents"] == 120_000_000
        assert computed["projected_annual_tax_cents"] == 3_000_000
        assert computed["delta_vs_prior_cents"] == (
            3_000_000 - acq["prior_year_tax_cents"]
        )


class TestTaxProjectionReviseLoop:
    def test_tax_projection_revise_clears_computed_fields(self, api):
        """PRD §3.6: "Revision returns a `COMPUTED` projection to `DRAFT` and
        clears its computed fields."
        PRD §3.6: "Computing a `DRAFT` projection runs a pinned one-pass
        evaluation in a fixed order — value conclusion first, then assessed
        value, then projected tax — and lands the projection in `COMPUTED`."

        Design: Corner/state_machines/tax_projection_revise_clears_computed_fields
        """
        acq = create_acquisition(property_name="Revise Deal")
        proj = get_success_data(api.create_tax_projection(
            acq["id"], {"method": "PURCHASE_PRICE_ANCHORED",
                        "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        first = get_success_data(api.compute_tax_projection(proj["id"], ANALYST))
        assert first["projected_annual_tax_cents"] == 2_000_000

        revised = validate_success(api.revise_tax_projection(proj["id"], UM1))
        assert revised["status"] == "DRAFT"
        after = get_success_data(api.get_tax_projection(proj["id"], ANALYST))
        assert after.get("projected_annual_tax_cents") is None, (
            "revise clears the computed fields"
        )

        second = get_success_data(api.compute_tax_projection(proj["id"], ANALYST))
        assert second["projected_annual_tax_cents"] == 2_000_000, (
            "identical inputs re-derive identical outputs"
        )
