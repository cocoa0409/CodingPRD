"""Rounding order, band constants and exactly which rows a figure is allowed to see."""

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_page,
    assert_score,
)

FLAT_WELL = dict(
    spud_year=1961,
    total_depth_ft=2500,
    casing_strings=1,
    methane_scfd=0,
    population_within_1000ft=0,
    surface_disturbance_acres=0,
)
UNSCORED_WELL = dict(
    spud_year=1988,
    methane_scfd=0,
    groundwater_depth_ft=600,
    population_within_1000ft=0,
    surface_disturbance_acres=0,
)


def test_each_risk_component_is_rounded_before_any_weight_touches_it(api: ApiClient):
    """A methane rate of 3.337 pins both rounding decisions in one row.

    The methane quotient 0.6674 becomes 0.67 before it is weighted, which is worth three
    hundredths of a point across the two rankings, and the remediation total lands exactly
    on 9.765, where rounding to the nearest even hundredth would report 9.76.

    PRD: "The four risk components that feed the two priority scores are each rounded to
    two decimal places before any weight touches them, and the weighted sum is then
    rounded to two decimal places again."

    Design: Corner/calculations/risk_components_are_rounded_to_two_dp_before_any_weighting
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=1000000,
    )
    well = fx.make_well(
        api,
        operator["id"],
        api_well_number="49-013-30001",
        spud_year=1961,
        total_depth_ft=2500,
        casing_strings=1,
        methane_scfd=3.337,
        groundwater_depth_ft=600,
        population_within_1000ft=3,
        surface_disturbance_acres=0.777,
    )

    assert_score(well["screening_score"], 7.97, "screening_score")
    assert_score(well["remediation_score"], 9.77, "remediation_score")
    assert well["screening_score"] != 7.96, (
        "7.96 is the figure produced by weighting the unrounded methane quotient"
    )
    assert well["remediation_score"] != 9.76, (
        "9.76 is the figure produced either by weighting the unrounded methane quotient "
        "or by rounding the exact 9.765 sum to the nearest even hundredth"
    )
    assert_fields(well, idle_months=999)
    assert_score(well["cumulative_boe_60mo"], 0.00, "cumulative_boe_60mo")


def test_the_groundwater_bands_claim_their_own_upper_edge(api: ApiClient):
    """Six wells straddle the three band edges with every other risk input at zero.

    With nothing else contributing, each score is a pure readout of the band constant, so
    the pair either side of each edge shows which side the edge belongs to: the shallower
    figure wins at 50, at 200 and at 500 feet.

    PRD: "Protected groundwater no deeper than 50 feet scores 100. Deeper than 50 feet but
    no deeper than 200 feet scores 75. Deeper than 200 feet but no deeper than 500 feet
    scores 40. Deeper than 500 feet scores 10."

    Design: Corner/calculations/groundwater_band_boundaries_select_the_adjacent_constant
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=1000000,
    )
    expectations = [
        (50, "49-013-30050", 30.00, 25.00),
        (51, "49-013-30051", 22.50, 18.75),
        (200, "49-013-30200", 22.50, 18.75),
        (201, "49-013-30201", 12.00, 10.00),
        (500, "49-013-30500", 12.00, 10.00),
        (501, "49-013-30501", 3.00, 2.50),
    ]
    for depth, number, screening, remediation in expectations:
        well = fx.make_well(
            api,
            operator["id"],
            api_well_number=number,
            groundwater_depth_ft=depth,
            **FLAT_WELL,
        )
        label = "%d ft well" % depth
        assert_score(well["screening_score"], screening, label + " screening_score")
        assert_score(well["remediation_score"], remediation, label + " remediation_score")
        assert well["screening_score"] != 0, (
            "%s reported no screening risk at all, which is what a linear depth term "
            "rather than a band lookup would produce" % label
        )


