"""Constants at their exact thresholds, filtered input sets and first-match rollups."""

from test_helpers import (
    EXPECTED_STUDY_FEE_USD,
    EXPECTED_UPGRADE_COST_USD,
    OPTION_APN_100,
    SCREEN_AIR_COOLED,
    SCREEN_EVAPORATIVE,
    TEST_USERS,
    add_sibling_site,
    api_client,
    assert_capacity_ledger,
    assert_clock_instant,
    assert_land_control,
    assert_money,
    assert_mw,
    assert_pct,
    assert_premium_ledger,
    assert_program_rollup,
    assert_ratio,
    assert_status,
    assert_version,
    commit_energization,
    create_energization_commitment_payload,
    declare_drought,
    disqualify_site,
    draft_application,
    exercise_option,
    file_company_round,
    make_utility_planner_headers,
    open_negotiation,
    read_application,
    read_option,
    read_program,
    read_site,
    read_utility,
    read_water_source,
    screen_site,
    set_clock,
    setup_committed_site,
    setup_draft_site,
    setup_reserved_application,
    setup_screened_site,
    sign_option,
    submit_application,
    validate_error,
    withdraw_application,
)

APN_200_SAME_WINDOW = {
    "parcel_apn": "APN-200",
    "phase_index": 2,
    "acres": 60,
    "option_premium_usd": 900000,
    "purchase_price_usd": 8000000,
    "premium_credit_pct": 0.5,
    "window_start": "2027-01-01T00:00:00Z",
    "window_end": "2027-12-31T00:00:00Z",
}
FLAT_SCORE_PACKAGE = dict(
    SCREEN_AIR_COOLED,
    transmission_headroom_mw=300,
    fiber_route_count=3,
    seismic_hazard_index=0.10,
    flood_hazard_index=0.20,
    wind_hazard_index=0.30,
    craft_labor_supply_index=2000,
    construction_peak_headcount=2000,
)
BOUNDARY_TERMS = {
    "sales_tax_exemption_pct": 1.0,
    "abatement_years": 1,
    "abatement_pct": 0.0,
    "jobs_commitment": 60,
}


def _two_fully_optioned_parcels_mid_window():
    """A 300-acre campus holding reserved capacity and two live options — 240 acres at a
    1,250,000 premium and 60 acres at 900,000 — with the clock inside both exclusivity
    windows so either may be exercised."""
    env = setup_reserved_application()
    env["first"] = sign_option(env["site"]["id"], **OPTION_APN_100)
    env["second"] = sign_option(env["site"]["id"], **APN_200_SAME_WINDOW)
    set_clock("2027-06-01T00:00:00Z")
    return env


def _three_submitted_applications_out_of_creation_order():
    """Three 50 MW applications created Alpha, Bravo, Charlie but submitted Charlie,
    Alpha, Bravo at three distinct logical-clock instants."""
    env = setup_screened_site(screening=FLAT_SCORE_PACKAGE)
    env["bravo"] = add_sibling_site(
        env, site={"name": "Site Bravo", "county": "Davie"}, screening=FLAT_SCORE_PACKAGE
    )
    env["charlie"] = add_sibling_site(
        env,
        site={"name": "Site Charlie", "county": "Iredell"},
        screening=FLAT_SCORE_PACKAGE,
    )
    for key, site_id in (
        ("alpha_application", env["site"]["id"]),
        ("bravo_application", env["bravo"]["id"]),
        ("charlie_application", env["charlie"]["id"]),
    ):
        env[key] = draft_application(site_id, env["utility"]["id"], requested_mw=50)
    for instant, key in (
        ("2026-08-05T00:00:00Z", "charlie_application"),
        ("2026-08-06T00:00:00Z", "alpha_application"),
        ("2026-08-07T00:00:00Z", "bravo_application"),
    ):
        set_clock(instant)
        submit_application(env[key]["id"])
    return env


