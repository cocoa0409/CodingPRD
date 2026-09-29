"""Resource shapes on creation and retrieval: declared inputs, defaults and rejections."""

from test_helpers import (
    ANALYST_USER_ID,
    EXPECTED_DIVERSIFIED_PEAK_MW,
    EXPECTED_SCREENING_SCORE_ALPHA,
    PROGRAM_ANNUAL_LOAD_MWH,
    TEST_USERS,
    UNKNOWN_UUID,
    add_site,
    api_client,
    assert_capacity_ledger,
    assert_error_envelope,
    assert_has_common_fields,
    assert_ids_in_order,
    assert_load_study_shape,
    assert_money,
    assert_mw,
    assert_pagination_meta,
    assert_premium_ledger,
    assert_program_rollup,
    assert_site_screening_outputs,
    assert_status,
    assert_version,
    create_candidate_site_payload,
    create_interconnection_application_payload,
    create_minimal_utility_payload,
    create_parcel_option_payload,
    create_screening_payload,
    create_siting_program_payload,
    create_utility_payload,
    file_load_study,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_applications,
    list_load_studies,
    list_sites,
    omit,
    open_program,
    read_site,
    register_utility,
    register_water_source,
    screen_site,
    setup_draft_site,
    setup_environment,
    setup_studied_application,
    site_version,
    validate_error,
    validate_success,
)

SECOND_UTILITY = {
    "name": "Catawba Electric",
    "state_code": "SC",
    "balancing_authority": "SOCO",
    "total_transmission_capacity_mw": 400,
}


def _three_sites_on_one_program_and_one_elsewhere():
    """Three sites on Hyperscale Alpha and a fourth on a second program, all sharing
    one utility and one basin so only the program filter separates them."""
    env = setup_environment()
    env["other_program"] = open_program(
        name="Hyperscale Delta",
        target_load_mw=150,
        required_energization_date="2030-06-30T00:00:00Z",
        capital_budget_usd=20000000,
    )
    env["sites"] = [
        add_site(
            env["program"]["id"],
            env["utility"]["id"],
            env["water_source"]["id"],
            name=name,
            county=county,
        )
        for name, county in (
            ("Site Alpha", "Rowan"),
            ("Site Bravo", "Davie"),
            ("Site Charlie", "Iredell"),
        )
    ]
    env["other_site"] = add_site(
        env["other_program"]["id"],
        env["utility"]["id"],
        env["water_source"]["id"],
        name="Site Delta",
        county="Wake",
    )
    return env


def test_opening_a_program_derives_its_annual_load_and_zeroes_every_rollup():
    """The create answers 201 in the standard envelope, and the one figure the server
    computes from the request is the annual load: 300 MW across 8,760 hours at a 0.90
    load factor is 2365200.0 MWh. Nothing else is derived yet, so the compound status
    reads `SCREENING`, all seven rollups stand at zero and the row is at version 1.

    PRD §3.1: "From the load target the system immediately derives `program_annual_load_mwh`, the denominator against which all renewable procurement is later measured: the target load is multiplied by the 8,760 hours in a year and then by a program load factor of 0.90, and the result is rounded to 3 decimal places."
    PRD §3.1: "A fresh program reports `program_status` of `SCREENING`, and every rollup starts at zero — `committed_load_mw`, `renewable_coverage_pct`, `option_exposure_usd`, `forfeited_premium_usd`, `capitalized_premium_usd`, `premium_committed_total_usd` and `full_land_control_site_count` alike."
    PRD §4: "An operation that brings a new resource into existence answers 201 Created; every other successful operation — reads, state transitions, sweeps, decisions and the clock control — answers 200 OK."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.4: "It is 1 when the resource is created and increases by exactly 1 on each request that mutates the resource, including mutations that a cascade performs rather than the caller addressing the resource directly."

    Design: Corner/entities/create_siting_program_returns_computed_load_and_defaults
    """
    response = api_client.create_siting_program(
        create_siting_program_payload(), TEST_USERS["director_headers"]
    )

    program = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert_mw(
        program["program_annual_load_mwh"],
        PROGRAM_ANNUAL_LOAD_MWH,
        "program_annual_load_mwh",
    )
    assert_program_rollup(
        program,
        program_status="SCREENING",
        committed_load_mw=0,
        renewable_coverage_pct=0,
        full_land_control_site_count=0,
    )
    assert_premium_ledger(program, 0, 0, 0, 0)
    assert_version(program, 1, "new siting program")


