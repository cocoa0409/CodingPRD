"""Fiscal impact projection, territory qualification scoring and tax-roll
proration for the Municipal Annexation And Boundary Adjustment API.

These tests exercise the arithmetic the statute pins by value: the two
service-cost methodologies a statute may mandate, the two bases on which written
objections are weighed, the four-term territory qualification score, the
overhead tier keyed to the pre-overhead base cost, and the per-parcel-first
rounding order of the municipal levy proration.
"""
from decimal import Decimal

from test_helpers import (
    assertions,
    constants,
    factories,
    fiscal_analyst_headers,
    fixtures,
    get_success_data,
)

# Territory used by every fiscal scenario below: four parcels summing to
# 100,000,000 cents of assessed value, which is what makes the two methodology
# variants comparable on byte-identical territory.
_FISCAL_PARCEL_VALUES_CENTS = [40000000, 30000000, 20000000, 10000000]

# The marginal inputs the MARGINAL_COST statute prices its extension from; their
# plain sum (2,400,000) deliberately differs from the AVERAGE_COST base cost the
# same population produces (2,000,000).
_MARGINAL_POLICE_COST_CENTS = 900000
_MARGINAL_FIRE_COST_CENTS = 800000
_MARGINAL_WATER_COST_CENTS = 400000
_MARGINAL_SEWER_COST_CENTS = 300000

_PROJECTED_POPULATION = 100

# A hearing timeline whose protest window closes early enough in October that
# the boundary change can be made effective on 2026-10-11, leaving 82 days of
# the 12-31 fiscal year to prorate.
_OCTOBER_HEARING_START_AT = "2026-09-10T18:00:00Z"
_OCTOBER_HEARING_END_AT = "2026-09-10T20:00:00Z"
_CLOCK_AFTER_OCTOBER_PROTEST = "2026-10-11T09:00:00Z"
_OCTOBER_EFFECTIVE_DATE = "2026-10-11"

# Chosen so that each parcel's annual levy (36,573 cents) prorates to a value
# with a fractional part of exactly .4 cents, which is where the per-parcel and
# sum-then-round orders diverge.
_PRORATION_PARCEL_ASSESSED_CENTS = 3657300


def _matched_jurisdiction(statute_overrides=None, municipality_overrides=None):
    """A statute profile payload and a municipality payload whose `state_code`
    values agree, as §3.1 requires of a city registered against a profile."""
    statute = dict(statute_overrides or {})
    statute.setdefault("state_code", factories.unique_state_code())
    municipality = dict(municipality_overrides or {})
    municipality["state_code"] = statute["state_code"]
    return statute, municipality


def _draft_territory(api, statute_overrides=None, case_overrides=None,
                     parcel_values_cents=None, owners_per_parcel=True):
    """A DRAFT case whose territory aggregates are already refreshed, which is
    all the fiscal impact analysis reads."""
    statute, municipality = _matched_jurisdiction(statute_overrides)
    return fixtures.setup_draft_case(
        api,
        statute=statute,
        municipality=municipality,
        case=case_overrides,
        parcel_values_cents=parcel_values_cents or _FISCAL_PARCEL_VALUES_CENTS,
        owners_per_parcel=owners_per_parcel,
    )


def _noticed_case_on_protest_basis(api, protest_basis):
    """A certified case with an adopted plan and published notice, under a
    statute that weighs objections on `protest_basis` against a 20.00 percent
    threshold."""
    statute, municipality = _matched_jurisdiction(
        {"protest_basis": protest_basis, "protest_threshold_pct": 20.00}
    )
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=_FISCAL_PARCEL_VALUES_CENTS,
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    return ctx


def _hold_and_object(api, ctx):
    """Hold the noticed hearing and let the owner of the least valuable parcel —
    one owner of four, 10,000,000 cents of 100,000,000 — object in full."""
    fixtures.setup_hearing_held(api, ctx)
    fixtures.file_protest(api, ctx, parcel_index=3)