def test_exercising_one_option_capitalizes_its_premium_and_credits_the_purchase():
    """Exercise credits half of the 1,250,000 premium against the 42,000,000 strike, so
    the buyer owes 41375000.00 and the premium moves from exposure into the capitalized
    bucket while its sibling's 900000.00 stays exposed — the conserved total never moves
    off 2150000.00. The exercised acreage still counts toward land control, so the campus
    stays `FULL`, and a second exercise is refused because the option is no longer
    `OPTIONED`.

    PRD §3.8: "On exercise the clock is stamped as `exercised_at`, `premium_credited_usd` becomes the option premium multiplied by the credit fraction rounded to 2 decimal places, and `net_purchase_usd` becomes the purchase price minus that credit, also rounded to 2 decimal places."
    PRD §3.8: "Three conditions apply: the option must be `OPTIONED`, otherwise `ERR_OPTION_INVALID_STATE`; the current logical clock must be **strictly before** `window_end`, since the window is half-open and a clock at or past that instant makes the option unexercisable, otherwise `ERR_OPTION_EXPIRED`; and the owning site's live interconnection application must already hold capacity, sitting in `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED`, otherwise `ERR_SITE_NOT_SCREENED` — the company does not buy land before the utility has reserved the power."
    PRD §3.8: "The premium moves from `option_exposure_usd` into `capitalized_premium_usd` with `premium_committed_total_usd` unchanged; the site's `land_control_pct`, then its `land_control_status`, then its `site_capital_commitment_usd` are recomputed in that order; the program's `full_land_control_site_count` and `program_status` are re-derived; and the option's `version` is incremented by one."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`."

    Design: Corner/calculations/option_exercise_credit_and_three_bucket_premium_ledger
    """
    env = _two_fully_optioned_parcels_mid_window()

    exercised = exercise_option(env["first"]["id"])

    assert_status(exercised, "EXERCISED", "APN-100 option")
    assert_money(exercised["premium_credited_usd"], 625000.00, "premium_credited_usd")
    assert_money(exercised["net_purchase_usd"], 41375000.00, "net_purchase_usd")
    assert_clock_instant(exercised["exercised_at"], "2027-06-01T00:00:00Z", "exercised_at")

    repeat = api_client.exercise_parcel_option(
        env["first"]["id"], TEST_USERS["director_headers"]
    )
    validate_error(repeat, "ERR_OPTION_INVALID_STATE", 409)

    sibling = read_option(env["second"]["id"])
    assert_status(sibling, "OPTIONED", "APN-200 option")
    assert_money(sibling["premium_credited_usd"], 0, "sibling premium_credited_usd")
    assert_money(sibling["net_purchase_usd"], 0, "sibling net_purchase_usd")

    program = read_program(env["program"]["id"])
    assert_premium_ledger(program, 900000.00, 0, 1250000.00, 2150000.00)
    assert program["full_land_control_site_count"] == 1

    site = read_site(env["site"]["id"])
    assert_land_control(site, 100.00, "FULL")
    assert_money(
        site["site_capital_commitment_usd"],
        EXPECTED_STUDY_FEE_USD + EXPECTED_UPGRADE_COST_USD + 41375000.00 + 900000.00,
        "site_capital_commitment_usd",
    )


