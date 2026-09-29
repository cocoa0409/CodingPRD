"""The one concurrency token, the recomputed capital total, and immediate visibility."""

from test_helpers import (
    APPLICATION_REQUESTED_MW,
    EXPECTED_DIVERSIFIED_PEAK_MW,
    EXPECTED_STUDY_FEE_USD,
    EXPECTED_UPGRADE_COST_USD,
    OPTION_APN_100,
    OPTION_APN_200,
    TEST_USERS,
    UTILITY_TOTAL_CAPACITY_MW,
    api_client,
    assert_land_control,
    assert_money,
    assert_mw,
    assert_program_rollup,
    assert_status,
    assert_utility_ledger_conserved,
    assert_version,
    create_parcel_option_payload,
    draft_application,
    file_load_study,
    list_options,
    read_application,
    read_program,
    read_site,
    read_utility,
    reserve_capacity,
    setup_draft_site,
    setup_reserved_application,
    setup_screened_site,
    setup_studied_application,
    sign_option,
    submit_application,
    validate_error,
    withdraw_application,
)

# The two premiums of the fully assembled campus, both still OPTIONED.
TOTAL_PREMIUM_EXPOSURE_USD = 2150000.00

# The study fee plus the network upgrade, which is the whole capital commitment of a
# campus that has no zoning docket and no land options.
EXPECTED_CAPITAL_AFTER_STUDY_USD = 27305136.00

WITHDRAWAL_REASON = "Utility upgrade cost exceeded the phase budget."


def test_a_stale_site_version_is_turned_away_and_the_refreshed_one_is_admitted():
    """The one optimistic-concurrency token in the system, exercised on the write that
    carries it. The first option moves the site's version, so replaying the client's
    original view is refused with the concurrency error and writes nothing at all — one
    option on the site, the version still where the first write left it. Re-reading the
    site and replaying the identical payload against the fresh view is admitted, and the
    second parcel completes the footprint.

    PRD §2.10: "A request creating a land parcel option — `POST /parcel-options` — must include `expected_site_version`, carrying the client's last observed `version` of the `CandidateSite` named by `site_id`. The value is not optional and has no default. If `expected_site_version` does not equal that site's current `version` integer, the create is rejected with `ERR_STALE_SITE_VERSION` and HTTP 412."
    PRD §2.10: "The check runs after path and body references have been resolved and before any state-machine or exclusivity condition is evaluated."
    PRD §3.8: "Signing also increments the addressed site's `version` by one — which is precisely why the next writer needs a fresh `expected_site_version` — moves the program's `option_exposure_usd` and `premium_committed_total_usd`, re-derives `program_status`, and recomputes the site's `site_capital_commitment_usd`."
    PRD §3.8: "The acreage of every option of that site whose `status` is `OPTIONED` or `EXERCISED` is summed, multiplied by 100, divided by the site's `gross_acres`, capped at 100.0 and rounded to 2 decimal places to give `land_control_pct` — so a campus that has optioned more acreage than its gross footprint still reports 100.00 rather than more. The `land_control_status` follows directly: `FULL` when the percentage is at or above 100, `NONE` when it is exactly 0, and `PARTIAL` at any value between."
    PRD §3.8: "`option_exposure_usd` totals the premiums of options still `OPTIONED`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_site_version_rejected_then_accepted
    """
    env = setup_draft_site()
    site_id = env["site"]["id"]
    observed_version = env["site"]["version"]

    first = sign_option(
        site_id, expected_site_version=observed_version, **OPTION_APN_100
    )
    assert_status(first, "OPTIONED", "the first option")
    after_first = read_site(site_id)
    assert_version(after_first, observed_version + 1, "the site after its first option")

    stale_payload = create_parcel_option_payload(
        site_id, observed_version, **OPTION_APN_200
    )
    validate_error(
        api_client.create_parcel_option(
            stale_payload, TEST_USERS["analyst_headers"]
        ),
        "ERR_STALE_SITE_VERSION",
        412,
    )

    # The refused create wrote nothing and consumed no version.
    assert list_options({"site_id": site_id})["meta"]["total_count"] == 1, (
        "a refused option create leaves the site with only its first option"
    )
    refreshed = read_site(site_id)
    assert_version(refreshed, observed_version + 1, "the site after the refusal")

    second = sign_option(
        site_id, expected_site_version=refreshed["version"], **OPTION_APN_200
    )
    assert_status(second, "OPTIONED", "the second option")

    settled = read_site(site_id)
    assert_version(settled, observed_version + 2, "the site after both options")
    assert_land_control(settled, 100.00, "FULL")
    assert list_options({"site_id": site_id})["meta"]["total_count"] == 2

    program = read_program(env["program"]["id"])
    assert_money(
        program["option_exposure_usd"],
        TOTAL_PREMIUM_EXPOSURE_USD,
        "option_exposure_usd",
    )


