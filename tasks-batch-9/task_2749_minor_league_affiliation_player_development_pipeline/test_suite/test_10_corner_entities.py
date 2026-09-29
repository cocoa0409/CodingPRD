"""Entity-level breadth: creation echoes, retrieval, listing, defaults,
system-generated fields, type constraints, parent resolution, immutability,
derived recomputation and the many-to-many junction.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    assert_affiliate,
    assert_append_only_event,
    assert_decimal,
    assert_integer,
    assert_player,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_registering_a_club_echoes_every_declared_field_and_starts_its_counters_clean(api: ApiClient):
    """All four optional inputs are honoured and the derived block is zeroed.

    PRD 3.1: "A freshly registered club has no history, so its derived fields
    start clean: `active_roster_count`, `rehab_assignment_count` and
    `reserve_list_count` all begin at 0, `facility_score` begins at `100.00`,
    `open_major_deficiency_count` begins at 0 and `facility_status` begins at
    `COMPLIANT`."

    Design: Corner/entities/create_affiliate_returns_all_declared_fields_with_computed_defaults
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    created = validate_success(
        api.create_affiliate(
            factories.affiliate_payload(
                name="Tulsa Drillers",
                level="DOUBLE_A",
                market_city="Tulsa",
                meal_stipend_cents_per_day=3200,
                roster_limit=26,
                reserve_slots=30,
                housing_beds=45,
                travel_standard_tier="BUS_SLEEPER",
            ),
            FARM_DIRECTOR_HEADERS,
        ),
        201,
    )
    assert_affiliate(created)
    assert created["name"] == "Tulsa Drillers", created
    assert created["level"] == "DOUBLE_A", created
    assert created["market_city"] == "Tulsa", created
    assert_integer(created["meal_stipend_cents_per_day"], 3200, "meal_stipend_cents_per_day")
    assert_integer(created["roster_limit"], 26, "roster_limit")
    assert_integer(created["reserve_slots"], 30, "reserve_slots")
    assert_integer(created["housing_beds"], 45, "housing_beds")
    assert created["travel_standard_tier"] == "BUS_SLEEPER", created

    assert_integer(created["active_roster_count"], 0, "active_roster_count")
    assert_integer(created["rehab_assignment_count"], 0, "rehab_assignment_count")
    assert_integer(created["reserve_list_count"], 0, "reserve_list_count")
    assert_integer(created["open_major_deficiency_count"], 0, "open_major_deficiency_count")
    assert_decimal(created["facility_score"], "100.00", 2, "facility_score")
    assert created["facility_status"] == "COMPLIANT", created
    assert_integer(created["version"], 1, "version")


def test_reading_the_club_back_returns_the_stored_row_without_bumping_version(api: ApiClient):
    """A read is not a mutation, so the version stays where the create left it.

    PRD 2.4: "A mutation for these purposes means any change to any stored or
    derived field on the resource, including changes the server makes on its own
    initiative."  A `GET` changes nothing, so the row read back by a different
    role carries the same `version` 1 and the same derived facility block the
    create returned.

    Design: Corner/entities/get_affiliate_by_id_returns_the_stored_row
    """
    created = fixtures.create_affiliate(
        api, name="Rome Emperors", level="HIGH_A", market_city="Rome", meal_stipend_cents_per_day=2800
    )
    assert_integer(created["version"], 1, "version")

    read_back = validate_success(api.get_affiliate(created["id"], MEDICAL_DIRECTOR_HEADERS), 200)
    assert read_back["name"] == "Rome Emperors", read_back
    assert read_back["level"] == "HIGH_A", read_back
    assert_integer(read_back["version"], created["version"], "version")
    assert_decimal(read_back["facility_score"], "100.00", 2, "facility_score")
    assert read_back["facility_status"] == "COMPLIANT", read_back