def test_reading_a_fresh_site_shows_its_inputs_and_its_undecided_derived_fields():
    """A read of a site nobody has screened returns the three foreign keys and the
    acreage exactly as supplied, and shows every derived field at the value the
    contract declares before screening: no score, no hazard tier, no land control and
    no capital commitment. The risk tier is the exception — it is derived at once, and
    with 500 MW available against a 300 MW target the site reads `ON_TRACK`.

    PRD §3.2: "A new site enters at `status` `DRAFT` with `land_control_pct` of 0 and `land_control_status` of `NONE`; its `energization_risk_tier` is derived immediately from the risk rules in §3.5, while `screening_score`, `hazard_tier` and the ten screening measurements including `transmission_headroom_mw` stay null until the site is screened, and its `water_feasible` flag reads false until screening establishes a demand to test."
    PRD §3.5: "Otherwise the tier is `AT_RISK` when either no live application exists at all or the live application is still in `DRAFT`, `SUBMITTED` or `STUDY_COMPLETE`, **and** the serving utility's `available_capacity_mw` is strictly less than the program's `target_load_mw` — in other words, the site has not yet locked capacity and its utility no longer visibly has enough to give."
    PRD §3.5: "In every other case the tier is `ON_TRACK`."
    PRD §3.10: "It aggregates six terms, all belonging to the one site: the `study_fee_usd` and the `network_upgrade_cost_usd` of the site's interconnection application that is not `WITHDRAWN`, each contributing zero when no such application exists; the `mitigation_cost_usd` and the `conditions_escrow_usd` of the site's zoning application, each contributing zero when no docket has been filed; the sum of `net_purchase_usd` over the site's options that are `EXERCISED`; and the sum of `option_premium_usd` over the site's options that are still `OPTIONED`."

    Design: Corner/entities/get_candidate_site_returns_stored_and_derived_fields
    """
    env = setup_draft_site()

    site = read_site(env["site"]["id"])

    assert site["program_id"] == env["program"]["id"]
    assert site["utility_id"] == env["utility"]["id"]
    assert site["water_source_id"] == env["water_source"]["id"]
    assert site["gross_acres"] == 300

    assert_status(site, "DRAFT", "Site Alpha")
    assert site["screening_score"] is None
    assert site["hazard_tier"] is None
    assert site["transmission_headroom_mw"] is None
    assert site["water_feasible"] is False
    assert site["land_control_pct"] == 0
    assert site["land_control_status"] == "NONE"
    assert site["energization_risk_tier"] == "ON_TRACK"
    assert_money(site["site_capital_commitment_usd"], 0, "site_capital_commitment_usd")

    assert_has_common_fields(site, "Site Alpha")
    assert_version(site, 1, "Site Alpha")


def test_the_site_listing_filters_by_program_and_pages_the_matching_rows():
    """Filtering by program narrows the four sites in the database to three, and
    `total_count` reports that three rather than the size of the page it returns. The
    first window of two leaves a row behind, so `has_more` is true; the second window
    picks up that last row and closes. Both pages are ordered by creation, and the
    other program's site never appears in either.

    PRD §3.2: "Sites can be listed and filtered by `program_id`, `utility_id`, `water_source_id` or `status`, which is how the analyst reaches every site attached to a program, a utility or a basin."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`: `total_count` counts the rows matching the request's filters before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a subsection states otherwise."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/list_candidate_sites_filtered_and_paginated
    """
    env = _three_sites_on_one_program_and_one_elsewhere()
    alpha, bravo, charlie = env["sites"]

    first_page = list_sites(
        {"program_id": env["program"]["id"], "limit": 2, "offset": 0}
    )

    assert first_page["response_type"] == "array"
    assert_pagination_meta(first_page["meta"], 2, 0, 3, True)
    assert_ids_in_order(first_page["data"], [alpha["id"], bravo["id"]])

    second_page = list_sites(
        {"program_id": env["program"]["id"], "limit": 2, "offset": 2}
    )

    assert_pagination_meta(second_page["meta"], 2, 2, 3, False)
    assert_ids_in_order(second_page["data"], [charlie["id"]])

    listed = [row["id"] for row in first_page["data"] + second_page["data"]]
    assert env["other_site"]["id"] not in listed