def test_the_capital_total_is_recomputed_as_each_of_its_sources_appears():
    """The denormalized capital figure is never incremented by hand: it is re-aggregated
    from its sources every time one of them moves. A screened campus with nothing filed
    against it carries zero; drafting the application still carries zero, because no fee
    is struck until submission; submission books the study fee; and the first study round
    books the network upgrade the diversified peak triggers, on a campus whose hazard tier
    lifts the rate by eight percent. Reserving capacity moves no source, so the figure
    holds exactly where the study left it.

    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`. The total is rounded to 2 decimal places. Premiums on `LAPSED` and `RELEASED` options are sunk money and are deliberately excluded. This figure is recomputed whenever any of its inputs moves — on application submission, on each load study round, on withdrawal, on a zoning decision, on option signature, exercise or lapse, and again at commitment."
    PRD §3.4: "A drafted application sits at `status` `DRAFT` with `queue_position` of 0, `reserved_mw` of 0, `study_round` of 0, `study_fee_usd` of 0, `network_upgrade_cost_usd` of 0 and `delay_exposure_usd` of 0: nothing is reserved and no fee is charged until it is submitted."
    PRD §3.4: "On submission the current logical clock is stamped as `submitted_at`, which becomes the primary queue sort key, and the study fee is struck: `study_fee_usd` is the requested megawatts multiplied by the utility's study fee rate per megawatt, rounded to 2 decimal places."
    PRD §3.4: "An upgrade trigger is computed as the utility's total transmission capacity multiplied by 0.50 and rounded to 3 decimal places, and `upgrade_required` is true only when the diversified peak is **strictly greater** than that trigger; a diversified peak exactly equal to the trigger does not require an upgrade. When no upgrade is required the study's `network_upgrade_cost_usd` is exactly 0.00. When one is required, the cost is the diversified peak multiplied by the utility's network upgrade rate per megawatt, multiplied by one plus a hazard uplift drawn from the owning site's hazard tier — no uplift at all for `LOW` at 0.00, an eight percent uplift for `MODERATE` at 0.08, and a twenty percent uplift for `SEVERE` at 0.20 — with the result rounded to 2 decimal places."
    PRD §3.4: "After each study round the application's own `diversified_peak_mw` and `network_upgrade_cost_usd` mirror the **newest** study — the one with the highest `study_round`, breaking any tie by the later `created_at` — so a restudy replaces the figures a client saw rather than adding to them. The application's `study_round` counter is incremented, and the owning site's `site_capital_commitment_usd` is recomputed because the upgrade cost feeds it."

    Design: Corner/cross_cutting_complexity_layers/site_capital_commitment_reconciles_across_create_and_reversal
    """
    env = setup_screened_site()
    site_id = env["site"]["id"]
    assert env["site"]["hazard_tier"] == "MODERATE", (
        "the screened campus carries the moderate tier the upgrade uplift reads"
    )
    assert_money(
        env["site"]["site_capital_commitment_usd"],
        0.00,
        "site_capital_commitment_usd at screening",
    )

    drafted = draft_application(site_id, env["utility"]["id"])
    assert_money(drafted["study_fee_usd"], 0.00, "study_fee_usd while DRAFT")
    assert_money(
        drafted["network_upgrade_cost_usd"], 0.00, "network_upgrade_cost_usd while DRAFT"
    )
    assert_money(
        read_site(site_id)["site_capital_commitment_usd"],
        0.00,
        "site_capital_commitment_usd while the application is DRAFT",
    )

    submitted = submit_application(drafted["id"])
    assert_money(submitted["study_fee_usd"], EXPECTED_STUDY_FEE_USD, "study_fee_usd")
    assert_money(
        read_site(site_id)["site_capital_commitment_usd"],
        EXPECTED_STUDY_FEE_USD,
        "site_capital_commitment_usd after submission",
    )

    study = file_load_study(drafted["id"], env["utility"]["id"])
    assert study["upgrade_required"] is True
    assert_mw(study["diversified_peak_mw"], EXPECTED_DIVERSIFIED_PEAK_MW, "diversified")
    assert_money(
        study["network_upgrade_cost_usd"],
        EXPECTED_UPGRADE_COST_USD,
        "the study's network_upgrade_cost_usd",
    )

    studied = read_application(drafted["id"])
    assert_money(
        studied["network_upgrade_cost_usd"],
        EXPECTED_UPGRADE_COST_USD,
        "the application's network_upgrade_cost_usd",
    )
    assert_money(
        read_site(site_id)["site_capital_commitment_usd"],
        EXPECTED_CAPITAL_AFTER_STUDY_USD,
        "site_capital_commitment_usd after the study round",
    )

    reserve_capacity(drafted["id"], env["utility"]["id"])
    assert_money(
        read_site(site_id)["site_capital_commitment_usd"],
        EXPECTED_CAPITAL_AFTER_STUDY_USD,
        "site_capital_commitment_usd after the reservation",
    )


