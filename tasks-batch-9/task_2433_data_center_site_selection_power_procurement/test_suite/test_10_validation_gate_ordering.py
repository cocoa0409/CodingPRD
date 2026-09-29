"""Uniqueness scopes, interval admission, and the fixed ladders behind each refusal."""

from test_helpers import (
    EXPECTED_CONDITIONS_ESCROW_USD,
    EXPECTED_MITIGATION_COST_USD,
    EXPECTED_STUDY_FEE_USD,
    EXPECTED_UPGRADE_COST_USD,
    INITIAL_CLOCK_UTC,
    OPTION_APN_100,
    TEST_USERS,
    add_sibling_site,
    api_client,
    assert_capacity_ledger,
    assert_land_control,
    assert_money,
    assert_mw,
    assert_premium_ledger,
    assert_program_rollup,
    assert_site_screening_outputs,
    assert_status,
    assert_version,
    assert_version_unchanged,
    create_incentive_negotiation_payload,
    create_interconnection_application_payload,
    create_parcel_option_payload,
    create_power_purchase_agreement_payload,
    create_zoning_application_payload,
    create_zoning_decision_payload,
    decide_zoning,
    declare_drought,
    draft_application,
    file_load_study,
    file_zoning,
    list_applications,
    list_options,
    list_site_negotiations,
    list_site_zoning,
    make_chair_headers,
    make_utility_planner_headers,
    open_negotiation,
    read_application,
    read_option,
    read_program,
    read_site,
    read_utility,
    reserve_capacity,
    set_clock,
    setup_approved_zoning,
    setup_draft_site,
    setup_executed_ppa_at_coverage_floor,
    setup_ratified_state_negotiation,
    setup_screened_site,
    setup_submitted_application,
    sign_option,
    site_version,
    validate_error,
)

APN_200_EIGHT_MILLION = {
    "parcel_apn": "APN-200",
    "phase_index": 2,
    "acres": 60,
    "option_premium_usd": 900000,
    "purchase_price_usd": 8000000,
    "premium_credit_pct": 0.5,
    "window_start": "2027-01-01T00:00:00Z",
    "window_end": "2027-12-31T00:00:00Z",
}
WHOLE_CAMPUS_OPTION = dict(OPTION_APN_100, acres=300)
BERM_DOCKET = {
    "noise_limit_dba": 55,
    "projected_noise_dba": 62,
    "visual_mitigation_tier": "BERM",
}
FIRST_STUDY = {
    "it_load_mw": 200,
    "cooling_load_mw": 40,
    "ancillary_load_mw": 10,
    "diversity_factor": 0.90,
}
RESTUDY = {
    "it_load_mw": 240,
    "cooling_load_mw": 66,
    "ancillary_load_mw": 12,
    "diversity_factor": 0.92,
}
TIGHT_BUDGET_PROGRAM = {"capital_budget_usd": 5000000}


def _read_docket(site_id, zoning_application_id):
    """Re-read a docket through its site's nested listing, the only read the PRD
    exposes for a zoning application."""
    for item in list_site_zoning(site_id)["data"]:
        if item["id"] == zoning_application_id:
            return item
    raise AssertionError(f"docket {zoning_application_id} is not listed under its site")


def _site_with_one_child_of_each_kind():
    """Screened Site Alpha carrying one DRAFT application, one SUBMITTED docket and
    one STATE negotiation — one of every child a site may hold."""
    env = setup_screened_site()
    env["application"] = draft_application(env["site"]["id"], env["utility"]["id"])
    env["zoning"] = file_zoning(
        env["site"]["id"], **dict(BERM_DOCKET, projected_noise_dba=57)
    )
    env["negotiation"] = open_negotiation(env["site"]["id"], "STATE")
    return env


def _two_dockets_offering_different_mitigation():
    """Two DRAFT campuses each facing a 7 dBA excess, one offering a berm alone and
    the other offering berm and screening."""
    env = setup_draft_site()
    env["bravo"] = add_sibling_site(
        env, site={"name": "Site Bravo", "county": "Davie"}, screen=False
    )
    env["berm"] = file_zoning(env["site"]["id"], **BERM_DOCKET)
    env["berm_and_screening"] = file_zoning(
        env["bravo"]["id"],
        jurisdiction="Davie County Board",
        hearing_date="2027-03-16T00:00:00Z",
        noise_limit_dba=55,
        projected_noise_dba=62,
        visual_mitigation_tier="BERM_AND_SCREENING",
    )
    return env


