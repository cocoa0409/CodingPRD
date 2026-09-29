"""Two variants of one formula: priority scoring and the assurance requirement."""

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_fields, assert_score
from test_helpers.constants import (
    CANONICAL_REMEDIATION_SCORE,
    CANONICAL_SCREENING_SCORE,
)


def test_one_well_row_yields_two_different_priority_scores(api):
    """One well row is scored twice and the two numbers diverge.

    Inputs methane_scfd 250, groundwater_depth_ft 40, population_within_1000ft 8 and
    surface_disturbance_acres 2.0 give a screening score of 59.90 and a remediation
    score of 81.00 on the very same row, because the remediation variant forces the
    population component to full scale and then weights it at 0.40.

    PRD: "Because population carries the heaviest weight here and the override can
    lift it to full scale, identical well inputs routinely yield a different number
    from the screening variant, and that is the intent".

    Design: Difficulty/dual_variant_calc/well_screening_variant_vs_remediation_variant_diverge_on_one_row
    """
    operator = fx.make_operator(
        api, name="Permian Legacy LLC", region_code="TX",
        financial_assurance_tier="BLANKET", bond_amount_cents=5000000,
    )
    well = fx.make_well(api, operator["id"], total_depth_ft=4200, spud_year=1974)

    assert_score(well["screening_score"], CANONICAL_SCREENING_SCORE, "screening_score")
    assert_score(
        well["remediation_score"], CANONICAL_REMEDIATION_SCORE, "remediation_score"
    )
    assert well["screening_score"] != well["remediation_score"], (
        "the two variants collapsed onto one number: %r" % (well,)
    )
    assert_fields(well, status="PRODUCING")

    stored = fx.read_well(api, well["id"])
    assert_score(stored["screening_score"], CANONICAL_SCREENING_SCORE, "screening_score")
    assert_score(
        stored["remediation_score"], CANONICAL_REMEDIATION_SCORE, "remediation_score"
    )


def test_population_override_fires_at_five_residents_only_in_the_remediation_variant(api):
    """The divergence between the two variants is driven by the population override.

    At four residents no override applies and the row scores 56.70 screening against
    47.40 remediation; at five residents the remediation variant jumps to 81.00 while
    the screening variant only creeps to 57.50, and at eight residents the screening
    variant reaches 59.90 with remediation still pinned at 81.00.

    PRD: "when the well has 5 or more residents within one thousand feet, the
    population component used by this variant is forced to 100 outright, regardless
    of what the multiply-and-cap rule produced; with fewer than 5 residents the
    ordinary population component is used unchanged".

    Design: Difficulty/dual_variant_calc/well_screening_variant_vs_remediation_variant_diverge_on_one_row
    """
    operator = fx.make_operator(api, region_code="TX")

    below = fx.make_well(api, operator["id"], population_within_1000ft=4)
    assert_score(below["screening_score"], 56.70, "screening_score at 4 residents")
    assert_score(below["remediation_score"], 47.40, "remediation_score at 4 residents")

    at_threshold = fx.make_well(api, operator["id"], population_within_1000ft=5)
    assert_score(at_threshold["screening_score"], 57.50, "screening_score at 5 residents")
    assert_score(
        at_threshold["remediation_score"], 81.00, "remediation_score at 5 residents"
    )

    above = fx.make_well(api, operator["id"], population_within_1000ft=8)
    assert_score(above["screening_score"], 59.90, "screening_score at 8 residents")
    assert_score(above["remediation_score"], 81.00, "remediation_score at 8 residents")

    assert at_threshold["remediation_score"] == above["remediation_score"], (
        "the override should pin remediation at full population scale for both rows"
    )
    assert below["remediation_score"] < below["screening_score"], (
        "without the override the remediation weighting is the lower of the two"
    )