def test_withdrawing_the_only_application_reverses_the_whole_capital_total():
    """The reversal is the same aggregation run again rather than a compensating
    subtraction. A withdrawn application contributes nothing, so a campus whose only
    capital sources were its study fee and its network upgrade drops straight back to
    zero; the utility's ledger is restored with no residual drift; and the site, which
    never left `SCREENED`, reads `ON_TRACK` afterwards because its utility visibly holds
    more capacity than the program targets.

    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`. The total is rounded to 2 decimal places. Premiums on `LAPSED` and `RELEASED` options are sunk money and are deliberately excluded. This figure is recomputed whenever any of its inputs moves — on application submission, on each load study round, on withdrawal, on a zoning decision, on option signature, exercise or lapse, and again at commitment."
    PRD §3.5: "Withdrawing sets `status` to `WITHDRAWN`, zeroes `reserved_mw` and `queue_position`, and recomputes the utility's `reserved_capacity_mw` and `available_capacity_mw`. Withdrawing an application that had reached `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED` restores the utility's available capacity to exactly the value it held before the reservation — full compensation, no residual drift. The queue is re-ranked for the utility's remaining applications so positions stay contiguous, the owning site's `energization_risk_tier` and `site_capital_commitment_usd` are recomputed, the program's status and `committed_load_mw` are re-derived, and the application's `version` is incremented by one."
    PRD §2.8: "A utility's `reserved_capacity_mw` plus its `available_capacity_mw` always equals its `total_transmission_capacity_mw`, and `available_capacity_mw` is never negative."
    PRD §3.5: "It reads the site's single application that is not `WITHDRAWN`, of which at most one exists. The tier is `BREACHED` when that application exists, sits in `ENERGIZATION_COMMITTED`, and its committed energization date is later than the program's required energization date. Otherwise the tier is `AT_RISK` when either no live application exists at all or the live application is still in `DRAFT`, `SUBMITTED` or `STUDY_COMPLETE`, **and** the serving utility's `available_capacity_mw` is strictly less than the program's `target_load_mw` — in other words, the site has not yet locked capacity and its utility no longer visibly has enough to give. In every other case the tier is `ON_TRACK`."
    PRD §3.10: "The derivation looks at the program's single site whose `status` is `COMMITTED`, of which at most one exists, and takes the **first** matching branch of four. The status is `STALLED` when a committed site exists and that site is impaired — meaning its `land_control_status` is anything other than `FULL`, **or** its `water_feasible` flag is false, **or** its `energization_risk_tier` is `BREACHED`. Failing that, the status is `ENERGIZATION_SECURED` when a committed site exists and its application that is not `WITHDRAWN` sits in `ENERGIZATION_COMMITTED`. Failing that, the status is `SITE_COMMITTED` when a committed site exists at all. Otherwise the status is `SCREENING`. Because the impairment test is evaluated **before** the energization test, a site that is energization-committed but has lost its land control or its water reports `STALLED` rather than `ENERGIZATION_SECURED`. Disqualified sites are excluded from every branch. Alongside the status, `committed_load_mw` is re-derived as the sum of `requested_mw` over the applications of this program's sites whose status is `ENERGIZATION_COMMITTED`, and every re-derivation that changes the program increments the program's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/site_capital_commitment_reconciles_across_create_and_reversal
    """
    env = setup_reserved_application()
    site_id = env["site"]["id"]
    live = read_application(env["application"]["id"])

    before = read_site(site_id)
    assert_money(
        before["site_capital_commitment_usd"],
        live["study_fee_usd"] + live["network_upgrade_cost_usd"],
        "site_capital_commitment_usd with only the application as a source",
    )
    assert before["site_capital_commitment_usd"] > 0

    withdrawn = withdraw_application(env["application"]["id"], WITHDRAWAL_REASON)
    assert_status(withdrawn, "WITHDRAWN", "the withdrawn application")
    assert_mw(withdrawn["reserved_mw"], 0, "reserved_mw after withdrawal")
    assert withdrawn["queue_position"] == 0
    assert withdrawn["withdrawal_reason"] == WITHDRAWAL_REASON

    after = read_site(site_id)
    assert_money(
        after["site_capital_commitment_usd"],
        0.00,
        "site_capital_commitment_usd after withdrawal",
    )
    assert_status(after, "SCREENED", "the site across the reversal")
    assert after["energization_risk_tier"] == "ON_TRACK", (
        "no live application remains, but the utility still holds more than the "
        "program targets, so the AT_RISK branch does not fire"
    )

    utility = read_utility(env["utility"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 0, "reserved_capacity_mw")
    assert_mw(
        utility["available_capacity_mw"],
        UTILITY_TOTAL_CAPACITY_MW,
        "available_capacity_mw",
    )
    assert_utility_ledger_conserved(utility)

    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SCREENING",
        committed_load_mw=0,
    )


