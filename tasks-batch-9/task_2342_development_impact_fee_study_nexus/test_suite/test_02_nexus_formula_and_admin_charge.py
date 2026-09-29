"""The pinned rounding points of the fee arithmetic: the allocation denominator,
the per-line administrative charge and the credit cap."""

from test_helpers import ANALYST_2, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data, make_analyst_headers, validate_error
from test_helpers.fixtures import ADMIN, ANALYST

REVIEWER = make_analyst_headers(ANALYST_2)


def _improvement_claim(code, value_cents):
    """A developer-improvement claim valued nominally at its face amount."""
    return {
        "facility_category_code": code,
        "credit_type": K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        "valuation_method": K.VALUATION_NOMINAL,
        "improvement_value_cents": value_cents,
        "contribution_years": 0,
    }


def _capacity_limited_parks_study(api):
    """A parks component whose planned capacity falls short of its projected
    growth demand."""
    chain = fixtures.program_with_categories(api, with_roads=False)
    study = fixtures.create_study(api, chain.program_id)
    chain.study_id = study["id"]
    component = fixtures.create_parks_component(
        api, chain.study_id, chain.parks_category_id, planned_capacity_demand_units=2500.0000
    )
    chain.parks_component_id = component["id"]
    return chain


def test_plan_based_allocation_divides_by_the_smaller_denominator(api):
    """Divide that net growth cost by the smaller of `growth_demand_units` and
    `planned_capacity_demand_units`, and round the quotient half up to whole cents.
    `adopted_cost_per_unit_cents` is then the study's chosen reading less the
    existing-tax credit, floored at zero: take `plan_based_cost_per_unit_cents` when
    the study's `methodology` is `PLAN_BASED` and `standard_based_cost_per_unit_cents`
    when it is `STANDARD_BASED`, subtract `existing_tax_credit_per_unit_cents`, and
    use zero instead if the subtraction would go negative.

    Design: Difficulty/combinatorial_formula/plan_based_denominator_takes_the_min_of_growth_and_planned_capacity
    """
    chain = _capacity_limited_parks_study(api)

    allocated = fixtures.allocate(api, chain.parks_component_id)

    check.assert_four_decimal_equals(
        allocated["growth_demand_units"], 3000.0000, "growth_demand_units"
    )
    check.assert_money_equals(
        allocated["plan_based_cost_per_unit_cents"], 140000, "plan_based_cost_per_unit_cents"
    )
    check.assert_money_equals(
        allocated["standard_based_cost_per_unit_cents"],
        135000,
        "standard_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["adopted_cost_per_unit_cents"], 125000, "adopted_cost_per_unit_cents"
    )
    check.assert_four_decimal_equals(allocated["nexus_ratio"], 0.8333, "nexus_ratio")

    line = fixtures.add_schedule_line(
        api, chain.parks_component_id, K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
    )
    check.assert_money_equals(line["fee_per_unit_cents"], 312500, "fee_per_unit_cents")


def test_certification_is_refused_when_capacity_falls_short_of_growth(api):
    """Certification is the analyst's formal record that the rational nexus and
    rough-proportionality tests are met for every category the study prices, and it
    moves the study `DRAFT → NEXUS_CERTIFIED`. It is refused unless the study is in
    `DRAFT` (`ERR_STUDY_INVALID_STATE`), unless the study has at least one component
    (`ERR_STUDY_HAS_NO_COMPONENTS`), unless every component of the study has
    `allocation_status` `VALID` and carries at least one schedule line
    (`ERR_COMPONENT_ALLOCATION_STALE` in either case), and unless every component's
    `nexus_ratio` is at least 1.0 (`ERR_NEXUS_RATIO_INSUFFICIENT`, HTTP 409) — a
    component whose planned capacity falls short of its projected growth demand would
    be charging new development for capacity the programme never buys.

    Design: Difficulty/combinatorial_formula/plan_based_denominator_takes_the_min_of_growth_and_planned_capacity
    """
    chain = _capacity_limited_parks_study(api)
    fixtures.allocate(api, chain.parks_component_id)
    fixtures.add_schedule_line(
        api, chain.parks_component_id, K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
    )

    response = api.certify_nexus(chain.study_id, ANALYST)

    validate_error(response, err.ERR_NEXUS_RATIO_INSUFFICIENT, 409)
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_DRAFT
    check.assert_fields_null(study, "certified_by_user_id", "certified_at")