def test_reading_a_site_that_was_never_minted_is_a_typed_not_found():
    """An identifier the server never issued does not resolve, and the collection the
    unresolved segment addresses decides which error comes back: a `candidate-sites`
    segment yields `ERR_SITE_NOT_FOUND` at HTTP 404. The answer is a full error
    envelope carrying a human-readable message, not an empty success.

    PRD §2.5: "Path parameters are resolved strictly left to right, and each segment must resolve before the next segment is examined or any body field is inspected."
    PRD §2.5: "Each collection has its own not-found error: a `siting-programs` segment that does not resolve yields `ERR_PROGRAM_NOT_FOUND`, a `utilities` segment yields `ERR_UTILITY_NOT_FOUND`, a `water-sources` segment yields `ERR_WATER_SOURCE_NOT_FOUND`, a `candidate-sites` segment yields `ERR_SITE_NOT_FOUND`, an `interconnection-applications` segment yields `ERR_APPLICATION_NOT_FOUND`, an `incentive-negotiations` segment yields `ERR_NEGOTIATION_NOT_FOUND`, a `zoning-applications` segment yields `ERR_ZONING_APPLICATION_NOT_FOUND`, a `power-purchase-agreements` segment yields `ERR_PPA_NOT_FOUND`, and a `parcel-options` segment yields `ERR_PARCEL_OPTION_NOT_FOUND`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/get_candidate_site_unknown_id_returns_site_not_found
    """
    open_program()

    response = api_client.get_candidate_site(
        UNKNOWN_UUID, TEST_USERS["analyst_headers"]
    )

    validate_error(response, "ERR_SITE_NOT_FOUND", 404)

    error = assert_error_envelope(response)
    assert isinstance(error["message"], str) and error["message"] != ""


def test_registering_a_utility_without_its_lead_time_is_a_shape_failure():
    """`energization_lead_days` is one of the registration's declared inputs and has no
    default to fall back on, so a body that omits it fails request-shape validation with
    HTTP 422 before any business rule is consulted. The refusal returns only an error
    identifier and a message — no partially built utility comes back in `data`.

    PRD §3.1: "The registration carries the utility's `name`, the two-letter `state_code` of its service territory, the `balancing_authority` code it settles into, its `total_transmission_capacity_mw` at the point of interconnection, an `interconnect_study_fee_per_mw_usd` rate charged per requested megawatt when an application is submitted, a `network_upgrade_rate_usd_per_mw` rate applied to diversified peak load when a study finds an upgrade necessary, and an `energization_lead_days` figure stating the minimum number of days that must separate a capacity reservation from the energization date the utility will commit to."
    PRD §3.1: "Two fields are optional."
    PRD §2.8: "Request-shape validation therefore concerns itself only with the fields the endpoint declares: required fields must be present, types must match, enum-typed values must fall inside their declared value sets, and numeric ranges must be respected — a program's `target_load_mw` strictly above zero, each hazard index between 0.0 and 1.0 inclusive, a load study's `diversity_factor` strictly above 0 and no greater than 1, an abatement term between 1 and 30 whole years, every percentage expressed as a fraction between 0.0 and 1.0 inclusive, and every `state_code` exactly two uppercase letters. Any failure here is `ERR_INVALID_REQUEST`."
    PRD §2.11: "**Request shape** — required fields, types, enum membership, numeric ranges and pagination bounds as described in §2.8, on every endpoint; otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_utility_missing_required_field_rejected
    """
    response = api_client.create_utility(
        omit(create_utility_payload(), "energization_lead_days"),
        TEST_USERS["director_headers"],
    )

    validate_error(response, "ERR_INVALID_REQUEST", 422)
    assert_error_envelope(response)


