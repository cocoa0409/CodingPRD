"""Typed refusals, the one shared error envelope, and who may act on what."""

from test_helpers import (
    ANALYST_USER_ID,
    CHAIR_USER_ID,
    EXPECTED_DIVERSIFIED_PEAK_MW,
    INITIAL_CLOCK_UTC,
    NEGOTIATOR_USER_ID,
    TEST_USERS,
    UNKNOWN_UUID,
    UTILITY_TOTAL_CAPACITY_MW,
    WATER_SOURCE_ANNUAL_PERMITTED_MGAL,
    api_client,
    assert_error_envelope,
    assert_money,
    assert_mw,
    assert_pct,
    assert_status,
    assert_version_unchanged,
    create_candidate_site_payload,
    create_capacity_revision_payload,
    create_clock_payload,
    create_drought_declaration_payload,
    create_load_study_payload,
    create_parcel_option_payload,
    create_screening_payload,
    create_zoning_decision_payload,
    decide_zoning,
    file_authority_round,
    file_company_round,
    file_load_study,
    file_zoning,
    is_iso8601_timestamp,
    list_load_studies,
    list_options,
    list_site_negotiations,
    list_site_zoning,
    list_sites,
    make_chair_headers,
    make_utility_planner_headers,
    open_negotiation,
    ratify_negotiation,
    read_application,
    read_site,
    read_utility,
    read_water_source,
    register_utility,
    setup_draft_site,
    setup_screened_site,
    setup_submitted_application,
    sign_negotiation,
    sign_option,
    validate_error,
    validate_success,
)

# A caller that presents an operator identifier but no role at all.
NO_ROLE_HEADERS = {"X-User-ID": ANALYST_USER_ID, "Content-Type": "application/json"}

CATAWBA = {
    "name": "Catawba Electric",
    "total_transmission_capacity_mw": 400,
    "interconnect_study_fee_per_mw_usd": 1000,
    "network_upgrade_rate_usd_per_mw": 70000,
}
QUIET_DOCKET = {
    "projected_noise_dba": 57,
    "visual_mitigation_tier": "BERM_AND_SCREENING",
}


def _read_negotiation(site_id: str, negotiation_id: str) -> dict:
    """Re-read a negotiation through the site's listing, the only read path the
    contract exposes for one."""
    rows = list_site_negotiations(site_id)["data"]
    return next(row for row in rows if row["id"] == negotiation_id)


def _read_docket(site_id: str, zoning_application_id: str) -> dict:
    """Re-read a zoning docket through the site's listing."""
    rows = list_site_zoning(site_id)["data"]
    return next(row for row in rows if row["id"] == zoning_application_id)


def _screened_site_with_approved_docket_and_signed_term_sheet() -> dict:
    """Site Alpha screened by the analyst operator, a docket modelled 2 dBA over the
    ordinance limit and approved with conditions, and a STATE term sheet signed by the
    negotiator operator after one company offer and one authority counter."""
    env = setup_screened_site()
    docket = file_zoning(env["site"]["id"], **QUIET_DOCKET)
    env["zoning"] = decide_zoning(
        docket["id"], "APPROVED_WITH_CONDITIONS", "Approved with berm and screening."
    )
    negotiation = open_negotiation(env["site"]["id"], "STATE")
    file_company_round(negotiation["id"])
    file_authority_round(negotiation["id"])
    env["negotiation"] = sign_negotiation(negotiation["id"])
    return env