def _case_with_posted_tax_roll(api):
    """Carry a case with four equally assessed parcels all the way to a posted
    tax roll with an effective date of 2026-10-11."""
    statute, municipality = _matched_jurisdiction()
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=[_PRORATION_PARCEL_ASSESSED_CENTS] * 4,
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(
        api,
        ctx,
        scheduled_start_at=_OCTOBER_HEARING_START_AT,
        scheduled_end_at=_OCTOBER_HEARING_END_AT,
    )
    fixtures.setup_hearing_held(api, ctx, clock_at_hearing=_OCTOBER_HEARING_START_AT)
    fixtures.close_protest_period(
        api, ctx, clock_after_window=_CLOCK_AFTER_OCTOBER_PROTEST
    )
    fixtures.setup_finalized_analysis(api, ctx)
    fixtures.adopt_ordinance(api, ctx)
    fixtures.effectuate(api, ctx, effective_date=_OCTOBER_EFFECTIVE_DATE)
    fixtures.post_tax_roll(api, ctx)
    return ctx


# ==========================================================================
# The two service-cost methodologies a statute may mandate
# ==========================================================================
def test_average_cost_variant_prices_service_from_the_citywide_per_capita_rate(api):
    """PRD §3.4: "Under the `AVERAGE_COST` variant, `base_service_cost_cents`
    is the municipality's `citywide_annual_service_cost_cents` multiplied by
    `projected_population`, divided by `citywide_population`, and rounded half
    up to a whole cent; the four marginal inputs are ignored entirely."

    Design: Difficulty/dual_variant_calc/fiscal_variant_average_vs_marginal_diverge_on_identical_territory
    """
    ctx = _draft_territory(api, statute_overrides={"fiscal_method": "AVERAGE_COST"})
    municipality = ctx["municipality"]
    assert ctx["case"]["territory_assessed_value_cents"] == 100000000

    analysis = fixtures.author_analysis(
        api,
        ctx,
        analysis_method="AVERAGE_COST",
        projected_population=_PROJECTED_POPULATION,
        # Supplied and expected to be ignored: the citywide averages govern here.
        marginal_police_cost_cents=_MARGINAL_POLICE_COST_CENTS,
        marginal_fire_cost_cents=_MARGINAL_FIRE_COST_CENTS,
        marginal_water_cost_cents=_MARGINAL_WATER_COST_CENTS,
        marginal_sewer_cost_cents=_MARGINAL_SEWER_COST_CENTS,
    )

    expected_property_tax = assertions.expected_property_tax_cents(
        100000000, municipality["general_fund_millage_rate"]
    )
    assert expected_property_tax == 1000000
    assert analysis["property_tax_revenue_cents"] == 1000000
    # No utility account exists, so the post-annexation projection is zero.
    assert analysis["projected_utility_revenue_cents"] == 0
    assert analysis["shared_revenue_cents"] == (
        _PROJECTED_POPULATION * constants.DEFAULT_PER_CAPITA_SHARED_REVENUE_CENTS
    )
    assert analysis["shared_revenue_cents"] == 1200000
    assert analysis["gross_annual_revenue_cents"] == 2200000

    expected_base = assertions.expected_average_cost_base_cents(
        municipality["citywide_annual_service_cost_cents"],
        _PROJECTED_POPULATION,
        municipality["citywide_population"],
    )
    assert expected_base == 2000000
    assert analysis["base_service_cost_cents"] == 2000000
    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"],
        assertions.expected_overhead_tier_pct(2000000),
        "overhead_tier_pct",
        places=4,
    )
    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"], 0.12, "overhead_tier_pct", places=4
    )
    assert analysis["administrative_overhead_cents"] == 240000
    assert analysis["projected_annual_service_cost_cents"] == 2240000
    assert analysis["net_annual_impact_cents"] == -40000
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"],
        assertions.expected_deficit_ratio_pct(-40000, 2200000),
        "deficit_ratio_pct",
    )
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"], 1.82, "deficit_ratio_pct"
    )