def test_the_affiliate_listing_pages_and_filters_with_the_declared_defaults(api: ApiClient):
    """Two pages of two cover three rows and flip `has_more` on the way.

    PRD 2.2: "`limit` caps the number of items returned; it defaults to 10, may
    not be lower than 1, and may not exceed 100. `offset` is the number of items
    to skip and defaults to 0."  PRD 2.2 also fixes the envelope: "List responses
    populate four pagination fields inside the envelope's `meta` object: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_affiliates_honours_limit_offset_total_count_and_has_more
    """
    alpha = fixtures.create_affiliate(
        api, name="Alpha Club", level="SINGLE_A", market_city="Asheville", meal_stipend_cents_per_day=2600
    )
    bravo = fixtures.create_affiliate(
        api, name="Bravo Club", level="HIGH_A", market_city="Bowling Green", meal_stipend_cents_per_day=2700
    )
    charlie = fixtures.create_affiliate(
        api, name="Charlie Club", level="DOUBLE_A", market_city="Chattanooga", meal_stipend_cents_per_day=2900
    )

    first_rows, first_meta = validate_paginated(
        api.list_affiliates(COMPLIANCE_OFFICER_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2, first_rows
    assert_integer(first_meta["total_count"], 3, "total_count")
    assert_integer(first_meta["limit"], 2, "limit")
    assert_integer(first_meta["offset"], 0, "offset")
    assert first_meta["has_more"] is True, first_meta

    second_rows, second_meta = validate_paginated(
        api.list_affiliates(COMPLIANCE_OFFICER_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, second_rows
    assert_integer(second_meta["total_count"], 3, "total_count")
    assert_integer(second_meta["offset"], 2, "offset")
    assert second_meta["has_more"] is False, second_meta

    paged = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert sorted(paged) == sorted([alpha["id"], bravo["id"], charlie["id"]]), paged

    filtered_rows, filtered_meta = validate_paginated(
        api.list_affiliates(COMPLIANCE_OFFICER_HEADERS, {"level": "HIGH_A"})
    )
    assert_integer(filtered_meta["total_count"], 1, "total_count")
    assert filtered_rows[0]["id"] == bravo["id"], filtered_rows

    _, default_meta = validate_paginated(api.list_affiliates(COMPLIANCE_OFFICER_HEADERS))
    assert_integer(default_meta["limit"], 10, "default limit")
    assert_integer(default_meta["offset"], 0, "default offset")


def test_an_unstored_affiliate_id_in_the_path_is_a_not_found(api: ApiClient):
    """A well-formed but unknown UUID is a 404, never an empty success.

    PRD 2.6: "Every id embedded in the request path resolves to a stored
    resource, validated strictly left to right, otherwise the not-found error for
    the leftmost unresolved segment (404)".

    Design: Corner/entities/get_affiliate_unknown_id_returns_affiliate_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    refused = api.get_affiliate(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS)
    body = validate_error(refused, ApiErrorId.ERR_AFFILIATE_NOT_FOUND.value, 404)
    assert body.get("message"), f"a not-found response must carry a message: {body!r}"


def test_omitting_the_required_level_is_refused_and_stores_nothing(api: ApiClient):
    """A missing required field is a shape violation, and nothing is persisted.

    PRD 2.6: "The request body is well-shaped, otherwise `ERR_INVALID_REQUEST`
    (400). A body is well-shaped when every required field is present, every enum
    field carries one of its declared values, every numeric field lies inside its
    declared range".

    Design: Corner/entities/create_affiliate_missing_required_level_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    payload = {"name": "No Level Club", "market_city": "Nowhere", "meal_stipend_cents_per_day": 2600}
    refused = api.create_affiliate(payload, FARM_DIRECTOR_HEADERS)
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_affiliates(FARM_DIRECTOR_HEADERS))
    assert_integer(meta["total_count"], 0, "total_count")


def test_an_omitted_roster_limit_takes_the_default_for_the_declared_level(api: ApiClient):
    """The roster default is keyed on level; the other three are flat.

    PRD 3.1: "`roster_limit` bounds how many level or complex assignments the
    club may carry concurrently; it accepts integers from 1 through 40, and when
    it is omitted the server applies the league default for the declared level —
    28 for both `TRIPLE_A` and `DOUBLE_A`, 30 for both `HIGH_A` and `SINGLE_A`,
    35 for `COMPLEX`, and 40 for `DOMINICAN_ACADEMY`. `reserve_slots` records how
    many domestic reserve list places the organization has allotted to this club;
    it accepts integers from 0 through 40 and defaults to 35. `housing_beds`
    records the league-certified player housing beds available at the club or
    academy complex; it accepts integers from 0 through 200 and defaults to 40.
    And `travel_standard_tier` records the travel standard the club commits to,
    one of `CHARTER`, `BUS_SLEEPER` or `BUS_STANDARD`, defaulting to
    `BUS_STANDARD`."

    Design: Corner/entities/omitting_roster_limit_applies_the_level_keyed_default
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    complex_site = fixtures.create_affiliate(
        api,
        name="Complex Site",
        level="COMPLEX",
        market_city="Port Charlotte",
        meal_stipend_cents_per_day=2500,
    )
    top_club = fixtures.create_affiliate(
        api, name="Top Club", level="TRIPLE_A", market_city="Reno", meal_stipend_cents_per_day=3300
    )

    assert_integer(complex_site["roster_limit"], 35, "COMPLEX roster_limit")
    assert_integer(top_club["roster_limit"], 28, "TRIPLE_A roster_limit")
    for club in (complex_site, top_club):
        assert_integer(club["reserve_slots"], 35, "reserve_slots")
        assert_integer(club["housing_beds"], 40, "housing_beds")
        assert club["travel_standard_tier"] == "BUS_STANDARD", club


def test_registering_a_player_mints_the_system_fields_and_zeroed_projections(api: ApiClient):
    """Everything except the four inputs is server-initialised.

    PRD 3.5: "On registration, `roster_status` is `RESERVE_LIST` and
    `medical_status` is `PENDING_CLEARANCE`; `option_years_used` is 0 and
    `option_years_remaining` is 3; `workload_index` and
    `workload_index_projected` are both `0.00`; `promotion_readiness` is
    `0.0000`; and `current_affiliate_id` is null."

    Design: Corner/entities/create_player_generates_system_fields_and_initial_projections
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    player = fixtures.create_player(
        api, full_name="Systemic Fields", origin="DOMESTIC_DRAFT", signed_date="2025-06-10"
    )
    assert_player(player)
    assert_integer(player["version"], 1, "version")
    assert player["roster_status"] == "RESERVE_LIST", player
    assert player["medical_status"] == "PENDING_CLEARANCE", player
    assert_integer(player["option_years_used"], 0, "option_years_used")
    assert_integer(player["option_years_remaining"], 3, "option_years_remaining")
    assert_decimal(player["workload_index"], "0.00", 2, "workload_index")
    assert_decimal(player["workload_index_projected"], "0.00", 2, "workload_index_projected")
    assert_decimal(player["promotion_readiness"], "0.0000", 4, "promotion_readiness")
    assert player["current_affiliate_id"] is None, player
    assert_integer(player["service_days_accrued"], 0, "service_days_accrued")


def test_an_undeclared_enum_member_and_an_out_of_range_number_are_both_refused(api: ApiClient):
    """A present-but-illegal value fails the same shape rule as an omission.

    PRD 2.6: "A body is well-shaped when every required field is present, every
    enum field carries one of its declared values, every numeric field lies inside
    its declared range, every date field parses as `YYYY-MM-DD` and every datetime
    field parses as ISO 8601".  `ROOKIE_LEAGUE` is not one of the six declared
    levels and `roster_limit` 0 sits below the declared floor of 1, so both are
    400s that persist nothing.

    Design: Corner/entities/create_affiliate_out_of_enum_level_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bad_enum = api.create_affiliate(
        factories.affiliate_payload(
            name="Bad Enum Club",
            level="ROOKIE_LEAGUE",
            market_city="Elsewhere",
            meal_stipend_cents_per_day=2600,
        ),
        FARM_DIRECTOR_HEADERS,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    bad_range = api.create_affiliate(
        factories.affiliate_payload(
            name="Bad Range Club",
            level="SINGLE_A",
            market_city="Elsewhere",
            meal_stipend_cents_per_day=2600,
            roster_limit=0,
        ),
        FARM_DIRECTOR_HEADERS,
    )
    validate_error(bad_range, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_affiliates(FARM_DIRECTOR_HEADERS))
    assert_integer(meta["total_count"], 0, "total_count")


def test_drafting_an_agreement_under_an_unstored_club_is_a_not_found(api: ApiClient):
    """The path parent is resolved before the body is even considered.

    PRD 2.6: "Every id embedded in the request path resolves to a stored
    resource, validated strictly left to right, otherwise the not-found error for
    the leftmost unresolved segment (404) — one of `ERR_AFFILIATE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_FACILITY_REVIEW_NOT_FOUND`,
    `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_STAFF_ALLOCATION_NOT_FOUND`,
    `ERR_PLAYER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_DEVELOPMENT_PLAN_NOT_FOUND`, `ERR_MEDICAL_CLEARANCE_NOT_FOUND`,
    `ERR_SIGNING_POOL_NOT_FOUND`, `ERR_SIGNING_NOT_FOUND` or
    `ERR_TRANSACTION_REPORT_NOT_FOUND`."  A `ComplianceOfficer` acts so that the
    affiliate-scope rule cannot mask the lookup.

    Design: Corner/entities/create_agreement_under_unknown_affiliate_returns_affiliate_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    refused = api.create_agreement(
        NON_EXISTENT_UUID,
        factories.agreement_payload(),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_AFFILIATE_NOT_FOUND.value, 404)


def test_a_workload_outing_carries_no_version_and_defaults_its_measures(api: ApiClient):
    """The outing is an append-only event, so the audit quartet is truncated.

    PRD 2.4: "The workload outing is the single exception: a workload log is an
    append-only event that is never edited after it is written, so it carries only
    `id` and `created_at` — it has neither an `updated_at` field nor a `version`
    field, and neither field appears in its response payload."  PRD 3.7 supplies
    the measure defaults: "`pitches_thrown`, an integer from 0 through 250
    defaulting to 0; `innings_pitched`, a number with one decimal place from `0.0`
    through `15.0` defaulting to `0.0`; and `high_intensity_minutes`, the
    conditioning minutes charged to the outing, an integer from 0 through 300
    defaulting to 0."

    Design: Corner/entities/workload_log_is_an_immutable_event_with_no_version_or_mutator
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Immutable Club",
            "level": "SINGLE_A",
            "market_city": "Lynchburg",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={"facility_standard_tier": "TIER_2", "minimum_active_players": 0},
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={"full_name": "Log Owner"},
        effective_date="2026-07-25",
        end_date="2026-09-30",
    )

    measured = fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-07-30",
        pitches_thrown=20,
        innings_pitched=1.0,
        high_intensity_minutes=5,
    )
    assert_append_only_event(measured, "WorkloadLog")
    assert measured["assignment_id"] == bundle["assignment_id"], measured

    rows, meta = validate_paginated(
        api.list_workload_logs(bundle["assignment_id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 1, "workload log total_count")
    assert rows[0]["id"] == measured["id"], rows

    bare = fixtures.log_outing(api, bundle["assignment_id"], "2026-07-31")
    assert_append_only_event(bare, "WorkloadLog")
    assert_integer(bare["pitches_thrown"], 0, "pitches_thrown")
    assert_decimal(bare["innings_pitched"], "0.0", 1, "innings_pitched")
    assert_integer(bare["high_intensity_minutes"], 0, "high_intensity_minutes")
    assert bare["is_rehab_outing"] is False, bare


def test_sliding_the_clock_past_the_window_recomputes_the_workload_index_to_zero(api: ApiClient):
    """The index is a function of the window, never a stored write-time total.

    PRD 3.7: "And the outing's `log_date` must fall inside a rolling fourteen-day
    window that is inclusive at both ends: the window runs from thirteen days
    before the current logical clock date through the clock date itself. Because
    the window is anchored on the clock, setting the clock forward silently drops
    outings out of the window and the figures must be recomputed."  A single
    100-pitch outing at a `SINGLE_A` club contributes 0.55 while it is in window
    and nothing once the clock has moved nineteen days past it.

    Design: Corner/entities/workload_index_recomputed_when_the_clock_slides_the_rolling_window
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Window Club",
            "level": "SINGLE_A",
            "market_city": "Kannapolis",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides={"facility_standard_tier": "TIER_2", "minimum_active_players": 0},
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={"full_name": "Window Watcher"},
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-04-01",
        pitches_thrown=100,
        innings_pitched=0.0,
        high_intensity_minutes=0,
    )

    in_window = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(in_window["workload_index"], "0.55", 2, "workload_index")
    assert_decimal(in_window["workload_index_projected"], "0.55", 2, "workload_index_projected")

    fixtures.set_clock(api, "2026-04-20T00:00:00Z")
    aged_out = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(aged_out["workload_index"], "0.00", 2, "workload_index")
    assert_decimal(aged_out["workload_index_projected"], "0.00", 2, "workload_index_projected")

    _, meta = validate_paginated(
        api.list_workload_logs(bundle["assignment_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(meta["total_count"], 1, "workload log total_count")


def test_the_allocation_junction_lists_from_the_member_and_the_club_side(api: ApiClient):
    """One coach at two clubs and one club with two coaches, both navigable.

    PRD 3.4: "Allocations can be listed from the member's side with a `status`
    filter, and from the club's side with filters on `staff_role` and `status`."
    PRD 2.7 explains why the affiliate must be re-read between the two proposals
    aimed at it: "each of the three guarded creates itself bumps the parent's
    `version` by one on success — creating an assignment advances the player's
    `version`, submitting a signing advances the pool's `version`, and proposing an
    allocation advances the affiliate's `version` — so a client that issues two
    creates in a row against the same parent must re-read the parent between
    them."

    Design: Corner/entities/staff_allocation_junction_is_reachable_from_both_member_and_affiliate
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    agreement_overrides = {"facility_standard_tier": "TIER_2", "minimum_active_players": 0}
    club_a = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Graph Club A",
            "level": "HIGH_A",
            "market_city": "Greensboro",
            "meal_stipend_cents_per_day": 2800,
        },
        agreement_overrides=dict(agreement_overrides),
    )
    club_b = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Graph Club B",
            "level": "SINGLE_A",
            "market_city": "Down East",
            "meal_stipend_cents_per_day": 2600,
        },
        agreement_overrides=dict(agreement_overrides),
    )
    member_one = fixtures.create_staff_member(
        api, full_name="Member One", discipline="PITCHING", certification_expires_on="2027-01-31"
    )
    member_two = fixtures.create_staff_member(
        api, full_name="Member Two", discipline="HITTING", certification_expires_on="2027-01-31"
    )

    version_before = fixtures.affiliate_version(api, club_a["affiliate_id"])
    first = fixtures.create_allocation(
        api,
        member_one["id"],
        club_a["affiliate_id"],
        expected_affiliate_version=version_before,
        staff_role="PITCHING_COACH",
        fte_pct=40,
        effective_start="2026-04-01",
        effective_end="2026-07-01",
    )
    second = fixtures.create_allocation(
        api,
        member_one["id"],
        club_b["affiliate_id"],
        staff_role="PITCHING_COACH",
        fte_pct=40,
        effective_start="2026-07-01",
        effective_end="2026-09-01",
    )
    version_after = fixtures.affiliate_version(api, club_a["affiliate_id"])
    assert_integer(version_after, version_before + 1, "Affiliate.version")
    third = fixtures.create_allocation(
        api,
        member_two["id"],
        club_a["affiliate_id"],
        expected_affiliate_version=version_after,
        staff_role="HITTING_COACH",
        fte_pct=50,
        effective_start="2026-04-01",
        effective_end="2026-07-01",
    )

    member_rows, member_meta = validate_paginated(
        api.list_staff_member_allocations(member_one["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_integer(member_meta["total_count"], 2, "member-side total_count")
    assert {row["id"] for row in member_rows} == {first["id"], second["id"]}, member_rows

    club_a_rows, club_a_meta = validate_paginated(
        api.list_affiliate_staff_allocations(club_a["affiliate_id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_integer(club_a_meta["total_count"], 2, "club-side total_count")
    assert {row["id"] for row in club_a_rows} == {first["id"], third["id"]}, club_a_rows

    club_b_rows, club_b_meta = validate_paginated(
        api.list_affiliate_staff_allocations(club_b["affiliate_id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert_integer(club_b_meta["total_count"], 1, "club-side total_count")
    assert club_b_rows[0]["id"] == second["id"], club_b_rows

    for allocation in (first, second, third):
        assert_status(allocation, "PROPOSED", "StaffAllocation")
    for member_id in (member_one["id"], member_two["id"]):
        member = validate_success(api.get_staff_member(member_id, FARM_DIRECTOR_HEADERS), 200)
        assert_integer(member["total_committed_fte_pct"], 0, "total_committed_fte_pct")