def _commit_attempt(site_id):
    return api_client.commit_candidate_site(site_id, make_chair_headers())


def _site_on_a_five_million_budget():
    """Screened Site Alpha under a 5,000,000 ceiling with no docket, no options, no
    negotiation and no agreement: every commit gate from zoning onward is unmet."""
    return setup_screened_site(program=TIGHT_BUDGET_PROGRAM)


def test_a_second_application_docket_or_state_negotiation_is_refused_per_site():
    """Each of the three per-site uniqueness rules answers with its own error id, and
    each is scoped differently: the application rule counts every row that is not
    withdrawn, the zoning rule counts every row whatever its status, and the
    negotiation rule counts only rows at the same authority tier — which is why the
    same site accepts a `LOCAL` term sheet alongside its `STATE` one and ends with two
    negotiations against one application and one docket.

    PRD §3.4: "A site may hold at most one application that is not `WITHDRAWN` — a second live application is refused with `ERR_DUPLICATE_APPLICATION` — and the site itself must be in `DRAFT`, `SCREENED` or `COMMITTED`, never `DISQUALIFIED`."
    PRD §3.6: "A site may hold at most one zoning application regardless of that application's status, so a second filing is refused with `ERR_DUPLICATE_ZONING_APPLICATION`, and the site must not be `DISQUALIFIED`."
    PRD §3.7: "A site may hold at most one negotiation per authority tier, so a second `STATE` negotiation on the same site is refused with `ERR_DUPLICATE_NEGOTIATION` while a `LOCAL` one alongside it is perfectly legitimate, and the site itself must be in `DRAFT`, `SCREENED` or `COMMITTED` rather than `DISQUALIFIED`, otherwise `ERR_SITE_INVALID_STATE`."

    Design: Corner/validations/duplicate_children_rejected_per_site
    """
    env = _site_with_one_child_of_each_kind()
    site_id = env["site"]["id"]

    second_application = api_client.create_interconnection_application(
        create_interconnection_application_payload(
            site_id,
            env["utility"]["id"],
            requested_mw=120,
            window_start="2029-02-01T00:00:00Z",
            window_end="2029-11-30T00:00:00Z",
        ),
        TEST_USERS["analyst_headers"],
    )
    validate_error(second_application, "ERR_DUPLICATE_APPLICATION", 409)

    second_docket = api_client.create_zoning_application(
        create_zoning_application_payload(
            site_id,
            hearing_date="2027-06-15T00:00:00Z",
            noise_limit_dba=55,
            projected_noise_dba=56,
            visual_mitigation_tier="BERM",
        ),
        TEST_USERS["analyst_headers"],
    )
    validate_error(second_docket, "ERR_DUPLICATE_ZONING_APPLICATION", 409)

    second_state = api_client.create_incentive_negotiation(
        create_incentive_negotiation_payload(
            site_id, "STATE", counterparty_name="NC Economic Investment Committee"
        ),
        TEST_USERS["negotiator_headers"],
    )
    validate_error(second_state, "ERR_DUPLICATE_NEGOTIATION", 409)

    local = open_negotiation(
        site_id, "LOCAL", counterparty_name="Rowan County Commission"
    )
    assert local["authority_level"] == "LOCAL"
    assert_status(local, "DRAFT", "the LOCAL negotiation")

    assert list_applications({"site_id": site_id})["meta"]["total_count"] == 1
    assert list_site_zoning(site_id)["meta"]["total_count"] == 1
    assert list_site_negotiations(site_id)["meta"]["total_count"] == 2