def test_marginal_cost_variant_prices_service_from_the_four_marginal_inputs(api):
    """PRD §3.4: "Under the `MARGINAL_COST` variant, `base_service_cost_cents`
    is instead the plain sum of `marginal_police_cost_cents`,
    `marginal_fire_cost_cents`, `marginal_water_cost_cents` and
    `marginal_sewer_cost_cents`; the citywide averages are ignored entirely."

    Design: Difficulty/dual_variant_calc/fiscal_variant_average_vs_marginal_diverge_on_identical_territory
    """
    ctx = _draft_territory(api, statute_overrides={"fiscal_method": "MARGINAL_COST"})
    assert ctx["case"]["territory_assessed_value_cents"] == 100000000

    analysis = fixtures.author_analysis(
        api,
        ctx,
        analysis_method="MARGINAL_COST",
        projected_population=_PROJECTED_POPULATION,
        marginal_police_cost_cents=_MARGINAL_POLICE_COST_CENTS,
        marginal_fire_cost_cents=_MARGINAL_FIRE_COST_CENTS,
        marginal_water_cost_cents=_MARGINAL_WATER_COST_CENTS,
        marginal_sewer_cost_cents=_MARGINAL_SEWER_COST_CENTS,
    )

    # The revenue side is untouched by the methodology switch.
    assert analysis["property_tax_revenue_cents"] == 1000000
    assert analysis["gross_annual_revenue_cents"] == 2200000

    expected_base = (
        _MARGINAL_POLICE_COST_CENTS
        + _MARGINAL_FIRE_COST_CENTS
        + _MARGINAL_WATER_COST_CENTS
        + _MARGINAL_SEWER_COST_CENTS
    )
    assert expected_base == 2400000
    assert analysis["base_service_cost_cents"] == 2400000
    # 2,400,000 is not the 2,000,000 the citywide averages would have produced.
    assert analysis["base_service_cost_cents"] != assertions.expected_average_cost_base_cents(
        ctx["municipality"]["citywide_annual_service_cost_cents"],
        _PROJECTED_POPULATION,
        ctx["municipality"]["citywide_population"],
    )
    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"],
        assertions.expected_overhead_tier_pct(2400000),
        "overhead_tier_pct",
        places=4,
    )
    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"], 0.12, "overhead_tier_pct", places=4
    )
    assert analysis["administrative_overhead_cents"] == 288000
    assert analysis["projected_annual_service_cost_cents"] == 2688000
    assert analysis["net_annual_impact_cents"] == -488000
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"],
        assertions.expected_deficit_ratio_pct(-488000, 2200000),
        "deficit_ratio_pct",
    )
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"], 22.18, "deficit_ratio_pct"
    )


def test_identical_territory_yields_a_448000_cent_net_impact_gap_between_fiscal_methods(api):
    """PRD §3.4: "Identical territory and population data therefore produce a
    different base cost under each variant, and — because the overhead tier is
    keyed to the base cost — potentially a different overhead rate, a different
    net impact and a different deficit ratio."

    Design: Difficulty/dual_variant_calc/fiscal_variant_average_vs_marginal_diverge_on_identical_territory
    """
    average_ctx = _draft_territory(
        api, statute_overrides={"fiscal_method": "AVERAGE_COST"}
    )
    marginal_ctx = _draft_territory(
        api, statute_overrides={"fiscal_method": "MARGINAL_COST"}
    )

    # The two territories are byte-identical on every input the projection reads.
    assert (
        average_ctx["case"]["territory_assessed_value_cents"]
        == marginal_ctx["case"]["territory_assessed_value_cents"]
        == 100000000
    )

    average_analysis = fixtures.author_analysis(
        api,
        average_ctx,
        analysis_method="AVERAGE_COST",
        projected_population=_PROJECTED_POPULATION,
    )
    marginal_analysis = fixtures.author_analysis(
        api,
        marginal_ctx,
        analysis_method="MARGINAL_COST",
        projected_population=_PROJECTED_POPULATION,
        marginal_police_cost_cents=_MARGINAL_POLICE_COST_CENTS,
        marginal_fire_cost_cents=_MARGINAL_FIRE_COST_CENTS,
        marginal_water_cost_cents=_MARGINAL_WATER_COST_CENTS,
        marginal_sewer_cost_cents=_MARGINAL_SEWER_COST_CENTS,
    )

    assert (
        average_analysis["gross_annual_revenue_cents"]
        == marginal_analysis["gross_annual_revenue_cents"]
        == 2200000
    )
    assert average_analysis["base_service_cost_cents"] == 2000000
    assert marginal_analysis["base_service_cost_cents"] == 2400000
    assert average_analysis["net_annual_impact_cents"] == -40000
    assert marginal_analysis["net_annual_impact_cents"] == -488000
    assert (
        average_analysis["net_annual_impact_cents"]
        - marginal_analysis["net_annual_impact_cents"]
        == 448000
    )
    # The deficit ratio diverges with it, on identical gross revenue.
    assertions.assert_numeric_equals(
        average_analysis["deficit_ratio_pct"], 1.82, "deficit_ratio_pct"
    )
    assertions.assert_numeric_equals(
        marginal_analysis["deficit_ratio_pct"], 22.18, "deficit_ratio_pct"
    )


