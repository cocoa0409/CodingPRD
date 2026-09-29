"""Multi-hop cascades: dropping a site, sweeping expired options, superseding a parcel."""

from test_helpers import (
    OPTION_APN_100,
    SCREEN_AIR_COOLED,
    SITE_DISQUALIFIED_WITHDRAWAL_REASON,
    add_sibling_site,
    assemble_full_land_control,
    assert_clock_instant,
    assert_land_control,
    assert_money,
    assert_mw,
    assert_premium_ledger,
    assert_program_rollup,
    assert_status,
    assert_utility_ledger_conserved,
    commit_energization,
    disqualify_site,
    draft_application,
    file_load_study,
    read_application,
    read_option,
    read_program,
    read_site,
    read_utility,
    reserve_capacity,
    run_expiry_sweep,
    set_clock,
    setup_draft_site,
    setup_screened_site,
    sign_option,
    site_version,
    submit_application,
)

CASCADE_UTILITY = {
    "name": "Catawba Electric",
    "state_code": "SC",
    "balancing_authority": "SOCO",
    "total_transmission_capacity_mw": 400,
}
CASCADE_BASIN = {"name": "Broad River", "basin_code": "BRD-01", "state_code": "SC"}


def _energization_committed_pipeline():
    """Two air-cooled sites on a 400 MW utility, with only the first carrying an
    application walked all the way to an energization commitment for 300 MW."""
    env = setup_screened_site(
        program={"name": "Hyperscale Bravo"},
        utility=CASCADE_UTILITY,
        water_source=CASCADE_BASIN,
        site={"name": "Site Alpha", "state_code": "SC", "county": "Cherokee"},
        screening=SCREEN_AIR_COOLED,
    )
    env["sibling"] = add_sibling_site(
        env,
        site={"name": "Site Bravo", "state_code": "SC", "county": "Union"},
        screening=SCREEN_AIR_COOLED,
    )
    application = draft_application(env["site"]["id"], env["utility"]["id"])
    submit_application(application["id"])
    file_load_study(application["id"], env["utility"]["id"])
    reserve_capacity(application["id"], env["utility"]["id"])
    env["application"] = commit_energization(
        application["id"], env["utility"]["id"], "2029-06-30T00:00:00Z"
    )
    return env


def _two_optioned_parcels_past_the_first_window():
    """A 300-acre campus fully controlled by two options, with the clock moved past
    the first option's window end but not the second's."""
    env = setup_draft_site()
    env["options"] = assemble_full_land_control(env["site"]["id"])
    set_clock("2028-01-01T00:00:00Z")
    return env


def test_dropping_a_site_withdraws_its_live_application_and_frees_the_ledger():
    """One disqualify call reaches an entity the request never names: the site's
    energization-committed application is withdrawn for it, with the reason recorded as
    the reserved `SITE_DISQUALIFIED` string rather than anything the caller supplied,
    and its reserved megawatts and queue position zeroed. The second hop then restores
    the serving utility's ledger to the 0 reserved against 400.0 available it held
    before the reservation.

    PRD §3.10: "The first hop withdraws the site's live interconnection application: any application in `SUBMITTED`, `STUDY_COMPLETE`, `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED` moves to `WITHDRAWN` with `withdrawal_reason` recorded as the string `SITE_DISQUALIFIED`, `reserved_mw` zeroed and `queue_position` zeroed."
    PRD §3.10: "The second hop, because that application released its reservation, recomputes the serving utility's `reserved_capacity_mw` and `available_capacity_mw`."
    PRD §3.10: "The site's `status` becomes `DISQUALIFIED`, its `disqualification_reason` is persisted, and its `version` is incremented by one."

    Design: Difficulty/transitive_cascade/site_disqualification_releases_queue_and_retiers_sibling
    """
    env = _energization_committed_pipeline()
    before = read_utility(env["utility"]["id"])
    assert_mw(before["reserved_capacity_mw"], 300.0, "reserved_capacity_mw before")
    assert_mw(before["available_capacity_mw"], 100.0, "available_capacity_mw before")

    dropped = disqualify_site(env["site"]["id"], "TRANSMISSION_RISK")

    assert_status(dropped, "DISQUALIFIED", "Site Alpha")
    assert dropped["disqualification_reason"] == "TRANSMISSION_RISK"

    application = read_application(env["application"]["id"])
    assert_status(application, "WITHDRAWN", "application")
    assert application["withdrawal_reason"] == SITE_DISQUALIFIED_WITHDRAWAL_REASON
    assert_mw(application["reserved_mw"], 0, "reserved_mw")
    assert application["queue_position"] == 0

    after = read_utility(env["utility"]["id"])
    assert_mw(after["reserved_capacity_mw"], 0, "reserved_capacity_mw")
    assert_mw(after["available_capacity_mw"], 400.0, "available_capacity_mw")
    assert_utility_ledger_conserved(after)


