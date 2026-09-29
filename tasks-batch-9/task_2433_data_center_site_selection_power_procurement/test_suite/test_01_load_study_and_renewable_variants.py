"""Two-variant derived figures: load study peaks, PPA credit and the screening score."""

from test_helpers import (
    EXPECTED_DIVERSIFIED_PEAK_MW,
    EXPECTED_NAMEPLATE_PEAK_MW,
    EXPECTED_SCREENING_SCORE_ALPHA,
    EXPECTED_STUDY_FEE_USD,
    EXPECTED_UPGRADE_COST_USD,
    PROGRAM_ANNUAL_LOAD_MWH,
    add_sibling_site,
    assert_money,
    assert_mw,
    assert_pct,
    assert_ratio,
    assert_site_screening_outputs,
    assert_status,
    draft_ppa,
    execute_ppa,
    file_load_study,
    open_program,
    read_application,
    read_program,
    read_site,
    read_water_source,
    setup_screened_site,
    setup_submitted_application,
)

SOLAR_TWIN = {
    "technology": "SOLAR",
    "contracted_capacity_mw": 900,
    "annual_generation_mwh": 2100000,
    "hourly_matched_mwh": 1500000,
    "strike_price_usd_per_mwh": 41.50,
    "delivery_start": "2029-07-01T00:00:00Z",
    "delivery_end": "2044-06-30T00:00:00Z",
}


def _solar_pair(program_id):
    """Two agreements with byte-identical volumes, differing only in matching mode."""
    volumetric = draft_ppa(
        program_id,
        counterparty_name="Sunbelt Solar I",
        matching_mode="ANNUAL_VOLUMETRIC",
        **SOLAR_TWIN,
    )
    hourly = draft_ppa(
        program_id,
        counterparty_name="Sunbelt Solar II",
        matching_mode="HOURLY_MATCHED",
        **SOLAR_TWIN,
    )
    return volumetric, hourly


def test_load_study_round_reports_nameplate_and_diversified_views_together():
    """A single study round of 240 + 66 + 12 MW at a diversity factor of 0.92 carries
    both readings of the same load: a nameplate stack of 318.0 MW that ignores
    diversity outright, and a coincident 293.52 MW that diversifies the IT block,
    floors the cooling block at 0.85 and leaves the ancillary block whole. The two
    readings differ by exactly 24.48 MW on identical inputs, and only the coincident
    one crosses the 250.0 MW upgrade trigger of a 500 MW utility, pricing the upgrade
    at 26945136.00 with the MODERATE hazard uplift.

    PRD §3.4: "The `nameplate_peak_mw` figure is the plain arithmetic sum of the IT, cooling and ancillary components: the diversity factor and the cooling floor are ignored entirely, and this is the figure the developer originally requested capacity against."
    PRD §3.4: "The `diversified_peak_mw` figure is the utility's coincident view: the IT component is multiplied by the diversity factor, the cooling component is multiplied by whichever is larger of the diversity factor and a cooling floor of 0.85 so that cooling load never diversifies below that floor, the ancillary component is taken undiversified at full value, the three products are added, and the total is rounded to 3 decimal places."
    PRD §3.4: "An upgrade trigger is computed as the utility's total transmission capacity multiplied by 0.50 and rounded to 3 decimal places, and `upgrade_required` is true only when the diversified peak is **strictly greater** than that trigger; a diversified peak exactly equal to the trigger does not require an upgrade."

    Design: Difficulty/dual_variant_calc/load_study_nameplate_vs_diversified_with_cooling_floor
    """
    env = setup_submitted_application()

    study = file_load_study(
        env["application"]["id"],
        env["utility"]["id"],
        it_load_mw=240,
        cooling_load_mw=66,
        ancillary_load_mw=12,
        diversity_factor=0.92,
    )

    assert study["study_round"] == 1
    assert_mw(study["nameplate_peak_mw"], EXPECTED_NAMEPLATE_PEAK_MW, "nameplate_peak_mw")
    assert_mw(
        study["diversified_peak_mw"], EXPECTED_DIVERSIFIED_PEAK_MW, "diversified_peak_mw"
    )
    assert_mw(
        study["nameplate_peak_mw"] - study["diversified_peak_mw"],
        24.48,
        "nameplate minus diversified",
    )
    assert study["upgrade_required"] is True
    assert_money(
        study["network_upgrade_cost_usd"],
        EXPECTED_UPGRADE_COST_USD,
        "network_upgrade_cost_usd",
    )


