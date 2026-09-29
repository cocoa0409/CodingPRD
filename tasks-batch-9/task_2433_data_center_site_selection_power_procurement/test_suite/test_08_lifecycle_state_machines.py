"""Declared initial states, refused transitions, terminal lockdown and reverse walks."""

from test_helpers import (
    EXPECTED_CONDITIONS_ESCROW_USD,
    EXPECTED_MITIGATION_COST_USD,
    EXPECTED_SCREENING_SCORE_ALPHA,
    SCREEN_AIR_COOLED,
    SCREEN_EVAPORATIVE,
    TEST_USERS,
    ZONING_DENIED_REASON,
    add_objection,
    api_client,
    assert_money,
    assert_mw,
    assert_pct,
    assert_program_rollup,
    assert_ratio,
    assert_status,
    assert_utility_ledger_conserved,
    assert_version,
    create_community_objection_payload,
    create_disqualification_payload,
    create_energization_commitment_payload,
    create_screening_payload,
    create_zoning_application_payload,
    create_zoning_decision_payload,
    decide_zoning,
    declare_drought,
    disqualify_site,
    draft_application,
    draft_ppa,
    execute_ppa,
    file_company_round,
    file_zoning,
    list_site_negotiations,
    list_site_zoning,
    make_utility_planner_headers,
    open_negotiation,
    read_application,
    read_program,
    read_site,
    read_utility,
    read_water_source,
    revise_capacity,
    setup_draft_site,
    setup_reserved_application,
    setup_screened_site,
    setup_studied_application,
    sign_option,
    validate_error,
)

SUNBELT_SOLAR = {
    "counterparty_name": "Sunbelt Solar I",
    "technology": "SOLAR",
    "contracted_capacity_mw": 900,
    "annual_generation_mwh": 2100000,
    "hourly_matched_mwh": 1500000,
    "strike_price_usd_per_mwh": 41.50,
    "matching_mode": "ANNUAL_VOLUMETRIC",
}
CAPACITY_REVISION_UTILITY = {
    "name": "Catawba Electric",
    "state_code": "SC",
    "balancing_authority": "SOCO",
    "total_transmission_capacity_mw": 400,
}
CAPACITY_REVISION_BASIN = {
    "name": "Broad River",
    "basin_code": "BRD-01",
    "state_code": "SC",
}


def _read_negotiation(site_id, negotiation_id):
    """Re-read a negotiation through the nested listing on its own site, which is the
    only read channel the contract offers for a negotiation."""
    for item in list_site_negotiations(site_id)["data"]:
        if item["id"] == negotiation_id:
            return item
    raise AssertionError(f"negotiation {negotiation_id} is not listed under its site")


def _read_docket(site_id, zoning_application_id):
    """Re-read a zoning docket through the nested listing on its own site."""
    for item in list_site_zoning(site_id)["data"]:
        if item["id"] == zoning_application_id:
            return item
    raise AssertionError(f"docket {zoning_application_id} is not listed under its site")


def test_a_second_screening_is_refused_and_the_first_package_survives():
    """Screening is declared from `DRAFT` only, so the second package — a cheaper
    air-cooled design with more headroom and gentler hazards, which would have scored
    higher — never lands. The site keeps the evaporative design, the 83.00 score and the
    `MODERATE` tier the first screening froze onto it, and its version does not move.

    PRD §3.2: "Screening a site that is not in `DRAFT` is rejected with `ERR_SITE_INVALID_STATE`."
    PRD §3.2: "It is computed at screening and never re-derived afterwards."
    PRD §2.11: "**Candidate site state** — the site's `status` permits the operation, on `POST /candidate-sites/{id}/screen`, `POST /candidate-sites/{id}/commit`, `POST /candidate-sites/{id}/disqualify`, `POST /interconnection-applications`, `POST /zoning-applications`, `POST /incentive-negotiations` and `POST /parcel-options`; otherwise `ERR_SITE_INVALID_STATE`."

    Design: Corner/state_machines/screen_twice_rejected_as_site_invalid_state
    """
    env = setup_screened_site()

    response = api_client.screen_candidate_site(
        env["site"]["id"],
        create_screening_payload(
            **dict(
                SCREEN_AIR_COOLED,
                transmission_headroom_mw=300,
                fiber_route_count=4,
                seismic_hazard_index=0.10,
                flood_hazard_index=0.10,
                wind_hazard_index=0.10,
                craft_labor_supply_index=2000,
                wage_premium_pct=0.05,
            )
        ),
        TEST_USERS["analyst_headers"],
    )

    validate_error(response, "ERR_SITE_INVALID_STATE", 409)

    site = read_site(env["site"]["id"])
    assert_status(site, "SCREENED", "Site Alpha")
    assert_pct(
        site["screening_score"], EXPECTED_SCREENING_SCORE_ALPHA, "screening_score"
    )
    assert site["hazard_tier"] == "MODERATE"
    assert site["cooling_type"] == "EVAPORATIVE"
    assert_version(site, 2, "Site Alpha")


