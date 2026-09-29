"""Two interval conventions side by side, and a gate that reads another entity's state."""

from test_helpers import (
    EXPECTED_STUDY_FEE_USD,
    INITIAL_CLOCK_UTC,
    SCREEN_AIR_COOLED,
    TEST_USERS,
    add_site,
    api_client,
    assert_clock_instant,
    assert_land_control,
    assert_money,
    assert_mw,
    assert_premium_ledger,
    assert_status,
    assert_version_unchanged,
    create_parcel_option_payload,
    draft_application,
    file_load_study,
    make_utility_planner_headers,
    open_program,
    read_application,
    read_option,
    read_program,
    read_site,
    read_utility,
    register_utility,
    register_water_source,
    reserve_capacity,
    screen_site,
    setup_draft_site,
    sign_option,
    site_version,
    submit_application,
    validate_error,
)

BIG_STUDY = {
    "it_load_mw": 240,
    "cooling_load_mw": 66,
    "ancillary_load_mw": 12,
    "diversity_factor": 0.92,
}
SMALL_STUDY = {
    "it_load_mw": 79,
    "cooling_load_mw": 20,
    "ancillary_load_mw": 4,
    "diversity_factor": 0.90,
}
FIRST_WINDOW = {
    "window_start": "2029-01-01T00:00:00Z",
    "window_end": "2029-12-31T00:00:00Z",
}
LATER_WINDOW = {
    "window_start": "2030-01-01T00:00:00Z",
    "window_end": "2030-06-30T00:00:00Z",
}
GEORGIA_UTILITY = {
    "state_code": "GA",
    "balancing_authority": "SOCO",
    "total_transmission_capacity_mw": 400,
}
INCUMBENT_OPTION = {
    "parcel_apn": "APN-100",
    "phase_index": 1,
    "acres": 120,
    "option_premium_usd": 500000,
    "purchase_price_usd": 18000000,
    "premium_credit_pct": 0.5,
    "window_start": "2027-01-01T00:00:00Z",
    "window_end": "2027-12-31T00:00:00Z",
}


def _studied_pipeline(env, utility_id, site, headroom, requested_mw, window, study, reserve):
    """A screened air-cooled site with its own studied application on one of the two
    utilities, optionally already holding capacity."""
    row = add_site(env["program"]["id"], utility_id, env["water_source"]["id"], **site)
    screen_site(row["id"], **dict(SCREEN_AIR_COOLED, transmission_headroom_mw=headroom))
    application = draft_application(
        row["id"], utility_id, requested_mw=requested_mw, **window
    )
    submit_application(application["id"])
    file_load_study(application["id"], utility_id, **study)
    if reserve:
        reserve_capacity(application["id"], utility_id)
    return row, read_application(application["id"])


def _two_utilities_differing_only_in_buffer():
    """Two 400 MW utilities differing only in their commissioning buffer, each carrying
    a reserved 300 MW application over 2029 and a studied 101 MW application over the
    disjoint first half of 2030."""
    env = {
        "program": open_program(name="Hyperscale Charlie"),
        "water_source": register_water_source(
            name="Flint River", basin_code="FLT-02", state_code="GA"
        ),
    }
    env["buffered"] = register_utility(
        name="Utility Buffered", commissioning_buffer_days=90, **GEORGIA_UTILITY
    )
    env["sharp"] = register_utility(
        name="Utility Sharp", commissioning_buffer_days=0, **GEORGIA_UTILITY
    )
    for key, utility_key, holder, pending in (
        ("a", "buffered", ("Site A1", "Bibb"), ("Site A2", "Houston")),
        ("b", "sharp", ("Site B1", "Dougherty"), ("Site B2", "Lowndes")),
    ):
        _studied_pipeline(
            env,
            env[utility_key]["id"],
            {"name": holder[0], "state_code": "GA", "county": holder[1]},
            300,
            300,
            FIRST_WINDOW,
            BIG_STUDY,
            True,
        )
        env[f"{key}2_site"], env[f"{key}2_application"] = _studied_pipeline(
            env,
            env[utility_key]["id"],
            {"name": pending[0], "state_code": "GA", "county": pending[1]},
            101,
            101,
            LATER_WINDOW,
            SMALL_STUDY,
            False,
        )
    return env


def _site_with_incumbent_option():
    """A 300-acre campus with one live option over 120 of those acres, and the site
    version the client observed after signing it."""
    env = setup_draft_site()
    env["option"] = sign_option(env["site"]["id"], **INCUMBENT_OPTION)
    env["observed_version"] = site_version(env["site"]["id"])
    return env