# ==========================================================================
# The two bases on which written objections are weighed
# ==========================================================================
def test_assessed_value_protest_basis_fails_a_single_low_value_objection(api):
    """PRD §3.6: "Under `ASSESSED_VALUE`, `protest_pct` is the exact integer sum
    of the qualifying filings' already-rounded `protest_value_cents`, divided by
    the case's `territory_assessed_value_cents`, multiplied by one hundred and
    rounded half up to two decimal places — or exactly 0.00 when the territory's
    assessed value is zero."

    Design: Difficulty/dual_variant_calc/protest_variant_value_vs_owner_count_flips_outcome_on_identical_filings
    """
    ctx = _noticed_case_on_protest_basis(api, "ASSESSED_VALUE")
    _hold_and_object(api, ctx)
    fixtures.close_protest_period(api, ctx)

    hearing = ctx["hearing"]
    expected_pct = assertions.expected_weight_pct(10000000, 100000000)
    assert expected_pct == assertions.pct(10.00)
    assertions.assert_numeric_equals(hearing["protest_pct"], 10.00, "protest_pct")
    # 10.00 is strictly below the 20.00 threshold, so the objection fails and the
    # case stays exactly where it was.
    assert hearing["protest_outcome"] == "FAILED"
    assertions.assert_numeric_equals(ctx["case"]["protest_pct"], 10.00, "protest_pct")
    assert ctx["case"]["protest_outcome"] == "FAILED"
    assert ctx["case"]["status"] == "HEARING_HELD"


def test_owner_count_protest_basis_sustains_the_same_single_objection(api):
    """PRD §3.6: "Under `OWNER_COUNT`, `protest_pct` is instead the number of
    distinct `property_owner_id` values among the qualifying filings divided by
    the number of distinct `primary_owner_id` values across the territory's
    parcels, multiplied by one hundred and rounded half up to two decimal places
    — or exactly 0.00 when the territory has no distinct owners."

    Design: Difficulty/dual_variant_calc/protest_variant_value_vs_owner_count_flips_outcome_on_identical_filings
    """
    ctx = _noticed_case_on_protest_basis(api, "OWNER_COUNT")
    _hold_and_object(api, ctx)
    fixtures.close_protest_period(api, ctx)

    hearing = ctx["hearing"]
    # One objecting owner out of the four owners of record in the territory.
    expected_pct = assertions.expected_weight_pct(1, 4)
    assert expected_pct == assertions.pct(25.00)
    assertions.assert_numeric_equals(hearing["protest_pct"], 25.00, "protest_pct")
    assert hearing["protest_outcome"] == "SUSTAINED"
    assertions.assert_numeric_equals(ctx["case"]["protest_pct"], 25.00, "protest_pct")
    assert ctx["case"]["protest_outcome"] == "SUSTAINED"
    assert ctx["case"]["status"] == "PROTEST_SUSTAINED"


