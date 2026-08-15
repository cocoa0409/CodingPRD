"""Rendition line generation: depreciation conventions, per-line rounding order,
de-minimis floor boundary, and the percent-good floor beyond the vector."""
import pytest

from test_helpers import (
    assert_rendition,
    create_asset_for,
    create_class_rule_for,
    create_client_account,
    create_jurisdiction_account,
    find_rendition_line,
    generate,
    new_analyst,
    open_rendition,
    validate_success,
    classify,
)


def _setup_dual_convention():
    """One client with an identical MACHINERY asset in a FULL_YEAR jurisdiction
    and a HALF_YEAR jurisdiction, each with a DRAFT 2027 rendition."""
    client = create_client_account(legal_name="DualCo", contact_email="dual@x.com")
    analyst = new_analyst()
    j_full = create_jurisdiction_account(county_name="Full County")
    j_half = create_jurisdiction_account(county_name="Half County")
    create_class_rule_for(j_full["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[80, 70, 60],
                          percent_good_floor_pct=30, de_minimis_line_cents=0)
    create_class_rule_for(j_half["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="HALF_YEAR",
                          percent_good_vector=[90, 75, 60, 45],
                          percent_good_floor_pct=20, de_minimis_line_cents=0)
    asset_data = dict(category="MACHINERY", acquisition_cost_cents=1000000,
                      acquisition_date="2025-03-10", in_service_date="2025-08-01")
    a_full = create_asset_for(client["id"], j_full["id"], analyst["headers"],
                              asset_tag="A-FULL", **asset_data)
    a_half = create_asset_for(client["id"], j_half["id"], analyst["headers"],
                              asset_tag="A-HALF", **asset_data)
    classify(a_full["id"], "TAXABLE", analyst["headers"])
    classify(a_half["id"], "TAXABLE", analyst["headers"])
    r_full = open_rendition(client["id"], j_full["id"], 2027, analyst["headers"])
    r_half = open_rendition(client["id"], j_half["id"], 2027, analyst["headers"])
    return {
        "analyst": analyst, "a_full": a_full, "a_half": a_half,
        "r_full": r_full, "r_half": r_half,
    }


def test_full_year_convention_ages_from_acquisition_year(api):
    """PRD §3.4: "Under the `FULL_YEAR` convention, `age_years` is the tax year
    minus the year of the asset's `acquisition_date` — an asset acquired at any
    point within a year counts that whole year." and "The line's
    `assessed_value_cents` is the `acquisition_cost_cents` multiplied by that
    factor and divided by 100, rounded half-up to whole cents"

    Design: Difficulty/dual_variant_calc/depreciation_convention_full_vs_half_year
    """
    ctx = _setup_dual_convention()
    r_full = generate(ctx["r_full"]["id"], ctx["analyst"]["headers"])
    assert_rendition(r_full)
    line = find_rendition_line(r_full, ctx["a_full"]["id"])
    assert line["age_years"] == 2, "2027 - 2025 under FULL_YEAR"
    assert line["percent_good_applied"] == 60
    assert line["assessed_value_cents"] == 600000
    assert line["included"] is True
    assert r_full["total_assessed_value_cents"] == 600000


def test_half_year_convention_ages_slower_for_second_half_service(api):
    """PRD §3.4: "Under the `HALF_YEAR` convention, `age_years` is the tax year
    minus the year of the `in_service_date`, reduced by one further step when the
    `in_service_date` falls on or after July 1 of its year; assets placed in
    service in the second half of a year therefore depreciate one age step more
    slowly, and identical asset data yields a smaller age and a larger assessed
    value than `FULL_YEAR`."

    Design: Difficulty/dual_variant_calc/depreciation_convention_full_vs_half_year
    """
    ctx = _setup_dual_convention()
    r_full = generate(ctx["r_full"]["id"], ctx["analyst"]["headers"])
    r_half = generate(ctx["r_half"]["id"], ctx["analyst"]["headers"])
    line = find_rendition_line(r_half, ctx["a_half"]["id"])
    assert line["age_years"] == 1, "2027 - 2025 - 1 (in service 2025-08-01 >= July 1)"
    assert line["percent_good_applied"] == 75
    assert line["assessed_value_cents"] == 750000
    assert r_half["total_assessed_value_cents"] == 750000
    assert r_full["total_assessed_value_cents"] != r_half["total_assessed_value_cents"], (
        "identical asset data must diverge across the two conventions"
    )


def _setup_rounding_pair():
    """Two 101-cent assets at 50 percent good: raw 50.5 cents per line."""
    client = create_client_account(legal_name="RoundCo", contact_email="round@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Round County",
                                               tax_rate=0.01)
    create_class_rule_for(jurisdiction["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[100, 50],
                          percent_good_floor_pct=10, de_minimis_line_cents=0)
    a1 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag="R1", acquisition_cost_cents=101,
                          acquisition_date="2026-02-01", in_service_date="2026-02-05")
    a2 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag="R2", acquisition_cost_cents=101,
                          acquisition_date="2026-02-01", in_service_date="2026-02-05")
    classify(a1["id"], "TAXABLE", analyst["headers"])
    classify(a2["id"], "TAXABLE", analyst["headers"])
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    return {"analyst": analyst, "a1": a1, "a2": a2, "rendition": rendition}


def test_each_line_rounded_half_up_individually(api):
    """PRD §3.4: "The line's `assessed_value_cents` is the `acquisition_cost_cents`
    multiplied by that factor and divided by 100, rounded half-up to whole cents"

    Design: Difficulty/combinatorial_formula/rendition_total_per_line_rounding_order
    """
    ctx = _setup_rounding_pair()
    rendition = generate(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    assert_rendition(rendition)
    assert len(rendition["lines"]) == 2
    for asset in (ctx["a1"], ctx["a2"]):
        line = find_rendition_line(rendition, asset["id"])
        assert line["assessed_value_cents"] == 51, (
            "round_half_up(101 * 50 / 100) = round_half_up(50.5) = 51 per line"
        )


def test_total_sums_per_line_rounded_values(api):
    """PRD §2.6: "First, rendition line values are rounded individually, and only
    then summed into the rendition's `total_assessed_value_cents`; the alternative
    order — summing unrounded products and rounding once at the end — is
    forbidden."

    Design: Difficulty/combinatorial_formula/rendition_total_per_line_rounding_order
    """
    ctx = _setup_rounding_pair()
    rendition = generate(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    assert rendition["total_assessed_value_cents"] == 102, (
        "51 + 51 = 102; the forbidden sum-then-round order would yield 101"
    )


def _setup_de_minimis_pair():
    """Assets at exactly the de-minimis floor (100000) and one cent below (99999)."""
    client = create_client_account(legal_name="MinCo", contact_email="min@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Min County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[100, 50],
                          percent_good_floor_pct=10, de_minimis_line_cents=100000)
    a1 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag="E1", acquisition_cost_cents=200000,
                          acquisition_date="2026-02-01", in_service_date="2026-02-05")
    a2 = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                          asset_tag="E2", acquisition_cost_cents=199998,
                          acquisition_date="2026-02-01", in_service_date="2026-02-05")
    classify(a1["id"], "TAXABLE", analyst["headers"])
    classify(a2["id"], "TAXABLE", analyst["headers"])
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])
    return {"analyst": analyst, "a1": a1, "a2": a2, "rendition": rendition}


