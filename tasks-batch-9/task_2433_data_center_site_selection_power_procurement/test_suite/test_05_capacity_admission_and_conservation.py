"""Transmission admission, gate priority on refusal, and the capacity conservation law."""

from test_helpers import (
    EXPECTED_STUDY_FEE_USD,
    SCREEN_AIR_COOLED,
    add_sibling_site,
    api_client,
    assert_land_control,
    assert_money,
    assert_mw,
    assert_program_rollup,
    assert_status,
    assert_utility_ledger_conserved,
    assert_version_unchanged,
    draft_application,
    file_load_study,
    file_zoning,
    list_site_negotiations,
    make_chair_headers,
    make_utility_planner_headers,
    read_application,
    read_program,
    read_site,
    read_utility,
    reserve_capacity,
    setup_reserved_application,
    setup_screened_site,
    submit_application,
    validate_error,
    withdraw_application,
)

FOUR_HUNDRED_MW_UTILITY = {
    "name": "Catawba Electric",
    "state_code": "SC",
    "balancing_authority": "SOCO",
    "total_transmission_capacity_mw": 400,
}
SC_BASIN = {"name": "Broad River", "basin_code": "BRD-01", "state_code": "SC"}
SECOND_WINDOW = {
    "window_start": "2030-01-01T00:00:00Z",
    "window_end": "2030-06-30T00:00:00Z",
}


def _four_hundred_mw_environment(headroom=None):
    """Site Alpha screened air-cooled on a 400 MW utility with a 90-day commissioning
    buffer, its 300 MW application already holding capacity."""
    screening = dict(SCREEN_AIR_COOLED)
    if headroom is not None:
        screening["transmission_headroom_mw"] = headroom
    return setup_reserved_application(
        program={"name": "Hyperscale Bravo"},
        utility=FOUR_HUNDRED_MW_UTILITY,
        water_source=SC_BASIN,
        site={"name": "Site Alpha", "state_code": "SC", "county": "Cherokee"},
        screening=screening,
    )


def _sibling_application(env, site, requested_mw, headroom, load_study=None):
    """Screen another site of the same utility and carry its own application as far as
    the caller asks — submitted only, or submitted and studied."""
    sibling = add_sibling_site(
        env,
        site=site,
        screening=dict(SCREEN_AIR_COOLED, transmission_headroom_mw=headroom),
    )
    application = draft_application(
        sibling["id"], env["utility"]["id"], requested_mw=requested_mw, **SECOND_WINDOW
    )
    application = submit_application(application["id"])
    if load_study is not None:
        file_load_study(application["id"], env["utility"]["id"], **load_study)
        application = read_application(application["id"])
    return sibling, application


def _contested_same_window_application(env):
    """Site Bravo with a 300 MW application over Site Alpha's own window, submitted but
    never studied, so both the study gate and the aggregate gate are unmet."""
    sibling = add_sibling_site(
        env,
        site={"name": "Site Bravo", "state_code": "SC", "county": "Union"},
        screening=SCREEN_AIR_COOLED,
    )
    application = draft_application(sibling["id"], env["utility"]["id"], requested_mw=300)
    return sibling, submit_application(application["id"])


def _exact_equality_environment():
    """A 400 MW utility carrying a reserved 300 MW application plus two studied
    applications over a later, buffer-overlapping window: one of 100 MW and one of
    101 MW."""
    env = _four_hundred_mw_environment(headroom=240)
    env["bravo"], env["bravo_application"] = _sibling_application(
        env,
        {"name": "Site Bravo", "state_code": "SC", "county": "Union"},
        100,
        100,
        load_study={
            "it_load_mw": 78,
            "cooling_load_mw": 20,
            "ancillary_load_mw": 4,
            "diversity_factor": 0.90,
        },
    )
    env["charlie"], env["charlie_application"] = _sibling_application(
        env,
        {"name": "Site Charlie", "state_code": "SC", "county": "York"},
        101,
        101,
        load_study={
            "it_load_mw": 79,
            "cooling_load_mw": 20,
            "ancillary_load_mw": 4,
            "diversity_factor": 0.90,
        },
    )
    return env