def test_freed_capacity_retiers_the_sibling_site_and_resets_the_program_rollup():
    """The cascade's last two hops leave the dropped site's own entity graph entirely.
    Site Bravo has no application of its own, so while its utility showed only 100.0 MW
    available against a 300 MW target its tier read `AT_RISK`; the release pushes
    availability back to 400.0 and the tier is recomputed to `ON_TRACK` even though
    nothing about Bravo changed. The program then loses its only
    energization-committed application, so `committed_load_mw` falls to 0.

    PRD §3.10: "The third hop, because the utility's available capacity changed, recomputes `energization_risk_tier` on every **other** candidate site of that utility whose status is `DRAFT`, `SCREENED` or `COMMITTED`."
    PRD §3.5: "Otherwise the tier is `AT_RISK` when either no live application exists at all or the live application is still in `DRAFT`, `SUBMITTED` or `STUDY_COMPLETE`, **and** the serving utility's `available_capacity_mw` is strictly less than the program's `target_load_mw` — in other words, the site has not yet locked capacity and its utility no longer visibly has enough to give."
    PRD §3.10: "Alongside the status, `committed_load_mw` is re-derived as the sum of `requested_mw` over the applications of this program's sites whose status is `ENERGIZATION_COMMITTED`, and every re-derivation that changes the program increments the program's `version` by one."

    Design: Difficulty/transitive_cascade/site_disqualification_releases_queue_and_retiers_sibling
    """
    env = _energization_committed_pipeline()
    sibling_before = read_site(env["sibling"]["id"])
    assert sibling_before["energization_risk_tier"] == "AT_RISK"

    disqualify_site(env["site"]["id"], "TRANSMISSION_RISK")

    sibling_after = read_site(env["sibling"]["id"])
    assert sibling_after["energization_risk_tier"] == "ON_TRACK"
    assert_status(sibling_after, "SCREENED", "Site Bravo")

    program = read_program(env["program"]["id"])
    assert_program_rollup(program, program_status="SCREENING", committed_load_mw=0)


def test_expiry_sweep_lapses_only_the_option_whose_window_has_closed():
    """With the clock at 2028-01-01 the first option's half-open window has closed at
    or before that instant while the second's runs to 2029-12-31, so the sweep carries
    exactly one option to `LAPSED` and stamps the logical clock as its `lapsed_at`. The
    forfeited premium moves bucket rather than disappearing: exposure falls to
    900000.00, forfeited rises to 1250000.00 and the conserved total stays 2150000.00.

    PRD §3.8: "A `PortfolioDirector` runs an explicit **option-expiry sweep** across every parcel option belonging to every site of one program, and each option still in `OPTIONED` whose half-open window has closed — that is, whose `window_end` is at or before the current logical clock — is carried `OPTIONED` to `LAPSED`."
    PRD §3.8: "The first hop lapses the option itself: `status` becomes `LAPSED`, `lapsed_at` records the current logical clock, and the premium shifts from `option_exposure_usd` into `forfeited_premium_usd` with `premium_committed_total_usd` unchanged."
    PRD §3.8: "`premium_committed_total_usd` totals every premium regardless of status and is therefore the conserved figure that the other three must always sum to, across every option of every site of the program regardless of those sites' own statuses."

    Design: Difficulty/transitive_cascade/option_expiry_sweep_degrades_land_control_rollup
    """
    env = _two_optioned_parcels_past_the_first_window()
    first, second = env["options"]

    run_expiry_sweep(env["program"]["id"])

    lapsed = read_option(first["id"])
    assert_status(lapsed, "LAPSED", "APN-100 option")
    assert_clock_instant(lapsed["lapsed_at"], "2028-01-01T00:00:00Z", "lapsed_at")

    survivor = read_option(second["id"])
    assert_status(survivor, "OPTIONED", "APN-200 option")

    program = read_program(env["program"]["id"])
    assert_premium_ledger(program, 900000.00, 1250000.00, 0, 2150000.00)