def test_identical_inventories_require_different_bonds_under_the_two_tiers(api):
    """The same two wells cost more assurance under BLANKET than under INDIVIDUAL.

    A 2500 ft well and an 8000 ft well sum to 250000 + 1500000 = 1750000 under
    BLANKET, but the deepest tier is clipped to 1000000 before summing under
    INDIVIDUAL, giving 1250000. Both operators posted 5000000, so both stay ACTIVE.

    PRD: "an identical inventory yields a strictly lower requirement under
    `INDIVIDUAL` than under `BLANKET` whenever any well falls in the deepest tier".

    Design: Difficulty/dual_variant_calc/assurance_blanket_cap_after_sum_vs_individual_cap_before_sum
    """
    blanket = fx.make_operator(
        api, name="Blanket Bond Operating", region_code="TX",
        financial_assurance_tier="BLANKET", bond_amount_cents=5000000,
    )
    individual = fx.make_operator(
        api, name="Individual Bond Operating", region_code="TX",
        financial_assurance_tier="INDIVIDUAL", bond_amount_cents=5000000,
    )

    deep = {
        "spud_year": 1969,
        "total_depth_ft": 8000,
        "casing_strings": 3,
        "methane_scfd": 310,
        "groundwater_depth_ft": 180,
        "population_within_1000ft": 3,
        "surface_disturbance_acres": 1.25,
    }
    fx.make_well(api, blanket["id"], spud_year=1981, total_depth_ft=2500)
    fx.make_well(api, individual["id"], spud_year=1981, total_depth_ft=2500)
    fx.make_well(api, blanket["id"], **deep)
    deep_well = fx.make_well(api, individual["id"], **deep)

    blanket_row = fx.read_operator(api, blanket["id"])
    individual_row = fx.read_operator(api, individual["id"])

    assert_cents(blanket_row["required_bond_cents"], 1750000, "BLANKET requirement")
    assert_cents(individual_row["required_bond_cents"], 1250000, "INDIVIDUAL requirement")
    assert_fields(blanket_row, active_well_count=2, status="ACTIVE")
    assert_fields(individual_row, active_well_count=2, status="ACTIVE")

    assert_score(deep_well["screening_score"], 50.35, "deep well screening_score")
    assert_score(deep_well["remediation_score"], 39.70, "deep well remediation_score")


def test_the_deepest_tier_is_clipped_before_summing_only_under_the_individual_tier(api):
    """A single 8000 ft well already separates the two tiers.

    Under BLANKET the well contributes its full 1500000 because the 25000000 cap is
    applied to the sum afterwards; under INDIVIDUAL the same well contributes only
    1000000 because the per-well cap is applied first. Adding a second shallow well
    then lifts the two requirements to 1750000 and 1250000.

    PRD: "Under the `INDIVIDUAL` variant each well's base amount is first capped at
    1000000 cents ($10,000) and only then are the capped amounts summed, with no
    blanket cap at all".

    Design: Difficulty/dual_variant_calc/assurance_blanket_cap_after_sum_vs_individual_cap_before_sum
    """
    blanket = fx.make_operator(
        api, region_code="TX", financial_assurance_tier="BLANKET",
        bond_amount_cents=5000000,
    )
    individual = fx.make_operator(
        api, region_code="TX", financial_assurance_tier="INDIVIDUAL",
        bond_amount_cents=5000000,
    )
    deep = {"spud_year": 1969, "total_depth_ft": 8000, "casing_strings": 3}

    fx.make_well(api, blanket["id"], **deep)
    fx.make_well(api, individual["id"], **deep)

    assert_cents(
        fx.read_operator(api, blanket["id"])["required_bond_cents"],
        1500000,
        "BLANKET requirement for one deep well",
    )
    assert_cents(
        fx.read_operator(api, individual["id"])["required_bond_cents"],
        1000000,
        "INDIVIDUAL requirement for one deep well",
    )

    fx.make_well(api, blanket["id"], total_depth_ft=2500)
    fx.make_well(api, individual["id"], total_depth_ft=2500)

    assert_cents(
        fx.read_operator(api, blanket["id"])["required_bond_cents"],
        1750000,
        "BLANKET requirement for both wells",
    )
    assert_cents(
        fx.read_operator(api, individual["id"])["required_bond_cents"],
        1250000,
        "INDIVIDUAL requirement for both wells",
    )