def test_a_degenerate_window_a_reversed_delivery_term_and_a_backdated_option():
    """Interval ordering is strict, so an application window whose end equals its
    start is as inadmissible as an agreement whose delivery term runs backwards, and
    both answer `ERR_INVALID_WINDOW`. An option is held to a second, separate rule
    against the clock: a window opening one day before the 2026-08-01 startup instant
    is backdated, while a window opening exactly on it is admitted — and only that
    admitted option touches the site, which advances by a single version.

    PRD §2.6: "In all three interval-bearing resources the end must be strictly after the start: an interconnection application's `window_end` after its `window_start`, a power purchase agreement's `delivery_end` after its `delivery_start`, and a land option's `window_end` after its `window_start`."
    PRD §2.6: "A violation is rejected with `ERR_INVALID_WINDOW`."
    PRD §2.6: "A new land option additionally may not be backdated: its `window_start` may not fall earlier than the current logical clock, and an attempt to do so is rejected with `ERR_OPTION_WINDOW_BACKDATED`."
    PRD §2.6: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must continue to read that instant until it is explicitly moved; it must never fall back to the host's wall clock."
    PRD §3.8: "Signing also increments the addressed site's `version` by one — which is precisely why the next writer needs a fresh `expected_site_version` — moves the program's `option_exposure_usd` and `premium_committed_total_usd`, re-derives `program_status`, and recomputes the site's `site_capital_commitment_usd`."

    Design: Corner/validations/interval_ordering_and_backdated_option_window
    """
    env = setup_draft_site()
    opening_version = site_version(env["site"]["id"])

    empty_window = api_client.create_interconnection_application(
        create_interconnection_application_payload(
            env["site"]["id"],
            env["utility"]["id"],
            window_start="2029-01-01T00:00:00Z",
            window_end="2029-01-01T00:00:00Z",
        ),
        TEST_USERS["analyst_headers"],
    )
    validate_error(empty_window, "ERR_INVALID_WINDOW", 422)

    reversed_delivery = api_client.create_power_purchase_agreement(
        create_power_purchase_agreement_payload(
            env["program"]["id"],
            counterparty_name="Sunbelt Solar I",
            technology="SOLAR",
            contracted_capacity_mw=900,
            annual_generation_mwh=2100000,
            strike_price_usd_per_mwh=41.50,
            delivery_start="2044-06-30T00:00:00Z",
            delivery_end="2029-07-01T00:00:00Z",
        ),
        TEST_USERS["director_headers"],
    )
    validate_error(reversed_delivery, "ERR_INVALID_WINDOW", 422)

    backdated = api_client.create_parcel_option(
        create_parcel_option_payload(
            env["site"]["id"],
            opening_version,
            acres=120,
            option_premium_usd=500000,
            purchase_price_usd=18000000,
            window_start="2026-07-31T00:00:00Z",
        ),
        TEST_USERS["analyst_headers"],
    )
    validate_error(backdated, "ERR_OPTION_WINDOW_BACKDATED", 422)

    at_the_clock = sign_option(
        env["site"]["id"],
        opening_version,
        acres=120,
        option_premium_usd=500000,
        purchase_price_usd=18000000,
        window_start=INITIAL_CLOCK_UTC,
    )
    assert at_the_clock["window_start"] == INITIAL_CLOCK_UTC
    assert_status(at_the_clock, "OPTIONED", "the option opening at the clock")

    assert_version(read_site(env["site"]["id"]), opening_version + 1, "Site Alpha")
    assert_money(
        read_program(env["program"]["id"])["option_exposure_usd"],
        500000.00,
        "option_exposure_usd",
    )


def test_a_berm_cannot_be_approved_against_a_seven_decibel_excess_but_can_be_continued():
    """A 7 dBA excess demands berm and screening, and the offered berm ranks below it,
    so the approval branch is refused and the docket is left exactly where it stood at
    `SUBMITTED` with no continuance recorded. The tier gate guards only that branch:
    the very same docket is then continued successfully, which counts the continuance
    while the required tier and the excess stand unchanged.

    PRD §3.6: "Step three selects the `required_mitigation_tier` on a first-match-wins ladder in which either driver can escalate the tier on its own: the tier is `FULL_ENCLOSURE` when the noise excess is at least 10 dBA **or** the weighted opposition score is at least 12; failing that it is `BERM_AND_SCREENING` when the noise excess is at least 5 dBA **or** the score is at least 6; failing that it is `BERM` when the noise excess is strictly greater than 0 **or** the score is at least 3; and otherwise it is `NONE`."
    PRD §3.6: "An applicant offering a berm while the noise excess and community opposition demand a full enclosure is refused with `ERR_MITIGATION_TIER_INSUFFICIENT`; an applicant offering more mitigation than demanded is approved."
    PRD §3.6: "A **continuance** carries the docket from `SUBMITTED` to `CONTINUED`, and a docket already in `CONTINUED` may be continued again, self-looping in place."
    PRD §3.6: "Both routes increment `continuance_count` by one, re-derive the `required_mitigation_tier`, the `mitigation_cost_usd` and the `conditions_escrow_usd`, and recompute the owning site's `site_capital_commitment_usd`."

    Design: Corner/validations/mitigation_tier_insufficient_then_sufficient
    """
    env = _two_dockets_offering_different_mitigation()

    refused = api_client.decide_zoning_application(
        env["berm"]["id"],
        create_zoning_decision_payload("APPROVED_WITH_CONDITIONS", "Berm only."),
        TEST_USERS["authority_headers"],
    )
    validate_error(refused, "ERR_MITIGATION_TIER_INSUFFICIENT", 409)

    standing = _read_docket(env["site"]["id"], env["berm"]["id"])
    assert_status(standing, "SUBMITTED", "the berm-only docket")
    assert standing["continuance_count"] == 0
    assert standing["required_mitigation_tier"] == "BERM_AND_SCREENING"
    assert standing["noise_excess_dba"] == 7

    continued = decide_zoning(
        env["berm"]["id"],
        "CONTINUED",
        "Continued for a revised mitigation package.",
    )

    assert_status(continued, "CONTINUED", "the berm-only docket")
    assert continued["continuance_count"] == 1
    assert continued["required_mitigation_tier"] == "BERM_AND_SCREENING"