def test_buffered_windows_overlap_even_though_the_calendar_windows_do_not():
    """The reserved 2029 window closes on 2029-12-31 and the pending window opens on
    2030-01-01, so on the calendar they share no instant at all. Extending both ends of
    both windows by the utility's 90 commissioning days makes them concurrent, so the
    pending 101 MW is aggregated on top of the reserved 300 MW and refused at 401
    against a 400 MW ceiling.

    PRD §3.5: "Transmission capacity is allocated against overlapping *windows*, not against a single instantaneous total, and the overlap test is buffered."
    PRD §3.5: "Two applications of the same utility are treated as concurrent when each one's `window_start` falls at or before the other's `window_end` extended forward by the utility's `commissioning_buffer_days` — that is, the buffer is applied to **both** ends of **both** windows under test, and the windows themselves are closed intervals."
    PRD §3.5: "Equality is admissible; one megawatt beyond it is rejected with `ERR_TRANSMISSION_CAPACITY_EXCEEDED`, and the comparison is made at 3 decimal places."

    Design: Difficulty/resource_temporal_overlap/transmission_buffered_closed_window_aggregate
    """
    env = _two_utilities_differing_only_in_buffer()

    response = api_client.reserve_capacity(
        env["a2_application"]["id"], make_utility_planner_headers(env["buffered"]["id"])
    )

    validate_error(response, "ERR_TRANSMISSION_CAPACITY_EXCEEDED", 409)

    refreshed = read_application(env["a2_application"]["id"])
    assert_status(refreshed, "STUDY_COMPLETE", "Site A2's application")

    utility = read_utility(env["buffered"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 300.0, "reserved_capacity_mw")
    assert_mw(utility["available_capacity_mw"], 100.0, "available_capacity_mw")


def test_zero_buffer_utility_admits_the_identical_windows_and_megawatts():
    """The second utility carries byte-identical windows and megawatts but declares no
    commissioning buffer, so the same two windows never share an instant and the 101 MW
    reservation is admitted. The utility's reserved figure is the largest group demand
    across its live set rather than a sum, so it stays at the 300 MW application alone
    instead of climbing to 401.

    PRD §3.5: "The utility's ledger is a peak-group figure rather than a naive sum."
    PRD §3.5: "Taking the set of that utility's applications in `CAPACITY_RESERVED` or `ENERGIZATION_COMMITTED`, each member's group demand is its own requested megawatts plus the requested megawatts of every other member whose buffered window overlaps it."
    PRD §3.5: "Because the admission test above bounds the same group demand by the same total, the available figure can never go negative, and two live applications whose buffered windows do not overlap never inflate each other's group demand."

    Design: Difficulty/resource_temporal_overlap/transmission_buffered_closed_window_aggregate
    """
    env = _two_utilities_differing_only_in_buffer()

    reserved = reserve_capacity(env["b2_application"]["id"], env["sharp"]["id"])

    assert_status(reserved, "CAPACITY_RESERVED", "Site B2's application")
    assert_mw(reserved["reserved_mw"], 101, "reserved_mw")

    utility = read_utility(env["sharp"]["id"])
    assert_mw(utility["reserved_capacity_mw"], 300.0, "reserved_capacity_mw")
    assert_mw(utility["available_capacity_mw"], 100.0, "available_capacity_mw")


def test_a_second_option_opening_inside_the_live_window_collides_on_that_parcel():
    """Exclusivity on a parcel is pairwise and carries no buffer of any kind: a window
    opening on 2027-06-01, halfway through the incumbent's, genuinely overlaps and is
    refused. The refusal writes nothing — land control still reflects only the
    incumbent's 120 of 300 acres, and the site's version is untouched, which is exactly
    why the next writer can reuse the version it already observed.

    PRD §3.8: "No other option sharing the same `site_id` and the same `parcel_apn`, and whose `status` is `OPTIONED` or `EXERCISED`, may have a half-open exclusivity window overlapping the new one; a collision is refused with `ERR_OPTION_WINDOW_CONFLICT`."
    PRD §3.8: "Signing also increments the addressed site's `version` by one — which is precisely why the next writer needs a fresh `expected_site_version` — moves the program's `option_exposure_usd` and `premium_committed_total_usd`, re-derives `program_status`, and recomputes the site's `site_capital_commitment_usd`."

    Design: Difficulty/resource_temporal_overlap/parcel_apn_half_open_window_adjacency
    """
    env = _site_with_incumbent_option()
    before = read_site(env["site"]["id"])
    assert_land_control(before, 40.00, "PARTIAL")

    response = api_client.create_parcel_option(
        create_parcel_option_payload(
            env["site"]["id"],
            env["observed_version"],
            parcel_apn="APN-100",
            phase_index=2,
            acres=30,
            option_premium_usd=200000,
            purchase_price_usd=5000000,
            window_start="2027-06-01T00:00:00Z",
            window_end="2028-06-01T00:00:00Z",
        ),
        TEST_USERS["analyst_headers"],
    )

    validate_error(response, "ERR_OPTION_WINDOW_CONFLICT", 409)

    after = read_site(env["site"]["id"])
    assert_land_control(after, 40.00, "PARTIAL")
    assert_version_unchanged(before, after, "Site Alpha")


def test_an_option_opening_exactly_at_the_incumbents_window_end_is_admitted():
    """Because option windows are half-open, the incumbent's exclusivity stops at the
    instant 2027-12-31 rather than including it, so a phase opening on precisely that
    instant abuts without overlapping and is accepted. The controlled footprint grows to
    150 of 300 acres and both live premiums stand in the exposure bucket.

    PRD §2.6: "A land parcel option's exclusivity window, also delimited by `window_start` and `window_end`, is **half-open**: `window_start` is inclusive and `window_end` is an exclusive upper bound, so two options that abut — one ending exactly where the next begins — do not overlap."
    PRD §3.8: "Because the windows are half-open, two options that abut exactly — the first ending on the instant the second begins — are admissible, and no commissioning-style buffer is applied here at all."
    PRD §3.8: "`option_exposure_usd` totals the premiums of options still `OPTIONED`."

    Design: Difficulty/resource_temporal_overlap/parcel_apn_half_open_window_adjacency
    """
    env = _site_with_incumbent_option()

    abutting = sign_option(
        env["site"]["id"],
        env["observed_version"],
        parcel_apn="APN-100",
        phase_index=3,
        acres=30,
        option_premium_usd=200000,
        purchase_price_usd=5000000,
        window_start="2027-12-31T00:00:00Z",
        window_end="2028-12-31T00:00:00Z",
    )

    assert_status(abutting, "OPTIONED", "abutting option")
    assert abutting["window_start"] == read_option(env["option"]["id"])["window_end"]

    site = read_site(env["site"]["id"])
    assert_land_control(site, 50.00, "PARTIAL")

    program = read_program(env["program"]["id"])
    assert_premium_ledger(program, 700000.00, 0, 0, 700000.00)


def test_submission_is_blocked_by_the_sites_state_not_the_applications_own():
    """The application is in a perfectly legal `DRAFT` — the only status from which
    submission is permitted — and is refused anyway, because submission reads a
    different entity: the site it serves has never been screened. Nothing is charged for
    the refusal, so the study fee remains 0 as it was at drafting.

    PRD §3.4: "Submission advances the application from `DRAFT` to `SUBMITTED`, and it is the point at which the site's screening becomes load-bearing: the referenced site must be in `SCREENED` status, and submitting on behalf of an unscreened site is rejected with `ERR_SITE_NOT_SCREENED`, while submitting an application that is not itself in `DRAFT` is rejected with `ERR_APPLICATION_INVALID_STATE`."
    PRD §3.4: "A drafted application sits at `status` `DRAFT` with `queue_position` of 0, `reserved_mw` of 0, `study_round` of 0, `study_fee_usd` of 0, `network_upgrade_cost_usd` of 0 and `delay_exposure_usd` of 0: nothing is reserved and no fee is charged until it is submitted."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_site_screened
    """
    env = setup_draft_site()
    application = draft_application(env["site"]["id"], env["utility"]["id"])
    assert_status(application, "DRAFT", "drafted application")

    response = api_client.submit_interconnection_application(
        application["id"], TEST_USERS["analyst_headers"]
    )

    validate_error(response, "ERR_SITE_NOT_SCREENED", 409)

    refreshed = read_application(application["id"])
    assert_status(refreshed, "DRAFT", "application")
    assert_money(refreshed["study_fee_usd"], 0, "study_fee_usd")


def test_the_same_submission_succeeds_once_only_the_site_has_been_screened():
    """Screening the site changes nothing about the application, yet the byte-identical
    submit call now succeeds: the logical clock is stamped as `submitted_at`, still
    reading its startup instant because nothing has moved it, the fee is struck at
    1200 dollars per megawatt of the 300 MW request, and the application takes the only
    place in its utility's queue.

    PRD §3.4: "On submission the current logical clock is stamped as `submitted_at`, which becomes the primary queue sort key, and the study fee is struck: `study_fee_usd` is the requested megawatts multiplied by the utility's study fee rate per megawatt, rounded to 2 decimal places."
    PRD §2.6: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must continue to read that instant until it is explicitly moved; it must never fall back to the host's wall clock."
    PRD §3.4: "The `queue_position` written back is the 1-based index in that ordering, and positions are dense and contiguous, so a withdrawal closes the gap behind it rather than leaving a hole."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_site_screened
    """
    env = setup_draft_site()
    application = draft_application(env["site"]["id"], env["utility"]["id"])
    api_client.submit_interconnection_application(
        application["id"], TEST_USERS["analyst_headers"]
    )

    screen_site(env["site"]["id"])
    submitted = submit_application(application["id"])

    assert_status(submitted, "SUBMITTED", "application")
    assert_money(submitted["study_fee_usd"], EXPECTED_STUDY_FEE_USD, "study_fee_usd")
    assert submitted["queue_position"] == 1
    assert_clock_instant(submitted["submitted_at"], INITIAL_CLOCK_UTC, "submitted_at")