def test_each_collection_answers_an_unknown_identifier_with_its_own_not_found():
    """Ten refusals, one per addressable collection, and none of them shares an error
    identifier with another: the id decides nothing, the collection the unresolved
    reference points at decides everything. The last two cases prove the rule reaches
    body foreign keys too — an unknown `water_source_id` on a site create and an unknown
    `replaces_option_id` on an option create whose concurrency token is perfectly
    current, which is why the option create is refused for the dangling reference rather
    than for its version.

    PRD §2.5: "Each collection has its own not-found error: a `siting-programs` segment that does not resolve yields `ERR_PROGRAM_NOT_FOUND`, a `utilities` segment yields `ERR_UTILITY_NOT_FOUND`, a `water-sources` segment yields `ERR_WATER_SOURCE_NOT_FOUND`, a `candidate-sites` segment yields `ERR_SITE_NOT_FOUND`, an `interconnection-applications` segment yields `ERR_APPLICATION_NOT_FOUND`, an `incentive-negotiations` segment yields `ERR_NEGOTIATION_NOT_FOUND`, a `zoning-applications` segment yields `ERR_ZONING_APPLICATION_NOT_FOUND`, a `power-purchase-agreements` segment yields `ERR_PPA_NOT_FOUND`, and a `parcel-options` segment yields `ERR_PARCEL_OPTION_NOT_FOUND`."
    PRD §2.5: "Foreign keys supplied in a request body are resolved after all path parameters, in a fixed declaration order: `program_id` first, then `utility_id`, then `water_source_id`, then `site_id`, then `application_id`, then `replaces_option_id`. Each unresolved reference raises the not-found error belonging to the collection it points at, so a create carrying both an unknown `program_id` and an unknown `utility_id` reports `ERR_PROGRAM_NOT_FOUND`."
    PRD §2.11: "**Body reference existence** — every foreign key in the body resolves, in declaration order, on `POST /candidate-sites`, `POST /interconnection-applications`, `POST /incentive-negotiations`, `POST /zoning-applications`, `POST /power-purchase-agreements` and `POST /parcel-options`."
    PRD §2.11: "**Site version match** — `expected_site_version` equals the addressed site's current `version`, on `POST /parcel-options`; otherwise `ERR_STALE_SITE_VERSION`."

    Design: Corner/errors/typed_not_found_for_every_addressable_entity
    """
    env = setup_draft_site()
    before = read_site(env["site"]["id"])

    validate_error(
        api_client.get_siting_program(UNKNOWN_UUID, TEST_USERS["director_headers"]),
        "ERR_PROGRAM_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_utility(UNKNOWN_UUID, TEST_USERS["director_headers"]),
        "ERR_UTILITY_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_water_source(UNKNOWN_UUID, TEST_USERS["authority_headers"]),
        "ERR_WATER_SOURCE_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_interconnection_application(
            UNKNOWN_UUID, TEST_USERS["analyst_headers"]
        ),
        "ERR_APPLICATION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_parcel_option(UNKNOWN_UUID, TEST_USERS["analyst_headers"]),
        "ERR_PARCEL_OPTION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.sign_incentive_negotiation(
            UNKNOWN_UUID, TEST_USERS["negotiator_headers"]
        ),
        "ERR_NEGOTIATION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.decide_zoning_application(
            UNKNOWN_UUID,
            create_zoning_decision_payload("CONTINUED", "Continued."),
            TEST_USERS["authority_headers"],
        ),
        "ERR_ZONING_APPLICATION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.execute_power_purchase_agreement(
            UNKNOWN_UUID, TEST_USERS["director_headers"]
        ),
        "ERR_PPA_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_candidate_site(
            create_candidate_site_payload(
                env["program"]["id"],
                env["utility"]["id"],
                UNKNOWN_UUID,
                name="Site Ghost",
            ),
            TEST_USERS["analyst_headers"],
        ),
        "ERR_WATER_SOURCE_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_parcel_option(
            create_parcel_option_payload(
                env["site"]["id"],
                before["version"],
                acres=120,
                option_premium_usd=500000,
                purchase_price_usd=18000000,
                replaces_option_id=UNKNOWN_UUID,
            ),
            TEST_USERS["analyst_headers"],
        ),
        "ERR_PARCEL_OPTION_NOT_FOUND",
        404,
    )

    assert list_sites({"program_id": env["program"]["id"]})["meta"]["total_count"] == 1
    assert list_options({"site_id": env["site"]["id"]})["meta"]["total_count"] == 0
    assert_version_unchanged(before, read_site(env["site"]["id"]), "Site Alpha")


