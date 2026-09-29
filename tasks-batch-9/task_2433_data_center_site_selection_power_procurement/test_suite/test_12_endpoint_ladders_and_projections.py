"""The whole ladder to a committed site, and the nested reads that project it."""

from test_helpers import (
    CHAIR_USER_ID,
    EXPECTED_DIVERSIFIED_PEAK_MW,
    EXPECTED_NAMEPLATE_PEAK_MW,
    PROGRAM_ANNUAL_LOAD_MWH,
    TEST_USERS,
    add_site,
    api_client,
    assert_land_control,
    assert_load_study_shape,
    assert_money,
    assert_mw,
    assert_pagination_meta,
    assert_pct,
    assert_program_rollup,
    assert_status,
    assert_version,
    assert_version_unchanged,
    commit_site,
    decide_zoning,
    draft_ppa,
    file_load_study,
    file_zoning,
    list_load_studies,
    list_program_ppas,
    read_program,
    read_site,
    screen_site,
    setup_commit_ready_site,
    setup_executed_ppa_at_coverage_floor,
    setup_screened_site,
    setup_studied_application,
    validate_error,
)

# The canonical capital commitment of the commit-ready campus: a 360000.00 study
# fee, a 26945136.00 network upgrade, 2975000.00 of mitigation, 446250.00 of
# conditions escrow and 2150000.00 of premiums on options still OPTIONED.
EXPECTED_SITE_CAPITAL_USD = 32876386.00

# A second campus on the same program, basin and utility: low hazard on every
# index and air-cooled, so it draws no shared basin headroom.
BRAVO_SITE = {"name": "Site Bravo", "county": "Davie", "gross_acres": 300}
BRAVO_SCREENING = {
    "transmission_headroom_mw": 300,
    "fiber_route_count": 3,
    "seismic_hazard_index": 0.10,
    "flood_hazard_index": 0.20,
    "wind_hazard_index": 0.30,
    "craft_labor_supply_index": 2000,
    "construction_peak_headcount": 2000,
    "wage_premium_pct": 0.10,
    "cooling_type": "AIR_COOLED",
    "annual_water_demand_mgal": 0,
}
# A docket modelled exactly at the ordinance ceiling, offering no mitigation.
BRAVO_DOCKET = {
    "jurisdiction": "Davie County Board",
    "hearing_date": "2027-04-15T00:00:00Z",
    "noise_limit_dba": 55,
    "projected_noise_dba": 55,
    "visual_mitigation_tier": "NONE",
}

# The first load study round: 250 MW nameplate against 226.0 MW diversified.
FIRST_ROUND = {
    "it_load_mw": 200,
    "cooling_load_mw": 40,
    "ancillary_load_mw": 10,
    "diversity_factor": 0.90,
}
FIRST_ROUND_NAMEPLATE_MW = 250.0
FIRST_ROUND_DIVERSIFIED_MW = 226.0

# A solar agreement left in DRAFT: priced, but crediting nothing.
DRAFT_SOLAR = {
    "counterparty_name": "Sunbelt Solar I",
    "technology": "SOLAR",
    "contracted_capacity_mw": 900,
    "annual_generation_mwh": 2100000,
    "hourly_matched_mwh": 1500000,
    "strike_price_usd_per_mwh": 41.50,
    "matching_mode": "ANNUAL_VOLUMETRIC",
    "delivery_start": "2029-07-01T00:00:00Z",
    "delivery_end": "2044-06-30T00:00:00Z",
}
DRAFT_SOLAR_ANNUAL_COST_USD = 87150000.00
EXECUTED_CREDITED_MWH = 1892160.0
EXECUTED_ANNUAL_COST_USD = 78840000.00


def _add_bravo(env: dict) -> dict:
    """A sibling campus screened on the same program and approved by its own board
    with no mitigation demanded of it."""
    bravo = add_site(
        env["program"]["id"],
        env["utility"]["id"],
        env["water_source"]["id"],
        **BRAVO_SITE,
    )
    bravo = screen_site(bravo["id"], **BRAVO_SCREENING)
    docket = file_zoning(bravo["id"], **BRAVO_DOCKET)
    decision = decide_zoning(
        docket["id"], "APPROVED_WITH_CONDITIONS", "No mitigation required."
    )
    return {"site": bravo, "zoning": decision}


