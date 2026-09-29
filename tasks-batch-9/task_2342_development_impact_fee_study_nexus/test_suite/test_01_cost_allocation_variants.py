"""Two readings of the same facts: the cost allocation methodologies and the
two credit valuation methods."""

from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data
from test_helpers.fixtures import ADMIN


def _parks_program_with_two_studies(api):
    """One parks standard priced by a plan-based and a standard-based study
    from byte-identical component inputs."""
    chain = fixtures.program_with_categories(api, with_roads=False)
    plan_study = fixtures.create_study(
        api,
        chain.program_id,
        methodology=K.METHODOLOGY_PLAN_BASED,
        title="2026 Impact Fee Study - Plan Based",
    )
    standard_study = fixtures.create_study(
        api,
        chain.program_id,
        methodology=K.METHODOLOGY_STANDARD_BASED,
        title="2026 Impact Fee Study - Standard Based",
    )
    plan_component = fixtures.create_parks_component(
        api, plan_study["id"], chain.parks_category_id
    )
    standard_component = fixtures.create_parks_component(
        api, standard_study["id"], chain.parks_category_id
    )
    return chain, plan_component, standard_component


def test_plan_based_study_adopts_the_incremental_expansion_reading(api):
    """The allocation prices the same statutory facts twice, and both results are
    always stored so the record shows the alternative the council did not adopt. A
    programme costing 500,000,000 cents with an 8000-basis-point growth share and
    50,000,000 cents of grants nets to 350,000,000 cents; divided by the smaller of
    3000 projected demand units and 3500 units of planned capacity, that is
    350,000,000 over 3000, or 116,666.66 recurring, stored as 116,667. A plan-based
    selection of 116,667 with a 15,000-cent existing-tax credit adopts 101,667; a
    standard-based selection of 135,000 with the same credit adopts 120,000.

    Design: Difficulty/dual_variant_calc/cost_allocation_plan_based_versus_standard_based_on_identical_facts
    """
    _, plan_component, standard_component = _parks_program_with_two_studies(api)

    plan_allocated = fixtures.allocate(api, plan_component["id"])
    fixtures.allocate(api, standard_component["id"])

    check.assert_four_decimal_equals(
        plan_allocated["growth_demand_units"], 3000.0000, "growth_demand_units"
    )
    check.assert_money_equals(
        plan_allocated["plan_based_cost_per_unit_cents"], 116667, "plan_based_cost_per_unit_cents"
    )
    check.assert_money_equals(
        plan_allocated["standard_based_cost_per_unit_cents"],
        135000,
        "standard_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        plan_allocated["adopted_cost_per_unit_cents"], 101667, "adopted_cost_per_unit_cents"
    )
    check.assert_four_decimal_equals(plan_allocated["nexus_ratio"], 1.1667, "nexus_ratio")
    assert plan_allocated["allocation_status"] == K.ALLOCATION_VALID


def test_standard_based_study_adopts_the_level_of_service_reading(api):
    """A plan-based selection of 116,667 with a 15,000-cent existing-tax credit
    adopts 101,667; a standard-based selection of 135,000 with the same credit
    adopts 120,000. Because the ratio measures capacity rather than price, it is
    identical under both methodologies.

    Design: Difficulty/dual_variant_calc/cost_allocation_plan_based_versus_standard_based_on_identical_facts
    """
    _, plan_component, standard_component = _parks_program_with_two_studies(api)

    plan_allocated = fixtures.allocate(api, plan_component["id"])
    standard_allocated = fixtures.allocate(api, standard_component["id"])

    check.assert_money_equals(
        standard_allocated["plan_based_cost_per_unit_cents"],
        116667,
        "plan_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        standard_allocated["standard_based_cost_per_unit_cents"],
        135000,
        "standard_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        standard_allocated["adopted_cost_per_unit_cents"], 120000, "adopted_cost_per_unit_cents"
    )
    assert (
        standard_allocated["adopted_cost_per_unit_cents"]
        != plan_allocated["adopted_cost_per_unit_cents"]
    ), "the two methodologies must adopt different per-unit costs on identical facts"
    check.assert_four_decimal_equals(standard_allocated["nexus_ratio"], 1.1667, "nexus_ratio")
    check.assert_four_decimal_equals(plan_allocated["nexus_ratio"], 1.1667, "nexus_ratio")


def test_nominal_credit_valuation_adds_contributions_at_face_value(api):
    """Under `NOMINAL`, contributions are added at face value:
    `claimed_credit_cents` is `improvement_value_cents` plus
    `annual_tax_contribution_cents` multiplied by `contribution_years`. Ten years of
    a 120,000-cent annual tax contribution is therefore 1,200,000 cents. A claim is
    born `SUBMITTED` with `approved_cents` at 0, `decided_by_user_id` and
    `decided_at` null, and no effect whatsoever on the application's money fields.

    Design: Difficulty/dual_variant_calc/credit_claim_nominal_versus_present_value_valuation
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)

    nominal = fixtures.file_credit_claim(api, chain.application_id)

    check.assert_money_equals(nominal["claimed_credit_cents"], 1200000, "claimed_credit_cents")
    assert nominal["status"] == K.CLAIM_SUBMITTED
    check.assert_money_equals(nominal["approved_cents"], 0, "approved_cents")
    check.assert_fields_null(nominal, "decided_by_user_id", "decided_at")

    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application, credit_applied_cents=0, net_due_cents=K.BASELINE_NET_DUE
    )


def test_present_value_credit_valuation_discounts_the_same_tax_stream(api):
    """The annuity factor is the sum, over each whole year from one through
    `contribution_years`, of one divided by one plus that rate raised to the power of
    that year; the annuity factor itself is not rounded. The present value of the tax
    stream is `annual_tax_contribution_cents` multiplied by that annuity factor. At a
    `discount_rate_bp` of 400, ten years of a 120,000-cent annual contribution has an
    annuity factor of 8.110895779 and a present value of 973,307 cents, against
    1,200,000 nominal; a 1,000,000-cent improvement over three years discounts to
    888,996 cents.

    Design: Difficulty/dual_variant_calc/credit_claim_nominal_versus_present_value_valuation
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)

    nominal = fixtures.file_credit_claim(api, chain.application_id)
    present_value = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.ROADS_CODE,
        valuation_method=K.VALUATION_PRESENT_VALUE,
    )

    check.assert_money_equals(
        present_value["claimed_credit_cents"], 973307, "claimed_credit_cents"
    )
    assert nominal["claimed_credit_cents"] - present_value["claimed_credit_cents"] == 226693
    assert present_value["status"] == K.CLAIM_SUBMITTED
    check.assert_money_equals(present_value["approved_cents"], 0, "approved_cents")

    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application, credit_applied_cents=0, net_due_cents=K.BASELINE_NET_DUE
    )