def test_the_reserving_response_already_carries_its_own_derived_figures():
    """Immediate consistency starts with the mutating response itself: the reservation
    reply already reports the reserved megawatts, the coincident peak the study produced
    and the network upgrade that peak priced, with no second call needed to see them. A
    read issued straight afterwards adds nothing — same figures, same version — which is
    the point.

    PRD §2.8: "A large share of this system's fields are derived, and the contract is that no response ever exposes a derived field that lags the mutation that request performed. Derived fields are recomputed inside the request that invalidates them, in dependency order, and the response body reflects the post-cascade state."
    PRD §3.5: "On success the application's `reserved_mw` is set to its requested megawatts, the utility's capacity ledger is recomputed, the `energization_risk_tier` of the owning site **and of every other site of that serving utility** is recomputed, the affected program's status is re-derived, and the application's `version` is incremented by one."
    PRD §3.4: "The `diversified_peak_mw` figure is the utility's coincident view: the IT component is multiplied by the diversity factor, the cooling component is multiplied by whichever is larger of the diversity factor and a cooling floor of 0.85 so that cooling load never diversifies below that floor, the ancillary component is taken undiversified at full value, the three products are added, and the total is rounded to 3 decimal places."
    PRD §3.4: "An upgrade trigger is computed as the utility's total transmission capacity multiplied by 0.50 and rounded to 3 decimal places, and `upgrade_required` is true only when the diversified peak is **strictly greater** than that trigger; a diversified peak exactly equal to the trigger does not require an upgrade. When no upgrade is required the study's `network_upgrade_cost_usd` is exactly 0.00. When one is required, the cost is the diversified peak multiplied by the utility's network upgrade rate per megawatt, multiplied by one plus a hazard uplift drawn from the owning site's hazard tier — no uplift at all for `LOW` at 0.00, an eight percent uplift for `MODERATE` at 0.08, and a twenty percent uplift for `SEVERE` at 0.20 — with the result rounded to 2 decimal places."
    PRD §3.4: "After each study round the application's own `diversified_peak_mw` and `network_upgrade_cost_usd` mirror the **newest** study — the one with the highest `study_round`, breaking any tie by the later `created_at` — so a restudy replaces the figures a client saw rather than adding to them."

    Design: Corner/consistency_model/derived_fields_visible_in_the_same_response
    """
    env = setup_studied_application()
    assert env["site"]["hazard_tier"] == "MODERATE", (
        "the screened campus carries the moderate tier the upgrade uplift reads"
    )
    studied = read_application(env["application"]["id"])

    reserved = reserve_capacity(env["application"]["id"], env["utility"]["id"])

    assert_status(reserved, "CAPACITY_RESERVED", "the reserving response")
    assert_mw(reserved["reserved_mw"], APPLICATION_REQUESTED_MW, "reserved_mw")
    assert_mw(
        reserved["diversified_peak_mw"],
        EXPECTED_DIVERSIFIED_PEAK_MW,
        "diversified_peak_mw in the reserving response",
    )
    assert_money(
        reserved["network_upgrade_cost_usd"],
        EXPECTED_UPGRADE_COST_USD,
        "network_upgrade_cost_usd in the reserving response",
    )
    assert_version(reserved, studied["version"] + 1, "the reserved application")

    # A read straight afterwards adds nothing the response did not already carry.
    reread = read_application(env["application"]["id"])
    assert_version(reread, reserved["version"], "the application on re-read")
    assert_mw(reread["reserved_mw"], reserved["reserved_mw"], "reserved_mw on re-read")
    assert_mw(
        reread["diversified_peak_mw"],
        reserved["diversified_peak_mw"],
        "diversified_peak_mw on re-read",
    )
    assert_money(
        reread["network_upgrade_cost_usd"],
        reserved["network_upgrade_cost_usd"],
        "network_upgrade_cost_usd on re-read",
    )


