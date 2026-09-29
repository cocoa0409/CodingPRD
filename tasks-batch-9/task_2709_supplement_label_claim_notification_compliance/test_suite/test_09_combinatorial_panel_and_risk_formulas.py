"""Two formulas whose evaluation order is pinned and observable.

Daily Value coverage rounds each printed line first and only then sums the whole
numbers, and the compliance risk index chooses its escalation tier from the
pre-surcharge base rather than from the running total that already includes it.
Both orders are separated by a single stored integer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_panel_computed,
    assert_posture,
    assert_risk_index,
)
from test_helpers.constants import (
    AER_TRIAGED_NONSERIOUS,
    AER_TRIAGED_SERIOUS,
    OUTCOME_DEATH,
    OUTCOME_HOSPITALIZATION,
    OUTCOME_OTHER,
    PANEL_STATUS_VALIDATED,
    POSTURE_OPEN,
    REPORTER_CONSUMER,
    REPORTER_HEALTHCARE_PROVIDER,
    WARNING_PEDIATRIC,
)
from test_helpers.fixtures import (
    make_aer,
    make_draft_panel,
    make_grandfathered_ingredient,
    make_line,
    make_product,
)

# Three ingredients whose reference intakes are 100, 400 and 800 mg, dosed so
# that every line lands on a raw 12.5 percent of Daily Value.
TWELVE_AND_A_HALF_PERCENT_LINES = [
    {
        "ingredient_name": "Zinc Gluconate",
        "ingredient_class": "MINERAL",
        "daily_intake_mg": 12.5,
        "rdi_mg": 100,
        "amount_per_serving_mg": 12.5,
        "panel_position": 1,
    },
    {
        "ingredient_name": "Riboflavin",
        "ingredient_class": "VITAMIN",
        "daily_intake_mg": 50,
        "rdi_mg": 400,
        "amount_per_serving_mg": 50,
        "panel_position": 2,
    },
    {
        "ingredient_name": "Pantothenic Acid",
        "ingredient_class": "VITAMIN",
        "daily_intake_mg": 100,
        "rdi_mg": 800,
        "amount_per_serving_mg": 100,
        "panel_position": 3,
    },
]


def _tri_blend_with_three_half_percent_lines(api, specialist_headers):
    """A DRAFT product with three ACTIVE lines, each printing 13 percent."""
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Tri-Blend Complex",
        net_quantity_g=120,
        servings_per_container=60,
    )
    lines = []
    for spec in TWELVE_AND_A_HALF_PERCENT_LINES:
        ingredient = make_grandfathered_ingredient(
            api,
            specialist_headers,
            ingredient_name=spec["ingredient_name"],
            ingredient_class=spec["ingredient_class"],
            daily_intake_mg=spec["daily_intake_mg"],
            rdi_mg=spec["rdi_mg"],
        )
        lines.append(
            make_line(
                api,
                product["id"],
                ingredient["id"],
                specialist_headers,
                amount_per_serving_mg=spec["amount_per_serving_mg"],
                panel_position=spec["panel_position"],
            )
        )
    return product, lines


def _three_reports_on_one_product(api, specialist_headers, quality_headers):
    """One bare product carrying two serious reports and one non-serious one."""
    product = make_product(
        api,
        specialist_headers,
        brand_name="NutraCore",
        product_name="Immune Boost",
        net_quantity_g=60,
        servings_per_container=30,
    )
    hospitalization = make_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-08-03",
        narrative="Hospitalized after three days of use",
        outcome_codes=[OUTCOME_HOSPITALIZATION],
    )
    fatality = make_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_HEALTHCARE_PROVIDER,
        received_date="2026-08-03",
        narrative="Fatal outcome reported by treating physician",
        outcome_codes=[OUTCOME_DEATH],
    )
    minor = make_aer(
        api,
        product["id"],
        quality_headers,
        reporter_type=REPORTER_CONSUMER,
        received_date="2026-08-03",
        narrative="Transient rash, resolved without treatment",
        outcome_codes=[OUTCOME_OTHER],
    )
    return product, hospitalization, fatality, minor


def test_each_line_rounds_its_own_percentage_before_the_panel_adds_them_up(
    api, specialist_headers
):
    """Three raw 12.5 percent lines sum to 39, not to 38.

    PRD §3.3: "if it is greater than zero but less than 0.5, the printed value is 1
    rather than 0, because a trace contribution is never printed as zero; otherwise
    it is rounded half up to the nearest whole percent, so a raw 12.5 prints as 13."
    PRD §3.5 pins the summation order: "Each line's percentage has **already** been
    rounded to a whole number by the per-line rule of §3.3, and it is those whole
    numbers that are added together; summing the unrounded ratios and rounding the
    total once is explicitly not the rule".

    Design: Difficulty/combinatorial_formula/panel_dv_coverage_round_each_line_then_sum
    """
    product, lines = _tri_blend_with_three_half_percent_lines(api, specialist_headers)
    for line in lines:
        assert line["dv_established"] is True
        assert line["percent_dv_declared"] == 13

    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=60,
        declared_warning_codes=[WARNING_PEDIATRIC],
    )
    assert panel["panel_total_dv_coverage_pct"] is None

    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_total_dv_coverage_pct"] == 39
    assert validated["panel_total_dv_coverage_pct"] != 38


def test_validation_persists_the_coverage_beside_the_line_budget(
    api, specialist_headers
):
    """All four computed panel figures land on the row in one call.

    PRD §3.5: "When every check passes, the panel persists
    ``required_warning_codes``, ``panel_lines_required``, ``panel_lines_allowed`` and
    ``panel_total_dv_coverage_pct``, moves ``DRAFT → VALIDATED``, and stamps
    ``validated_at`` from the logical clock." The same section pins the allowance: "A
    ``STANDARD`` panel takes the product's ``net_quantity_g`` divided by 10 with the
    fraction discarded, adds 12 to that whole number, caps the result at 40, and then
    raises it to 20 if it fell below".

    Design: Difficulty/combinatorial_formula/panel_dv_coverage_round_each_line_then_sum
    """
    product, _lines = _tri_blend_with_three_half_percent_lines(api, specialist_headers)
    panel = make_draft_panel(
        api,
        product["id"],
        specialist_headers,
        servings_per_container_declared=60,
        declared_warning_codes=[WARNING_PEDIATRIC],
    )

    validated = validate_success(
        api.validate_label_panel(panel["id"], specialist_headers), 200
    )
    assert validated["panel_status"] == PANEL_STATUS_VALIDATED
    assert validated["validated_at"] is not None
    assert_panel_computed(
        validated,
        required_warning_codes=[WARNING_PEDIATRIC],
        panel_lines_required=8,
        panel_lines_allowed=24,
        panel_total_dv_coverage_pct=39,
    )


def test_the_escalation_tier_is_selected_from_the_base_before_the_surcharge(
    api, specialist_headers, quality_headers
):
    """A base of 56 yields an index of 61, and never of 68.

    PRD §2.9: "First a **base** is formed: start from a floor of 10, add 20 for each
    serious adverse event, add 6 for each non-serious adverse event, add 15 for each
    late agency filing, and add 8 for each rejected certificate of analysis. Second,
    an **escalation surcharge** is chosen *from the base alone* — the pre-surcharge
    figure, never from the running total that already includes it." The section names
    the wrong answer outright: "a base of 56 yields an index of 61 under the pinned
    order, but 68 under the other."

    Design: Difficulty/combinatorial_formula/risk_index_escalation_tier_selected_from_pre_surcharge_base
    """
    product, hospitalization, fatality, minor = _three_reports_on_one_product(
        api, specialist_headers, quality_headers
    )
    assert_risk_index(
        validate_success(api.get_product(product["id"], specialist_headers), 200), 10
    )

    validate_success(
        api.triage_adverse_event_report(hospitalization["id"], quality_headers), 200
    )
    after_one = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert_risk_index(after_one, 35)

    validate_success(
        api.triage_adverse_event_report(fatality["id"], quality_headers), 200
    )
    after_two = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert_risk_index(after_two, 55)

    validate_success(api.triage_adverse_event_report(minor["id"], quality_headers), 200)
    after_three = validate_success(
        api.get_product(product["id"], specialist_headers), 200
    )
    assert_risk_index(after_three, 61)
    assert after_three["compliance_risk_index"] != 68


def test_a_sixty_one_point_index_leaves_the_posture_open_and_the_label_unflagged(
    api, specialist_headers, quality_headers
):
    """The two serious reports and one non-serious one stay below the threshold.

    PRD §2.9: "Otherwise the posture is ``RESTRICTED`` if the
    ``compliance_risk_index`` is 70 or more, **or** any supplier in the derived
    supplier set has ``qualification_status`` equal to ``PROBATION``. Otherwise the
    posture is ``OPEN``." The flag follows the posture: "The boolean
    ``requires_label_revision`` is simply the statement that the posture is not
    ``OPEN``: it is set to true whenever the posture leaves ``OPEN`` and cleared to
    false only when the posture returns to ``OPEN``."

    Design: Difficulty/combinatorial_formula/risk_index_escalation_tier_selected_from_pre_surcharge_base
    """
    product, hospitalization, fatality, minor = _three_reports_on_one_product(
        api, specialist_headers, quality_headers
    )
    first = validate_success(
        api.triage_adverse_event_report(hospitalization["id"], quality_headers), 200
    )
    assert first["aer_status"] == AER_TRIAGED_SERIOUS
    validate_success(
        api.triage_adverse_event_report(fatality["id"], quality_headers), 200
    )
    third = validate_success(
        api.triage_adverse_event_report(minor["id"], quality_headers), 200
    )
    assert third["aer_status"] == AER_TRIAGED_NONSERIOUS
    assert third["submission_due_date"] is None

    settled = validate_success(api.get_product(product["id"], specialist_headers), 200)
    assert settled["serious_ae_count"] == 2
    assert settled["nonserious_ae_count"] == 1
    assert settled["late_notification_count"] == 0
    assert settled["rejected_coa_count"] == 0
    assert_risk_index(settled, 61)
    assert_posture(settled, POSTURE_OPEN)
    assert settled["requires_label_revision"] is False