def test_identical_objection_splits_fifteen_points_between_the_two_protest_bases(api):
    """PRD §3.6: "The two bases can disagree sharply on the identical set of
    filings: under assessed value one high-value parcel can carry a protest by
    itself, while under owner count value is irrelevant and only heads matter,
    so the same filings can flip the outcome from one basis to the other."

    Design: Difficulty/dual_variant_calc/protest_variant_value_vs_owner_count_flips_outcome_on_identical_filings
    """
    value_ctx = _noticed_case_on_protest_basis(api, "ASSESSED_VALUE")
    count_ctx = _noticed_case_on_protest_basis(api, "OWNER_COUNT")

    # Both hearings are noticed before either is held so that each satisfies the
    # 30-day notice window from the same publication instant.
    _hold_and_object(api, value_ctx)
    _hold_and_object(api, count_ctx)

    # The single filing on each side is the identical objection: the owner of the
    # 10,000,000-cent parcel, at a full 100 percent ownership share.
    assert value_ctx["filings"][0]["protest_value_cents"] == 10000000
    assert count_ctx["filings"][0]["protest_value_cents"] == 10000000

    fixtures.close_protest_period(api, value_ctx)
    fixtures.close_protest_period(api, count_ctx)

    assertions.assert_numeric_equals(
        value_ctx["hearing"]["protest_pct"], 10.00, "protest_pct"
    )
    assertions.assert_numeric_equals(
        count_ctx["hearing"]["protest_pct"], 25.00, "protest_pct"
    )
    gap = assertions.pct(count_ctx["hearing"]["protest_pct"]) - assertions.pct(
        value_ctx["hearing"]["protest_pct"]
    )
    assert gap == assertions.pct(15.00)
    # The identical filing flips the outcome, and with it the case status.
    assert value_ctx["hearing"]["protest_outcome"] == "FAILED"
    assert count_ctx["hearing"]["protest_outcome"] == "SUSTAINED"
    assert value_ctx["case"]["status"] == "HEARING_HELD"
    assert count_ctx["case"]["status"] == "PROTEST_SUSTAINED"


# ==========================================================================
# The four-term territory qualification score
# ==========================================================================
def _qualification_territory(api):
    """A DRAFT case whose contiguity sits exactly at the statutory minimum, whose
    lots pass the subdivision limb but not the density limb, and whose service
    distance is half a mile past the free three."""
    return _draft_territory(
        api,
        case_overrides={
            "shared_boundary_feet": 10000,
            "total_lot_count": 4,
            "developed_lot_count": 3,
            "dwelling_units": 3,
            "max_service_distance_miles": 3.5,
        },
        parcel_values_cents=_FISCAL_PARCEL_VALUES_CENTS,
    )


def test_qualification_index_composes_capped_ramp_urban_bonus_and_distance_step(api):
    """PRD §3.2: "The four terms are combined as base plus urban bonus minus
    density penalty minus distance penalty; the result is capped at 100, floored
    at 0, and rounded half up to two decimal places to give
    `qualification_index`."

    Design: Difficulty/combinatorial_formula/qualification_index_combines_capped_ramp_bonus_and_step_penalty
    """
    ctx = _qualification_territory(api)
    statute = ctx["statute"]
    ctx = fixtures.setup_certified_case(api, ctx=ctx)
    case = ctx["case"]

    contiguity_ratio = assertions.expected_contiguity_ratio(
        10000, ctx["municipality"]["corporate_boundary_perimeter_feet"]
    )
    assert contiguity_ratio == assertions.ratio4("0.1250")
    developed_ratio = assertions.expected_developed_lot_ratio(3, 4)
    density = assertions.expected_density(3, 20.00)

    expected_index = assertions.expected_qualification_index(
        contiguity_ratio=contiguity_ratio,
        contiguity_min_ratio=statute["contiguity_min_ratio"],
        urban_development_qualified=True,
        density=density,
        urban_density_min_units_per_acre=statute["urban_density_min_units_per_acre"],
        developed_lot_ratio=developed_ratio,
        subdivision_test_min_developed_ratio=statute[
            "subdivision_test_min_developed_ratio"
        ],
        max_service_distance_miles=3.5,
    )
    # A ramp base of 50.00 plus a 25.00 urban bonus less a 10.00 distance step.
    assert expected_index == assertions.pct(65.00)
    assertions.assert_numeric_equals(
        case["qualification_index"], 65.00, "qualification_index"
    )
    assertions.assert_numeric_equals(
        case["qualification_index"], expected_index, "qualification_index"
    )
    # 65.00 clears the 60.00 statutory floor, so the territory certifies.
    assert case["status"] == "TERRITORY_CERTIFIED"