def test_the_sibling_offering_the_demanded_tier_is_approved_and_priced():
    """Offering exactly the tier the analysis demands satisfies the ranking gate, so
    the sibling docket is approved and priced: a 2,100,000 base plus 125,000 for each
    of the 7 excess decibels is 2975000.00, and because that cost sits in the
    1,000,000-to-4,000,000 band the escrow is fifteen percent of it, 446250.00. Both
    figures land on the campus's capital aggregate, and approving a docket does not
    itself commit either site.

    PRD §3.6: "Approval has one gate: the applicant's offered mitigation must rank at least as high as the tier the analysis demands, where the ranking places `NONE` lowest, then `BERM`, then `BERM_AND_SCREENING`, then `FULL_ENCLOSURE` highest."
    PRD §3.6: "Step four prices that tier as `mitigation_cost_usd`: a tier base of 0 for `NONE`, 750,000 dollars for `BERM`, 2,100,000 dollars for `BERM_AND_SCREENING` and 5,400,000 dollars for `FULL_ENCLOSURE`, plus a per-decibel adder of 125,000 dollars applied to the **acoustic excess only** and never to the raw noise figures, with the total rounded to 2 decimal places."
    PRD §3.6: "Step five sets the escrow the board will hold, and the crucial subtlety is that the escrow percentage is tiered on the **cost computed in step four**, not on the tier chosen in step three: the percentage is 0.00 when the cost is exactly zero, one tenth at 0.10 when the cost is strictly below 1,000,000 dollars, fifteen hundredths at 0.15 when the cost is strictly below 4,000,000 dollars, and one fifth at 0.20 otherwise."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`."

    Design: Corner/validations/mitigation_tier_insufficient_then_sufficient
    """
    env = _two_dockets_offering_different_mitigation()

    approved = decide_zoning(
        env["berm_and_screening"]["id"],
        "APPROVED_WITH_CONDITIONS",
        "Approved with berm and screening.",
    )

    assert_status(approved, "APPROVED_WITH_CONDITIONS", "Site Bravo's docket")
    assert_money(
        approved["mitigation_cost_usd"], EXPECTED_MITIGATION_COST_USD, "mitigation_cost_usd"
    )
    assert_money(
        approved["conditions_escrow_usd"],
        EXPECTED_CONDITIONS_ESCROW_USD,
        "conditions_escrow_usd",
    )

    assert_money(
        read_site(env["bravo"]["id"])["site_capital_commitment_usd"],
        EXPECTED_MITIGATION_COST_USD + EXPECTED_CONDITIONS_ESCROW_USD,
        "site_capital_commitment_usd",
    )
    assert_status(read_site(env["site"]["id"]), "DRAFT", "Site Alpha")
    assert_status(read_site(env["bravo"]["id"]), "DRAFT", "Site Bravo")