def test_energization_cannot_be_committed_straight_from_a_completed_study():
    """The commitment is declared only out of `CAPACITY_RESERVED`, and this application
    has a study but has never held capacity, so the date is refused before any of the
    three temporal conditions is even reached. Nothing is written: the application keeps
    no committed date and no delay exposure, and the utility's whole 500 MW is still
    available because no reservation ever existed to price.

    PRD §3.5: "A date failing any of the three is rejected with `ERR_ENERGIZATION_DEADLINE_MISSED`, while attempting the commitment from a status other than `CAPACITY_RESERVED` is rejected with `ERR_APPLICATION_INVALID_STATE`."
    PRD §3.4: "Its `diversified_peak_mw` is null until the serving utility files the first load study, its `committed_energization_date` is null until the utility commits one, and its `withdrawal_reason` is null unless and until it is withdrawn."
    PRD §3.5: "The utility's `reserved_capacity_mw` is the largest such group demand across the set, rounded to 3 decimal places, and it is exactly 0 when the set is empty."

    Design: Corner/state_machines/commit_energization_from_study_complete_rejected
    """
    env = setup_studied_application()

    response = api_client.commit_energization(
        env["application"]["id"],
        create_energization_commitment_payload("2029-06-30T00:00:00Z"),
        make_utility_planner_headers(env["utility"]["id"]),
    )

    validate_error(response, "ERR_APPLICATION_INVALID_STATE", 409)

    application = read_application(env["application"]["id"])
    assert_status(application, "STUDY_COMPLETE", "application")
    assert application["committed_energization_date"] is None
    assert_money(application["delay_exposure_usd"], 0, "delay_exposure_usd")
    assert_mw(application["reserved_mw"], 0, "reserved_mw")

    utility = read_utility(env["utility"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 0, "reserved_capacity_mw")
    assert_mw(utility["available_capacity_mw"], 500.0, "available_capacity_mw")
    assert_utility_ledger_conserved(utility)


def test_a_disqualified_site_accepts_neither_screening_nor_a_new_child_docket():
    """`DISQUALIFIED` is terminal for a candidate site, and the lockdown is wider than
    the site's own operations: screening it, dropping it a second time and filing a
    zoning docket against it are all refused with the same site-state error. The reason
    recorded by the original drop is not overwritten by the refused second drop, and the
    site still carries no screening score.

    PRD §3.10: "The site's `status` becomes `DISQUALIFIED`, its `disqualification_reason` is persisted, and its `version` is incremented by one."
    PRD §3.10: "Dropping a site is the `PortfolioDirector`'s act, requires a `disqualification_reason`, and is permitted from `DRAFT`, `SCREENED` or `COMMITTED`; a site already `DISQUALIFIED` cannot be dropped again and the attempt is refused with `ERR_SITE_INVALID_STATE`."
    PRD §2.11: "**Candidate site state** — the site's `status` permits the operation, on `POST /candidate-sites/{id}/screen`, `POST /candidate-sites/{id}/commit`, `POST /candidate-sites/{id}/disqualify`, `POST /interconnection-applications`, `POST /zoning-applications`, `POST /incentive-negotiations` and `POST /parcel-options`; otherwise `ERR_SITE_INVALID_STATE`."

    Design: Corner/state_machines/disqualified_site_is_locked_down
    """
    env = setup_draft_site()
    disqualify_site(env["site"]["id"], "LAND_ASSEMBLY_FAILED")

    screen_again = api_client.screen_candidate_site(
        env["site"]["id"], create_screening_payload(), TEST_USERS["analyst_headers"]
    )
    validate_error(screen_again, "ERR_SITE_INVALID_STATE", 409)

    drop_again = api_client.disqualify_candidate_site(
        env["site"]["id"],
        create_disqualification_payload("TRANSMISSION_RISK"),
        TEST_USERS["director_headers"],
    )
    validate_error(drop_again, "ERR_SITE_INVALID_STATE", 409)

    new_docket = api_client.create_zoning_application(
        create_zoning_application_payload(env["site"]["id"]),
        TEST_USERS["analyst_headers"],
    )
    validate_error(new_docket, "ERR_SITE_INVALID_STATE", 409)

    site = read_site(env["site"]["id"])
    assert_status(site, "DISQUALIFIED", "Site Alpha")
    assert site["disqualification_reason"] == "LAND_ASSEMBLY_FAILED"
    assert site["screening_score"] is None


def test_one_row_of_each_stateful_entity_opens_in_its_declared_initial_state():
    """Eight creates, eight declared entry points: the program opens in `SCREENING`, the
    basin at `NORMAL` with nothing curtailed and nothing committed against it, the site
    in `DRAFT`, the application in `DRAFT` outside the queue at position 0, the zoning
    docket in `SUBMITTED` with no continuances, the negotiation in `DRAFT` with no
    rounds, the agreement in `DRAFT` crediting no coverage at all, and the land option
    in `OPTIONED`.

    PRD §3.1: "A fresh program reports `program_status` of `SCREENING`, and every rollup starts at zero — `committed_load_mw`, `renewable_coverage_pct`, `option_exposure_usd`, `forfeited_premium_usd`, `capitalized_premium_usd`, `premium_committed_total_usd` and `full_land_control_site_count` alike."
    PRD §3.1: "At registration the basin sits at `drought_stage` `NORMAL` with a `stage_curtailment_pct` of 0.00, so its `effective_supply_mgal` equals its permitted withdrawal exactly, its `committed_annual_demand_mgal` is 0, and its `last_declaration_effective_date` is null because no declaration has yet been issued."
    PRD §3.4: "A drafted application sits at `status` `DRAFT` with `queue_position` of 0, `reserved_mw` of 0, `study_round` of 0, `study_fee_usd` of 0, `network_upgrade_cost_usd` of 0 and `delay_exposure_usd` of 0: nothing is reserved and no fee is charged until it is submitted."
    PRD §3.6: "A freshly filed docket sits at `status` `SUBMITTED` with `continuance_count` of 0 and `objection_count` of 0, and its acoustic and mitigation figures are already computed from the noise inputs on the assumption of zero objections."
    PRD §3.7: "A new negotiation sits at `status` `DRAFT` with `round_count` of 0 and `last_party` null, and all four of its money figures — `npv_incentive_usd`, `sales_tax_benefit_usd`, `abatement_npv_usd` and `clawback_exposure_usd` — are 0 until the first round of terms arrives."
    PRD §3.9: "A drafted agreement sits at `status` `DRAFT`, its `annual_cost_usd` already computed as the annual generation multiplied by the strike price rounded to 2 decimal places, and its `credited_coverage_mwh` at exactly 0 — a draft agreement never counts toward coverage."
    PRD §3.8: "A new option enters at `status` `OPTIONED`."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    env = setup_draft_site()

    program = read_program(env["program"]["id"])
    assert_program_rollup(program, program_status="SCREENING")

    basin = read_water_source(env["water_source"]["id"])
    assert basin["drought_stage"] == "NORMAL"
    assert_ratio(basin["stage_curtailment_pct"], 0, "stage_curtailment_pct")
    assert basin["effective_supply_mgal"] == 900.0
    assert basin["committed_annual_demand_mgal"] == 0
    assert basin["last_declaration_effective_date"] is None

    assert_status(read_site(env["site"]["id"]), "DRAFT", "Site Alpha")

    application = draft_application(env["site"]["id"], env["utility"]["id"])
    assert_status(application, "DRAFT", "application")
    assert application["queue_position"] == 0

    docket = file_zoning(env["site"]["id"])
    assert_status(docket, "SUBMITTED", "zoning docket")
    assert docket["continuance_count"] == 0
    assert docket["objection_count"] == 0

    negotiation = open_negotiation(env["site"]["id"], "STATE")
    assert_status(negotiation, "DRAFT", "negotiation")
    assert negotiation["round_count"] == 0
    assert negotiation["last_party"] is None

    agreement = draft_ppa(env["program"]["id"], **SUNBELT_SOLAR)
    assert_status(agreement, "DRAFT", "power purchase agreement")
    assert_mw(agreement["credited_coverage_mwh"], 0, "credited_coverage_mwh")

    option = sign_option(env["site"]["id"])
    assert_status(option, "OPTIONED", "land parcel option")


def test_denying_a_docket_drops_its_site_and_leaves_the_pricing_where_it_stood():
    """Denial is the only zoning outcome that reaches outside the docket: the board's
    refusal drives the `SCREENED` site to `DISQUALIFIED` with the reserved
    `ZONING_DENIED` reason in the same request. The two priced figures are deliberately
    frozen rather than recomputed or zeroed — a 7 dBA excess and two noise objections had
    already demanded `BERM_AND_SCREENING` at 2975000.00 with 446250.00 escrowed, and
    those values survive the denial. Losing its only candidate returns the program to
    `SCREENING`.

    PRD §3.6: "On denial the mitigation cost and conditions escrow are left exactly at their pre-decision values rather than being re-derived — a denied campus is not priced."
    PRD §3.6: "Instead the referenced candidate site is driven to `DISQUALIFIED` with its `disqualification_reason` set to the string `ZONING_DENIED`, and the full four-hop disqualification cascade described in §3.10 fires as though a `PortfolioDirector` had dropped the site by hand."
    PRD §3.6: "Each objection increments `objection_count` by one and feeds the `weighted_opposition_score`, which is the sum of a per-type weight over all objections recorded against that docket, rounded to 2 decimal places."
    PRD §3.10: "Otherwise the status is `SCREENING`."

    Design: Corner/state_machines/zoning_denied_branch_disqualifies_the_site
    """
    env = setup_screened_site()
    docket = file_zoning(env["site"]["id"], visual_mitigation_tier="NONE")
    add_objection(docket["id"], objection_type="NOISE", commenter_reference="CMT-001")
    add_objection(docket["id"], objection_type="NOISE", commenter_reference="CMT-002")

    denied = decide_zoning(
        docket["id"],
        outcome="DENIED",
        decision_note="Denied: incompatible with the rural overlay district.",
    )

    assert_status(denied, "DENIED", "zoning docket")
    assert denied["objection_count"] == 2
    assert_pct(denied["weighted_opposition_score"], 3.00, "weighted_opposition_score")
    assert denied["noise_excess_dba"] == 7
    assert denied["required_mitigation_tier"] == "BERM_AND_SCREENING"
    assert_money(
        denied["mitigation_cost_usd"], EXPECTED_MITIGATION_COST_USD, "mitigation_cost_usd"
    )
    assert_money(
        denied["conditions_escrow_usd"],
        EXPECTED_CONDITIONS_ESCROW_USD,
        "conditions_escrow_usd",
    )

    site = read_site(env["site"]["id"])
    assert_status(site, "DISQUALIFIED", "Site Alpha")
    assert site["disqualification_reason"] == ZONING_DENIED_REASON

    assert_program_rollup(
        read_program(env["program"]["id"]), program_status="SCREENING"
    )


def test_executing_an_already_executed_agreement_never_double_counts_coverage():
    """Execution is declared from `DRAFT` alone, so the repeat call is refused and the
    coverage arithmetic runs exactly once. The solar agreement credits 2,100,000 MWh less
    a 6 percent curtailment, which is 1974000.0, and against the program's 2365200.0 MWh
    denominator that is 83.46 percent — not the doubled figure a second execution would
    have produced.

    PRD §3.9: "Executing the agreement moves it `DRAFT` to `EXECUTED`; executing one that is already `EXECUTED` is refused with `ERR_PPA_INVALID_STATE`."
    PRD §3.9: "Under `ANNUAL_VOLUMETRIC` accounting the whole contracted output counts subject to a technology curtailment haircut: `credited_coverage_mwh` is the annual generation multiplied by one minus the technology's curtailment factor, rounded to 3 decimal places, where solar is curtailed 6 percent at 0.06, wind 11 percent at 0.11, storage hybrids 4 percent at 0.04 and nuclear just 1 percent at 0.01."
    PRD §3.9: "The credited volumes of every agreement of that program whose `status` is `EXECUTED` are summed — drafts contribute exactly nothing to the numerator — multiplied by 100, divided by the program's `program_annual_load_mwh`, and rounded to 2 decimal places to give `renewable_coverage_pct`."

    Design: Corner/state_machines/execute_ppa_twice_rejected
    """
    env = setup_draft_site()
    agreement = draft_ppa(env["program"]["id"], **SUNBELT_SOLAR)
    executed = execute_ppa(agreement["id"])

    response = api_client.execute_power_purchase_agreement(
        agreement["id"], TEST_USERS["director_headers"]
    )

    validate_error(response, "ERR_PPA_INVALID_STATE", 409)

    assert_status(executed, "EXECUTED", "power purchase agreement")
    assert_mw(executed["credited_coverage_mwh"], 1974000.0, "credited_coverage_mwh")

    program = read_program(env["program"]["id"])
    assert_program_rollup(program, renewable_coverage_pct=83.46)


def test_a_term_sheet_cannot_be_signed_on_the_companys_own_opening_offer():
    """One company round leaves the table waiting on the authority, so signature is
    refused on two counts at once — the negotiation is in `AUTHORITY_COUNTER_PENDING`
    rather than `COMPANY_OFFER_PENDING`, and only one of the two required rounds has been
    recorded. No signer is stamped, the round count stays at 1, and the money the opening
    offer priced at 438114552.25 is left standing.

    PRD §3.7: "Signature is the `IncentiveNegotiator`'s act and only ever closes on an authority counter that is on the table: the negotiation must be in `COMPANY_OFFER_PENDING`, and it must have accumulated at least 2 rounds, so a term sheet cannot be signed before one company offer and one authority counter have both been recorded."
    PRD §3.7: "Attempting to sign from any other status, or before the second round, is rejected with `ERR_NEGOTIATION_INVALID_STATE`."
    PRD §3.7: "Signature moves the negotiation `COMPANY_OFFER_PENDING` to `SIGNED` and stamps the acting operator as `signed_by_user_id`, which becomes the comparand for the duty separation at ratification."

    Design: Corner/state_machines/sign_before_minimum_rounds_rejected
    """
    env = setup_draft_site()
    negotiation = open_negotiation(env["site"]["id"], "STATE")
    file_company_round(negotiation["id"])

    response = api_client.sign_incentive_negotiation(
        negotiation["id"], TEST_USERS["negotiator_headers"]
    )

    validate_error(response, "ERR_NEGOTIATION_INVALID_STATE", 409)

    refreshed = _read_negotiation(env["site"]["id"], negotiation["id"])
    assert_status(refreshed, "AUTHORITY_COUNTER_PENDING", "negotiation")
    assert refreshed["round_count"] == 1
    assert refreshed["signed_by_user_id"] is None
    assert_money(refreshed["npv_incentive_usd"], 438114552.25, "npv_incentive_usd")


def test_an_approved_docket_takes_no_reversal_and_no_late_objection():
    """`APPROVED_WITH_CONDITIONS` is terminal, so the board can neither reverse itself
    with a denial nor let a late traffic objection onto the record; both attempts answer
    the same zoning-state error. The docket therefore still shows no objections and the
    figures approval finalized: a berm at 750,000 plus 125,000 for each of the two excess
    decibels is exactly 1000000.00, which lands in the 0.15 escrow band rather than the
    lowest one and holds 150000.00.

    PRD §3.6: "The board's decision is a three-way fork carrying an `outcome` and an optional `decision_note`, and the docket must be in `SUBMITTED` or `CONTINUED` for any of the three; a decision on a terminal docket is rejected with `ERR_ZONING_INVALID_STATE`."
    PRD §3.6: "Recording an objection on a docket that has already reached `APPROVED_WITH_CONDITIONS` or `DENIED` is rejected with `ERR_ZONING_INVALID_STATE`, since both are terminal."
    PRD §3.6: "A cost of exactly 1,000,000.00 dollars therefore lands in the 0.15 band because the lowest band is a strict "below"."

    Design: Corner/state_machines/decide_on_terminal_zoning_application_rejected
    """
    env = setup_draft_site()
    docket = file_zoning(
        env["site"]["id"], projected_noise_dba=57, visual_mitigation_tier="BERM"
    )
    decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved with berm condition.",
    )

    reversal = api_client.decide_zoning_application(
        docket["id"],
        create_zoning_decision_payload(
            outcome="DENIED", decision_note="Attempted reversal."
        ),
        TEST_USERS["authority_headers"],
    )
    validate_error(reversal, "ERR_ZONING_INVALID_STATE", 409)

    late_objection = api_client.create_community_objection(
        docket["id"],
        create_community_objection_payload(
            objection_type="TRAFFIC", commenter_reference="CMT-009"
        ),
        TEST_USERS["authority_headers"],
    )
    validate_error(late_objection, "ERR_ZONING_INVALID_STATE", 409)

    refreshed = _read_docket(env["site"]["id"], docket["id"])
    assert_status(refreshed, "APPROVED_WITH_CONDITIONS", "zoning docket")
    assert refreshed["objection_count"] == 0
    assert_money(refreshed["mitigation_cost_usd"], 1000000.00, "mitigation_cost_usd")
    assert_money(refreshed["conditions_escrow_usd"], 150000.00, "conditions_escrow_usd")

    assert_status(read_site(env["site"]["id"]), "DRAFT", "Site Alpha")


def test_a_derate_walks_the_reservation_back_to_submitted_without_losing_its_place():
    """Cutting the utility's ceiling from 400 MW to 250 strands a 300 MW reservation, so
    the utility itself pushes the application backward from `CAPACITY_RESERVED` to
    `SUBMITTED` with its megawatts released — a reverse transition nobody withdrew. The
    application keeps queue position 1 because it lost the reservation, not its place in
    line; the ledger rebuilds against the new ceiling as 0 against 250.0; and the site,
    now holding no capacity while its utility shows less available than the program
    needs, is retiered to `AT_RISK`.

    PRD §3.5: "The utility's `total_transmission_capacity_mw` is replaced with the revised figure, and then every reservation is re-tested against the new ceiling using the same buffered overlap aggregate: any application in `CAPACITY_RESERVED` whose group demand no longer fits is walked backward to `SUBMITTED` with its `reserved_mw` zeroed, and any application in `ENERGIZATION_COMMITTED` that no longer fits is walked back to `SUBMITTED` with its `reserved_mw` zeroed, its `committed_energization_date` cleared to null and its `delay_exposure_usd` reset to 0."
    PRD §3.5: "In both cases the application keeps its queue position — it loses the reservation, not its place in line — so an application may legitimately travel `SUBMITTED` to `STUDY_COMPLETE` to `CAPACITY_RESERVED` and back to `SUBMITTED`, then forward again."
    PRD §3.5: "Otherwise the tier is `AT_RISK` when either no live application exists at all or the live application is still in `DRAFT`, `SUBMITTED` or `STUDY_COMPLETE`, **and** the serving utility's `available_capacity_mw` is strictly less than the program's `target_load_mw` — in other words, the site has not yet locked capacity and its utility no longer visibly has enough to give."

    Design: Corner/state_machines/capacity_revision_walks_reservation_back_into_the_queue
    """
    env = setup_reserved_application(
        program={"name": "Hyperscale Bravo"},
        utility=CAPACITY_REVISION_UTILITY,
        water_source=CAPACITY_REVISION_BASIN,
        site={"name": "Site Alpha", "state_code": "SC", "county": "Cherokee"},
        screening=dict(SCREEN_AIR_COOLED, transmission_headroom_mw=300),
    )

    revised = revise_capacity(
        env["utility"]["id"], 250, reason="Line rerating after the summer assessment."
    )

    assert revised["total_transmission_capacity_mw"] == 250
    assert_mw(revised["reserved_capacity_mw"], 0, "reserved_capacity_mw")
    assert_mw(revised["available_capacity_mw"], 250.0, "available_capacity_mw")
    assert_utility_ledger_conserved(revised)

    application = read_application(env["application"]["id"])
    assert_status(application, "SUBMITTED", "application")
    assert_mw(application["reserved_mw"], 0, "reserved_mw")
    assert application["queue_position"] == 1

    site = read_site(env["site"]["id"])
    assert site["energization_risk_tier"] == "AT_RISK"

    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SCREENING",
        committed_load_mw=0,
    )


def test_a_stage_two_declaration_curtails_the_basin_and_flips_site_feasibility():
    """A single declaration on the basin reprices every site drawing on it: a
    `STAGE_2` stage withholds 0.30 of the 900 Mgal permit, so effective supply falls to
    630.0 and the screened campus, whose own 700 Mgal demand had comfortable headroom
    against the full permit, is no longer feasible. What does *not* move is the site's
    own lifecycle: it is still `SCREENED`, and the score frozen at screening time stays
    83.00 even though the water input behind it has changed.

    PRD §3.3: "A basin's `effective_supply_mgal` is its annual permitted withdrawal multiplied by one minus its `stage_curtailment_pct`, rounded to 3 decimal places."
    PRD §3.3: "The curtailment fraction is a direct lookup on the current drought stage: `NORMAL` curtails nothing at 0.00, `STAGE_1` withholds a tenth of the permit at 0.10, `STAGE_2` withholds nearly a third at 0.30, and `STAGE_3` withholds more than half at 0.55."
    PRD §3.3: "Then, for every candidate site drawing on that basin whose `status` is `DRAFT`, `SCREENED` or `COMMITTED`, the site's `water_headroom_mgal` is recomputed and only afterwards its `water_feasible` flag re-evaluated — the order matters, since feasibility reads the freshly computed headroom."
    PRD §3.2: "When a later drought declaration or a sibling site's screening changes this site's water headroom, the `water_headroom_mgal` and `water_feasible` fields **are** brought up to date, but the `screening_score` and the `hazard_tier` frozen at screening time stay exactly as they were."

    Design: Corner/state_machines/drought_declaration_reprices_water_feasibility_on_every_site
    """
    env = setup_screened_site(
        screening=dict(SCREEN_EVAPORATIVE, annual_water_demand_mgal=700)
    )
    before = read_site(env["site"]["id"])
    assert before["water_headroom_mgal"] == 900.0
    assert before["water_feasible"] is True

    declared = declare_drought(
        env["water_source"]["id"], "STAGE_2", "2027-05-01T00:00:00Z"
    )

    assert declared["drought_stage"] == "STAGE_2"
    assert_ratio(declared["stage_curtailment_pct"], 0.30, "stage_curtailment_pct")
    assert declared["effective_supply_mgal"] == 630.0
    assert declared["committed_annual_demand_mgal"] == 700.0
    assert declared["last_declaration_effective_date"] == "2027-05-01T00:00:00Z"

    after = read_site(env["site"]["id"])
    assert after["water_headroom_mgal"] == 630.0
    assert after["water_feasible"] is False
    assert_status(after, "SCREENED", "Site Alpha")
    assert_pct(
        after["screening_score"], EXPECTED_SCREENING_SCORE_ALPHA, "screening_score"
    )

    assert_program_rollup(
        read_program(env["program"]["id"]), program_status="SCREENING"
    )