def test_the_full_commit_ladder_settles_on_one_capital_number():
    """Every gate of the commitment satisfied at once — a screened campus on a moderate
    hazard tier, an approved docket, a ratified state term sheet, both parcels optioned,
    feasible water and executed renewables — and the act itself produces one number the
    committee can read: six sources aggregated into 32876386.00 inside the 60000000
    ceiling, with the program's projection following in the same breath.

    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`. The total is rounded to 2 decimal places. Premiums on `LAPSED` and `RELEASED` options are sunk money and are deliberately excluded."
    PRD §3.10: "On success the site's `status` becomes `COMMITTED`, the acting operator is stamped as `committed_by_user_id` — null until that moment — the capital commitment is recomputed and compared against the ceiling, the program moves `SCREENING` to `SITE_COMMITTED`, and the site's `version` is incremented by one."
    PRD §3.8: "The acreage of every option of that site whose `status` is `OPTIONED` or `EXERCISED` is summed, multiplied by 100, divided by the site's `gross_acres`, capped at 100.0 and rounded to 2 decimal places to give `land_control_pct` — so a campus that has optioned more acreage than its gross footprint still reports 100.00 rather than more. The `land_control_status` follows directly: `FULL` when the percentage is at or above 100, `NONE` when it is exactly 0, and `PARTIAL` at any value between. The program's `full_land_control_site_count` then counts its sites whose `status` is `DRAFT`, `SCREENED` or `COMMITTED` and whose land control status is `FULL`."
    PRD §3.10: "Alongside the status, `committed_load_mw` is re-derived as the sum of `requested_mw` over the applications of this program's sites whose status is `ENERGIZATION_COMMITTED`, and every re-derivation that changes the program increments the program's `version` by one."

    Design: Corner/endpoints/full_ladder_commit_then_second_site_blocked
    """
    env = setup_commit_ready_site()

    # The capital total is already assembled before the commitment is attempted.
    assert_money(
        env["site"]["site_capital_commitment_usd"],
        EXPECTED_SITE_CAPITAL_USD,
        "site_capital_commitment_usd before the commitment",
    )
    assert_status(env["site"], "SCREENED", "the site before its commitment")
    assert env["site"]["committed_by_user_id"] is None

    committed = commit_site(env["site"]["id"])

    assert_status(committed, "COMMITTED", "the committed site")
    assert committed["committed_by_user_id"] == CHAIR_USER_ID, (
        "the operator who committed the site is stamped as committed_by_user_id"
    )
    assert_money(
        committed["site_capital_commitment_usd"],
        EXPECTED_SITE_CAPITAL_USD,
        "site_capital_commitment_usd after the commitment",
    )
    assert_land_control(committed, 100.00, "FULL")
    assert_version(committed, env["site"]["version"] + 1, "the committed site")

    program = read_program(env["program"]["id"])
    assert_program_rollup(
        program,
        program_status="SITE_COMMITTED",
        committed_load_mw=0,
        full_land_control_site_count=1,
    )