def test_restudy_round_mirrors_the_newest_diversified_peak_on_the_application():
    """A second round with the same three components at a diversity factor of 0.60
    keeps the nameplate stack at 318.0 MW but drops the coincident reading to
    212.1 MW, which no longer exceeds the 250.0 MW trigger, so the round prices no
    upgrade at all. The application mirrors the newest round rather than the first:
    round 2's 212.1 MW and 0.00 upgrade cost replace what a client saw after round 1,
    while the sunk 360000.00 study fee remains the site's whole capital commitment.

    PRD §3.4: "After each study round the application's own `diversified_peak_mw` and `network_upgrade_cost_usd` mirror the **newest** study — the one with the highest `study_round`, breaking any tie by the later `created_at` — so a restudy replaces the figures a client saw rather than adding to them."
    PRD §3.4: "Filing a study advances the application from `SUBMITTED` to `STUDY_COMPLETE`; filing another study against an application already in `STUDY_COMPLETE` is a legitimate restudy that leaves the application in `STUDY_COMPLETE` and simply appends the next round."

    Design: Difficulty/dual_variant_calc/load_study_nameplate_vs_diversified_with_cooling_floor
    """
    env = setup_submitted_application()
    file_load_study(
        env["application"]["id"],
        env["utility"]["id"],
        it_load_mw=240,
        cooling_load_mw=66,
        ancillary_load_mw=12,
        diversity_factor=0.92,
    )

    second = file_load_study(
        env["application"]["id"],
        env["utility"]["id"],
        it_load_mw=240,
        cooling_load_mw=66,
        ancillary_load_mw=12,
        diversity_factor=0.60,
    )

    assert second["study_round"] == 2
    assert_mw(second["nameplate_peak_mw"], EXPECTED_NAMEPLATE_PEAK_MW, "nameplate_peak_mw")
    assert_mw(second["diversified_peak_mw"], 212.1, "diversified_peak_mw")
    assert second["upgrade_required"] is False
    assert_money(second["network_upgrade_cost_usd"], 0.00, "network_upgrade_cost_usd")

    application = read_application(env["application"]["id"])
    assert_status(application, "STUDY_COMPLETE", "application")
    assert application["study_round"] == 2
    assert_mw(application["diversified_peak_mw"], 212.1, "application diversified_peak_mw")
    assert_money(
        application["network_upgrade_cost_usd"], 0.00, "application network_upgrade_cost_usd"
    )
    assert_money(application["study_fee_usd"], EXPECTED_STUDY_FEE_USD, "study_fee_usd")

    site = read_site(env["site"]["id"])
    assert_money(
        site["site_capital_commitment_usd"],
        EXPECTED_STUDY_FEE_USD,
        "site_capital_commitment_usd",
    )


def test_annual_volumetric_agreement_credits_curtailed_annual_generation():
    """Executing the annual-volumetric twin credits 1974000.0 MWh: the whole
    2100000 MWh of contracted solar output less the six percent solar curtailment,
    with the 1500000 MWh load-coincident subset stored but idle. The annual cost is
    struck from generation and strike price alone, so both twins price identically at
    87150000.00 even though they will credit materially different volumes.

    PRD §3.9: "Under `ANNUAL_VOLUMETRIC` accounting the whole contracted output counts subject to a technology curtailment haircut: `credited_coverage_mwh` is the annual generation multiplied by one minus the technology's curtailment factor, rounded to 3 decimal places, where solar is curtailed 6 percent at 0.06, wind 11 percent at 0.11, storage hybrids 4 percent at 0.04 and nuclear just 1 percent at 0.01."
    PRD §3.9: "A drafted agreement sits at `status` `DRAFT`, its `annual_cost_usd` already computed as the annual generation multiplied by the strike price rounded to 2 decimal places, and its `credited_coverage_mwh` at exactly 0 — a draft agreement never counts toward coverage."

    Design: Difficulty/dual_variant_calc/ppa_annual_volumetric_vs_hourly_matched_credit
    """
    program = open_program()
    volumetric, hourly = _solar_pair(program["id"])

    executed = execute_ppa(volumetric["id"])

    assert_status(executed, "EXECUTED", "annual-volumetric agreement")
    assert_mw(executed["credited_coverage_mwh"], 1974000.0, "credited_coverage_mwh")
    assert_money(executed["annual_cost_usd"], 87150000.00, "annual_cost_usd")
    assert_money(hourly["annual_cost_usd"], 87150000.00, "twin annual_cost_usd")

    refreshed = read_program(program["id"])
    assert_mw(
        refreshed["program_annual_load_mwh"],
        PROGRAM_ANNUAL_LOAD_MWH,
        "program_annual_load_mwh",
    )