def test_reservation_reports_the_missing_study_before_the_capacity_shortfall():
    """This one call breaks two rules at once: the application is `SUBMITTED` rather
    than `STUDY_COMPLETE`, and 300 MW on top of the 300 MW already reserved over the
    same buffered window would demand 600 MW from a 400 MW utility. Because the study
    gate is evaluated first, the client is told the application has no study to reserve
    against and never sees the capacity error.

    PRD §3.5: "The application must be in exactly `STUDY_COMPLETE`: a `SUBMITTED` application has no study to reserve against and a `CAPACITY_RESERVED` one is already reserved, so either is rejected with `ERR_APPLICATION_NOT_STUDIED`."
    PRD §2.11: "**Study completeness for reservation** — the application's `status` is exactly `STUDY_COMPLETE`, on `POST /interconnection-applications/{id}/reserve-capacity`; otherwise `ERR_APPLICATION_NOT_STUDIED`."
    PRD §2.11: "**Aggregate transmission capacity** — on `POST /interconnection-applications/{id}/reserve-capacity`; otherwise `ERR_TRANSMISSION_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/reserve_capacity_state_beats_transmission_capacity
    """
    env = _four_hundred_mw_environment()
    _bravo, contested = _contested_same_window_application(env)

    response = api_client.reserve_capacity(
        contested["id"], make_utility_planner_headers(env["utility"]["id"])
    )

    validate_error(response, "ERR_APPLICATION_NOT_STUDIED", 409)