def test_lapsed_acreage_degrades_land_control_and_the_program_land_rollup():
    """Losing the 240-acre parcel drops the controlled footprint to the 60 acres of the
    surviving option, so the site's land control falls from 100.00 percent to 20.00 and
    its status from `FULL` to `PARTIAL`, which in turn removes the site from the
    program's full-land-control count. The forfeited premium is sunk money and drops out
    of the site's capital commitment, leaving only the surviving option's 900000.00.

    PRD §3.8: "The second hop, because that option has left the controlled set, recomputes the owning site's `land_control_pct`."
    PRD §3.8: "The `land_control_status` follows directly: `FULL` when the percentage is at or above 100, `NONE` when it is exactly 0, and `PARTIAL` at any value between."
    PRD §3.10: "Premiums on `LAPSED` and `RELEASED` options are sunk money and are deliberately excluded."

    Design: Difficulty/transitive_cascade/option_expiry_sweep_degrades_land_control_rollup
    """
    env = _two_optioned_parcels_past_the_first_window()
    before_site = read_site(env["site"]["id"])
    assert_land_control(before_site, 100.00, "FULL")
    before_program = read_program(env["program"]["id"])
    assert before_program["full_land_control_site_count"] == 1

    run_expiry_sweep(env["program"]["id"])

    after_site = read_site(env["site"]["id"])
    assert_land_control(after_site, 20.00, "PARTIAL")
    assert_money(
        after_site["site_capital_commitment_usd"], 900000.00, "site_capital_commitment_usd"
    )

    after_program = read_program(env["program"]["id"])
    assert after_program["full_land_control_site_count"] == 0


def test_supersession_releases_the_predecessor_within_the_same_create():
    """Creating a replacement option on the same parcel names the option it supersedes,
    and that predecessor is released inside the very same request rather than by a
    separate call — which is also why the predecessor is exempt from the exclusivity
    test its own window would otherwise fail against the replacement.

    PRD §3.8: "Where the create supersedes a predecessor, that predecessor moves `OPTIONED` to `RELEASED` in the same request and its premium shifts out of `option_exposure_usd` into `forfeited_premium_usd`."
    PRD §3.8: "The option named by `replaces_option_id` is exempt from the test, because it is released within the same request."

    Design: Difficulty/compensating_invariant/option_premium_conserved_on_supersede_release
    """
    env = setup_draft_site()
    original = sign_option(env["site"]["id"], **OPTION_APN_100)
    assert_status(original, "OPTIONED", "original option")

    replacement = sign_option(
        env["site"]["id"],
        site_version(env["site"]["id"]),
        parcel_apn="APN-100",
        phase_index=1,
        acres=300,
        option_premium_usd=400000,
        purchase_price_usd=50000000,
        premium_credit_pct=0.5,
        window_start="2027-06-01T00:00:00Z",
        window_end="2028-12-31T00:00:00Z",
        replaces_option_id=original["id"],
    )

    assert_status(replacement, "OPTIONED", "replacement option")
    assert replacement["replaces_option_id"] == original["id"]
    assert_status(read_option(original["id"]), "RELEASED", "superseded option")


def test_superseded_premium_moves_bucket_without_changing_the_conserved_total():
    """The released premium of 1250000.00 leaves exposure and lands in the forfeited
    bucket, while the total only grows by the replacement's own 400000.00 — the money
    is redistributed across three buckets, never created or destroyed, and the three
    still sum to the total. Land control is restated from the replacement's larger
    300-acre footprint, so the campus stays fully controlled, but only the live
    premium counts toward the site's capital commitment.

    PRD §2.8: "A program's `option_exposure_usd` plus its `forfeited_premium_usd` plus its `capitalized_premium_usd` always equals its `premium_committed_total_usd`."
    PRD §2.8: "Releasing a reservation or forfeiting a premium moves value between buckets; it never creates or destroys value, and it never leaves residual drift."
    PRD §3.8: "The acreage of every option of that site whose `status` is `OPTIONED` or `EXERCISED` is summed, multiplied by 100, divided by the site's `gross_acres`, capped at 100.0 and rounded to 2 decimal places to give `land_control_pct` — so a campus that has optioned more acreage than its gross footprint still reports 100.00 rather than more."

    Design: Difficulty/compensating_invariant/option_premium_conserved_on_supersede_release
    """
    env = setup_draft_site()
    original = sign_option(env["site"]["id"], **OPTION_APN_100)
    baseline = read_program(env["program"]["id"])
    assert_premium_ledger(baseline, 1250000.00, 0, 0, 1250000.00)

    sign_option(
        env["site"]["id"],
        site_version(env["site"]["id"]),
        parcel_apn="APN-100",
        phase_index=1,
        acres=300,
        option_premium_usd=400000,
        purchase_price_usd=50000000,
        premium_credit_pct=0.5,
        window_start="2027-06-01T00:00:00Z",
        window_end="2028-12-31T00:00:00Z",
        replaces_option_id=original["id"],
    )

    program = read_program(env["program"]["id"])
    assert_premium_ledger(program, 400000.00, 1250000.00, 0, 1650000.00)
    assert program["full_land_control_site_count"] == 1

    site = read_site(env["site"]["id"])
    assert_land_control(site, 100.00, "FULL")
    assert_money(
        site["site_capital_commitment_usd"], 400000.00, "site_capital_commitment_usd"
    )