def test_a_disqualified_siblings_demand_leaves_the_basin_input_set():
    """Headroom is computed over siblings that are `SCREENED` or `COMMITTED` only. While
    both campuses are screened, Site Alpha's 500 Mgal leaves Site Bravo just 400.0 of the
    900 Mgal permit and its 700 Mgal demand is infeasible; dropping Alpha removes that
    demand from the set entirely, restoring Bravo's headroom to the full 900.0 and
    flipping it to feasible. Bravo's score is not recomputed on the way — it stays at the
    76.57 its own screening froze.

    PRD §3.3: "For a given site, the demand of every **other** site on the same basin whose `status` is `SCREENED` or `COMMITTED` is summed, and that total is subtracted from the basin's effective supply, with the result rounded to 3 decimal places, to give the site's `water_headroom_mgal`."
    PRD §3.3: "Sites in `DRAFT` and sites that have been `DISQUALIFIED` consume no headroom at all and never appear in that sum."
    PRD §3.3: "The basin's own `committed_annual_demand_mgal` is the parallel figure computed over **all** its `SCREENED` and `COMMITTED` sites including the one under examination."
    PRD §3.3: "A basin's `effective_supply_mgal` is its annual permitted withdrawal multiplied by one minus its `stage_curtailment_pct`, rounded to 3 decimal places."
    PRD §3.2: "When a later drought declaration or a sibling site's screening changes this site's water headroom, the `water_headroom_mgal` and `water_feasible` fields **are** brought up to date, but the `screening_score` and the `hazard_tier` frozen at screening time stay exactly as they were."

    Design: Corner/calculations/water_headroom_excludes_disqualified_sibling_demand
    """
    env = setup_screened_site(
        screening=dict(SCREEN_EVAPORATIVE, annual_water_demand_mgal=500)
    )
    bravo = add_sibling_site(
        env,
        site={"name": "Site Bravo", "county": "Davie"},
        screening=dict(SCREEN_EVAPORATIVE, annual_water_demand_mgal=700),
    )

    before = read_site(bravo["id"])
    assert before["water_headroom_mgal"] == 400.0
    assert before["water_feasible"] is False
    assert_pct(before["screening_score"], 76.57, "Site Bravo screening_score")

    disqualify_site(env["site"]["id"], "LAND_ASSEMBLY_FAILED")

    after = read_site(bravo["id"])
    assert after["water_headroom_mgal"] == 900.0
    assert after["water_feasible"] is True
    assert_pct(after["screening_score"], 76.57, "Site Bravo screening_score")

    basin = read_water_source(env["water_source"]["id"])
    assert basin["committed_annual_demand_mgal"] == 700.0
    assert basin["effective_supply_mgal"] == 900.0
    assert basin["drought_stage"] == "NORMAL"


def test_each_drought_stage_curtails_the_same_permit_by_its_own_constant():
    """Four declarations walk the basin `NORMAL` to `STAGE_1` to `STAGE_2` to `STAGE_3`
    and back to `STAGE_1`, and the same 900 Mgal permit yields 810.0, 630.0, 405.0 and
    810.0 in turn — one lookup per stage, and the relaxing fourth declaration proves the
    stages are not a ratchet. Each declaration increments the basin's version, so it ends
    at 5, and the 250 Mgal campus stays feasible throughout because 250 fits even inside
    the harshest 405.0.

    PRD §3.3: "The curtailment fraction is a direct lookup on the current drought stage: `NORMAL` curtails nothing at 0.00, `STAGE_1` withholds a tenth of the permit at 0.10, `STAGE_2` withholds nearly a third at 0.30, and `STAGE_3` withholds more than half at 0.55."
    PRD §3.3: "Stages are not a ratchet: a declaration may advance the basin, relax it, or skip stages in either direction, so `NORMAL` to `STAGE_1`, `STAGE_1` to `STAGE_2`, `NORMAL` straight to `STAGE_2`, `STAGE_2` to `STAGE_3`, `STAGE_3` back to `STAGE_1` and `STAGE_2` back to `NORMAL` are all legal single declarations, and a basin may cycle from `NORMAL` up to `STAGE_2` and back to `NORMAL` over its lifetime."
    PRD §3.3: "The site's `water_feasible` flag is then true exactly when its own `annual_water_demand_mgal` is less than or equal to that headroom — equality is feasible, not marginal."
    PRD §3.3: "The basin's own `version` is incremented by one."

    Design: Corner/calculations/drought_stage_curtailment_constant_walk
    """
    env = setup_screened_site()

    expected = (
        ("STAGE_1", "2027-03-01T00:00:00Z", 0.10, 810.0),
        ("STAGE_2", "2027-05-01T00:00:00Z", 0.30, 630.0),
        ("STAGE_3", "2027-07-01T00:00:00Z", 0.55, 405.0),
        ("STAGE_1", "2027-11-01T00:00:00Z", 0.10, 810.0),
    )
    for stage, effective_date, curtailment, supply in expected:
        basin = declare_drought(env["water_source"]["id"], stage, effective_date)
        assert basin["drought_stage"] == stage
        assert_ratio(basin["stage_curtailment_pct"], curtailment, "stage_curtailment_pct")
        assert basin["effective_supply_mgal"] == supply
        site = read_site(env["site"]["id"])
        assert site["water_headroom_mgal"] == supply
        assert site["water_feasible"] is True

    assert basin["last_declaration_effective_date"] == "2027-11-01T00:00:00Z"
    assert_version(basin, 5, "Yadkin Basin")