def test_a_severe_hazard_answers_the_commit_before_any_later_gate_can():
    """One measurement moves — a flood index of 0.75 rather than 0.45 — and the campus
    tiers `SEVERE`, which costs 15 points instead of 6 and leaves the score at 74.00.
    Commit is refused on that hazard alone even though the docket, the options, the
    term sheet and the coverage floor are all missing too, because the hazard rung
    fires ahead of every one of them. Nothing is stamped: the site is still screened
    with no committing operator and the program is still screening.

    PRD §3.2: "First, `hazard_tier` is set from the largest of the three hazard indices: `SEVERE` when that largest value is at least 0.70, `MODERATE` when it is at least 0.40 but below 0.70, and `LOW` otherwise."
    PRD §3.2: "The **hazard penalty** is then subtracted, and it depends on the tier just derived: 0 points for `LOW`, 6 points for `MODERATE` and 15 points for `SEVERE`."
    PRD §3.10: "The site's `hazard_tier` must not be `SEVERE`, because a severe seismic, flood or wind exposure disqualifies a campus regardless of how well it scored, else `ERR_HAZARD_TIER_PROHIBITED`."
    PRD §2.11: "On a site commitment, the ten domain gates fire in the order segregation of duties, hazard prohibition, zoning approval, single-committed-site, land control, ratified state incentives, water sufficiency, renewable coverage, capital ceiling — after the site's own state has been checked — so a caller who is both the screener and short of land control learns about the duty conflict first."
    PRD §3.10: "On success the site's `status` becomes `COMMITTED`, the acting operator is stamped as `committed_by_user_id` — null until that moment — the capital commitment is recomputed and compared against the ceiling, the program moves `SCREENING` to `SITE_COMMITTED`, and the site's `version` is incremented by one."

    Design: Corner/validations/severe_hazard_blocks_commit_before_later_gates
    """
    env = setup_screened_site(screening={"flood_hazard_index": 0.75})
    assert_site_screening_outputs(env["site"], 74.00, "SEVERE")

    response = _commit_attempt(env["site"]["id"])

    validate_error(response, "ERR_HAZARD_TIER_PROHIBITED", 409)

    site = read_site(env["site"]["id"])
    assert_status(site, "SCREENED", "Site Alpha")
    assert site["committed_by_user_id"] is None
    assert_program_rollup(
        read_program(env["program"]["id"]), program_status="SCREENING"
    )


def test_the_commit_ladder_names_zoning_then_land_control_then_incentives():
    """Three commit attempts against one campus, each made after satisfying exactly
    one more gate, walk the ladder in order. With nothing in place the answer is
    zoning; with the docket approved it becomes land control; with both parcels
    optioned to a full 100.00 percent it becomes the missing ratified term sheet. Each
    answer is the lowest unmet rung, never a later one.

    PRD §3.10: "The site's zoning docket must stand at `APPROVED_WITH_CONDITIONS`, else `ERR_ZONING_NOT_APPROVED`."
    PRD §3.10: "The site's `land_control_pct` must be at least 100, because a partially optioned campus cannot be committed, else `ERR_LAND_CONTROL_INCOMPLETE`."
    PRD §3.10: "The site must carry an incentive negotiation at `STATE` authority level whose status is `RATIFIED`, else `ERR_INCENTIVES_NOT_RATIFIED`."
    PRD §2.11: "On a site commitment, the ten domain gates fire in the order segregation of duties, hazard prohibition, zoning approval, single-committed-site, land control, ratified state incentives, water sufficiency, renewable coverage, capital ceiling — after the site's own state has been checked — so a caller who is both the screener and short of land control learns about the duty conflict first."

    Design: Corner/validations/commit_gate_ladder_surfaces_lowest_unmet_priority
    """
    env = _site_on_a_five_million_budget()

    validate_error(
        _commit_attempt(env["site"]["id"]), "ERR_ZONING_NOT_APPROVED", 409
    )

    setup_approved_zoning(env["site"]["id"])
    validate_error(
        _commit_attempt(env["site"]["id"]), "ERR_LAND_CONTROL_INCOMPLETE", 409
    )

    sign_option(env["site"]["id"], **OPTION_APN_100)
    sign_option(env["site"]["id"], **APN_200_EIGHT_MILLION)
    assert_land_control(read_site(env["site"]["id"]), 100.00, "FULL")

    validate_error(
        _commit_attempt(env["site"]["id"]), "ERR_INCENTIVES_NOT_RATIFIED", 409
    )