def test_one_envelope_shape_carries_three_different_status_families():
    """A pagination bound, a negative acreage, an unknown id and a re-screen fail for
    four unrelated reasons and answer with three different statuses — 422, 404 and 409 —
    yet every one of them comes back in the identical envelope: `response_type` of
    `error`, a `data` object holding nothing but `error_id` and `message`, and a `meta`
    holding nothing but the request id and its timestamp. Nothing is written along the
    way: the negative-acreage create leaves the program with its one site and the
    rejected re-screen leaves the site's version alone.

    PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.2: "A `SiteScreeningAnalyst` adds a **candidate site** to a program by naming the program as `program_id`, the serving utility whose transmission capacity the campus will draw on as `utility_id`, the basin supplying cooling water as `water_source_id`, a site label as `name`, its two-letter `state_code`, its `county` or local jurisdiction, and the `gross_acres` the campus needs, which must be strictly positive and which later serves as the denominator of land control."
    PRD §3.2: "Screening a site that is not in `DRAFT` is rejected with `ERR_SITE_INVALID_STATE`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

    Design: Corner/errors/error_envelope_shape_and_status_families
    """
    env = setup_screened_site()
    before = read_site(env["site"]["id"])

    over_limit = api_client.list_candidate_sites(
        TEST_USERS["analyst_headers"],
        params={"program_id": env["program"]["id"], "limit": 101},
    )
    negative_acres = api_client.create_candidate_site(
        create_candidate_site_payload(
            env["program"]["id"],
            env["utility"]["id"],
            env["water_source"]["id"],
            name="Site Negative",
            gross_acres=-5,
        ),
        TEST_USERS["analyst_headers"],
    )
    unknown_site = api_client.get_candidate_site(
        UNKNOWN_UUID, TEST_USERS["analyst_headers"]
    )
    second_screening = api_client.screen_candidate_site(
        env["site"]["id"], create_screening_payload(), TEST_USERS["analyst_headers"]
    )

    validate_error(over_limit, "ERR_INVALID_REQUEST", 422)
    validate_error(negative_acres, "ERR_INVALID_REQUEST", 422)
    validate_error(unknown_site, "ERR_SITE_NOT_FOUND", 404)
    validate_error(second_screening, "ERR_SITE_INVALID_STATE", 409)

    for response in (over_limit, negative_acres, unknown_site, second_screening):
        error = assert_error_envelope(response)
        assert isinstance(error["error_id"], str) and error["error_id"] != ""
        assert is_iso8601_timestamp(response.json()["meta"]["api_request_timestamp"])

    assert list_sites({"program_id": env["program"]["id"]})["meta"]["total_count"] == 1
    assert_version_unchanged(before, read_site(env["site"]["id"]), "Site Alpha")


