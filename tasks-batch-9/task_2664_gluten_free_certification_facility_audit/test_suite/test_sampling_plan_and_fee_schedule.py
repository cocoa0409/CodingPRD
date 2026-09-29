"""Two multi-input formulas: the per-line sampling arithmetic that rounds before
it sums, and the certification fee whose rate band is keyed on the base fee.
"""

from test_helpers import (
    IngredientSpec,
    MarkTier,
    RiskClass,
    activate_testing_plan,
    add_certified_product,
    create_product,
    issue_certificate,
    link_ingredient,
    make_decision_maker_headers,
    make_reviewer_headers,
    read_applicant,
    read_certificate,
    read_product,
    review_formula,
    review_label,
    set_clock,
    setup_applicant_with_facility,
    setup_approved_formula_lines,
    setup_certification_ready_product,
    setup_passed_audit,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
ISSUE_DAY = "2026-08-11T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"

RICE_FLOUR = IngredientSpec(
    name="Brown Rice Flour",
    risk_class=RiskClass.INHERENTLY_GF,
    inclusion_pct=40,
    doc_expires_on=DOC_EXPIRES,
)
OAT_FLOUR_TRACE = IngredientSpec(
    name="Purity Protocol Oat Flour",
    risk_class=RiskClass.GF_PROCESSED,
    inclusion_pct=1.0,
    doc_expires_on=DOC_EXPIRES,
)


def _cleared_two_line_formula(api):
    """A CLEARED, unplanned product on a shared-equipment ADJACENT_LINES site with
    one INHERENTLY_GF line at 40 pct and one GF_PROCESSED line at 1.0 pct."""
    return setup_certification_ready_product(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(RICE_FLOUR, OAT_FLOUR_TRACE),
        product_overrides={"name": "Multigrain Rice Loaf", "sku": "MRL-001"},
        activate_plan=False,
        review_label_decision=None,
        run_audit=False,
    )


def test_two_lines_each_rounding_to_two_lots_give_four_lots_a_year(api):
    """Both lines reach a raw 1.5 lots and each rounds up to 2, so the plan is 4
    lots a year rather than the 3 a rounded sum of 3.0 would have given.

    PRD: "Round that per-line product half up to a whole number of lots **before**
    going on to the next line."
    PRD: "The placement of the rounding is the whole point: two lines each
    computing 1.5 give 2 plus 2, which is 4 lots per year, whereas rounding a sum
    of 3.0 would have given 3."

    Design: Difficulty/combinatorial_formula/sampling_frequency_per_line_round_half_up_before_summation
    """
    context = _cleared_two_line_formula(api)

    activate_testing_plan(api, context.product_id, context.product_version)

    product = read_product(api, context.product_id)
    assert product["threshold_ppm"] == 10
    assert product["sampling_lots_per_year"] == 4
    assert product["sampling_exclusion_days"] == 91
    assert product["linked_ingredient_count"] == 2
    assert product["formula_status"] == "CLEARED"


def test_the_exclusion_span_is_a_floor_division_of_the_year_by_the_lot_count(api):
    """Activation answers 200 with an ACTIVE plan at revision 1, whose 91-day
    exclusion span is 365 divided by 4 lots with the remainder discarded.

    PRD: "`sampling_exclusion_days` follows immediately: divide the 365 days of a
    year by `sampling_lots_per_year`, discard any fractional part, and take the
    larger of that quotient and 7 days."
    PRD: "Activation computes `threshold_ppm`, then `sampling_lots_per_year` and
    `sampling_exclusion_days` from it, sets `testing_plan_status` to `ACTIVE`,
    increases `testing_plan_revision` by 1 — so the counter records how many plans
    this product has had, each superseding the last — and increases the product's
    `version` by 1."

    Design: Difficulty/combinatorial_formula/sampling_frequency_per_line_round_half_up_before_summation
    """
    context = _cleared_two_line_formula(api)
    version_before = context.product_version

    response = api.activate_testing_plan(
        context.product_id,
        make_reviewer_headers(),
        expected_product_version=version_before,
    )
    assert response.status_code == 200, response.text
    planned = response.json()["data"]

    assert planned["testing_plan_status"] == "ACTIVE"
    assert planned["testing_plan_revision"] == 1
    assert planned["version"] == version_before + 1
    assert planned["sampling_lots_per_year"] == 4
    assert planned["sampling_exclusion_days"] == 91


def _two_products_sharing_one_shared_equipment_site(api):
    """One shared-equipment site, two approved ingredients, and two products: A
    links one ingredient (base 149000) and B links two (base 155000). Both carry
    an active plan and an approved STANDARD label; the site has passed its audit.
    """
    context = setup_applicant_with_facility(
        api, clock=SANITATION_DAY, sanitation_validated_on=SANITATION_DAY
    )
    setup_approved_formula_lines(
        api,
        context,
        ingredients=(
            IngredientSpec(
                name="Brown Rice Flour",
                risk_class=RiskClass.INHERENTLY_GF,
                doc_expires_on=DOC_EXPIRES,
            ),
            IngredientSpec(
                name="Purity Protocol Oat Flour",
                risk_class=RiskClass.GF_PROCESSED,
                doc_expires_on=DOC_EXPIRES,
            ),
        ),
    )
    ing_a, ing_b = context.ingredients[0]["id"], context.ingredients[1]["id"]

    product_a = add_certified_product(
        api,
        context,
        name="Rice Sandwich Loaf",
        sku="RSL-001",
        inclusion_pct=40,
        ingredient_id=ing_a,
    )

    raw_b = create_product(
        api,
        context.applicant_id,
        context.facility_id,
        name="Multigrain Rice Loaf",
        sku="MRL-001",
        requested_mark_tier=MarkTier.STANDARD,
    )
    link_ingredient(api, context.applicant_id, raw_b["id"], ing_a, 40)
    link_ingredient(api, context.applicant_id, raw_b["id"], ing_b, 25)
    cleared_b = review_formula(api, raw_b["id"])
    planned_b = activate_testing_plan(api, raw_b["id"], cleared_b["version"])
    labelled_b = review_label(api, raw_b["id"], mark_tier_granted=MarkTier.STANDARD)
    assert planned_b["testing_plan_status"] == "ACTIVE"

    context.audit = setup_passed_audit(api, context.facility_id)

    set_clock(api, ISSUE_DAY)
    certificate_a = issue_certificate(
        api, product_a["product"]["id"], product_a["version"]
    )
    return context, product_a, labelled_b, certificate_a


def test_the_larger_base_fee_takes_the_cheaper_rate_and_bills_less_in_total(api):
    """Product B's base of 155000 selects the 0.15 band, so its 178250 total comes
    out below the 178800 billed against product A's smaller 149000 base.

    PRD: "Step two selects the surveillance rate by comparing `base_fee_cents` —
    and specifically the base, never the eventual total — against two ceilings: a
    base below 150000 cents takes a rate of 0.20, a base from 150000 cents up to
    but not including 250000 cents takes 0.15, and a base of 250000 cents or more
    takes 0.10."

    Design: Difficulty/combinatorial_formula/fee_tier_selected_on_base_fee_so_larger_base_bills_less
    """
    _context, _product_a, labelled_b, certificate_a = (
        _two_products_sharing_one_shared_equipment_site(api)
    )

    response = api.issue_certificate(
        make_decision_maker_headers(),
        product_id=labelled_b["id"],
        expected_product_version=labelled_b["version"],
    )
    assert response.status_code == 201, response.text
    certificate_b = response.json()["data"]

    assert certificate_b["base_fee_cents"] == 155000
    assert certificate_b["surveillance_surcharge_cents"] == 23250
    assert certificate_b["total_fee_cents"] == 178250

    read_a = read_certificate(api, certificate_a["id"])
    assert read_a["base_fee_cents"] == 149000
    assert read_a["surveillance_surcharge_cents"] == 29800
    assert read_a["total_fee_cents"] == 178800
    assert read_a["total_fee_cents"] > certificate_b["total_fee_cents"]


def test_the_fee_ledger_carries_the_sum_of_both_billed_certificates(api):
    """After the second issuance the applicant's balance is exactly 178800 plus
    178250, and two products count as actively certified.

    PRD: "At every observable instant it equals the sum of `total_fee_cents` over
    that applicant's certificates whose `fee_charged` is true and whose
    `fee_refunded` is false."
    PRD: "Step one computes `base_fee_cents` as 98000 cents of product base fee,
    plus 6000 cents for each ingredient counted in the product's
    `linked_ingredient_count`, plus a further 45000 cents when the manufacturing
    facility has `shared_equipment_present` true and nothing extra when it is
    false."

    Design: Difficulty/combinatorial_formula/fee_tier_selected_on_base_fee_so_larger_base_bills_less
    """
    context, product_a, labelled_b, _certificate_a = (
        _two_products_sharing_one_shared_equipment_site(api)
    )

    issue_certificate(api, labelled_b["id"], labelled_b["version"])

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["fee_balance_cents"] == 357050
    assert applicant["active_certified_product_count"] == 2

    assert read_product(api, product_a["product"]["id"])["linked_ingredient_count"] == 1
    assert read_product(api, labelled_b["id"])["linked_ingredient_count"] == 2