def test_urban_qualification_rides_the_subdivision_limb_while_density_fails(api):
    """PRD §3.2: "A flat density penalty of fifteen points is subtracted when the
    dwelling-unit density is strictly below `urban_density_min_units_per_acre`
    **and** the developed-lot ratio is strictly below
    `subdivision_test_min_developed_ratio`, and nothing is subtracted
    otherwise."

    Design: Difficulty/combinatorial_formula/qualification_index_combines_capped_ramp_bonus_and_step_penalty
    """
    ctx = _qualification_territory(api)
    statute = ctx["statute"]
    ctx = fixtures.setup_certified_case(api, ctx=ctx)
    case = ctx["case"]

    developed_ratio = assertions.expected_developed_lot_ratio(3, 4)
    density = assertions.expected_density(3, 20.00)
    assert developed_ratio == assertions.ratio4("0.7500")
    assert density == assertions.ratio4("0.1500")
    # The density limb fails outright, so only the subdivision limb can qualify
    # the territory as urban.
    assert float(density) < float(statute["urban_density_min_units_per_acre"])
    assert float(developed_ratio) >= float(
        statute["subdivision_test_min_developed_ratio"]
    )
    assert case["urban_development_qualified"] is True

    # Because the developed-lot ratio is not below its minimum, the fifteen-point
    # density penalty stays suppressed even though the density limb failed.
    penalised_index = assertions.pct(
        assertions.pct(65.00) - assertions.pct(constants.DENSITY_PENALTY)
    )
    assert penalised_index == assertions.pct(50.00)
    assertions.assert_numeric_equals(
        case["qualification_index"], 65.00, "qualification_index"
    )
    assert assertions.pct(case["qualification_index"]) != penalised_index


def test_certification_stamps_territory_aggregates_and_promotes_parcels(api):
    """PRD §3.2: "A successful certification stamps `parcel_count`,
    `territory_acreage`, `territory_assessed_value_cents`, `contiguity_ratio`,
    `urban_development_qualified` and `qualification_index` onto the case,
    promotes every parcel of the case still in `PROPOSED` to `PENDING_ANNEX`,
    and increments the case's `version`."

    Design: Difficulty/combinatorial_formula/qualification_index_combines_capped_ramp_bonus_and_step_penalty
    """
    ctx = _qualification_territory(api)
    ctx = fixtures.setup_certified_case(api, ctx=ctx)
    case = ctx["case"]

    assert case["parcel_count"] == 4
    assertions.assert_numeric_equals(
        case["territory_acreage"], assertions.acres("20.00"), "territory_acreage"
    )
    assert case["territory_assessed_value_cents"] == sum(_FISCAL_PARCEL_VALUES_CENTS)
    assert case["territory_assessed_value_cents"] == 100000000
    assertions.assert_numeric_equals(
        case["contiguity_ratio"],
        assertions.expected_contiguity_ratio(
            10000, ctx["municipality"]["corporate_boundary_perimeter_feet"]
        ),
        "contiguity_ratio",
        places=4,
    )
    assertions.assert_numeric_equals(
        case["contiguity_ratio"], 0.1250, "contiguity_ratio", places=4
    )
    for parcel in ctx["parcels"]:
        assert parcel["parcel_status"] == "PENDING_ANNEX"