def test_hourly_matched_agreement_credits_only_the_deliverable_coincident_volume():
    """The hourly-matched twin ignores both the 2100000 MWh annual figure and the
    solar curtailment, crediting 1470000.0 MWh — the 1500000 MWh coincident subset at
    a deliverability of 0.98. With both twins executed the program's coverage
    aggregates the two credited volumes against its 2365200.0 MWh annual load and
    reads 145.61 percent.

    PRD §3.9: "Under `HOURLY_MATCHED` accounting only load-coincident hours count: `credited_coverage_mwh` is the hourly-matched volume multiplied by an hourly deliverability factor of 0.98, rounded to 3 decimal places — and here it is the `annual_generation_mwh` and the technology curtailment that are ignored entirely."
    PRD §3.9: "The credited volumes of every agreement of that program whose `status` is `EXECUTED` are summed — drafts contribute exactly nothing to the numerator — multiplied by 100, divided by the program's `program_annual_load_mwh`, and rounded to 2 decimal places to give `renewable_coverage_pct`."

    Design: Difficulty/dual_variant_calc/ppa_annual_volumetric_vs_hourly_matched_credit
    """
    program = open_program()
    volumetric, hourly = _solar_pair(program["id"])

    execute_ppa(volumetric["id"])
    executed_hourly = execute_ppa(hourly["id"])

    assert_status(executed_hourly, "EXECUTED", "hourly-matched agreement")
    assert_mw(executed_hourly["credited_coverage_mwh"], 1470000.0, "credited_coverage_mwh")
    assert_money(executed_hourly["annual_cost_usd"], 87150000.00, "annual_cost_usd")

    refreshed = read_program(program["id"])
    assert_pct(refreshed["renewable_coverage_pct"], 145.61, "renewable_coverage_pct")


def test_screening_score_composes_five_capped_components_minus_a_hazard_penalty():
    """Site Alpha's ten measurements compose into 83.00: power 24.0 from 240 MW of
    headroom against a 300 MW target, fiber 15.0 at the three-route reference, water
    15.0, workforce 20.0 from a 0.8 availability ratio and land 15.0 from 300 acres,
    less the six-point MODERATE penalty that the largest of its three hazard indices
    selects. A sibling differing only in a flood index of 0.399 lands in the LOW tier
    and therefore scores 89.00 — no single component decides the result.

    PRD §3.2: "First, `hazard_tier` is set from the largest of the three hazard indices: `SEVERE` when that largest value is at least 0.70, `MODERATE` when it is at least 0.40 but below 0.70, and `LOW` otherwise."
    PRD §3.2: "The **hazard penalty** is then subtracted, and it depends on the tier just derived: 0 points for `LOW`, 6 points for `MODERATE` and 15 points for `SEVERE`."
    PRD §3.2: "None of the five components is rounded before the sum is taken."

    Design: Difficulty/combinatorial_formula/site_screening_score_five_component_weighted_composite
    """
    env = setup_screened_site()
    bravo = add_sibling_site(
        env,
        site={"name": "Site Bravo", "county": "Davie"},
        screening={"flood_hazard_index": 0.399},
    )

    alpha = read_site(env["site"]["id"])
    assert_status(alpha, "SCREENED", "Site Alpha")
    assert_site_screening_outputs(
        alpha, EXPECTED_SCREENING_SCORE_ALPHA, "MODERATE", workforce_ratio=0.8
    )
    assert_ratio(alpha["workforce_availability_ratio"], 0.8, "workforce_availability_ratio")

    assert_site_screening_outputs(bravo, 89.00, "LOW")

    basin = read_water_source(env["water_source"]["id"])
    assert_mw(
        basin["committed_annual_demand_mgal"], 500.0, "committed_annual_demand_mgal"
    )


def test_sibling_screening_refreshes_water_headroom_but_freezes_the_score():
    """Screening Site Bravo takes 250 Mgal of shared basin headroom, so Site Alpha's
    own `water_headroom_mgal` falls from 900.0 to 650.0 and its feasibility is
    re-tested inside that request. Its `screening_score` and `hazard_tier` are
    point-in-time artifacts, so both stay exactly at 83.00 and MODERATE rather than
    being re-derived against the smaller headroom.

    PRD §3.2: "When a later drought declaration or a sibling site's screening changes this site's water headroom, the `water_headroom_mgal` and `water_feasible` fields **are** brought up to date, but the `screening_score` and the `hazard_tier` frozen at screening time stay exactly as they were."
    PRD §3.3: "For a given site, the demand of every **other** site on the same basin whose `status` is `SCREENED` or `COMMITTED` is summed, and that total is subtracted from the basin's effective supply, with the result rounded to 3 decimal places, to give the site's `water_headroom_mgal`."

    Design: Difficulty/combinatorial_formula/site_screening_score_five_component_weighted_composite
    """
    env = setup_screened_site()
    before = read_site(env["site"]["id"])
    assert_mw(before["water_headroom_mgal"], 900.0, "Alpha water_headroom_mgal")

    bravo = add_sibling_site(
        env,
        site={"name": "Site Bravo", "county": "Davie"},
        screening={"flood_hazard_index": 0.399},
    )

    assert_mw(bravo["water_headroom_mgal"], 650.0, "Bravo water_headroom_mgal")
    assert bravo["water_feasible"] is True

    after = read_site(env["site"]["id"])
    assert_mw(after["water_headroom_mgal"], 650.0, "Alpha water_headroom_mgal")
    assert after["water_feasible"] is True
    assert_pct(
        after["screening_score"], EXPECTED_SCREENING_SCORE_ALPHA, "frozen screening_score"
    )
    assert after["hazard_tier"] == "MODERATE"