def test_a_wage_premium_of_exactly_fifteen_percent_escapes_the_workforce_penalty():
    """The penalty is a strict comparison, so a campus paying exactly a fifteen percent
    premium keeps its whole 25-point workforce component and reaches the clamped ceiling
    of 100.00. Its twin, identical in every other measurement and one point of premium
    higher, has that component multiplied by 0.8 — losing exactly 5 points and landing on
    95.00. Both are air-cooled, so both take the full water credit without any headroom
    arithmetic.

    PRD §3.2: "The **workforce** component is worth up to 25 points: 25 multiplied by the workforce availability ratio capped at 1.0, and then — only when the wage premium is strictly greater than 0.15, that is strictly more than a fifteen percent premium over the prevailing craft wage — that component is multiplied by a wage penalty factor of 0.8."
    PRD §3.2: "A site whose annual water demand is exactly 0 — an air-cooled campus — earns the full 15 points outright."
    PRD §3.2: "The sum minus the penalty is finally clamped into the range 0.0 to 100.0 and rounded to 2 decimal places to give the score."

    Design: Corner/calculations/screening_score_wage_penalty_at_exact_threshold
    """
    env = setup_draft_site()
    twin = add_sibling_site(
        env, site={"name": "Site Bravo", "county": "Davie"}, screen=False
    )

    at_threshold = screen_site(
        env["site"]["id"], **dict(FLAT_SCORE_PACKAGE, wage_premium_pct=0.15)
    )
    past_threshold = screen_site(
        twin["id"], **dict(FLAT_SCORE_PACKAGE, wage_premium_pct=0.16)
    )

    assert_pct(at_threshold["screening_score"], 100.00, "Site Alpha screening_score")
    assert_pct(past_threshold["screening_score"], 95.00, "Site Bravo screening_score")

    for site, label in ((at_threshold, "Site Alpha"), (past_threshold, "Site Bravo")):
        assert site["hazard_tier"] == "LOW"
        assert_ratio(
            site["workforce_availability_ratio"],
            1.0000,
            f"{label} workforce_availability_ratio",
        )
        assert site["water_feasible"] is True

    assert read_site(env["site"]["id"])["water_headroom_mgal"] == 900.0


def test_a_capital_commitment_exactly_at_the_mid_tier_floor_takes_the_lower_rate():
    """The sales-tax tiers step *down* as investment grows and the mid floor is
    inclusive, so a commitment of exactly 500,000,000 is taxed at 5.50 percent for a
    17050000.00 benefit while one dollar less stays on 6.25 percent and earns the larger
    19374999.96. A one-year abatement at a zero fraction contributes nothing, isolating
    the tier arithmetic, and each 60-job commitment falls short of the hundred-job
    threshold so both are clawed back at the harsher 0.60 share.

    PRD §3.7: "First, the sales-tax benefit is tiered on the capital commitment, and the tiers move *downward* as the investment grows: the applicable rate is 6.25 percent, expressed as 0.0625, when the capital commitment is strictly below 500 million dollars; 5.50 percent, expressed as 0.0550, when it is strictly below 1.5 billion dollars; and 4.75 percent, expressed as 0.0475, at 1.5 billion dollars or above."
    PRD §3.7: "The `sales_tax_benefit_usd` is then the capital commitment multiplied by an equipment share of 0.62 — the fraction of the capital spend that is taxable equipment — multiplied by that rate, multiplied by the negotiated exemption fraction, and rounded to 2 decimal places."
    PRD §3.7: "Fourth, `npv_incentive_usd` is the sales-tax benefit plus the abatement present value, rounded to 2 decimal places, and `clawback_exposure_usd` is that total multiplied by a clawback share, rounded to 2 decimal places — where the share is the gentler 0.40 when the company has committed to at least 100 permanent jobs and the harsher 0.60 when it has committed to fewer."

    Design: Corner/calculations/sales_tax_tier_at_exact_mid_floor_boundary
    """
    env = setup_draft_site()
    twin = add_sibling_site(
        env, site={"name": "Site Bravo", "county": "Davie"}, screen=False
    )
    at_floor = open_negotiation(env["site"]["id"], "STATE")
    below_floor = open_negotiation(twin["id"], "STATE")

    on_the_floor = file_company_round(
        at_floor["id"], capex_commitment_usd=500000000, **BOUNDARY_TERMS
    )
    one_dollar_short = file_company_round(
        below_floor["id"], capex_commitment_usd=499999999, **BOUNDARY_TERMS
    )

    assert_money(
        on_the_floor["sales_tax_benefit_usd"], 17050000.00, "sales_tax_benefit_usd"
    )
    assert_money(on_the_floor["abatement_npv_usd"], 0.00, "abatement_npv_usd")
    assert_money(on_the_floor["npv_incentive_usd"], 17050000.00, "npv_incentive_usd")
    assert_money(
        on_the_floor["clawback_exposure_usd"], 10230000.00, "clawback_exposure_usd"
    )

    assert_money(
        one_dollar_short["sales_tax_benefit_usd"], 19374999.96, "sales_tax_benefit_usd"
    )
    assert_money(
        one_dollar_short["npv_incentive_usd"], 19374999.96, "npv_incentive_usd"
    )
    assert_money(
        one_dollar_short["clawback_exposure_usd"], 11624999.98, "clawback_exposure_usd"
    )

    for negotiation in (on_the_floor, one_dollar_short):
        assert_status(negotiation, "AUTHORITY_COUNTER_PENDING", "negotiation")
        assert negotiation["round_count"] == 1
        assert negotiation["last_party"] == "COMPANY"