def test_de_minimis_floor_equality_keeps_line(api):
    """PRD §3.4: "A line is excluded with `exclusion_reason` `DEMINIMIS` when its
    assessed value is strictly below the rule's `de_minimis_line_cents`; a value
    exactly equal to that floor is kept."

    Design: Difficulty/boundary_precision_check/de_minimis_floor_equality_keeps_line
    """
    ctx = _setup_de_minimis_pair()
    rendition = generate(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    line = find_rendition_line(rendition, ctx["a1"]["id"])
    assert line["assessed_value_cents"] == 100000
    assert line["included"] is True, "a value exactly equal to the floor is kept"
    assert line.get("exclusion_reason") is None


def test_one_cent_below_de_minimis_floor_drops_line(api):
    """PRD §3.4: "A line is excluded with `exclusion_reason` `DEMINIMIS` when its
    assessed value is strictly below the rule's `de_minimis_line_cents`; a value
    exactly equal to that floor is kept." and "The rendition's
    `total_assessed_value_cents` is then the sum of `assessed_value_cents` over
    the included lines"

    Design: Difficulty/boundary_precision_check/de_minimis_floor_equality_keeps_line
    """
    ctx = _setup_de_minimis_pair()
    rendition = generate(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    line = find_rendition_line(rendition, ctx["a2"]["id"])
    assert line["assessed_value_cents"] == 99999
    assert line["included"] is False
    assert line["exclusion_reason"] == "DEMINIMIS"
    assert rendition["total_assessed_value_cents"] == 100000


def test_depreciation_floor_pct_applies_beyond_vector(api):
    """PRD §3.4: "The percent-good factor is the rule's `percent_good_vector`
    entry at the index equal to the age when the age falls within the vector's
    length, and the rule's `percent_good_floor_pct` when it does not."

    Design: Corner/calculations/depreciation_floor_pct_applies_beyond_vector
    """
    client = create_client_account(legal_name="FloorCo", contact_email="floor@x.com")
    analyst = new_analyst()
    jurisdiction = create_jurisdiction_account(county_name="Floor County")
    create_class_rule_for(jurisdiction["id"], category="MACHINERY", is_taxable=True,
                          depreciation_convention="FULL_YEAR",
                          percent_good_vector=[90, 80],
                          percent_good_floor_pct=25, de_minimis_line_cents=0)
    asset = create_asset_for(client["id"], jurisdiction["id"], analyst["headers"],
                             asset_tag="FL1", acquisition_cost_cents=1000000,
                             acquisition_date="2010-01-05",
                             in_service_date="2010-01-10")
    classify(asset["id"], "TAXABLE", analyst["headers"])
    rendition = open_rendition(client["id"], jurisdiction["id"], 2027,
                               analyst["headers"])

    rendition = generate(rendition["id"], analyst["headers"])
    line = find_rendition_line(rendition, asset["id"])
    assert line["age_years"] == 17, "2027 - 2010 under FULL_YEAR"
    assert line["percent_good_applied"] == 25, "floor applies past the vector"
    assert line["assessed_value_cents"] == 250000
    assert rendition["total_assessed_value_cents"] == 250000
