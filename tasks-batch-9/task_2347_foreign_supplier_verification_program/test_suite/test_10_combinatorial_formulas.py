"""Multi-input score formulas: the clamp, the round-then-sum order, the tier lock.

These assertions are exact to the cent, because a cent is exactly what separates
the specified arithmetic from the plausible alternative.
"""

from typing import Any

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_money
from test_helpers.test_users import make_qualified_individual_headers


def _cents(value: Any) -> float:
    """Read a 2-decimal field back as an exact cent value."""
    return round(float(value), 2)


# --- Infant ready-to-eat food: the product overshoots the cap ---------------
CRONOBACTER = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Cronobacter sakazakii",
    severity=5,
    probability=5,
    control_owner="FOREIGN_SUPPLIER",
)


def _infant_draft_analysis(api: ApiClient):
    """An importer, an INFANT ready-to-eat food, and an empty draft analysis."""
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_infant_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    analysis = fx.create_hazard_analysis(
        api,
        pair["id"],
        qi_a["id"],
        methodology_note="Infant food hazard identification per Codex and FDA guidance",
    )
    return qi_a, pair, analysis


def test_hazard_risk_score_is_clamped_to_the_cap_on_infant_ready_to_eat_food(
    api: ApiClient,
) -> None:
    """Severity 5 x probability 5 x 1.4 x 1.15 overshoots the cap and is clamped.

    "The resulting product is clamped so that anything below 1.00 becomes 1.00
    and anything above 25.00 becomes 25.00, and the clamped value is then rounded
    half up to two decimal places to give `risk_score`." The exposure multiplier
    is "1.4 for `INFANT`" and the ready-to-eat penalty is 1.15 for a biological
    hazard, so the unclamped product is well past the ceiling.

    Design: Difficulty/combinatorial_formula/hazard_risk_score_nonlinear_clamp_on_infant_ready_to_eat_food
    """
    qi_a, _pair, analysis = _infant_draft_analysis(api)

    response = api.create_hazard(
        analysis["id"], CRONOBACTER, make_qualified_individual_headers(qi_a["id"])
    )

    hazard = validate_success(response, 201)
    assert _cents(hazard["risk_score"]) == 25.00
    assert hazard["requires_control"] is True


def test_clamped_hazard_rolls_up_into_the_analysis_totals(api: ApiClient) -> None:
    """The clamped value, not the raw product, is what the analysis sums.

    "Writing a hazard recomputes its analysis's `hazard_count` as the number of
    hazard rows, its `significant_hazard_count` as the number of those rows whose
    `requires_control` is true, and its `risk_total`."

    Design: Difficulty/combinatorial_formula/hazard_risk_score_nonlinear_clamp_on_infant_ready_to_eat_food
    """
    qi_a, _pair, analysis = _infant_draft_analysis(api)

    fx.add_hazard(api, analysis["id"], qi_a["id"], **CRONOBACTER)

    rolled_up = fx.get_analysis(api, analysis["id"])
    assert _cents(rolled_up["risk_total"]) == 25.00
    assert rolled_up["hazard_count"] == 1
    assert rolled_up["significant_hazard_count"] == 1


# --- Immunocompromised raw commodity: three hazards, three roundings --------
LISTERIA_ON_RIND = dict(
    hazard_type="BIOLOGICAL",
    hazard_name="Listeria on rind",
    severity=1,
    probability=3,
    control_owner="FOREIGN_SUPPLIER",
)
POST_HARVEST_FUNGICIDE = dict(
    hazard_type="CHEMICAL_INCL_RADIOLOGICAL",
    hazard_name="Post-harvest fungicide",
    severity=1,
    probability=4,
    control_owner="SUPPLIER_OF_SUPPLIER",
)
GLASS_FRAGMENTS = dict(
    hazard_type="PHYSICAL",
    hazard_name="Glass fragments from field bins",
    severity=3,
    probability=4,
    control_owner="SUPPLIER_OF_SUPPLIER",
)


def _cantaloupe_analysis_with_two_hazards(api: ApiClient):
    """A raw, ready-to-eat, immunocompromised-consumer food with two hazards filed."""
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(api, importer["id"])
    food = fx.create_food(
        api,
        importer["id"],
        food_name="Fresh cantaloupe",
        fda_product_code="22-CAN-03",
        is_raw_agricultural_commodity=True,
        intended_consumer_group="IMMUNOCOMPROMISED",
        ready_to_eat=True,
    )
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    analysis = fx.create_hazard_analysis(
        api,
        pair["id"],
        qi_a["id"],
        methodology_note="Melon hazard identification for an immunocompromised consumer group",
    )
    first = fx.add_hazard(api, analysis["id"], qi_a["id"], **LISTERIA_ON_RIND)
    second = fx.add_hazard(api, analysis["id"], qi_a["id"], **POST_HARVEST_FUNGICIDE)
    return qi_a, analysis, first, second