def test_the_server_fills_in_the_buffer_the_queue_policy_and_the_premium_credit():
    """Three optional fields are left out of two different creates, and each comes back
    carrying the value the contract names: 90 commissioning days, a first-come queue and
    half the premium credited on exercise. The freshly registered utility also reports
    its ledger at rest, with nothing reserved and the whole 500 MW available.

    PRD §3.1: "`commissioning_buffer_days` defaults to 90 when omitted and expresses how much commissioning slack the utility adds to **both** ends of **every** energization window when testing whether two reservations collide."
    PRD §3.1: "`queue_policy` defaults to `FIRST_COME_FIRST_SERVED` when omitted and may otherwise be `FIRST_READY_FIRST_SERVED`."
    PRD §3.1: "A newly registered utility reports `reserved_capacity_mw` of 0 and an `available_capacity_mw` equal to its total transmission capacity."
    PRD §3.8: "Two fields are optional: `premium_credit_pct`, the fraction of the premium credited against the purchase price on exercise, which defaults to 0.5 when omitted and must lie between 0.0 and 1.0 inclusive; and `replaces_option_id`, naming a prior option on the same parcel that this one supersedes, which is null for a first-time option."
    PRD §3.8: "A new option enters at `status` `OPTIONED`."

    Design: Corner/entities/utility_and_option_defaults_applied_when_omitted
    """
    program = open_program()
    basin = register_water_source()

    utility = validate_success(
        api_client.create_utility(
            create_minimal_utility_payload(), TEST_USERS["director_headers"]
        ),
        201,
    )

    assert utility["commissioning_buffer_days"] == 90
    assert utility["queue_policy"] == "FIRST_COME_FIRST_SERVED"
    assert_capacity_ledger(utility, 0, 500.0)

    site = add_site(program["id"], utility["id"], basin["id"])
    option = validate_success(
        api_client.create_parcel_option(
            omit(
                create_parcel_option_payload(
                    site["id"],
                    site_version(site["id"]),
                    acres=120,
                    option_premium_usd=500000,
                    purchase_price_usd=18000000,
                ),
                "premium_credit_pct",
            ),
            TEST_USERS["analyst_headers"],
        ),
        201,
    )

    assert option["premium_credit_pct"] == 0.5
    assert option["replaces_option_id"] is None
    assert_status(option, "OPTIONED", "new option")


def test_computed_and_system_fields_ignore_the_client_and_appear_only_when_derived():
    """The create body carries a status and a screening score it has no business
    supplying; both extra keys are dropped silently, so the site is minted in `DRAFT`
    with no score at all, on a server-minted UUID and an ISO 8601 timestamp. Only the
    screening call derives the score — 83.00 from the ten measurements — the hazard tier
    from the largest of the three indices, and the workforce ratio at four decimals,
    stamping the acting analyst and taking the row to version 2.

    PRD §2.8: "A request body may name a computed or system-maintained field, or a field the endpoint does not recognize at all; in both cases the extra key is silently ignored rather than rejected."
    PRD §2.4: "Every resource is identified by an `id` that the server mints as a UUID."
    PRD §3.2: "First, `hazard_tier` is set from the largest of the three hazard indices: `SEVERE` when that largest value is at least 0.70, `MODERATE` when it is at least 0.40 but below 0.70, and `LOW` otherwise."
    PRD §3.2: "Second, `workforce_availability_ratio` is the craft labor supply divided by the peak construction headcount, rounded to 4 decimal places."
    PRD §3.2: "On success the acting operator's identifier is stamped as `screened_by_user_id`, which becomes the comparand for the segregation-of-duties rule at commitment time."

    Design: Corner/entities/computed_and_system_fields_are_server_derived_only
    """
    env = setup_environment()

    site = validate_success(
        api_client.create_candidate_site(
            create_candidate_site_payload(
                env["program"]["id"],
                env["utility"]["id"],
                env["water_source"]["id"],
                status="COMMITTED",
                screening_score=99.0,
                land_control_pct=100.0,
            ),
            TEST_USERS["analyst_headers"],
        ),
        201,
    )

    assert is_valid_uuid(site["id"])
    assert is_iso8601_timestamp(site["created_at"])
    assert_status(site, "DRAFT", "Site Alpha")
    assert site["screening_score"] is None
    assert site["land_control_pct"] == 0
    assert_version(site, 1, "Site Alpha")

    screened = screen_site(site["id"])

    assert_site_screening_outputs(
        screened, EXPECTED_SCREENING_SCORE_ALPHA, "MODERATE", workforce_ratio=0.8000
    )
    assert screened["screened_by_user_id"] == ANALYST_USER_ID
    assert_version(screened, 2, "Site Alpha after screening")