def test_the_reads_that_follow_a_reservation_show_every_aggregate_already_moved():
    """Consistency reaches across aggregates, not merely across one row. The reads issued
    immediately after the reservation — the utility, then the site, then the program —
    already show the recomputed capacity ledger, the re-aggregated capital total and the
    unchanged rollup. The rollup is the interesting one: a reservation is not an
    energization commitment, so the program is still screening and still carries no
    committed load.

    PRD §2.8: "A large share of this system's fields are derived, and the contract is that no response ever exposes a derived field that lags the mutation that request performed. Derived fields are recomputed inside the request that invalidates them, in dependency order, and the response body reflects the post-cascade state."
    PRD §3.5: "Taking the set of that utility's applications in `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED`, each member's group demand is its own requested megawatts plus the requested megawatts of every other member whose buffered window overlaps it. The utility's `reserved_capacity_mw` is the largest such group demand across the set, rounded to 3 decimal places, and it is exactly 0 when the set is empty. Its `available_capacity_mw` is the total transmission capacity minus the reserved figure, rounded to 3 decimal places."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`. The total is rounded to 2 decimal places."
    PRD §3.5: "It reads the site's single application that is not `WITHDRAWN`, of which at most one exists. The tier is `BREACHED` when that application exists, sits in `ENERGIZATION_COMMITTED`, and its committed energization date is later than the program's required energization date. Otherwise the tier is `AT_RISK` when either no live application exists at all or the live application is still in `DRAFT`, `SUBMITTED` or `STUDY_COMPLETE`, **and** the serving utility's `available_capacity_mw` is strictly less than the program's `target_load_mw` — in other words, the site has not yet locked capacity and its utility no longer visibly has enough to give. In every other case the tier is `ON_TRACK`."
    PRD §3.10: "The derivation looks at the program's single site whose `status` is `COMMITTED`, of which at most one exists, and takes the **first** matching branch of four. The status is `STALLED` when a committed site exists and that site is impaired — meaning its `land_control_status` is anything other than `FULL`, **or** its `water_feasible` flag is false, **or** its `energization_risk_tier` is `BREACHED`. Failing that, the status is `ENERGIZATION_SECURED` when a committed site exists and its application that is not `WITHDRAWN` sits in `ENERGIZATION_COMMITTED`. Failing that, the status is `SITE_COMMITTED` when a committed site exists at all. Otherwise the status is `SCREENING`. Because the impairment test is evaluated **before** the energization test, a site that is energization-committed but has lost its land control or its water reports `STALLED` rather than `ENERGIZATION_SECURED`. Disqualified sites are excluded from every branch. Alongside the status, `committed_load_mw` is re-derived as the sum of `requested_mw` over the applications of this program's sites whose status is `ENERGIZATION_COMMITTED`, and every re-derivation that changes the program increments the program's `version` by one."

    Design: Corner/consistency_model/derived_fields_visible_in_the_same_response
    """
    env = setup_studied_application()
    reserved = reserve_capacity(env["application"]["id"], env["utility"]["id"])

    utility = read_utility(env["utility"]["id"])
    assert_mw(
        utility["reserved_capacity_mw"], APPLICATION_REQUESTED_MW, "reserved_capacity_mw"
    )
    assert_mw(
        utility["available_capacity_mw"],
        UTILITY_TOTAL_CAPACITY_MW - APPLICATION_REQUESTED_MW,
        "available_capacity_mw",
    )
    assert_utility_ledger_conserved(utility)

    site = read_site(env["site"]["id"])
    assert_money(
        site["site_capital_commitment_usd"],
        reserved["study_fee_usd"] + reserved["network_upgrade_cost_usd"],
        "site_capital_commitment_usd straight after the reservation",
    )
    assert site["energization_risk_tier"] == "ON_TRACK", (
        "the site has locked capacity, so neither the BREACHED nor the AT_RISK "
        "branch applies"
    )

    assert_program_rollup(
        read_program(env["program"]["id"]),
        program_status="SCREENING",
        committed_load_mw=0,
    )