def test_the_role_check_answers_before_any_business_state_is_consulted():
    """Four operations are each addressed by a role that is not on their authorized list,
    and all four are refused for the role alone: the analyst's commit reports the role
    failure rather than the `DRAFT` site's state, because role authorization is the
    second rung of the ladder and the site's own state is the tenth. None of the four
    writes anything — no second site, a basin still at `NORMAL`, and a logical clock that
    never moved, which is why an option opening at the startup instant is still not
    backdated. Dropping the role header entirely moves the answer up one rung further,
    from the role failure to the authentication failure.

    PRD §2.1: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` before any other consideration."
    PRD §2.1: "If `X-User-Role` is not one of the six role names below, or is a valid role name that the addressed endpoint does not list as authorized, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.11: "**Role authorization** — `X-User-Role` is one of the six declared roles and is listed on the addressed endpoint, on every endpoint; otherwise `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.1: "At registration the basin sits at `drought_stage` `NORMAL` with a `stage_curtailment_pct` of 0.00, so its `effective_supply_mgal` equals its permitted withdrawal exactly, its `committed_annual_demand_mgal` is 0, and its `last_declaration_effective_date` is null because no declaration has yet been issued."
    PRD §2.6: "A new land option additionally may not be backdated: its `window_start` may not fall earlier than the current logical clock, and an attempt to do so is rejected with `ERR_OPTION_WINDOW_BACKDATED`."

    Design: Corner/rbac/exclusive_operations_denied_to_other_roles_and_to_anonymous
    """
    env = setup_draft_site()
    before = read_site(env["site"]["id"])

    validate_error(
        api_client.commit_candidate_site(
            env["site"]["id"], TEST_USERS["analyst_headers"]
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_candidate_site(
            create_candidate_site_payload(
                env["program"]["id"],
                env["utility"]["id"],
                env["water_source"]["id"],
                name="Site Bravo",
                county="Davie",
            ),
            TEST_USERS["director_headers"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.set_clock(
            create_clock_payload("2027-01-01T00:00:00Z"),
            make_utility_planner_headers(env["utility"]["id"]),
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_drought_declaration(
            env["water_source"]["id"],
            create_drought_declaration_payload("STAGE_1", "2027-03-01T00:00:00Z"),
            TEST_USERS["director_headers"],
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.commit_candidate_site(env["site"]["id"], NO_ROLE_HEADERS),
        "ERR_UNAUTHENTICATED",
        401,
    )

    assert list_sites({"program_id": env["program"]["id"]})["meta"]["total_count"] == 1

    basin = read_water_source(env["water_source"]["id"])
    assert basin["drought_stage"] == "NORMAL"
    assert_pct(basin["stage_curtailment_pct"], 0.00, "stage_curtailment_pct")
    assert_mw(
        basin["effective_supply_mgal"],
        WATER_SOURCE_ANNUAL_PERMITTED_MGAL,
        "effective_supply_mgal",
    )

    after = read_site(env["site"]["id"])
    assert_status(after, "DRAFT", "Site Alpha")
    assert_version_unchanged(before, after, "Site Alpha")

    at_the_clock = sign_option(
        env["site"]["id"],
        window_start=INITIAL_CLOCK_UTC,
        window_end="2027-12-31T00:00:00Z",
    )
    assert_status(at_the_clock, "OPTIONED", "the option opening at the startup instant")


def test_a_planner_wearing_the_wrong_utility_is_refused_before_its_payload_is_read():
    """`UtilityPlanner` is the one role whose identifier is an entity id, so the study
    filed by Catawba against a Piedmont application is turned away on identity — and it
    carries a `diversity_factor` of 2.0, far outside the permitted range, which would
    have been a shape failure if the shape were reached at all. The same identity rule
    guards the path form on a capacity revision, leaving Piedmont's declared capacity at
    500 MW. Filed by Piedmont itself the byte-identical operation succeeds, stamping the
    utility's own id on round 1 and diversifying 318 MW of nameplate down to 293.52 MW.

    PRD §2.1: "When `X-User-Role` is `UtilityPlanner`, `X-User-ID` is the `id` of the acting `Utility`; ownership checks on any resource that references a `Utility` compare the resource's foreign-key field to `X-User-ID`. Concretely, for a capacity revision the utility named in the path must be the caller's own utility, and for a load study, a capacity reservation or an energization commitment the addressed application's `utility_id` must equal `X-User-ID`. A mismatch is rejected with `ERR_UTILITY_IDENTITY_MISMATCH`. When a `UtilityPlanner` files a load study, that same identifier is stamped onto the study row as `filed_by_user_id`."
    PRD §2.11: "**Utility identity binding** — for the entity-backed `UtilityPlanner` role, `X-User-ID` equals the `Utility` `id` that owns the addressed resource. This applies to exactly four operations: `POST /utilities/{id}/capacity-revisions`, `POST /interconnection-applications/{id}/load-studies`, `POST /interconnection-applications/{id}/reserve-capacity` and `POST /interconnection-applications/{id}/commit-energization`. Otherwise `ERR_UTILITY_IDENTITY_MISMATCH`."
    PRD §3.4: "The study is appended to its application, recording the `application_id` it belongs to and a 1-based `study_round` equal to the owning application's round count after the append, and the operator's identifier is stamped as `filed_by_user_id`. Filing a study advances the application from `SUBMITTED` to `STUDY_COMPLETE`; filing another study against an application already in `STUDY_COMPLETE` is a legitimate restudy that leaves the application in `STUDY_COMPLETE` and simply appends the next round."
    PRD §3.4: "The `diversified_peak_mw` figure is the utility's coincident view: the IT component is multiplied by the diversity factor, the cooling component is multiplied by whichever is larger of the diversity factor and a cooling floor of 0.85 so that cooling load never diversifies below that floor, the ancillary component is taken undiversified at full value, the three products are added, and the total is rounded to 3 decimal places."

    Design: Corner/rbac/utility_planner_bound_to_its_own_utility
    """
    env = setup_submitted_application()
    catawba = register_utility(**CATAWBA)

    validate_error(
        api_client.create_load_study(
            env["application"]["id"],
            create_load_study_payload(diversity_factor=2.0),
            make_utility_planner_headers(catawba["id"]),
        ),
        "ERR_UTILITY_IDENTITY_MISMATCH",
        403,
    )
    validate_error(
        api_client.create_capacity_revision(
            env["utility"]["id"],
            create_capacity_revision_payload(900, reason="Rebuild completed."),
            make_utility_planner_headers(catawba["id"]),
        ),
        "ERR_UTILITY_IDENTITY_MISMATCH",
        403,
    )

    piedmont = read_utility(env["utility"]["id"])
    assert_mw(
        piedmont["total_transmission_capacity_mw"],
        UTILITY_TOTAL_CAPACITY_MW,
        "total_transmission_capacity_mw",
    )

    study = file_load_study(env["application"]["id"], env["utility"]["id"])

    assert study["study_round"] == 1
    assert study["filed_by_user_id"] == env["utility"]["id"]
    assert_mw(
        study["diversified_peak_mw"],
        EXPECTED_DIVERSIFIED_PEAK_MW,
        "diversified_peak_mw",
    )
    assert_status(
        read_application(env["application"]["id"]), "STUDY_COMPLETE", "the application"
    )
    assert (
        list_load_studies(env["application"]["id"])["meta"]["total_count"] == 1
    )


def test_the_screener_cannot_commit_and_the_signer_cannot_ratify():
    """Both two-person decisions are enforced on the operator identifier rather than on
    the role, so wearing the chair's role buys neither operator anything: the analyst who
    screened the site is refused the commit, and the negotiator who signed the term sheet
    is refused the ratification, each with the same identifier at HTTP 403. The refused
    ratification leaves the term sheet exactly where it stood, and a third operator —
    neither the screener nor the signer — ratifies it and is stamped as the ratifier.

    PRD §2.9: "Two decisions in this system are structurally two-person decisions, and the system enforces that separation on the acting operator identifier rather than on the role, because an opaque operator may hold more than one role."
    PRD §2.9: "First, the operator committing a candidate site must not be the operator who screened it: at commit time, `X-User-ID` is compared against the site's `screened_by_user_id`, and an equal comparison is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.9: "Second, the operator ratifying an incentive term sheet must not be the operator who signed it: at ratify time, `X-User-ID` is compared against the negotiation's `signed_by_user_id`, and an equal comparison is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`. Both rejections carry HTTP 403."
    PRD §3.7: "Ratification belongs to the `CapitalCommitteeChair` and moves the negotiation `SIGNED` to `RATIFIED`, stamping `ratified_by_user_id`."

    Design: Corner/rbac/segregation_of_duties_on_screen_commit_and_sign_ratify
    """
    env = _screened_site_with_approved_docket_and_signed_term_sheet()
    assert env["site"]["screened_by_user_id"] == ANALYST_USER_ID
    assert env["negotiation"]["signed_by_user_id"] == NEGOTIATOR_USER_ID

    validate_error(
        api_client.commit_candidate_site(
            env["site"]["id"], make_chair_headers(ANALYST_USER_ID)
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    validate_error(
        api_client.ratify_incentive_negotiation(
            env["negotiation"]["id"], make_chair_headers(NEGOTIATOR_USER_ID)
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    still_signed = _read_negotiation(env["site"]["id"], env["negotiation"]["id"])
    assert_status(still_signed, "SIGNED", "the term sheet")

    ratified = ratify_negotiation(env["negotiation"]["id"], make_chair_headers())

    assert_status(ratified, "RATIFIED", "the term sheet")
    assert ratified["ratified_by_user_id"] == CHAIR_USER_ID
    assert_status(read_site(env["site"]["id"]), "SCREENED", "Site Alpha")


def test_clearing_the_duty_conflict_only_moves_the_commit_to_the_next_unmet_gate():
    """The chair who ratified the term sheet is not the screener, so the duty gate lets
    the commit through — and the ladder immediately stops it at land control, the next
    condition this site does not meet, which is the whole point of the fixed order. The
    docket meanwhile stands priced on the tier the analysis demanded rather than the
    richer one offered: 2 dBA of excess demands a berm, which costs 750,000 dollars plus
    two decibels at 125,000 each, and a cost of exactly 1,000,000.00 falls in the 0.15
    escrow band because the lowest band stops strictly below it.

    PRD §2.11: "On a site commitment, the ten domain gates fire in the order segregation of duties, hazard prohibition, zoning approval, single-committed-site, land control, ratified state incentives, water sufficiency, renewable coverage, capital ceiling — after the site's own state has been checked — so a caller who is both the screener and short of land control learns about the duty conflict first."
    PRD §3.10: "The site's `land_control_pct` must be at least 100, because a partially optioned campus cannot be committed, else `ERR_LAND_CONTROL_INCOMPLETE`."
    PRD §3.6: "Step three selects the `required_mitigation_tier` on a first-match-wins ladder in which either driver can escalate the tier on its own: the tier is `FULL_ENCLOSURE` when the noise excess is at least 10 dBA **or** the weighted opposition score is at least 12; failing that it is `BERM_AND_SCREENING` when the noise excess is at least 5 dBA **or** the score is at least 6; failing that it is `BERM` when the noise excess is strictly greater than 0 **or** the score is at least 3; and otherwise it is `NONE`."
    PRD §3.6: "Step four prices that tier as `mitigation_cost_usd`: a tier base of 0 for `NONE`, 750,000 dollars for `BERM`, 2,100,000 dollars for `BERM_AND_SCREENING` and 5,400,000 dollars for `FULL_ENCLOSURE`, plus a per-decibel adder of 125,000 dollars applied to the **acoustic excess only** and never to the raw noise figures, with the total rounded to 2 decimal places."
    PRD §3.6: "Step five sets the escrow the board will hold, and the crucial subtlety is that the escrow percentage is tiered on the **cost computed in step four**, not on the tier chosen in step three: the percentage is 0.00 when the cost is exactly zero, one tenth at 0.10 when the cost is strictly below 1,000,000 dollars, fifteen hundredths at 0.15 when the cost is strictly below 4,000,000 dollars, and one fifth at 0.20 otherwise. A cost of exactly 1,000,000.00 dollars therefore lands in the 0.15 band because the lowest band is a strict "below". The `conditions_escrow_usd` is the mitigation cost multiplied by that percentage, rounded to 2 decimal places."

    Design: Corner/rbac/segregation_of_duties_on_screen_commit_and_sign_ratify
    """
    env = _screened_site_with_approved_docket_and_signed_term_sheet()
    ratify_negotiation(env["negotiation"]["id"], make_chair_headers())

    response = api_client.commit_candidate_site(env["site"]["id"], make_chair_headers())

    validate_error(response, "ERR_LAND_CONTROL_INCOMPLETE", 409)
    assert_status(read_site(env["site"]["id"]), "SCREENED", "Site Alpha")

    docket = _read_docket(env["site"]["id"], env["zoning"]["id"])
    assert_status(docket, "APPROVED_WITH_CONDITIONS", "the docket")
    assert docket["required_mitigation_tier"] == "BERM"
    assert_money(docket["mitigation_cost_usd"], 1000000.00, "mitigation_cost_usd")
    assert_money(docket["conditions_escrow_usd"], 150000.00, "conditions_escrow_usd")


def test_the_shared_site_read_and_the_shared_application_read_invert_their_audiences():
    """The site projection is authorized for three roles and returns the same body to
    each of them, byte for byte — the analyst, the director and the chair see one truth,
    including the `MODERATE` tier the 0.45 flood index earns. The permitting authority is
    not on that list and is refused, while the transmission-facing application read
    inverts the pairing: it admits the serving utility's planner, who sees the only place
    in the queue, and refuses the chair. Six reads later the site's version is exactly
    where it started, because a read is not a mutation.

    PRD §2.1: "If `X-User-Role` is not one of the six role names below, or is a valid role name that the addressed endpoint does not list as authorized, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."
    PRD §4: "An operation that brings a new resource into existence answers 201 Created; every other successful operation — reads, state transitions, sweeps, decisions and the clock control — answers 200 OK."
    PRD §3.2: "First, `hazard_tier` is set from the largest of the three hazard indices: `SEVERE` when that largest value is at least 0.70, `MODERATE` when it is at least 0.40 but below 0.70, and `LOW` otherwise."
    PRD §3.4: "The `queue_position` written back is the 1-based index in that ordering, and positions are dense and contiguous, so a withdrawal closes the gap behind it rather than leaving a hole."
    PRD §2.4: "Mutable resources also carry a `version` integer. It is 1 when the resource is created and increases by exactly 1 on each request that mutates the resource, including mutations that a cascade performs rather than the caller addressing the resource directly."

    Design: Corner/rbac/peer_roles_share_reads_but_not_each_others_resources
    """
    env = setup_submitted_application()

    by_analyst = validate_success(
        api_client.get_candidate_site(env["site"]["id"], TEST_USERS["analyst_headers"])
    )
    by_director = validate_success(
        api_client.get_candidate_site(env["site"]["id"], TEST_USERS["director_headers"])
    )
    by_chair = validate_success(
        api_client.get_candidate_site(env["site"]["id"], TEST_USERS["chair_headers"])
    )

    assert by_analyst == by_director == by_chair
    assert by_analyst["hazard_tier"] == "MODERATE"

    validate_error(
        api_client.get_candidate_site(
            env["site"]["id"], TEST_USERS["authority_headers"]
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    by_planner = validate_success(
        api_client.get_interconnection_application(
            env["application"]["id"], make_utility_planner_headers(env["utility"]["id"])
        )
    )

    assert_status(by_planner, "SUBMITTED", "the application")
    assert by_planner["queue_position"] == 1

    validate_error(
        api_client.get_interconnection_application(
            env["application"]["id"], TEST_USERS["chair_headers"]
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    assert_version_unchanged(by_analyst, read_site(env["site"]["id"]), "Site Alpha")