def test_each_hazard_score_is_rounded_half_up_before_it_is_stored(
    api: ApiClient,
) -> None:
    """Raw products 4.3125, 4.675 and 14.025 round half up, away from zero.

    "Rounding half up means a digit sequence exactly at the midpoint rounds away
    from zero: 12.345 becomes 12.35." The relief of 0.85 "when the food's
    `is_raw_agricultural_commodity` is true *and* the `hazard_type` is not
    `BIOLOGICAL`" and the 1.15 penalty for the biological hazard never both
    apply to one row.

    Design: Difficulty/combinatorial_formula/hazard_analysis_risk_total_rounds_per_hazard_then_sums
    """
    qi_a, analysis, first, second = _cantaloupe_analysis_with_two_hazards(api)

    response = api.create_hazard(
        analysis["id"], GLASS_FRAGMENTS, make_qualified_individual_headers(qi_a["id"])
    )

    third = validate_success(response, 201)
    assert _cents(first["risk_score"]) == 4.31
    assert _cents(second["risk_score"]) == 4.68
    assert _cents(third["risk_score"]) == 14.03
    assert first["requires_control"] is False
    assert second["requires_control"] is False
    assert third["requires_control"] is True


def test_analysis_risk_total_sums_the_rounded_hazard_scores(api: ApiClient) -> None:
    """The total is 23.02, the round-then-sum answer, not the 23.01 alternative.

    "Because each `risk_score` was already rounded to two decimal places when its
    hazard was written, this is a round-then-sum: the already-rounded per-hazard
    values are added, and the sum is rounded. Summing the unrounded products and
    rounding once at the end produces a different total and is not the specified
    behaviour."

    Design: Difficulty/combinatorial_formula/hazard_analysis_risk_total_rounds_per_hazard_then_sums
    """
    qi_a, analysis, _first, _second = _cantaloupe_analysis_with_two_hazards(api)

    fx.add_hazard(api, analysis["id"], qi_a["id"], **GLASS_FRAGMENTS)

    rolled_up = fx.get_analysis(api, analysis["id"])
    assert _cents(rolled_up["risk_total"]) == 23.02
    assert _cents(rolled_up["risk_total"]) != 23.01


# --- Warning-letter supplier: the tier is fixed before the relief ----------
def _warning_letter_pair_with_draft_analysis(api: ApiClient):
    """A never-evaluated warning-letter supplier and one controlled hazard on file."""
    fx.set_clock(api, fx.CLOCK_BASE)
    importer = fx.create_importer(api)
    qi_a = fx.create_qualified_individual(api, importer["id"])
    supplier = fx.create_supplier(
        api,
        importer["id"],
        approve_by_qi_id=None,
        name="Andes Frutas SAC",
        facility_registration_number="FRN-PE-77002",
        regulatory_compliance_status="WARNING_LETTER",
    )
    food = fx.create_food(api, importer["id"])
    pair = fx.create_pair(api, importer["id"], supplier["id"], food["id"], qi_a["id"])
    analysis = fx.create_hazard_analysis(
        api,
        pair["id"],
        qi_a["id"],
        methodology_note="Single controlled biological hazard for this frozen fruit line",
    )
    hazard = fx.add_hazard(api, analysis["id"], qi_a["id"], **fx.HAZARD_LISTERIA)
    return qi_a, pair, analysis, hazard


def test_risk_tier_comes_from_gross_risk_and_survives_the_relief(api: ApiClient) -> None:
    """Gross 19.80 fixes MODERATE; the 4.00 relief drops the composite below 18.00.

    "**Step two** fixes `risk_tier` from the gross risk and from nothing else:
    `HIGH` when gross risk is at or above 40.00, otherwise `MODERATE` when it is
    at or above 18.00, otherwise `LOW`." The warning-letter penalty is 6.00 and
    the relief base for a MODERATE tier is 4.00 at a full relief factor.

    Design: Difficulty/combinatorial_formula/pair_risk_tier_fixed_before_relief_keeps_moderate_frequency
    """
    qi_a, pair, analysis, hazard = _warning_letter_pair_with_draft_analysis(api)

    response = api.post_hazard_analysis_approval(
        analysis["id"],
        {"approval_note": "Hazard analysis approved for the warning-letter supplier"},
        make_qualified_individual_headers(qi_a["id"]),
    )

    validate_success(response)
    assert_money(hazard["risk_score"], 13.80, "risk_score")
    approved_pair = fx.get_pair(api, pair["id"])
    assert approved_pair["risk_tier"] == "MODERATE"
    assert_money(approved_pair["composite_hazard_risk"], 15.80, "composite_hazard_risk")


def test_plan_requirements_read_off_the_pre_relief_tier(api: ApiClient) -> None:
    """The required frequency still reflects MODERATE, not a re-derived LOW.

    "**Step five** reads the plan requirements off the tier fixed in step two and
    never re-derives that tier from the composite: `required_annual_frequency` is
    1 for a `LOW` tier, 2 for `MODERATE`, and 4 for `HIGH`; and
    `required_coverage` is `composite_hazard_risk` multiplied by 1.5, rounded half
    up to two decimal places."

    Design: Difficulty/combinatorial_formula/pair_risk_tier_fixed_before_relief_keeps_moderate_frequency
    """
    qi_a, pair, analysis, _hazard = _warning_letter_pair_with_draft_analysis(api)

    fx.approve_analysis(
        api,
        analysis["id"],
        qi_a["id"],
        approval_note="Hazard analysis approved for the warning-letter supplier",
    )

    approved_pair = fx.get_pair(api, pair["id"])
    assert approved_pair["required_annual_frequency"] == 2
    assert_money(approved_pair["required_coverage"], 23.70, "required_coverage")
    assert approved_pair["uncontrolled_significant_hazard_count"] == 1
    assert approved_pair["verification_status"] == "HAZARD_ANALYZED"