def test_a_second_screened_site_is_refused_by_the_single_committed_site_gate():
    """Site Bravo is approved by its own board and short of every later gate — no
    options, no application, no ratified incentives — yet the refusal names the one
    committed sibling rather than its own missing land control, because the
    single-committed-site gate sits one rung above land control. Bravo's own docket shows
    why nothing is demanded of it acoustically: modelled exactly at the ordinance ceiling,
    its excess floors at 0, so the ladder stops at `NONE` and both money figures are zero,
    leaving its capital commitment at zero as well.

    PRD §3.10: "No other site of the same program may already be `COMMITTED`, else `ERR_SITE_COMMITMENT_EXISTS`. The site's `land_control_pct` must be at least 100, because a partially optioned campus cannot be committed, else `ERR_LAND_CONTROL_INCOMPLETE`."
    PRD §2.11: "On a site commitment, the ten domain gates fire in the order segregation of duties, hazard prohibition, zoning approval, single-committed-site, land control, ratified state incentives, water sufficiency, renewable coverage, capital ceiling — after the site's own state has been checked — so a caller who is both the screener and short of land control learns about the duty conflict first."
    PRD §3.6: "Step two computes `noise_excess_dba` as the modelled noise minus the ordinance limit, floored at 0, so a campus modelled at or below the limit has no excess. Step three selects the `required_mitigation_tier` on a first-match-wins ladder in which either driver can escalate the tier on its own: the tier is `FULL_ENCLOSURE` when the noise excess is at least 10 dBA **or** the weighted opposition score is at least 12; failing that it is `BERM_AND_SCREENING` when the noise excess is at least 5 dBA **or** the score is at least 6; failing that it is `BERM` when the noise excess is strictly greater than 0 **or** the score is at least 3; and otherwise it is `NONE`. Step four prices that tier as `mitigation_cost_usd`: a tier base of 0 for `NONE`, 750,000 dollars for `BERM`, 2,100,000 dollars for `BERM_AND_SCREENING` and 5,400,000 dollars for `FULL_ENCLOSURE`, plus a per-decibel adder of 125,000 dollars applied to the **acoustic excess only** and never to the raw noise figures, with the total rounded to 2 decimal places. Step five sets the escrow the board will hold, and the crucial subtlety is that the escrow percentage is tiered on the **cost computed in step four**, not on the tier chosen in step three: the percentage is 0.00 when the cost is exactly zero, one tenth at 0.10 when the cost is strictly below 1,000,000 dollars, fifteen hundredths at 0.15 when the cost is strictly below 4,000,000 dollars, and one fifth at 0.20 otherwise."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`."

    Design: Corner/endpoints/full_ladder_commit_then_second_site_blocked
    """
    env = setup_commit_ready_site()
    bravo = _add_bravo(env)

    assert_status(bravo["zoning"], "APPROVED_WITH_CONDITIONS", "Bravo's docket")
    assert bravo["zoning"]["noise_excess_dba"] == 0, (
        "a campus modelled at the ordinance ceiling carries no acoustic excess"
    )
    assert bravo["zoning"]["required_mitigation_tier"] == "NONE"
    assert_money(bravo["zoning"]["mitigation_cost_usd"], 0.00, "mitigation_cost_usd")
    assert_money(bravo["zoning"]["conditions_escrow_usd"], 0.00, "conditions_escrow_usd")

    committed = commit_site(env["site"]["id"])
    assert_status(committed, "COMMITTED", "Site Alpha")

    before = read_site(bravo["site"]["id"])
    validate_error(
        api_client.commit_candidate_site(
            bravo["site"]["id"], TEST_USERS["chair_headers"]
        ),
        "ERR_SITE_COMMITMENT_EXISTS",
        409,
    )

    after = read_site(bravo["site"]["id"])
    assert_status(after, "SCREENED", "Site Bravo after the refusal")
    assert after["committed_by_user_id"] is None
    assert_land_control(after, 0.00, "NONE")
    assert_money(
        after["site_capital_commitment_usd"],
        0.00,
        "Bravo's site_capital_commitment_usd",
    )
    assert_version_unchanged(before, after, "Site Bravo")

    # The refusal leaves the committed sibling and the program projection alone.
    assert_status(read_site(env["site"]["id"]), "COMMITTED", "Site Alpha")
    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SITE_COMMITTED",
        full_land_control_site_count=1,
    )


def test_the_load_study_rounds_page_in_order_with_both_load_views():
    """Two rounds against one application, read one page at a time through the only
    channel the contract offers for study rows. Each page carries its own round with both
    views of the same load — the plain sum and the coincident view with cooling held at
    its 0.85 floor — the window meta counts both rows behind a page of one, and neither
    row admits a `version` or an `updated_at`.

    PRD §2.5: "The load-study listing deserves particular attention: because study rows have no top-level collection of their own, listing them under their application is the only discovery channel for them."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a subsection states otherwise. Where two rows carry the same `created_at`, the row that was inserted first sorts first, so ordering is total and repeatable. The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`: `total_count` counts the rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."
    PRD §3.4: "The study is appended to its application, recording the `application_id` it belongs to and a 1-based `study_round` equal to the owning application's round count after the append, and the operator's identifier is stamped as `filed_by_user_id`."
    PRD §3.4: "The `nameplate_peak_mw` figure is the plain arithmetic sum of the IT, cooling and ancillary components: the diversity factor and the cooling floor are ignored entirely, and this is the figure the developer originally requested capacity against. The `diversified_peak_mw` figure is the utility's coincident view: the IT component is multiplied by the diversity factor, the cooling component is multiplied by whichever is larger of the diversity factor and a cooling floor of 0.85 so that cooling load never diversifies below that floor, the ancillary component is taken undiversified at full value, the three products are added, and the total is rounded to 3 decimal places."
    PRD §2.4: "Load study rows are the single exception. A study, once filed, is an immutable historical artifact: it carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all, and neither field should appear in its representation."

    Design: Corner/endpoints/nested_list_reads_expose_derived_projections
    """
    env = setup_studied_application(load_study=FIRST_ROUND)
    application_id = env["application"]["id"]
    file_load_study(application_id, env["utility"]["id"])

    first_page = list_load_studies(application_id, {"limit": 1, "offset": 0})
    assert_pagination_meta(first_page["meta"], 1, 0, 2, True)
    assert len(first_page["data"]) == 1
    round_one = first_page["data"][0]
    assert round_one["study_round"] == 1
    assert round_one["application_id"] == application_id
    assert_mw(round_one["nameplate_peak_mw"], FIRST_ROUND_NAMEPLATE_MW, "nameplate round 1")
    assert_mw(
        round_one["diversified_peak_mw"], FIRST_ROUND_DIVERSIFIED_MW, "diversified round 1"
    )
    assert_load_study_shape(round_one)

    second_page = list_load_studies(application_id, {"limit": 1, "offset": 1})
    assert_pagination_meta(second_page["meta"], 1, 1, 2, False)
    assert len(second_page["data"]) == 1
    round_two = second_page["data"][0]
    assert round_two["study_round"] == 2
    assert_mw(
        round_two["nameplate_peak_mw"], EXPECTED_NAMEPLATE_PEAK_MW, "nameplate round 2"
    )
    assert_mw(
        round_two["diversified_peak_mw"],
        EXPECTED_DIVERSIFIED_PEAK_MW,
        "diversified round 2",
    )
    assert_load_study_shape(round_two)

    both = list_load_studies(application_id)
    assert [row["study_round"] for row in both["data"]] == [1, 2], (
        "the rounds list in the order they were filed"
    )
    assert [row["id"] for row in both["data"]] == [round_one["id"], round_two["id"]]