def test_refused_reservation_leaves_the_application_and_the_ledger_untouched():
    """A refusal is not a partial write. The contested application stays `SUBMITTED`
    with no megawatts reserved against it, and the utility's ledger still reads the
    300.0 reserved against 100.0 available that Site Alpha's reservation established —
    the two figures still summing to the 400 MW the utility can deliver.

    PRD §3.5: "On success the application's `reserved_mw` is set to its requested megawatts, the utility's capacity ledger is recomputed, the `energization_risk_tier` of the owning site **and of every other site of that serving utility** is recomputed, the affected program's status is re-derived, and the application's `version` is incremented by one."
    PRD §2.8: "A utility's `reserved_capacity_mw` plus its `available_capacity_mw` always equals its `total_transmission_capacity_mw`, and `available_capacity_mw` is never negative."

    Design: Difficulty/priority_pair_validation_conflict/reserve_capacity_state_beats_transmission_capacity
    """
    env = _four_hundred_mw_environment()
    _bravo, contested = _contested_same_window_application(env)

    api_client.reserve_capacity(
        contested["id"], make_utility_planner_headers(env["utility"]["id"])
    )

    refreshed = read_application(contested["id"])
    assert_status(refreshed, "SUBMITTED", "contested application")
    assert_mw(refreshed["reserved_mw"], 0, "reserved_mw")

    utility = read_utility(env["utility"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 300.0, "reserved_capacity_mw")
    assert_mw(utility["available_capacity_mw"], 100.0, "available_capacity_mw")
    assert_utility_ledger_conserved(utility)


def test_commitment_reports_the_zoning_gate_ahead_of_land_and_incentive_gates():
    """Three commit gates are unmet at once — the docket is still `SUBMITTED`, the
    campus has no options at all, and no term sheet has even been opened — yet the
    ladder is fixed, so the safety gate on zoning answers first. Neither the land
    control error nor the ratified-incentives error can surface while zoning is
    outstanding.

    PRD §3.10: "The site's zoning docket must stand at `APPROVED_WITH_CONDITIONS`, else `ERR_ZONING_NOT_APPROVED`."
    PRD §2.11: "On a site commitment, the ten domain gates fire in the order segregation of duties, hazard prohibition, zoning approval, single-committed-site, land control, ratified state incentives, water sufficiency, renewable coverage, capital ceiling — after the site's own state has been checked — so a caller who is both the screener and short of land control learns about the duty conflict first."
    PRD §3.10: "The site's `land_control_pct` must be at least 100, because a partially optioned campus cannot be committed, else `ERR_LAND_CONTROL_INCOMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/commit_zoning_safety_beats_incentive_referential
    """
    env = setup_screened_site()
    file_zoning(env["site"]["id"], visual_mitigation_tier="BERM_AND_SCREENING")

    before = read_site(env["site"]["id"])
    assert_land_control(before, 0, "NONE")
    assert list_site_negotiations(env["site"]["id"])["data"] == []

    response = api_client.commit_candidate_site(env["site"]["id"], make_chair_headers())

    validate_error(response, "ERR_ZONING_NOT_APPROVED", 409)


def test_refused_commitment_stamps_nobody_and_leaves_the_program_screening():
    """The single most consequential act in the system is all-or-nothing. After the
    refusal the site is still `SCREENED` at the same version, `committed_by_user_id`
    remains null — it is null until the moment of a successful commitment — and the
    program's rollup still reads `SCREENING` because it has no committed site.

    PRD §3.10: "On success the site's `status` becomes `COMMITTED`, the acting operator is stamped as `committed_by_user_id` — null until that moment — the capital commitment is recomputed and compared against the ceiling, the program moves `SCREENING` to `SITE_COMMITTED`, and the site's `version` is incremented by one."
    PRD §3.10: "Failing that, the status is `SITE_COMMITTED` when a committed site exists at all. Otherwise the status is `SCREENING`."

    Design: Difficulty/priority_pair_validation_conflict/commit_zoning_safety_beats_incentive_referential
    """
    env = setup_screened_site()
    file_zoning(env["site"]["id"], visual_mitigation_tier="BERM_AND_SCREENING")
    before = read_site(env["site"]["id"])

    api_client.commit_candidate_site(env["site"]["id"], make_chair_headers())

    after = read_site(env["site"]["id"])
    assert_status(after, "SCREENED", "Site Alpha")
    assert after["committed_by_user_id"] is None
    assert_version_unchanged(before, after, "Site Alpha")

    assert_program_rollup(
        read_program(env["program"]["id"]), program_status="SCREENING"
    )


def test_group_demand_of_exactly_the_utility_capacity_is_admitted():
    """Site Bravo's 2030 window opens inside Site Alpha's 2029 window extended by the
    90-day commissioning buffer, so the two applications are concurrent and Bravo's
    group demand is 300 plus 100, exactly the 400 MW the utility can deliver. Equality
    is admissible, so the reservation succeeds and drives available capacity to exactly
    0.0 without ever going negative.

    PRD §3.5: "Second, the aggregate must fit: the requested megawatts of every **other** reserved or energization-committed application of that utility whose buffered window overlaps this one are summed, this application's own requested megawatts are added, and that total must be less than or equal to the utility's `total_transmission_capacity_mw`."
    PRD §3.5: "Two applications of the same utility are treated as concurrent when each one's `window_start` falls at or before the other's `window_end` extended forward by the utility's `commissioning_buffer_days` — that is, the buffer is applied to **both** ends of **both** windows under test, and the windows themselves are closed intervals."
    PRD §3.5: "The utility's `reserved_capacity_mw` is the largest such group demand across the set, rounded to 3 decimal places, and it is exactly 0 when the set is empty."

    Design: Difficulty/boundary_precision_check/transmission_group_demand_exact_equality_admits
    """
    env = _exact_equality_environment()

    reserved = reserve_capacity(env["bravo_application"]["id"], env["utility"]["id"])

    assert_status(reserved, "CAPACITY_RESERVED", "Site Bravo's application")
    assert_mw(reserved["reserved_mw"], 100, "reserved_mw")

    utility = read_utility(env["utility"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 400.0, "reserved_capacity_mw")
    assert_mw(utility["available_capacity_mw"], 0.0, "available_capacity_mw")
    assert_utility_ledger_conserved(utility)


def test_one_megawatt_past_the_ceiling_is_refused_on_the_same_utility():
    """Site Charlie asks for 101 MW over that same overlapping window, which lands its
    group demand at 501.0 against a ceiling of 400 — one megawatt beyond admissible is
    refused. Its application therefore stays in `STUDY_COMPLETE` and the utility's
    reserved figure is unchanged at the 400.0 the admitted reservation set.

    PRD §3.5: "Equality is admissible; one megawatt beyond it is rejected with `ERR_TRANSMISSION_CAPACITY_EXCEEDED`, and the comparison is made at 3 decimal places."
    PRD §3.5: "Because the admission test above bounds the same group demand by the same total, the available figure can never go negative, and two live applications whose buffered windows do not overlap never inflate each other's group demand."

    Design: Difficulty/boundary_precision_check/transmission_group_demand_exact_equality_admits
    """
    env = _exact_equality_environment()
    reserve_capacity(env["bravo_application"]["id"], env["utility"]["id"])

    response = api_client.reserve_capacity(
        env["charlie_application"]["id"],
        make_utility_planner_headers(env["utility"]["id"]),
    )

    validate_error(response, "ERR_TRANSMISSION_CAPACITY_EXCEEDED", 409)

    refreshed = read_application(env["charlie_application"]["id"])
    assert_status(refreshed, "STUDY_COMPLETE", "Site Charlie's application")
    assert_mw(refreshed["reserved_mw"], 0, "reserved_mw")

    utility = read_utility(env["utility"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 400.0, "reserved_capacity_mw")
    assert_utility_ledger_conserved(utility)


def test_withdrawing_a_reservation_restores_the_ledger_with_no_residual_drift():
    """Transmission capacity is conserved rather than consumed: the ledger sums to the
    400 MW ceiling before the reservation, while 300.0 is held against 100.0 available,
    and again after the withdrawal — which returns the utility to exactly the 0 reserved
    against 400.0 available it started from, with no residual megawatt left behind.

    PRD §3.5: "Withdrawing an application that had reached `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED` restores the utility's available capacity to exactly the value it held before the reservation — full compensation, no residual drift."
    PRD §2.8: "Releasing a reservation or forfeiting a premium moves value between buckets; it never creates or destroys value, and it never leaves residual drift."

    Design: Difficulty/compensating_invariant/utility_capacity_restored_on_withdraw
    """
    env = _four_hundred_mw_environment(headroom=300)
    while_reserved = read_utility(env["utility"]["id"])
    assert_mw(while_reserved["reserved_capacity_mw"], 300.0, "reserved_capacity_mw")
    assert_mw(while_reserved["available_capacity_mw"], 100.0, "available_capacity_mw")
    assert_utility_ledger_conserved(while_reserved)

    withdraw_application(env["application"]["id"], "SPONSOR_DEFERRED")

    after = read_utility(env["utility"]["id"])
    assert_mw(after["reserved_capacity_mw"], 0, "reserved_capacity_mw")
    assert_mw(after["available_capacity_mw"], 400.0, "available_capacity_mw")
    assert_utility_ledger_conserved(after)


def test_withdrawal_clears_the_queue_position_but_the_study_fee_stays_sunk():
    """The compensation is deliberately partial. Withdrawal zeroes the reserved
    megawatts and the queue position, but the 360000.00 the study cost is money already
    spent and stays recorded on the application; because a withdrawn application no
    longer feeds its site's capital commitment, that site now aggregates to zero.

    PRD §3.5: "Withdrawing sets `status` to `WITHDRAWN`, zeroes `reserved_mw` and `queue_position`, and recomputes the utility's `reserved_capacity_mw` and `available_capacity_mw`."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`."

    Design: Difficulty/compensating_invariant/utility_capacity_restored_on_withdraw
    """
    env = _four_hundred_mw_environment(headroom=300)

    withdrawn = withdraw_application(env["application"]["id"], "SPONSOR_DEFERRED")

    assert_status(withdrawn, "WITHDRAWN", "application")
    assert_mw(withdrawn["reserved_mw"], 0, "reserved_mw")
    assert withdrawn["queue_position"] == 0
    assert_money(withdrawn["study_fee_usd"], EXPECTED_STUDY_FEE_USD, "study_fee_usd")

    site = read_site(env["site"]["id"])
    assert_money(site["site_capital_commitment_usd"], 0, "site_capital_commitment_usd")