def test_ninety_days_late_is_admissible_and_prices_the_slip_exactly():
    """The grace on the program's required date is inclusive, so a date 91 days past
    2029-06-30 is refused outright and leaves the application reserved with no committed
    date and no exposure, while exactly 90 days past is admitted. The slip then prices at
    250 dollars per day per megawatt across 90 days and 300 MW, which is 6750000.00, and
    the site is retiered `BREACHED` even though the commitment itself was legal.

    PRD §3.5: "Three temporal conditions must all hold: the date must fall at or after the application's own `window_start`; it must be at least the utility's `energization_lead_days` days after the current logical clock; and it must not be more than 90 days beyond the program's `required_energization_date`."
    PRD §3.5: "Otherwise the exposure is the delay in days multiplied by a penalty of 250 US dollars per day per megawatt, multiplied by the application's requested megawatts, rounded to 2 decimal places — a commitment that slips the full 90-day grace on a 300 MW request therefore prices at six million, seven hundred and fifty thousand dollars of exposure."
    PRD §3.5: "The owning site's `energization_risk_tier` is recomputed, and it becomes `BREACHED` whenever the committed date falls beyond the program's required date even though the commitment itself was admissible."

    Design: Corner/calculations/energization_delay_exposure_at_max_delay_boundary
    """
    env = setup_reserved_application()

    one_day_too_late = api_client.commit_energization(
        env["application"]["id"],
        create_energization_commitment_payload("2029-09-29T00:00:00Z"),
        make_utility_planner_headers(env["utility"]["id"]),
    )
    validate_error(one_day_too_late, "ERR_ENERGIZATION_DEADLINE_MISSED", 409)

    refused = read_application(env["application"]["id"])
    assert_status(refused, "CAPACITY_RESERVED", "application")
    assert refused["committed_energization_date"] is None
    assert_money(refused["delay_exposure_usd"], 0, "delay_exposure_usd")

    committed = commit_energization(
        env["application"]["id"], env["utility"]["id"], "2029-09-28T00:00:00Z"
    )

    assert_status(committed, "ENERGIZATION_COMMITTED", "application")
    assert committed["committed_energization_date"] == "2029-09-28T00:00:00Z"
    assert_money(committed["delay_exposure_usd"], 6750000.00, "delay_exposure_usd")
    assert_mw(committed["reserved_mw"], 300, "reserved_mw")

    assert read_site(env["site"]["id"])["energization_risk_tier"] == "BREACHED"
    assert_capacity_ledger(read_utility(env["utility"]["id"]), 300.0, 200.0)
    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SCREENING",
        committed_load_mw=300,
    )