def test_the_program_agreement_listing_credits_only_executed_volumes():
    """One program, two agreements, and the listing separates the priced from the
    credited: both rows carry an annual cost from the moment they are drafted, but only
    the executed row credits coverage, and the filtered read counts one row where the
    unfiltered read counts two. The program's coverage percentage follows from the
    executed row alone, measured against the annual load its target derives.

    PRD §3.1: "From the load target the system immediately derives `program_annual_load_mwh`, the denominator against which all renewable procurement is later measured: the target load is multiplied by the 8,760 hours in a year and then by a program load factor of 0.90, and the result is rounded to 3 decimal places."
    PRD §3.9: "A drafted agreement sits at `status` `DRAFT`, its `annual_cost_usd` already computed as the annual generation multiplied by the strike price rounded to 2 decimal places, and its `credited_coverage_mwh` at exactly 0 — a draft agreement never counts toward coverage."
    PRD §3.9: "Under `ANNUAL_VOLUMETRIC` accounting the whole contracted output counts subject to a technology curtailment haircut: `credited_coverage_mwh` is the annual generation multiplied by one minus the technology's curtailment factor, rounded to 3 decimal places, where solar is curtailed 6 percent at 0.06, wind 11 percent at 0.11, storage hybrids 4 percent at 0.04 and nuclear just 1 percent at 0.01."
    PRD §3.9: "The credited volumes of every agreement of that program whose `status` is `EXECUTED` are summed — drafts contribute exactly nothing to the numerator — multiplied by 100, divided by the program's `program_annual_load_mwh`, and rounded to 2 decimal places to give `renewable_coverage_pct`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`: `total_count` counts the rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."

    Design: Corner/endpoints/nested_list_reads_expose_derived_projections
    """
    env = setup_screened_site()
    program_id = env["program"]["id"]

    draft = draft_ppa(program_id, **DRAFT_SOLAR)
    assert_status(draft, "DRAFT", "the solar agreement")
    executed = setup_executed_ppa_at_coverage_floor(program_id)
    assert_status(executed, "EXECUTED", "the storage-hybrid agreement")

    executed_page = list_program_ppas(program_id, {"status": "EXECUTED"})
    assert_pagination_meta(executed_page["meta"], 10, 0, 1, False)
    assert [row["id"] for row in executed_page["data"]] == [executed["id"]]
    assert_mw(
        executed_page["data"][0]["credited_coverage_mwh"],
        EXECUTED_CREDITED_MWH,
        "credited_coverage_mwh of the executed agreement",
    )
    assert_money(
        executed_page["data"][0]["annual_cost_usd"],
        EXECUTED_ANNUAL_COST_USD,
        "annual_cost_usd of the executed agreement",
    )

    all_page = list_program_ppas(program_id)
    assert_pagination_meta(all_page["meta"], 10, 0, 2, False)
    drafted_row = next(row for row in all_page["data"] if row["id"] == draft["id"])
    assert_mw(
        drafted_row["credited_coverage_mwh"],
        0,
        "credited_coverage_mwh of the drafted agreement",
    )
    assert_money(
        drafted_row["annual_cost_usd"],
        DRAFT_SOLAR_ANNUAL_COST_USD,
        "annual_cost_usd of the drafted agreement",
    )

    program = read_program(program_id)
    assert_mw(
        program["program_annual_load_mwh"],
        PROGRAM_ANNUAL_LOAD_MWH,
        "program_annual_load_mwh",
    )
    assert_pct(program["renewable_coverage_pct"], 80.0, "renewable_coverage_pct")
