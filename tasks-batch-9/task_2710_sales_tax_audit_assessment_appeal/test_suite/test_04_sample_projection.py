"""Projecting an examined sample onto the population under each methodology."""
from test_helpers import (
    draw_sample_unit,
    project_sample,
    read_audit,
    setup_agreed_methodology,
    stratum,
)

SCOPE_START = "2023-01-01"
SCOPE_END = "2024-12-31"
BIG_STRATA = [
    stratum("2023-01-01", "2024-01-01", 500_000_000, 1_000),
    stratum("2024-01-01", "2025-01-01", 700_000_000, 1_400),
]
POPULATION_BASE_CENTS = 1_200_000_000
POPULATION_UNITS = 2_400

# The two examined invoices: 81,250 cents of error over a 2,200,000-cent base.
FIRST_UNIT = {
    "stratum_index": 0,
    "invoice_date": "2023-03-15",
    "invoice_amount_cents": 1_000_000,
    "invoice_reference": "A-1",
    "error_class": "UNREPORTED_TAXABLE_SALE",
    "declared_error_amount_cents": 62_500,
}
SECOND_UNIT = {
    "stratum_index": 1,
    "invoice_date": "2024-05-20",
    "invoice_amount_cents": 1_200_000,
    "invoice_reference": "A-2",
    "error_class": "UNREPORTED_TAXABLE_SALE",
    "declared_error_amount_cents": 18_750,
}

ERROR_RATE_BP = 369
RATIO_DEFICIENCY_CENTS = 44_280_000
UNROUNDED_RATIO_DEFICIENCY_CENTS = 44_318_182
MEAN_DEFICIENCY_CENTS = 97_500_000


def _projected_audit(methodology):
    """A two-stratum FIELD audit carrying the same two examined invoices."""
    ctx = setup_agreed_methodology(
        methodology=methodology,
        confidence_level_bp=9_500,
        minimum_sample_size=2,
        strata=BIG_STRATA,
        scope_period_start=SCOPE_START,
        scope_period_end=SCOPE_END,
        audit_type="FIELD",
    )
    draw_sample_unit(ctx["agreement"]["id"], **FIRST_UNIT)
    draw_sample_unit(ctx["agreement"]["id"], **SECOND_UNIT)
    project_sample(ctx["audit"]["id"])
    ctx["audit"] = read_audit(ctx["audit"]["id"])
    return ctx


def test_the_two_methodologies_read_different_halves_of_the_same_population():
    """Ratio estimation consumes the dollar base; mean per unit consumes the count.

    PRD 3.4: "Under `MEAN_PER_UNIT`, the mean error per examined unit is computed
    first — the error sum divided by the examined count, rounded half up to whole
    cents — and that rounded mean is then multiplied by the agreement's
    `population_unit_count` to give the projected population deficiency; the
    population's dollar base plays no part."
    PRD 3.4: "Under `RATIO_ESTIMATION`, the error rate is computed first — the error
    sum multiplied by 10,000, divided by the base sum, rounded half up to a whole
    basis point — and that rounded rate is then applied to the agreement's
    `population_base_amount_cents`, multiplying and dividing by 10,000 and rounding
    half up once more; the population's unit count plays no part."

    Design: Difficulty/dual_variant_calc/projection_variant_ratio_vs_mean_same_sample
    """
    ratio_audit = _projected_audit("RATIO_ESTIMATION")["audit"]
    mean_audit = _projected_audit("MEAN_PER_UNIT")["audit"]

    assert ratio_audit["projected_deficiency_cents"] == RATIO_DEFICIENCY_CENTS
    assert mean_audit["projected_deficiency_cents"] == MEAN_DEFICIENCY_CENTS
    assert ratio_audit["projected_deficiency_cents"] != mean_audit[
        "projected_deficiency_cents"
    ]


def test_both_methodologies_report_the_same_sample_error_rate_and_count():
    """The sample statistics are identical; only the projection arithmetic differs.

    PRD 3.4: "Either way the audit records the results: `sample_error_rate_bp` is
    the error sum multiplied by 10,000, divided by the base sum and rounded half up
    to a whole basis point — computed and reported under both methodologies, even
    though only ratio estimation uses it arithmetically — `projected_deficiency_cents`
    holds the projected population deficiency, `examined_unit_count` holds the
    examined count, `projection_method` records the methodology just applied, and
    `projection_status` becomes `CURRENT`."

    Design: Difficulty/dual_variant_calc/projection_variant_ratio_vs_mean_same_sample
    """
    ratio_audit = _projected_audit("RATIO_ESTIMATION")["audit"]
    mean_audit = _projected_audit("MEAN_PER_UNIT")["audit"]

    assert ratio_audit["sample_error_rate_bp"] == ERROR_RATE_BP
    assert mean_audit["sample_error_rate_bp"] == ERROR_RATE_BP
    assert ratio_audit["examined_unit_count"] == 2
    assert mean_audit["examined_unit_count"] == 2
    assert ratio_audit["projection_method"] == "RATIO_ESTIMATION"
    assert mean_audit["projection_method"] == "MEAN_PER_UNIT"


def test_the_error_rate_is_a_whole_basis_point_before_the_population_is_touched():
    """81,250 over 2,200,000 rounds to 369 basis points, and that is what is stored.

    PRD 3.4: "Either way the audit records the results: `sample_error_rate_bp` is
    the error sum multiplied by 10,000, divided by the base sum and rounded half up
    to a whole basis point — computed and reported under both methodologies, even
    though only ratio estimation uses it arithmetically — `projected_deficiency_cents`
    holds the projected population deficiency, `examined_unit_count` holds the
    examined count, `projection_method` records the methodology just applied, and
    `projection_status` becomes `CURRENT`."

    Design: Difficulty/combinatorial_formula/projection_rate_rounded_to_whole_bp_before_population_multiply
    """
    audit = _projected_audit("RATIO_ESTIMATION")["audit"]

    assert audit["sample_error_rate_bp"] == ERROR_RATE_BP
    assert audit["projection_status"] == "CURRENT"
    assert audit["examined_unit_count"] == 2


def test_rounding_the_rate_last_would_overstate_the_population_deficiency():
    """The rounded rate applied to the base gives 44,280,000, not 44,318,182.

    PRD 3.4: "The order is mandatory in both branches. Multiplying an unrounded
    ratio by the population base and rounding only at the end is a different number
    and is not an acceptable implementation of ratio estimation."

    Design: Difficulty/combinatorial_formula/projection_rate_rounded_to_whole_bp_before_population_multiply
    """
    audit = _projected_audit("RATIO_ESTIMATION")["audit"]

    assert audit["projected_deficiency_cents"] == RATIO_DEFICIENCY_CENTS
    assert audit["projected_deficiency_cents"] != UNROUNDED_RATIO_DEFICIENCY_CENTS
    # The stored whole-basis-point rate applied to the population base.
    assert (
        audit["projected_deficiency_cents"]
        == audit["sample_error_rate_bp"] * POPULATION_BASE_CENTS // 10_000
    )