def test_an_unknown_cooling_design_and_an_out_of_range_hazard_index_are_both_refused():
    """Two screening packages break the shape contract in two different ways: one names
    a cooling design outside the declared set of three, the other carries a hazard index
    of 1.40 when the indices are fractions bounded at 1.0. Both are refused at HTTP 422
    with the same identifier, and neither touches the site, which is left in `DRAFT`
    with no score and at its original version.

    PRD §3.2: "The cooling design is one of `EVAPORATIVE`, `AIR_COOLED` or `HYBRID`, and an `AIR_COOLED` campus must declare an annual water demand of exactly 0 — a non-zero demand paired with an air-cooled design is a contradiction the screening operation refuses."
    PRD §3.2: "The hazard indices are fractions between 0.0 and 1.0 inclusive; the headroom, the route count and the labor supply must be zero or greater; the peak headcount must be strictly greater than zero; the wage premium must be zero or greater."
    PRD §2.8: "Request-shape validation therefore concerns itself only with the fields the endpoint declares: required fields must be present, types must match, enum-typed values must fall inside their declared value sets, and numeric ranges must be respected — a program's `target_load_mw` strictly above zero, each hazard index between 0.0 and 1.0 inclusive, a load study's `diversity_factor` strictly above 0 and no greater than 1, an abatement term between 1 and 30 whole years, every percentage expressed as a fraction between 0.0 and 1.0 inclusive, and every `state_code` exactly two uppercase letters. Any failure here is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/invalid_enum_and_out_of_range_numbers_rejected
    """
    env = setup_draft_site()

    bad_enum = api_client.screen_candidate_site(
        env["site"]["id"],
        create_screening_payload(cooling_type="GEOTHERMAL"),
        TEST_USERS["analyst_headers"],
    )
    validate_error(bad_enum, "ERR_INVALID_REQUEST", 422)

    bad_range = api_client.screen_candidate_site(
        env["site"]["id"],
        create_screening_payload(seismic_hazard_index=1.40),
        TEST_USERS["analyst_headers"],
    )
    validate_error(bad_range, "ERR_INVALID_REQUEST", 422)

    site = read_site(env["site"]["id"])
    assert_status(site, "DRAFT", "Site Alpha")
    assert site["screening_score"] is None
    assert_version(site, 1, "Site Alpha")


def test_a_restudy_appends_a_second_immutable_row_beside_the_first():
    """A second study round on the same application does not rewrite the first: the
    listing returns two rows, numbered 1 and 2, and round one still reports the 0.92
    diversity factor and the 293.52 MW diversified peak a client read before the
    restudy. Neither row carries `updated_at` or `version`, because a study is a
    historical artifact rather than a mutable record, and each is stamped with the
    utility that filed it.

    PRD §2.4: "Load study rows are the single exception."
    PRD §2.4: "A study, once filed, is an immutable historical artifact: it carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all, and neither field should appear in its representation."
    PRD §3.4: "The study is appended to its application, recording the `application_id` it belongs to and a 1-based `study_round` equal to the owning application's round count after the append, and the operator's identifier is stamped as `filed_by_user_id`."
    PRD §3.4: "Filing a study advances the application from `SUBMITTED` to `STUDY_COMPLETE`; filing another study against an application already in `STUDY_COMPLETE` is a legitimate restudy that leaves the application in `STUDY_COMPLETE` and simply appends the next round."
    PRD §2.1: "When a `UtilityPlanner` files a load study, that same identifier is stamped onto the study row as `filed_by_user_id`."

    Design: Corner/entities/load_study_is_append_only_and_carries_no_version
    """
    env = setup_studied_application()

    file_load_study(
        env["application"]["id"], env["utility"]["id"], diversity_factor=0.60
    )

    listing = list_load_studies(env["application"]["id"])
    assert listing["meta"]["total_count"] == 2

    first, second = listing["data"]
    assert first["study_round"] == 1
    assert second["study_round"] == 2
    assert first["diversity_factor"] == 0.92
    assert_mw(
        first["diversified_peak_mw"],
        EXPECTED_DIVERSIFIED_PEAK_MW,
        "round one diversified_peak_mw",
    )

    for study in (first, second):
        assert_load_study_shape(study)
        assert study["application_id"] == env["application"]["id"]
        assert study["filed_by_user_id"] == env["utility"]["id"]