# ==========================================================================
# Per-parcel-first rounding of the prorated municipal levy
# ==========================================================================
def test_each_incorporated_parcel_is_prorated_over_the_remaining_fiscal_days(api):
    """PRD §3.8: "Then walk the case's parcels in `INCORPORATED`, ordered by
    `created_at` ascending and never by identifier, and for each one stamp
    `annual_tax_cents` as the parcel's `assessed_value_cents` multiplied by the
    municipality's `general_fund_millage_rate`, divided by one thousand, rounded
    half up to a whole cent; then stamp `prorated_tax_cents` as that
    `annual_tax_cents` multiplied by the remaining days, divided by the three
    hundred and sixty-five days of the fiscal year, rounded half up to a whole
    cent."

    Design: Difficulty/combinatorial_formula/tax_roll_proration_rounds_per_parcel_before_summation
    """
    ctx = _case_with_posted_tax_roll(api)
    municipality_id = ctx["municipality"]["id"]

    remaining_days = assertions.remaining_fiscal_days(
        _OCTOBER_EFFECTIVE_DATE, constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY
    )
    # 2026-10-11 through 2026-12-31, both endpoints counted.
    assert remaining_days == 82

    expected_annual = assertions.expected_property_tax_cents(
        _PRORATION_PARCEL_ASSESSED_CENTS,
        ctx["municipality"]["general_fund_millage_rate"],
    )
    assert expected_annual == 36573
    expected_prorated = assertions.expected_prorated_tax_cents(
        expected_annual, remaining_days
    )
    assert expected_prorated == 8216

    for parcel in ctx["parcels"]:
        stored = fixtures.read_parcel(api, municipality_id, parcel["id"])
        assert stored["parcel_status"] == "INCORPORATED"
        assert stored["annual_tax_cents"] == 36573
        assert stored["prorated_tax_cents"] == 8216


def test_case_transferred_tax_sums_already_rounded_per_parcel_amounts(api):
    """PRD §3.8: "The case's `tax_roll_transferred_tax_cents` is the exact
    integer sum of those already-rounded per-parcel amounts — rounding is per
    parcel first and summation second, never the other way around — and
    `tax_roll_transferred_assessed_value_cents` is the exact integer sum of
    their `assessed_value_cents`."

    Design: Difficulty/combinatorial_formula/tax_roll_proration_rounds_per_parcel_before_summation
    """
    ctx = _case_with_posted_tax_roll(api)
    case = ctx["case"]

    remaining_days = assertions.remaining_fiscal_days(
        _OCTOBER_EFFECTIVE_DATE, constants.DEFAULT_FISCAL_YEAR_END_MONTH_DAY
    )
    annual = assertions.expected_property_tax_cents(
        _PRORATION_PARCEL_ASSESSED_CENTS,
        ctx["municipality"]["general_fund_millage_rate"],
    )
    per_parcel = assertions.expected_prorated_tax_cents(annual, remaining_days)
    rounded_first_total = per_parcel * 4
    assert rounded_first_total == 32864

    # Summing the unrounded products and rounding once at the end is explicitly
    # not the rule, and here it would differ by two cents.
    summed_then_rounded = assertions.cents(
        Decimal(annual * 4 * remaining_days) / Decimal(constants.FISCAL_YEAR_DAYS)
    )
    assert summed_then_rounded == 32866

    assert case["tax_roll_transferred_tax_cents"] == 32864
    assert case["tax_roll_transferred_tax_cents"] == rounded_first_total
    assert case["tax_roll_transferred_tax_cents"] != summed_then_rounded
    assert case["tax_roll_transferred_assessed_value_cents"] == 14629200
    assert case["tax_roll_status"] == "POSTED"
    assert case["status"] == "EFFECTIVE"

    municipality = fixtures.read_municipality(api, ctx["municipality"]["id"])
    assert municipality["taxable_assessed_value_cents"] == 14629200