def test_the_fiscal_ceiling_is_the_last_word_after_coverage_is_secured():
    """Once the term sheet is ratified the only outstanding rungs are coverage and the
    ceiling, and coverage answers first. Executing the storage-hybrid agreement lifts
    the program to exactly the 80.0 percent floor, which retires that rung and leaves
    the capital ceiling alone to refuse the commitment: 5571250.00 of mitigation,
    escrow and standing premiums against a 5,000,000 budget.

    PRD §3.10: "The program's `renewable_coverage_pct` from executed agreements must be at least 80.0 percent, with exactly 80.00 acceptable, else `ERR_RENEWABLE_COVERAGE_INSUFFICIENT`."
    PRD §3.10: "And last of all, the site's `site_capital_commitment_usd` must be less than or equal to the program's `capital_budget_usd`, with equality acceptable, else `ERR_CAPITAL_BUDGET_EXCEEDED`."
    PRD §2.11: "**Capital ceiling** — on `POST /candidate-sites/{id}/commit`; otherwise `ERR_CAPITAL_BUDGET_EXCEEDED`. The fiscal ceiling is deliberately the last gate of all."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`."

    Design: Corner/validations/commit_gate_ladder_surfaces_lowest_unmet_priority
    """
    env = _site_on_a_five_million_budget()
    env["zoning"] = setup_approved_zoning(env["site"]["id"])
    sign_option(env["site"]["id"], **OPTION_APN_100)
    sign_option(env["site"]["id"], **APN_200_EIGHT_MILLION)
    env["negotiation"] = setup_ratified_state_negotiation(env["site"]["id"])
    assert_status(env["negotiation"], "RATIFIED", "the STATE negotiation")

    validate_error(
        _commit_attempt(env["site"]["id"]), "ERR_RENEWABLE_COVERAGE_INSUFFICIENT", 409
    )

    setup_executed_ppa_at_coverage_floor(env["program"]["id"])
    assert_program_rollup(
        read_program(env["program"]["id"]), renewable_coverage_pct=80.0
    )

    validate_error(
        _commit_attempt(env["site"]["id"]), "ERR_CAPITAL_BUDGET_EXCEEDED", 409
    )

    site = read_site(env["site"]["id"])
    assert_money(
        site["site_capital_commitment_usd"],
        EXPECTED_MITIGATION_COST_USD + EXPECTED_CONDITIONS_ESCROW_USD + 1250000 + 900000,
        "site_capital_commitment_usd",
    )
    assert_status(site, "SCREENED", "Site Alpha")
    assert site["committed_by_user_id"] is None


def test_a_stage_two_declaration_closes_the_water_gate_ahead_of_coverage():
    """The campus draws 700 Mgal, comfortably inside the 900 Mgal permit — until a
    stage-two declaration withholds thirty percent of that permit and drops the
    headroom to 630.0, which makes the demand infeasible. Commit now answers on water
    even though this program has no executed agreement at all and its coverage stands
    at 0, because the water rung precedes the coverage rung.

    PRD §3.10: "The site's `water_feasible` flag must be true, meaning its annual water demand is less than or equal to its drought-curtailed headroom with equality acceptable, else `ERR_WATER_SUPPLY_INSUFFICIENT`."
    PRD §3.3: "The curtailment fraction is a direct lookup on the current drought stage: `NORMAL` curtails nothing at 0.00, `STAGE_1` withholds a tenth of the permit at 0.10, `STAGE_2` withholds nearly a third at 0.30, and `STAGE_3` withholds more than half at 0.55."
    PRD §3.9: "The credited volumes of every agreement of that program whose `status` is `EXECUTED` are summed — drafts contribute exactly nothing to the numerator — multiplied by 100, divided by the program's `program_annual_load_mwh`, and rounded to 2 decimal places to give `renewable_coverage_pct`."
    PRD §2.11: "On a site commitment, the ten domain gates fire in the order segregation of duties, hazard prohibition, zoning approval, single-committed-site, land control, ratified state incentives, water sufficiency, renewable coverage, capital ceiling — after the site's own state has been checked — so a caller who is both the screener and short of land control learns about the duty conflict first."

    Design: Corner/validations/drought_curtailment_blocks_commit_at_water_gate
    """
    env = setup_screened_site(screening={"annual_water_demand_mgal": 700})
    setup_approved_zoning(env["site"]["id"])
    sign_option(env["site"]["id"], **WHOLE_CAMPUS_OPTION)
    negotiation = setup_ratified_state_negotiation(env["site"]["id"])
    assert read_site(env["site"]["id"])["water_feasible"] is True

    declare_drought(env["water_source"]["id"], "STAGE_2", "2027-05-01T00:00:00Z")

    validate_error(
        _commit_attempt(env["site"]["id"]), "ERR_WATER_SUPPLY_INSUFFICIENT", 409
    )

    site = read_site(env["site"]["id"])
    assert site["water_headroom_mgal"] == 630.0
    assert site["water_feasible"] is False
    assert_status(site, "SCREENED", "Site Alpha")
    assert_land_control(site, 100.00, "FULL")
    assert_status(negotiation, "RATIFIED", "the STATE negotiation")
    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SCREENING",
        renewable_coverage_pct=0,
    )