def test_administrative_charge_is_rounded_once_per_assessed_line(api):
    """`line_admin_cents` is that net multiplied by the program's
    `admin_charge_bp` divided by ten thousand, rounded half up to whole cents
    once, per line. At a 300-basis-point charge, a parks net of 41,680 rounds
    1,250.4 to 1,250 and a roads net of 2,477,505 rounds 74,325.15 to 74,325,
    summing to 75,575, whereas charging the combined 2,519,185 remainder in one
    operation would have produced 75,576 — one cent apart, which is exactly the
    discrimination the per-line rule exists to make.

    Design: Difficulty/combinatorial_formula/administrative_charge_rounds_per_line_then_sums
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    parks_claim = fixtures.file_credit_claim(
        api, chain.application_id, **_improvement_claim(K.PARKS_CODE, 2500000)
    )
    roads_claim = fixtures.file_credit_claim(
        api, chain.application_id, **_improvement_claim(K.ROADS_CODE, 2400000)
    )

    fixtures.decide_credit_claim(
        api, parks_claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )
    application = fixtures.decide_credit_claim(
        api, roads_claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application,
        gross_assessed_cents=5038370,
        credit_applied_cents=2519185,
        admin_charge_cents=75575,
        net_due_cents=2594760,
    )
    parks_line = check.line_for_code(application["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(application["assessed_lines"], K.ROADS_CODE)
    check.assert_assessed_line(parks_line, line_admin_cents=1250)
    check.assert_assessed_line(roads_line, line_admin_cents=74325)


def test_credit_waterfall_fills_the_first_line_before_the_second(api):
    """The first bucket fills before the second: with a 2,519,185-cent capped
    total, raw parks credit of 2,500,000 and raw roads credit of 2,400,000, parks
    takes 2,500,000 and roads takes the remaining 19,185.

    Design: Difficulty/combinatorial_formula/administrative_charge_rounds_per_line_then_sums
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    parks_claim = fixtures.file_credit_claim(
        api, chain.application_id, **_improvement_claim(K.PARKS_CODE, 2500000)
    )
    roads_claim = fixtures.file_credit_claim(
        api, chain.application_id, **_improvement_claim(K.ROADS_CODE, 2400000)
    )

    fixtures.decide_credit_claim(
        api, parks_claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )
    fixtures.decide_credit_claim(
        api, roads_claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["assessment_status"] == K.ASSESSMENT_REASSESSED
    parks_line = check.line_for_code(application["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(application["assessed_lines"], K.ROADS_CODE)
    check.assert_assessed_line(parks_line, line_credit_cents=2500000)
    check.assert_assessed_line(roads_line, line_credit_cents=19185)
    check.assert_net_due_identity(application)


def test_credit_cap_is_taken_on_the_gross_fee(api):
    """The credit cap is `gross_assessed_cents` multiplied by the program's
    `credit_cap_bp` divided by ten thousand, rounded half up to whole cents. On a
    gross of 5,038,370 cents with a `credit_cap_bp` of 5000, the cap is 2,519,185
    cents, so 1,000,000 cents of approved parks credit applies in full while
    3,000,000 cents of approved parks credit is cut back to 2,519,185.

    Design: Difficulty/combinatorial_formula/credit_cap_bites_on_gross_fee_before_the_admin_charge
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    claim = fixtures.file_credit_claim(
        api, chain.application_id, **_improvement_claim(K.PARKS_CODE, 3000000)
    )

    decided = fixtures.decide_credit_claim(
        api, claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    check.assert_money_equals(decided["approved_cents"], 3000000, "approved_cents")
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application,
        gross_assessed_cents=5038370,
        credit_applied_cents=2519185,
        admin_charge_cents=75576,
        net_due_cents=2594761,
    )


def test_the_capped_credit_is_charged_administration_line_by_line(api):
    """Each line's `line_credit_cents` is the smallest of that line's own raw
    approved credit, the amount still remaining from the capped total, and the line's
    own `line_gross_cents` — a line's credit may never exceed its own gross fee. The
    cap is taken on the gross fee, before any administrative charge exists — never on
    the post-administrative total.

    Design: Difficulty/combinatorial_formula/credit_cap_bites_on_gross_fee_before_the_admin_charge
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    claim = fixtures.file_credit_claim(
        api, chain.application_id, **_improvement_claim(K.PARKS_CODE, 3000000)
    )

    fixtures.decide_credit_claim(
        api, claim["id"], chain.application_id, K.DECISION_APPROVE_FULL, headers=REVIEWER
    )

    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    parks_line = check.line_for_code(application["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(application["assessed_lines"], K.ROADS_CODE)
    check.assert_assessed_line(parks_line, line_credit_cents=2519185, line_admin_cents=675)
    check.assert_assessed_line(roads_line, line_credit_cents=0, line_admin_cents=74901)
    check.assert_net_due_identity(application)