# ==========================================================================
# The overhead tier keyed to the pre-overhead base cost
# ==========================================================================
def test_overhead_tier_keys_off_the_pre_overhead_base_cost(api):
    """PRD §3.4: "The tier is never re-selected from the post-overhead total
    even though the total later includes the overhead, and there is no iteration
    and no fixed point to converge on."

    Design: Difficulty/combinatorial_formula/overhead_tier_selected_from_pre_overhead_base_cost
    """
    ctx = _draft_territory(
        api,
        statute_overrides={
            "fiscal_method": "AVERAGE_COST",
            "per_capita_shared_revenue_cents": 12000,
        },
    )
    municipality = ctx["municipality"]

    # 240 projected residents at 20,000 cents of citywide service cost each puts
    # the base cost just under the five-million-cent first tier ceiling while the
    # post-overhead total lands above it.
    analysis = fixtures.author_analysis(
        api, ctx, analysis_method="AVERAGE_COST", projected_population=240
    )

    expected_base = assertions.expected_average_cost_base_cents(
        municipality["citywide_annual_service_cost_cents"],
        240,
        municipality["citywide_population"],
    )
    assert expected_base == 4800000
    assert analysis["base_service_cost_cents"] == 4800000
    assert expected_base < constants.OVERHEAD_TIER_1_CEILING_CENTS

    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"],
        assertions.expected_overhead_tier_pct(expected_base),
        "overhead_tier_pct",
        places=4,
    )
    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"], 0.12, "overhead_tier_pct", places=4
    )
    assert analysis["administrative_overhead_cents"] == 576000
    assert analysis["projected_annual_service_cost_cents"] == 5376000
    # The post-overhead total sits in the second band, and a tier re-selected
    # from it would have produced 432,000 of overhead and a 5,232,000 total.
    assert analysis["projected_annual_service_cost_cents"] >= (
        constants.OVERHEAD_TIER_1_CEILING_CENTS
    )
    assertions.assert_numeric_equals(
        assertions.expected_overhead_tier_pct(5376000), 0.09, "post_overhead_tier",
        places=4,
    )
    assert analysis["administrative_overhead_cents"] != 432000
    assert analysis["projected_annual_service_cost_cents"] != 5232000


def test_pre_overhead_tier_selection_drives_net_impact_and_deficit_ratio(api):
    """PRD §3.4: "Step six derives `deficit_ratio_pct`: it is exactly 0.00 when
    the net impact is at or above zero; it is exactly 100.00 when the net impact
    is negative and gross annual revenue is zero; otherwise it is the magnitude
    of the negative net impact divided by `gross_annual_revenue_cents`,
    multiplied by one hundred and rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/overhead_tier_selected_from_pre_overhead_base_cost
    """
    ctx = _draft_territory(
        api,
        statute_overrides={
            "fiscal_method": "AVERAGE_COST",
            "per_capita_shared_revenue_cents": 12000,
        },
    )
    analysis = fixtures.author_analysis(
        api, ctx, analysis_method="AVERAGE_COST", projected_population=240
    )

    assert analysis["property_tax_revenue_cents"] == 1000000
    assert analysis["shared_revenue_cents"] == 240 * 12000
    assert analysis["shared_revenue_cents"] == 2880000
    assert analysis["gross_annual_revenue_cents"] == 3880000

    expected_net = 3880000 - 5376000
    assert expected_net == -1496000
    assert analysis["net_annual_impact_cents"] == -1496000
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"],
        assertions.expected_deficit_ratio_pct(-1496000, 3880000),
        "deficit_ratio_pct",
    )
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"], 38.56, "deficit_ratio_pct"
    )
    # Every figure is stamped at creation time, and the analysis begins in DRAFT.
    assert analysis["status"] == "DRAFT"
    stored = get_success_data(
        api.get_fiscal_impact_analysis(fiscal_analyst_headers(), analysis["id"])
    )
    assertions.assert_numeric_equals(
        stored["deficit_ratio_pct"], 38.56, "deficit_ratio_pct"
    )
    assert stored["projected_annual_service_cost_cents"] == 5376000