def test_expiry_overtakes_the_missing_reservation_once_the_window_closes():
    """Both exercise conditions fail on this option, and the order in which they are
    reported is visible on the clock. Two days inside the window the answer is the
    unreserved power, because the campus has no application holding capacity at all.
    Move the clock to `window_end` itself and the earlier expiry rung takes over — the
    window is half-open, so its closing instant is already outside it. Neither refusal
    credits anything: the option is still `OPTIONED` with its premium standing in
    exposure alone.

    PRD §3.8: "Three conditions apply: the option must be `OPTIONED`, otherwise `ERR_OPTION_INVALID_STATE`; the current logical clock must be **strictly before** `window_end`, since the window is half-open and a clock at or past that instant makes the option unexercisable, otherwise `ERR_OPTION_EXPIRED`; and the owning site's live interconnection application must already hold capacity, sitting in `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED`, otherwise `ERR_SITE_NOT_SCREENED` — the company does not buy land before the utility has reserved the power."
    PRD §2.11: "**Option window still open** — on `POST /parcel-options/{id}/exercise`; otherwise `ERR_OPTION_EXPIRED`."
    PRD §2.11: "**Cross-entity state** — a submit requires its site to be `SCREENED` and an exercise requires the site's live application to hold capacity, on `POST /interconnection-applications/{id}/submit` and `POST /parcel-options/{id}/exercise`; otherwise `ERR_SITE_NOT_SCREENED`."
    PRD §3.8: "`option_exposure_usd` totals the premiums of options still `OPTIONED`."

    Design: Corner/validations/option_exercise_gates_expiry_before_reservation
    """
    env = setup_draft_site()
    option = sign_option(env["site"]["id"], **OPTION_APN_100)

    set_clock("2027-12-30T00:00:00Z")
    inside_the_window = api_client.exercise_parcel_option(
        option["id"], TEST_USERS["director_headers"]
    )
    validate_error(inside_the_window, "ERR_SITE_NOT_SCREENED", 409)

    set_clock("2027-12-31T00:00:00Z")
    at_the_close = api_client.exercise_parcel_option(
        option["id"], TEST_USERS["director_headers"]
    )
    validate_error(at_the_close, "ERR_OPTION_EXPIRED", 409)

    standing = read_option(option["id"])
    assert_status(standing, "OPTIONED", "the APN-100 option")
    assert_money(standing["premium_credited_usd"], 0, "premium_credited_usd")
    assert_money(standing["net_purchase_usd"], 0, "net_purchase_usd")
    assert standing["exercised_at"] is None

    assert_premium_ledger(
        read_program(env["program"]["id"]), 1250000.00, 0, 0, 1250000.00
    )


def test_a_restudy_inside_the_tolerance_unlocks_the_reservation_the_first_study_blocked():
    """The first study diversifies 250 MW of nameplate down to 226.0, which sits 24.67
    percent away from the 300 MW request and is refused as a load mismatch — no
    reservation is taken and the utility's ledger stays empty. The restudy is a
    legitimate second round: 293.52 lands 2.16 percent from the request, inside the ten
    percent tolerance, and the identical reservation call now books all 300 MW. The
    newest round also carries the upgrade the first did not, since 293.52 clears the
    250 MW trigger and takes the moderate eight percent uplift.

    PRD §3.5: "First, the newest study must agree with the request: the absolute difference between `requested_mw` and `diversified_peak_mw`, divided by `requested_mw`, must be no greater than a restudy tolerance of 0.10, so a study landing more than ten percent away from the request in either direction must be restudied before capacity can be reserved, and a drift outside the tolerance is rejected with `ERR_STUDY_LOAD_MISMATCH`."
    PRD §3.4: "The `diversified_peak_mw` figure is the utility's coincident view: the IT component is multiplied by the diversity factor, the cooling component is multiplied by whichever is larger of the diversity factor and a cooling floor of 0.85 so that cooling load never diversifies below that floor, the ancillary component is taken undiversified at full value, the three products are added, and the total is rounded to 3 decimal places."
    PRD §3.4: "An upgrade trigger is computed as the utility's total transmission capacity multiplied by 0.50 and rounded to 3 decimal places, and `upgrade_required` is true only when the diversified peak is **strictly greater** than that trigger; a diversified peak exactly equal to the trigger does not require an upgrade."
    PRD §3.4: "When no upgrade is required the study's `network_upgrade_cost_usd` is exactly 0.00."
    PRD §3.4: "After each study round the application's own `diversified_peak_mw` and `network_upgrade_cost_usd` mirror the **newest** study — the one with the highest `study_round`, breaking any tie by the later `created_at` — so a restudy replaces the figures a client saw rather than adding to them."

    Design: Corner/validations/reserve_capacity_requires_study_within_restudy_tolerance
    """
    env = setup_submitted_application()
    first = file_load_study(env["application"]["id"], env["utility"]["id"], **FIRST_STUDY)

    assert_mw(first["diversified_peak_mw"], 226.0, "diversified_peak_mw")
    assert first["upgrade_required"] is False
    assert_money(first["network_upgrade_cost_usd"], 0.00, "network_upgrade_cost_usd")

    refused = api_client.reserve_capacity(
        env["application"]["id"], make_utility_planner_headers(env["utility"]["id"])
    )
    validate_error(refused, "ERR_STUDY_LOAD_MISMATCH", 409)
    assert_status(
        read_application(env["application"]["id"]), "STUDY_COMPLETE", "application"
    )
    assert_mw(
        read_utility(env["utility"]["id"])["reserved_capacity_mw"],
        0,
        "reserved_capacity_mw",
    )

    second = file_load_study(env["application"]["id"], env["utility"]["id"], **RESTUDY)
    assert second["study_round"] == 2
    assert_mw(second["diversified_peak_mw"], 293.52, "diversified_peak_mw")
    assert_money(
        second["network_upgrade_cost_usd"],
        EXPECTED_UPGRADE_COST_USD,
        "network_upgrade_cost_usd",
    )

    reserved = reserve_capacity(env["application"]["id"], env["utility"]["id"])

    assert_status(reserved, "CAPACITY_RESERVED", "application")
    assert_mw(reserved["reserved_mw"], 300, "reserved_mw")
    assert_capacity_ledger(read_utility(env["utility"]["id"]), 300.0, 200.0)
    assert_money(
        read_site(env["site"]["id"])["site_capital_commitment_usd"],
        EXPECTED_STUDY_FEE_USD + EXPECTED_UPGRADE_COST_USD,
        "site_capital_commitment_usd",
    )