def test_a_site_naming_a_program_or_a_basin_that_does_not_exist_is_refused():
    """Body foreign keys are resolved in a fixed declaration order, and each unresolved
    one raises the error of the collection it points at: an unknown `program_id` answers
    `ERR_PROGRAM_NOT_FOUND` and an unknown `water_source_id` answers
    `ERR_WATER_SOURCE_NOT_FOUND`, both at HTTP 404. Neither attempt leaves a site
    behind, so the collection is still empty afterwards.

    PRD §2.5: "Foreign keys supplied in a request body are resolved after all path parameters, in a fixed declaration order: `program_id` first, then `utility_id`, then `water_source_id`, then `site_id`, then `application_id`, then `replaces_option_id`."
    PRD §2.5: "Each unresolved reference raises the not-found error belonging to the collection it points at, so a create carrying both an unknown `program_id` and an unknown `utility_id` reports `ERR_PROGRAM_NOT_FOUND`."
    PRD §2.11: "**Body reference existence** — every foreign key in the body resolves, in declaration order, on `POST /candidate-sites`, `POST /interconnection-applications`, `POST /incentive-negotiations`, `POST /zoning-applications`, `POST /power-purchase-agreements` and `POST /parcel-options`."

    Design: Corner/entities/candidate_site_requires_existing_program_and_water_source
    """
    env = setup_environment()

    unknown_program = api_client.create_candidate_site(
        create_candidate_site_payload(
            UNKNOWN_UUID, env["utility"]["id"], env["water_source"]["id"]
        ),
        TEST_USERS["analyst_headers"],
    )
    validate_error(unknown_program, "ERR_PROGRAM_NOT_FOUND", 404)

    unknown_basin = api_client.create_candidate_site(
        create_candidate_site_payload(
            env["program"]["id"], env["utility"]["id"], UNKNOWN_UUID
        ),
        TEST_USERS["analyst_headers"],
    )
    validate_error(unknown_basin, "ERR_WATER_SOURCE_NOT_FOUND", 404)

    assert list_sites()["meta"]["total_count"] == 0


def test_an_application_must_name_the_same_utility_its_site_is_bound_to():
    """Both identifiers in the body resolve perfectly well, so this is not a missing
    reference but a disagreement between two foreign keys of the same flat create: the
    application names the second utility while its site is served by the first, and it
    is refused at HTTP 422. Naming the site's own utility instead is accepted, and the
    site ends with exactly one application.

    PRD §3.4: "The named utility must be the same utility the site itself is bound to; an application naming a different utility from its site's is rejected with `ERR_APPLICATION_SITE_UTILITY_MISMATCH`."
    PRD §2.11: "**Referential agreement** — an application's `utility_id` matches its site's, and a superseding option matches its predecessor's site and parcel, on `POST /interconnection-applications` and `POST /parcel-options`; otherwise `ERR_APPLICATION_SITE_UTILITY_MISMATCH`."
    PRD §2: "Every resource collection in this API is mounted as a top-level path segment; there are no compound identity paths."

    Design: Corner/entities/flat_topology_application_utility_must_match_site_utility
    """
    env = setup_environment()
    other_utility = register_utility(**SECOND_UTILITY)
    site = add_site(
        env["program"]["id"], env["utility"]["id"], env["water_source"]["id"]
    )
    screen_site(site["id"])

    mismatched = api_client.create_interconnection_application(
        create_interconnection_application_payload(site["id"], other_utility["id"]),
        TEST_USERS["analyst_headers"],
    )
    validate_error(mismatched, "ERR_APPLICATION_SITE_UTILITY_MISMATCH", 422)

    application = validate_success(
        api_client.create_interconnection_application(
            create_interconnection_application_payload(
                site["id"], env["utility"]["id"]
            ),
            TEST_USERS["analyst_headers"],
        ),
        201,
    )

    assert application["utility_id"] == env["utility"]["id"]
    assert list_applications({"site_id": site["id"]})["meta"]["total_count"] == 1