def test_row_level_barrel_equivalents_are_summed_before_they_are_rounded(api: ApiClient):
    """Three months of one thousand cubic feet each expose the aggregation order.

    A sixth of a barrel stored three times sums to exactly half a barrel, while rounding
    each row to seventeen hundredths first and then summing overstates the well by a
    hundredth - precisely the margin the de-minimis test is decided on.

    PRD: "A production record's barrel-of-oil-equivalent value `boe` is stored unrounded at
    the row level; the two-decimal rounding happens exactly once, on the well's
    sixty-month aggregate."

    Design: Corner/calculations/unrounded_row_boe_is_summed_and_rounded_once_at_the_aggregate
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=1000000,
    )
    well = fx.make_well(api, operator["id"], api_well_number="49-013-30777")

    for month in ("2026-06", "2026-07", "2026-08"):
        row = fx.report_production(api, well["id"], month, oil_bbl=0, gas_mcf=1)
        assert abs(float(row["boe"]) - 1.0 / 6.0) < 1e-9, (
            "the %s row should carry the unrounded sixth of a barrel, got %r"
            % (month, row["boe"])
        )

    stored = fx.read_well(api, well["id"])
    assert_score(stored["cumulative_boe_60mo"], 0.50, "cumulative_boe_60mo")
    assert round(float(stored["cumulative_boe_60mo"]), 2) != 0.51, (
        "0.51 is the total produced by rounding each row to 0.17 before summing"
    )
    assert_fields(stored, last_production_month="2026-08", idle_months=0)
    assert_score(stored["screening_score"], 59.90, "screening_score")
    assert_score(stored["remediation_score"], 81.00, "remediation_score")


def test_the_de_minimis_window_is_sixty_months_counted_inclusively(api: ApiClient):
    """A row one month outside the window carries five thousand barrels and is dropped.

    With the clock in August 2026 the window opens in September 2021, so the August 2021
    row is out by a single month; it stays stored and readable, but the aggregate is built
    from the two months inside the window and nothing else.

    PRD: "the window starts fifty-nine months before the clock month and ends at the clock
    month itself, and production months are compared as `YYYY-MM` strings."

    Design: Corner/calculations/de_minimis_window_is_sixty_inclusive_months_ending_at_the_clock_month
    """
    operator = fx.make_operator(
        api,
        name="Wind River Petroleum",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=1000000,
    )
    well = fx.make_well(api, operator["id"], api_well_number="49-013-30888")

    fx.report_production(api, well["id"], "2021-08", oil_bbl=5000, gas_mcf=0)
    outside_only = fx.read_well(api, well["id"])
    assert_score(
        outside_only["cumulative_boe_60mo"], 0.00, "cumulative_boe_60mo after 2021-08"
    )

    fx.report_production(api, well["id"], "2021-09", oil_bbl=10, gas_mcf=0)
    first_in_window = fx.read_well(api, well["id"])
    assert_score(
        first_in_window["cumulative_boe_60mo"],
        10.00,
        "cumulative_boe_60mo after 2021-09",
    )

    fx.report_production(api, well["id"], "2026-08", oil_bbl=20, gas_mcf=0)
    final = fx.read_well(api, well["id"])
    assert_score(final["cumulative_boe_60mo"], 30.00, "cumulative_boe_60mo")
    assert round(float(final["cumulative_boe_60mo"]), 2) != 5030.00, (
        "5030.00 is the total a window that reached back one month too far would produce"
    )
    assert_fields(final, last_production_month="2026-08", idle_months=0)
    assert_page(
        api.list_production_records(well["id"], users.INSPECTOR), 3, expected_total=3
    )


def test_the_depth_tiers_claim_their_own_upper_edge_as_well(api: ApiClient):
    """Four wells straddle both tier edges inside one blanket inventory.

    The three thousand foot well takes the shallow base and the seven thousand foot well
    takes the middle one, so the running requirement walks 250000, 1000000, 1750000 and
    3250000 as the wells arrive; a strict comparison would push both edge wells up a tier
    and demand a million cents more.

    PRD: "Each well contributes a base amount determined by a depth tier whose upper edges
    are inclusive: a well no deeper than 3000 feet contributes 250000 cents ($2,500); a
    well deeper than 3000 feet but no deeper than 7000 feet contributes 750000 cents
    ($7,500); a well deeper than 7000 feet contributes 1500000 cents ($15,000)."

    Design: Corner/calculations/depth_tier_boundaries_are_inclusive_on_their_upper_edge
    """
    operator = fx.make_operator(
        api,
        name="Powder River Deep Gas",
        region_code="WY",
        financial_assurance_tier="BLANKET",
        bond_amount_cents=3250000,
    )
    steps = [
        (3000, "49-005-13000", 2, 250000),
        (3001, "49-005-13001", 2, 1000000),
        (7000, "49-005-17000", 3, 1750000),
        (7001, "49-005-17001", 3, 3250000),
    ]
    for depth, number, casing_strings, expected_requirement in steps:
        fx.make_well(
            api,
            operator["id"],
            api_well_number=number,
            total_depth_ft=depth,
            casing_strings=casing_strings,
            **UNSCORED_WELL,
        )
        assert_cents(
            fx.read_operator(api, operator["id"])["required_bond_cents"],
            expected_requirement,
            "required_bond_cents after the %d ft well" % depth,
        )

    final = fx.read_operator(api, operator["id"])
    assert_cents(final["required_bond_cents"], 3250000, "required_bond_cents")
    assert final["required_bond_cents"] != 4250000, (
        "4250000 is the requirement a strict tier comparison would produce"
    )
    assert_fields(final, active_well_count=4, status="ACTIVE")


def test_the_price_benchmark_ignores_the_cheapest_bid_when_it_is_nonresponsive(api: ApiClient):
    """A lowball bid that failed the technical minimum must not rescale the field.

    It is the cheapest basket in the solicitation and it is excluded from the candidate
    pool, so the cheapest responsive basket becomes the benchmark and scores exactly one
    hundred; the excluded bid itself is never scored at all.

    PRD: "The price benchmark is the lowest `evaluated_unit_cost_cents` among the
    candidates and nothing else - never the full bid population, and never recomputed
    after a winner is chosen."

    Design: Corner/calculations/price_score_basis_is_the_cheapest_responsive_bid_not_the_cheapest_bid
    """
    lowball = fx.make_contractor(
        api,
        name="Lowball Well Service",
        license_number="P-20001",
        performance_score=40,
    )
    middle = fx.make_contractor(
        api, name="Bighorn Plugging", license_number="P-20002", performance_score=89
    )
    premium = fx.make_contractor(
        api, name="Teton Cementing", license_number="P-20003", performance_score=95
    )
    solicitation = fx.make_open_solicitation(
        api, scope_description="district 3 orphan well plugging"
    )
    cheap = fx.place_bid(
        api,
        solicitation["id"],
        lowball["id"],
        rates={
            "cement_per_sack_cents": 3000,
            "rig_day_rate_cents": 700000,
            "casing_per_ft_cents": 1000,
            "mobilization_fee_cents": 2000000,
        },
        technical_score=55,
    )
    winner = fx.place_bid(
        api,
        solicitation["id"],
        middle["id"],
        rates={
            "cement_per_sack_cents": 4000,
            "rig_day_rate_cents": 800000,
            "casing_per_ft_cents": 1200,
            "mobilization_fee_cents": 2400000,
        },
        technical_score=80,
    )
    runner_up = fx.place_bid(
        api,
        solicitation["id"],
        premium["id"],
        rates={
            "cement_per_sack_cents": 5000,
            "rig_day_rate_cents": 1000000,
            "casing_per_ft_cents": 1500,
            "mobilization_fee_cents": 3000000,
        },
        technical_score=95,
    )
    for bid, expected_cost in (
        (cheap, 5960000),
        (winner, 7040000),
        (runner_up, 8800000),
    ):
        assert_cents(
            bid["evaluated_unit_cost_cents"], expected_cost, "evaluated_unit_cost_cents"
        )
        assert bid["price_score"] is None and bid["composite_score"] is None, (
            "no score may exist before the award: %r" % (bid,)
        )

    fx.advance_solicitation(api, solicitation["id"], "CLOSE")
    fx.evaluate_bid(
        api,
        cheap["id"],
        "NONRESPONSIVE",
        reason="technical score 55 below the 70 minimum",
    )
    fx.evaluate_bid(api, winner["id"], "RESPONSIVE")
    fx.evaluate_bid(api, runner_up["id"], "RESPONSIVE")

    contract = fx.award(api, solicitation["id"])
    assert_fields(contract, winning_bid_id=winner["id"])
    assert_cents(contract["cement_per_sack_cents"], 4000, "cement_per_sack_cents")
    assert_cents(contract["rig_day_rate_cents"], 800000, "rig_day_rate_cents")
    assert_cents(contract["casing_per_ft_cents"], 1200, "casing_per_ft_cents")
    assert_cents(contract["mobilization_fee_cents"], 2400000, "mobilization_fee_cents")

    scored_winner = fx.read_bid(api, winner["id"])
    assert_score(scored_winner["price_score"], 100.00, "winner price_score")
    assert_score(scored_winner["composite_score"], 92.00, "winner composite_score")
    assert_fields(scored_winner, status="AWARDED")
    assert round(float(scored_winner["price_score"]), 2) != 84.66, (
        "84.66 is the price score the excluded 5960000 basket would produce as benchmark"
    )

    scored_runner_up = fx.read_bid(api, runner_up["id"])
    assert_score(scored_runner_up["price_score"], 80.00, "runner up price_score")
    assert_score(scored_runner_up["composite_score"], 86.00, "runner up composite_score")
    assert_fields(scored_runner_up, status="NOT_AWARDED")

    excluded = fx.read_bid(api, cheap["id"])
    assert_fields(excluded, status="NOT_AWARDED")
    assert excluded["price_score"] is None and excluded["composite_score"] is None, (
        "a nonresponsive bid must never be scored: %r" % (excluded,)
    )


def test_a_composite_tie_is_settled_on_price_and_not_on_arrival_order(api: ApiClient):
    """Two bids meet at exactly eighty-eight points from opposite directions.

    The expensive, technically perfect bid arrived first and the cheap bid scraped in at
    exactly the technical minimum, so arrival order and price point at different winners;
    the cheaper basket takes the contract.

    PRD: "A tie on composite score is broken by `evaluated_unit_cost_cents` ascending, so
    the cheaper basket wins. A remaining tie is broken by `created_at` ascending, so the
    earlier-filed bid wins"

    Design: Corner/calculations/composite_tie_is_broken_by_unit_cost_ascending_before_created_at
    """
    premium = fx.make_contractor(
        api, name="Teton Cementing", license_number="P-30001", performance_score=99
    )
    thrifty = fx.make_contractor(
        api, name="Bighorn Plugging", license_number="P-30002", performance_score=70
    )
    solicitation = fx.make_open_solicitation(
        api, scope_description="district 4 orphan well plugging"
    )
    early_expensive = fx.place_bid(
        api,
        solicitation["id"],
        premium["id"],
        rates={
            "cement_per_sack_cents": 5000,
            "rig_day_rate_cents": 1000000,
            "casing_per_ft_cents": 1500,
            "mobilization_fee_cents": 3000000,
        },
        technical_score=100,
    )
    late_cheap = fx.place_bid(
        api,
        solicitation["id"],
        thrifty["id"],
        rates={
            "cement_per_sack_cents": 4000,
            "rig_day_rate_cents": 800000,
            "casing_per_ft_cents": 1200,
            "mobilization_fee_cents": 2400000,
        },
        technical_score=70,
    )
    assert_cents(
        early_expensive["evaluated_unit_cost_cents"], 8800000, "expensive unit cost"
    )
    assert_cents(late_cheap["evaluated_unit_cost_cents"], 7040000, "cheap unit cost")

    fx.advance_solicitation(api, solicitation["id"], "CLOSE")
    fx.evaluate_bid(api, early_expensive["id"], "RESPONSIVE")
    fx.evaluate_bid(api, late_cheap["id"], "RESPONSIVE")

    contract = fx.award(api, solicitation["id"])
    assert_fields(contract, winning_bid_id=late_cheap["id"])
    assert contract["winning_bid_id"] != early_expensive["id"], (
        "the first bid in is what falling straight through to created_at would select"
    )

    winner = fx.read_bid(api, late_cheap["id"])
    loser = fx.read_bid(api, early_expensive["id"])
    assert_score(winner["price_score"], 100.00, "winner price_score")
    assert_score(winner["composite_score"], 88.00, "winner composite_score")
    assert_score(loser["price_score"], 80.00, "loser price_score")
    assert_score(loser["composite_score"], 88.00, "loser composite_score")
    assert float(winner["composite_score"]) == float(loser["composite_score"]), (
        "the tie is the whole point of this pair of baskets"
    )
    assert_fields(winner, status="AWARDED")
    assert_fields(loser, status="NOT_AWARDED")


def test_the_waterfall_pool_drops_three_rich_but_ineligible_sources(api: ApiClient):
    """Each rejected source could have paid for the whole job on its own.

    A forfeited bond belonging to another operator, a federal grant whose authority lapsed
    a month ago while its status still reads active, and a state account that may only fund
    surface work are all excluded, and the one eligible account is ranked first because the
    rank counts positions in the surviving pool rather than kinds of money.

    PRD: "a source qualifies when its `status` is `ACTIVE`, its `expires_at` is strictly
    after the logical clock, `PLUGGING` is present among its `allowable_cost_categories`,
    its `authorized_cents` minus its `committed_cents` is strictly greater than zero, and -
    for a source whose `kind` is `FORFEITED_BOND` - its `bond_operator_id` equals the
    `operator_id` of the job's well."

    Design: Corner/calculations/waterfall_pool_drops_foreign_bonds_wrong_categories_and_stale_sources
    """
    orphan = fx.make_confirmed_orphan_well(
        api, api_well_number="49-001-04001"
    )
    stranger = fx.make_operator(api, name="Absaroka Minerals Inc", region_code="WY")
    procurement = fx.make_active_contract(
        api, scope_description="single orphan well plugging"
    )
    job = fx.make_plugging_job(
        api, orphan["well"]["id"], procurement["contract"]["id"]
    )

    foreign_bond = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Absaroka Minerals forfeited bond",
        authorized_cents=20000000,
        expires_at="2027-12-31T00:00:00Z",
        bond_operator_id=stranger["id"],
    )
    lapsed_grant = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="lapsed FY24 orphan well grant",
        authorized_cents=20000000,
        expires_at="2026-07-01T00:00:00Z",
        federal_match_required_pct=40,
    )
    surface_only = fx.make_funding_source(
        api,
        name="surface reclamation only account",
        authorized_cents=20000000,
        expires_at="2027-12-31T00:00:00Z",
        allowable_cost_categories=["RECLAMATION", "ADMIN"],
    )
    eligible = fx.make_funding_source(
        api,
        name="Wyoming orphan well plugging account",
        authorized_cents=10000000,
        expires_at="2027-12-31T00:00:00Z",
    )

    allocations = fx.commit_funding(api, job["id"])
    assert len(allocations) == 1, (
        "only the one eligible account should have been drawn on: %r" % (allocations,)
    )
    allocation = allocations[0]
    assert_fields(allocation, source_id=eligible["id"], waterfall_rank=1)
    assert_cents(allocation["allocated_cents"], 6070196, "allocated_cents")
    assert allocation["waterfall_rank"] != 3, (
        "rank 3 is the position a source's kind would give it in the unfiltered ordering"
    )

    for source, why in (
        (foreign_bond, "its bond belongs to another operator"),
        (lapsed_grant, "its authority lapsed before the clock"),
        (surface_only, "it may not fund plugging"),
    ):
        assert_cents(
            fx.read_source(api, source["id"])["committed_cents"],
            0,
            "committed_cents of the source excluded because %s" % why,
        )
    drawn = fx.read_source(api, eligible["id"])
    assert_cents(drawn["committed_cents"], 6070196, "committed_cents")
    assert_fields(drawn, status="ACTIVE")
    assert_cents(fx.read_job(api, job["id"])["funded_cents"], 6070196, "funded_cents")


def test_a_grant_report_separates_its_own_disbursements_from_the_project_total(api: ApiClient):
    """One disbursement set is reported through two windows, and only one window sees it.

    The August window has to keep two easily conflated sums apart: what this grant paid,
    and what the whole job cost across every stream. The January window sees nothing at
    all, so the share it reports comes from the zero-total guard rather than from a
    division.

    PRD: "When the total is zero, `federal_share_pct` is exactly 0.00 rather than an
    error."

    Design: Corner/calculations/grant_report_counts_only_disbursed_rows_inside_the_inclusive_window
    """
    orphan = fx.make_confirmed_orphan_well(api, api_well_number="49-001-05001")
    fx.authorize_site_access(api, orphan["well"]["id"])
    procurement = fx.make_active_contract(
        api, scope_description="single orphan well plugging"
    )
    job = fx.make_plugging_job(
        api, orphan["well"]["id"], procurement["contract"]["id"]
    )

    bond = fx.make_funding_source(
        api,
        kind="FORFEITED_BOND",
        name="Cottonwood forfeited bond",
        authorized_cents=1000000,
        expires_at="2027-12-31T00:00:00Z",
        bond_operator_id=orphan["operator"]["id"],
    )
    federal = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2027-12-31T00:00:00Z",
        federal_match_required_pct=40,
    )
    state = fx.make_funding_source(
        api,
        name="Wyoming orphan well plugging account",
        authorized_cents=9000000,
        expires_at="2027-12-31T00:00:00Z",
    )
    by_source = {row["source_id"]: row for row in fx.commit_funding(api, job["id"])}

    fx.mobilize(api, job["id"])
    fx.file_field_report(api, job["id"])
    fx.review_job(api, job["id"], "ACCEPT", "plugging documentation complete")

    fx.set_clock(api, "2026-08-10T00:00:00Z")
    for source, invoice_cents in (
        (bond, 1000000),
        (federal, 1500000),
        (state, 3570196),
    ):
        fx.transition_allocation(
            api, by_source[source["id"]]["id"], "DISBURSE", invoice_cents
        )

    august = fx.make_grant_report(api, federal["id"], "2026-08-01", "2026-08-31")
    assert_fields(
        august, wells_plugged_count=1, status="DUE", revision_round=0
    )
    assert august["submitted_by_user_id"] is None, (
        "a freshly generated report has not been submitted by anybody"
    )
    assert_cents(august["reported_cost_cents"], 1500000, "reported_cost_cents")
    assert_score(august["federal_share_pct"], 24.71, "federal_share_pct")
    assert round(float(august["federal_share_pct"]), 2) != 100.00, (
        "100.00 is the share reported cost would produce as its own denominator"
    )

    january = fx.make_grant_report(api, federal["id"], "2026-01-01", "2026-01-31")
    assert_fields(january, wells_plugged_count=0)
    assert_cents(january["reported_cost_cents"], 0, "reported_cost_cents")
    assert_score(january["federal_share_pct"], 0.00, "federal_share_pct")

    assert_cents(
        fx.read_source(api, federal["id"])["disbursed_cents"],
        1500000,
        "federal disbursed_cents",
    )
    assert_cents(
        fx.read_source(api, bond["id"])["disbursed_cents"],
        1000000,
        "bond disbursed_cents",
    )
    assert_fields(
        fx.read_allocation(api, by_source[federal["id"]]["id"]),
        disbursed_at="2026-08-10T00:00:00Z",
        disbursed_by_user_id="u_fund2",
    )