def test_a_supersede_must_name_a_predecessor_on_the_very_same_parcel():
    """The predecessor named here exists, is `OPTIONED` and belongs to this same site —
    but it covers APN-100 while the new option covers APN-200, and the supersede clause
    demands both. The create is refused as a referential mismatch, and because a
    refused create writes nothing the predecessor is neither released nor forfeited:
    one option remains, the premium stands wholly in exposure, land control is still
    the partial 80.00 percent that 240 of 300 acres buys, and the site's version has
    not moved.

    PRD §3.8: "That predecessor must itself be `OPTIONED`, otherwise `ERR_OPTION_INVALID_STATE`, and it must belong to the same site and the same parcel as the option superseding it, otherwise `ERR_APPLICATION_SITE_UTILITY_MISMATCH`."
    PRD §3.8: "An option create that names `replaces_option_id` moves the prior option to `RELEASED` and rewrites the site's `land_control_pct` in the same request."
    PRD §3.8: "The acreage of every option of that site whose `status` is `OPTIONED` or `EXERCISED` is summed, multiplied by 100, divided by the site's `gross_acres`, capped at 100.0 and rounded to 2 decimal places to give `land_control_pct` — so a campus that has optioned more acreage than its gross footprint still reports 100.00 rather than more."
    PRD §2.11: "**Referential agreement** — an application's `utility_id` matches its site's, and a superseding option matches its predecessor's site and parcel, on `POST /interconnection-applications` and `POST /parcel-options`; otherwise `ERR_APPLICATION_SITE_UTILITY_MISMATCH`."

    Design: Corner/validations/supersede_requires_same_site_and_parcel_apn
    """
    env = setup_draft_site()
    incumbent = sign_option(env["site"]["id"], **OPTION_APN_100)
    before = read_site(env["site"]["id"])

    response = api_client.create_parcel_option(
        create_parcel_option_payload(
            env["site"]["id"],
            before["version"],
            replaces_option_id=incumbent["id"],
            **APN_200_EIGHT_MILLION,
        ),
        TEST_USERS["analyst_headers"],
    )

    validate_error(response, "ERR_APPLICATION_SITE_UTILITY_MISMATCH", 422)

    assert_status(read_option(incumbent["id"]), "OPTIONED", "the APN-100 option")
    assert list_options({"site_id": env["site"]["id"]})["meta"]["total_count"] == 1

    assert_premium_ledger(
        read_program(env["program"]["id"]), 1250000.00, 0, 0, 1250000.00
    )

    after = read_site(env["site"]["id"])
    assert_land_control(after, 80.00, "PARTIAL")
    assert_version_unchanged(before, after, "Site Alpha")