def test_queue_rank_follows_submission_time_and_closes_the_gap_on_withdrawal():
    """The three applications were created Alpha, Bravo, Charlie but submitted Charlie,
    Alpha, Bravo, and the ranking follows the submission clock rather than creation order,
    so Charlie holds position 1 and Alpha only 2. Withdrawing the middle application does
    not leave a hole at 2: the survivors re-rank to the dense 1 and 2, the withdrawn row
    drops out of the ranking to 0, and its 60000.00 study fee leaves its site's capital
    aggregate with it.

    PRD §3.4: "Under a `FIRST_COME_FIRST_SERVED` policy those applications are ordered by `submitted_at` ascending, with `created_at` ascending as the tie-break."
    PRD §3.4: "The `queue_position` written back is the 1-based index in that ordering, and positions are dense and contiguous, so a withdrawal closes the gap behind it rather than leaving a hole."
    PRD §3.4: "Applications in `DRAFT` or `WITHDRAWN` are outside the ranking entirely and carry a `queue_position` of 0."

    Design: Corner/calculations/queue_positions_dense_and_chronological_after_withdrawal
    """
    env = _three_submitted_applications_out_of_creation_order()

    charlie = read_application(env["charlie_application"]["id"])
    assert charlie["queue_position"] == 1
    assert_clock_instant(charlie["submitted_at"], "2026-08-05T00:00:00Z", "submitted_at")
    assert read_application(env["alpha_application"]["id"])["queue_position"] == 2
    assert read_application(env["bravo_application"]["id"])["queue_position"] == 3

    withdrawn = withdraw_application(
        env["alpha_application"]["id"],
        "Site deprioritized after the labor market review.",
    )

    assert_status(withdrawn, "WITHDRAWN", "Site Alpha's application")
    assert withdrawn["queue_position"] == 0
    assert read_application(env["charlie_application"]["id"])["queue_position"] == 1
    assert read_application(env["bravo_application"]["id"])["queue_position"] == 2

    assert_capacity_ledger(read_utility(env["utility"]["id"]), 0, 500.0)
    assert_money(
        read_site(env["site"]["id"])["site_capital_commitment_usd"],
        0,
        "site_capital_commitment_usd",
    )


def test_an_impaired_committed_site_reports_stalled_not_energization_secured():
    """The committed campus secures its energization date, which would ordinarily carry
    the program to `ENERGIZATION_SECURED` — but the date is 90 days late, so the site is
    `BREACHED`, and the rollup tests impairment before it tests energization. The program
    therefore reports `STALLED` while simultaneously reporting the 300 MW of committed
    load that the same commitment produced, with land control and water both healthy so
    the breach is the only impairment in play.

    PRD §3.10: "The status is `STALLED` when a committed site exists and that site is impaired — meaning its `land_control_status` is anything other than `FULL`, **or** its `water_feasible` flag is false, **or** its `energization_risk_tier` is `BREACHED`."
    PRD §3.10: "Because the impairment test is evaluated **before** the energization test, a site that is energization-committed but has lost its land control or its water reports `STALLED` rather than `ENERGIZATION_SECURED`."
    PRD §3.10: "Alongside the status, `committed_load_mw` is re-derived as the sum of `requested_mw` over the applications of this program's sites whose status is `ENERGIZATION_COMMITTED`, and every re-derivation that changes the program increments the program's `version` by one."

    Design: Corner/calculations/program_status_stalled_precedes_energization_secured
    """
    env = setup_committed_site()
    assert_status(read_site(env["site"]["id"]), "COMMITTED", "Site Alpha")
    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SITE_COMMITTED",
        committed_load_mw=0,
    )

    committed = commit_energization(
        env["application"]["id"], env["utility"]["id"], "2029-09-28T00:00:00Z"
    )

    assert_status(committed, "ENERGIZATION_COMMITTED", "application")
    assert_money(committed["delay_exposure_usd"], 6750000.00, "delay_exposure_usd")

    site = read_site(env["site"]["id"])
    assert site["energization_risk_tier"] == "BREACHED"
    assert_land_control(site, 100.00, "FULL")
    assert site["water_feasible"] is True

    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="STALLED",
        committed_load_mw=300,
        renewable_coverage_pct=80.0,
        full_land_control_site_count=1,
    )
