"""Resource-level breadth: declared fields, defaults, computed zero-states,
server-stamped properties, foreign keys and the junction row's two parents."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_common_properties,
    assert_immutable_row_properties,
    create_athlete,
    create_edition,
    create_sport,
    create_sport_event,
    games_edition_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    personnel_payload,
    setup_open_edition,
    sport_event_payload,
    unique_sport_code,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["games_admin_headers"]
OFFICER = TEST_USERS["registration_officer_headers"]
OFFICIAL = TEST_USERS["sport_official_headers"]


def test_creating_an_edition_echoes_every_input_and_stamps_every_default():
    """PRD §3.1: "The edition is described by its public `name`, the `host_city` whose
    economic impact will eventually be reported, and the `host_state_code`, given as
    exactly two uppercase letters, which is the reference point for residency-based
    qualification exemptions."
    PRD §3.1: "Its calendar is fixed by `competition_start_date`, `competition_end_date`
    and the masters `age_reference_date`, and its registration cut-off by the instant
    `registration_deadline_utc`."
    PRD §3.1: "Two inputs are optional: `age_basis`, which selects which of the two age
    computations drives band assignment and defaults to `REFERENCE_DATE` with
    `FIRST_COMPETITION_DAY` as the alternative; and `municipal_support_cents`, the cash
    the host municipality has pledged, which defaults to 0 and may not be negative."
    PRD §3.1: "A newly created edition is `DRAFT`, its `ops_epoch` counter reads 0, both
    `sponsorship_recognized_cents` and `provisional_impact_cents` read 0, and
    `final_impact_cents` is null."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by
    one on every mutation of that row, including mutations the server performs on its
    own initiative as part of a cascade, and including mutations that only touch a
    derived counter such as `accepted_entry_count`, `confirmed_official_count`,
    `assigned_minutes_total`, `reserved_bed_nights` or `sponsorship_recognized_cents`."

    A create carrying only the required fields answers 201, returns each field as
    submitted and applies every declared default exactly once: `DRAFT`, the
    reference-date age basis, no municipal support, a zero epoch, zero ledgers and
    a null settled figure.

    Design: Corner/entities/corner_entity_creation_games_edition_returns_declared_fields_and_defaults
    """
    empty, meta = validate_paginated(api_client.list_games_editions(ADMIN, {"limit": 10}))
    assert empty == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    payload = games_edition_payload()
    response = api_client.create_games_edition(payload, ADMIN)

    edition = validate_success(response, expected_status=201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
    for field in (
        "name", "host_city", "host_state_code", "competition_start_date",
        "competition_end_date", "age_reference_date", "registration_deadline_utc",
    ):
        assert edition[field] == payload[field]
    assert edition["status"] == "DRAFT"
    assert edition["age_basis"] == "REFERENCE_DATE"
    assert edition["municipal_support_cents"] == 0
    assert edition["ops_epoch"] == 0
    assert edition["sponsorship_recognized_cents"] == 0
    assert edition["provisional_impact_cents"] == 0
    assert edition["final_impact_cents"] is None
    assert_common_properties(edition)
    assert edition["version"] == 1


def test_reading_a_sport_event_returns_exactly_the_row_that_was_written():
    """PRD §3.1: "It is created against a `sport_id` and a `games_edition_id`, and carries
    an `event_code` such as a distance or a doubles designation, an `age_group_code`
    that is either a five-year band written as two ages joined by a hyphen — the lower
    bound in the fifties through nineties, the upper bound likewise — or the literal
    open band `100+`, a `gender_division` of `MEN`, `WOMEN` or `MIXED`, an
    `entry_fee_cents` figure of zero or more, and a `capacity` of at least one accepted
    entry."
    PRD §3.1: "Two inputs are optional: `min_entries_to_stage`, the accepted-entry floor
    below which the event cannot be staged, which defaults to 3 and must be at least 1;
    and `national_qualifying_standard`, the mark a verified performance must reach for
    national qualification, which defaults to null and when null disables national
    qualification for that event entirely."
    PRD §3.1: "A fresh event is `OPEN`, with `accepted_entry_count` at 0,
    `available_slots` equal to its `capacity`, `current_record_id` null and
    `seeded_at_utc` null."
    PRD §2.1: "Every single-resource read and every list read is available to all seven
    roles; write access is per-endpoint, and a role that is not listed for the endpoint
    it calls is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    The single-row read round-trips every stored field, including the capacity
    accounting seeded from `capacity` and the entry floor's default of three, and it
    is available to a role that never writes events.

    Design: Corner/entities/corner_entity_retrieval_sport_event_round_trips_stored_fields
    """
    edition = create_edition()
    sport = create_sport()
    payload = sport_event_payload(sport["id"], edition["id"], capacity=8)
    payload.pop("min_entries_to_stage")
    created = validate_success(
        api_client.create_sport_event(payload, ADMIN), expected_status=201
    )

    event = validate_success(api_client.get_sport_event(created["id"], OFFICER))

    assert event["sport_id"] == sport["id"]
    assert event["games_edition_id"] == edition["id"]
    assert event["event_code"] == payload["event_code"]
    assert event["age_group_code"] == payload["age_group_code"]
    assert event["gender_division"] == "MEN"
    assert event["entry_fee_cents"] == 6000
    assert event["capacity"] == 8
    assert event["min_entries_to_stage"] == 3
    assert event["status"] == "OPEN"
    assert event["accepted_entry_count"] == 0
    assert event["available_slots"] == 8
    assert event["current_record_id"] is None
    assert event["seeded_at_utc"] is None
    assert event["national_qualifying_standard"] is None


def test_athlete_pages_report_a_stable_total_count_and_an_honest_has_more():
    """PRD §2.3: "`offset` sets how many rows to skip; when omitted it defaults to 0, and
    its minimum accepted value is 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope."
    PRD §2.3: "`total_count` reports the number of rows matching the filters before
    pagination is applied, and `has_more` is true when rows remain beyond the returned
    page."
    PRD §2.5: "Every resource that has a lifecycle also exposes a `status` field naming
    the state it currently occupies, and the corresponding list read may be narrowed by
    a `status` filter; the athlete is the one exception, splitting its lifecycle across
    two separately named dimensions instead of a single `status`."

    Two pages of two over three rows: the first is full and reports more to come,
    the second holds the remainder and reports none, the total is the pre-pagination
    count on both, and the two pages partition the three rows.  A filter that
    matches nothing reports zero rather than everything.

    Design: Corner/entities/corner_entity_listing_athletes_pagination_reports_total_count_and_has_more
    """
    ctx = setup_open_edition()
    ids = {
        create_athlete(ctx["edition"]["id"], full_name=name)["id"]
        for name in ("Ada Fenn", "Ben Orsi", "Cleo Marsh")
    }

    page_one, meta_one = validate_paginated(
        api_client.list_athletes(ADMIN, {"limit": 2, "offset": 0})
    )
    page_two, meta_two = validate_paginated(
        api_client.list_athletes(ADMIN, {"limit": 2, "offset": 2})
    )
    registered, meta_registered = validate_paginated(
        api_client.list_athletes(ADMIN, {"registration_status": "REGISTERED", "limit": 10})
    )

    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert {row["id"] for row in page_one + page_two} == ids
    assert registered == []
    assert meta_registered["total_count"] == 0
    assert meta_registered["has_more"] is False


def test_an_absent_athlete_id_answers_the_athlete_not_found_error():
    """PRD §2.6: "Each has a dedicated HTTP 404 error: `ERR_GAMES_EDITION_NOT_FOUND`,
    `ERR_SPORT_NOT_FOUND`, `ERR_SPORT_EVENT_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
    `ERR_SESSION_SLOT_NOT_FOUND`, `ERR_ATHLETE_NOT_FOUND`,
    `ERR_QUALIFYING_RESULT_NOT_FOUND`, `ERR_SPORT_ENTRY_NOT_FOUND`,
    `ERR_MEDICAL_SCREENING_NOT_FOUND`, `ERR_PERSONNEL_NOT_FOUND`,
    `ERR_PERSONNEL_ASSIGNMENT_NOT_FOUND`, `ERR_COMPETITION_RESULT_NOT_FOUND`,
    `ERR_AGE_GROUP_RECORD_NOT_FOUND`, `ERR_ACCOMMODATION_BLOCK_NOT_FOUND`,
    `ERR_VILLAGE_STAY_NOT_FOUND` and `ERR_SPONSORSHIP_COMMITMENT_NOT_FOUND`."
    PRD §2.2: "- The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "- The `message` provides a human-readable explanation of what went
    wrong."

    A well-formed identifier that names no row is a 404 carrying that resource's
    own dedicated error, in the error envelope — never an empty success.

    Design: Corner/entities/corner_entity_not_found_athlete_unknown_uuid_returns_404
    """
    _rows, meta = validate_paginated(api_client.list_athletes(ADMIN, {"limit": 10}))
    assert meta["total_count"] == 0

    response = api_client.get_athlete(NON_EXISTENT_UUID, ADMIN)

    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_FOUND.value, expected_status=404)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}


def test_omitting_a_required_field_is_a_malformed_request_that_writes_nothing():
    """PRD §2.10: "On every POST endpoint, each required body field is present, correctly
    typed, inside its declared numeric range, and for enum fields a declared member;
    unknown body fields are rejected — otherwise `ERR_INVALID_REQUEST`."
    PRD §3.2: "A `GamesAdmin` or a `RegistrationOfficer` registers an **athlete** into
    an edition by supplying the `games_edition_id`, the athlete's `full_name`, a contact
    `email`, a `date_of_birth` in `YYYY-MM-DD` form, and a `residency_state_code` of
    exactly two uppercase letters."
    PRD §2.10: "The practical consequence of this ordering is that structural and
    authorisation failures always mask business failures, cross-entity state gates are
    decided before safety gates, safety gates are decided before eligibility arithmetic,
    and capacity and fiscal checks are decided last."

    A missing date of birth is caught by the structural check that runs ahead of
    every age-band and deadline rule, so the answer is the 400 rather than an
    age-eligibility verdict, and no athlete row survives the attempt.

    Design: Corner/entities/corner_entity_missing_required_date_of_birth_rejected
    """
    ctx = setup_open_edition()

    response = api_client.create_athlete(
        {
            "games_edition_id": ctx["edition"]["id"],
            "full_name": "Ada Fenn",
            "email": "ada.fenn@example.org",
            "residency_state_code": "IL",
        },
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    _rows, meta = validate_paginated(api_client.list_athletes(ADMIN, {"limit": 10}))
    assert meta["total_count"] == 0


def test_every_optional_input_omitted_falls_back_to_its_declared_default():
    """PRD §3.1: "Two inputs are optional: `age_basis`, which selects which of the two age
    computations drives band assignment and defaults to `REFERENCE_DATE` with
    `FIRST_COMPETITION_DAY` as the alternative; and `municipal_support_cents`, the cash
    the host municipality has pledged, which defaults to 0 and may not be negative."
    PRD §3.1: "Three inputs are optional: `min_age`, the sport-specific minimum basis
    age, which defaults to 50 and may not be set below 50; and the two age-keyed
    modification maps, `equipment_profile` and `format_modifications`, which default to
    empty objects."
    PRD §3.1: "Two inputs are optional: `min_entries_to_stage`, the accepted-entry floor
    below which the event cannot be staged, which defaults to 3 and must be at least 1;
    and `national_qualifying_standard`, the mark a verified performance must reach for
    national qualification, which defaults to null and when null disables national
    qualification for that event entirely."
    PRD §3.5: "Each venue declares the emergency tier in force on site as
    `emergency_protocol_code`, one of `EP_BASIC`, `EP_ADVANCED` or `EP_CARDIAC`, and may
    optionally declare `has_onsite_medical_bay`, which defaults to false."
    PRD §3.5: "Two inputs are optional: `teardown_buffer_minutes`, the minutes of
    field-of-play teardown appended to the block when venue occupancy is tested, which
    defaults to 15 and is accepted only in the range 0 through 120; and
    `required_official_count`, the number of confirmed official assignments the slot
    needs before it may start, which defaults to 2 and must be at least 1."
    PRD §3.6: "A `GamesAdmin` registers a person against a `games_edition_id` with a
    `full_name` and a `personnel_type` of either `OFFICIAL` or `VOLUNTEER`, and may
    supply a `certification_level`, an integer from 0 through 4 that defaults to 0,
    together with `certified_sport_codes`, a list of the sport codes that person is
    badged to officiate, which defaults to empty."

    Seven resources created with their optional inputs left out: the sport's
    minimum age and two opaque adaptation maps, the event's entry floor and its
    absent national standard, the venue's medical bay, the block's teardown buffer
    and required officials, and the volunteer's badge level and empty badge list.

    Design: Corner/entities/corner_entity_defaults_applied_when_optional_inputs_omitted
    """
    edition = create_edition()

    sport = validate_success(
        api_client.create_sport(
            {
                "sport_code": unique_sport_code("SWM"),
                "name": "Swimming",
                "contact_class": "LOW",
                "mark_direction": "LOWER_IS_BETTER",
                "required_certification_level": 1,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    event = validate_success(
        api_client.create_sport_event(
            {
                "sport_id": sport["id"],
                "games_edition_id": edition["id"],
                "event_code": "S50FREE",
                "age_group_code": "60-64",
                "gender_division": "WOMEN",
                "entry_fee_cents": 5000,
                "capacity": 6,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    venue = validate_success(
        api_client.create_venue(
            {
                "games_edition_id": edition["id"],
                "name": "Municipal Natatorium",
                "competition_area_count": 3,
                "spectator_capacity": 250,
                "emergency_protocol_code": "EP_ADVANCED",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    slot = validate_success(
        api_client.create_session_slot(
            {
                "venue_id": venue["id"],
                "sport_event_id": event["id"],
                "start_utc": "2026-09-12T09:00:00Z",
                "end_utc": "2026-09-12T10:00:00Z",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    volunteer = validate_success(
        api_client.create_personnel(
            {
                "games_edition_id": edition["id"],
                "full_name": "Iris Vale",
                "personnel_type": "VOLUNTEER",
            },
            ADMIN,
        ),
        expected_status=201,
    )

    assert edition["age_basis"] == "REFERENCE_DATE"
    assert edition["municipal_support_cents"] == 0
    assert sport["min_age"] == 50
    assert sport["equipment_profile"] == {}
    assert sport["format_modifications"] == {}
    assert event["min_entries_to_stage"] == 3
    assert event["national_qualifying_standard"] is None
    assert venue["has_onsite_medical_bay"] is False
    assert slot["teardown_buffer_minutes"] == 15
    assert slot["required_official_count"] == 2
    assert volunteer["certification_level"] == 0
    assert volunteer["certified_sport_codes"] == []


def test_derived_counters_read_their_zero_state_immediately_after_creation():
    """PRD §3.1: "A fresh event is `OPEN`, with `accepted_entry_count` at 0,
    `available_slots` equal to its `capacity`, `current_record_id` null and
    `seeded_at_utc` null."
    PRD §3.2: "A newly created athlete also reads `fee_total_cents` 0, `fee_paid_cents`
    0 and an empty `fee_breakdown`."
    PRD §3.2: "`age_at_reference` applies that count from `date_of_birth` to the
    edition's `age_reference_date`, and `age_at_first_day` applies it from
    `date_of_birth` to the edition's `competition_start_date`."
    PRD §3.6: "Two ledgers accompany every person and both start at zero:
    `assigned_minutes_total`, the sum of the `duration_minutes` of that person's
    assignments whose status is `ASSIGNED`, `CONFIRMED` or `COMPLETED`; and
    `no_show_count`, the number of that person's assignments that ended in `NO_SHOW`."
    PRD §3.5: "A new slot is `SCHEDULED` with `confirmed_official_count` at 0."
    PRD §3.8: "A block carries one ledger, `reserved_bed_nights`, which starts at zero
    and holds the sum of the `nights` of every stay in that block whose status is
    `RESERVED`, `CHECKED_IN` or `COMPLETED`."

    None of the ledgers is client-supplied, and each reads its declared opening
    value on the create response: an event's free seats start at the full capacity
    rather than at zero, an athlete's fee figures start empty because settlement runs
    only at payment, and the minutes, no-show, coverage and bed-night counters all
    start at zero.  The two ages, by contrast, are computed at once.

    Design: Corner/entities/corner_entity_computed_counters_start_at_zero_on_create
    """
    ctx = setup_open_edition()
    edition_id = ctx["edition"]["id"]
    venue = validate_success(
        api_client.create_venue(
            {
                "games_edition_id": edition_id,
                "name": "North Oval",
                "competition_area_count": 4,
                "spectator_capacity": 500,
                "emergency_protocol_code": "EP_ADVANCED",
                "has_onsite_medical_bay": True,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    athlete = create_athlete(edition_id, full_name="Ada Fenn", date_of_birth="1966-03-02")
    person = validate_success(
        api_client.create_personnel(
            personnel_payload(edition_id, full_name="Dana Reyes"), ADMIN
        ),
        expected_status=201,
    )
    slot = validate_success(
        api_client.create_session_slot(
            {
                "venue_id": venue["id"],
                "sport_event_id": ctx["event"]["id"],
                "start_utc": "2026-09-12T09:00:00Z",
                "end_utc": "2026-09-12T10:00:00Z",
                "teardown_buffer_minutes": 0,
                "required_official_count": 1,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    block = validate_success(
        api_client.create_accommodation_block(
            {
                "games_edition_id": edition_id,
                "name": "Birch Hall",
                "bed_capacity": 4,
                "nightly_rate_cents": 11000,
            },
            ADMIN,
        ),
        expected_status=201,
    )

    assert ctx["event"]["accepted_entry_count"] == 0
    assert ctx["event"]["available_slots"] == ctx["event"]["capacity"]
    assert athlete["fee_total_cents"] == 0
    assert athlete["fee_paid_cents"] == 0
    assert athlete["fee_breakdown"] == {}
    assert athlete["age_at_reference"] == 60
    assert athlete["age_at_first_day"] == 60
    assert athlete["age_group_code"] == "60-64"
    assert person["assigned_minutes_total"] == 0
    assert person["no_show_count"] == 0
    assert slot["confirmed_official_count"] == 0
    assert block["reserved_bed_nights"] == 0


def test_the_server_mints_the_identity_properties_and_a_read_never_bumps_the_version():
    """PRD §2.5: "`id` is a server-minted UUID with no type prefix."
    PRD §2.5: "`created_at` is an ISO 8601 UTC timestamp with three fractional digits,
    stamped when the row is first written."
    PRD §2.5: "`updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed
    on every mutation of the row."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by
    one on every mutation of that row, including mutations the server performs on its
    own initiative as part of a cascade, and including mutations that only touch a
    derived counter such as `accepted_entry_count`, `confirmed_official_count`,
    `assigned_minutes_total`, `reserved_bed_nights` or `sponsorship_recognized_cents`."

    The identifier appears in no request body, both timestamps are populated
    instants, and the version starts at one for every resource that carries the
    common property set.  Reading the row back leaves that version alone.

    Design: Corner/entities/corner_entity_system_fields_stamped_on_sport_create
    """
    edition = create_edition()

    sport = create_sport()
    read_back = validate_success(api_client.get_sport(sport["id"], OFFICIAL))

    assert is_valid_uuid(sport["id"])
    assert is_iso8601_timestamp(sport["created_at"])
    assert is_iso8601_timestamp(sport["updated_at"])
    assert sport["version"] == 1
    assert read_back["version"] == sport["version"]
    assert edition["version"] == 1


def test_a_value_outside_a_declared_enum_or_range_is_a_malformed_request():
    """PRD §2.10: "On every POST endpoint, each required body field is present, correctly
    typed, inside its declared numeric range, and for enum fields a declared member;
    unknown body fields are rejected — otherwise `ERR_INVALID_REQUEST`."
    PRD §3.6: "A `GamesAdmin` registers a person against a `games_edition_id` with a
    `full_name` and a `personnel_type` of either `OFFICIAL` or `VOLUNTEER`, and may
    supply a `certification_level`, an integer from 0 through 4 that defaults to 0,
    together with `certified_sport_codes`, a list of the sport codes that person is
    badged to officiate, which defaults to empty."

    Both halves of the type contract are enforced structurally: a personnel type
    that is neither official nor volunteer, and a certification level above the
    declared nought-to-four range.  Neither attempt leaves a row behind.

    Design: Corner/entities/corner_entity_invalid_enum_personnel_type_rejected
    """
    edition = create_edition()

    bad_enum = api_client.create_personnel(
        {
            "games_edition_id": edition["id"],
            "full_name": "Dana Reyes",
            "personnel_type": "REFEREE",
        },
        ADMIN,
    )
    bad_range = api_client.create_personnel(
        {
            "games_edition_id": edition["id"],
            "full_name": "Dana Reyes",
            "personnel_type": "OFFICIAL",
            "certification_level": 5,
        },
        ADMIN,
    )

    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    validate_error(bad_range, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    _rows, meta = validate_paginated(api_client.list_personnel(ADMIN, {"limit": 10}))
    assert meta["total_count"] == 0


def test_ordering_constraints_between_two_fields_of_one_body_are_enforced():
    """PRD §2.4: "`competition_end_date` must be on or after `competition_start_date`, and
    `age_reference_date` must be on or after `competition_end_date`."
    PRD §2.4: "A violation of either is a malformed request and is refused with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "An event whose `capacity` is smaller than its `min_entries_to_stage` is a
    contradiction and is refused as a malformed request."
    PRD §2.10: "Structural arithmetic on writes holds: an event's `capacity` is at least
    its `min_entries_to_stage` at creation, and `end_utc` is strictly after `start_utc`
    on any slot write — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Three contradictions inside a single payload: a competition window that ends
    before it starts, an age reference date earlier than the window's close, and an
    event whose capacity cannot even hold the entries it requires to be staged.

    Design: Corner/entities/corner_entity_date_ordering_constraint_rejected
    """
    edition = create_edition()
    sport = create_sport()

    backwards = api_client.create_games_edition(
        games_edition_payload(
            name="Backwards Games",
            competition_start_date="2026-09-20",
            competition_end_date="2026-09-10",
        ),
        ADMIN,
    )
    early_reference = api_client.create_games_edition(
        games_edition_payload(name="Early Reference Games", age_reference_date="2026-09-15"),
        ADMIN,
    )
    impossible_capacity = api_client.create_sport_event(
        sport_event_payload(
            sport["id"], edition["id"], capacity=2, min_entries_to_stage=5
        ),
        ADMIN,
    )

    validate_error(backwards, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    validate_error(early_reference, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    validate_error(
        impossible_capacity, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )
    _editions, edition_meta = validate_paginated(
        api_client.list_games_editions(ADMIN, {"limit": 10})
    )
    assert edition_meta["total_count"] == 1
    _events, event_meta = validate_paginated(
        api_client.list_sport_events(ADMIN, {"limit": 10})
    )
    assert event_meta["total_count"] == 0


def test_an_immutable_row_carries_a_reduced_property_set_and_is_corrected_by_appending():
    """PRD §2.5: "A `QualifyingResult` and a `MedicalScreening` each expose only `id` and
    `created_at`; both `updated_at` and `version` are absent from those two resources
    entirely, and no endpoint modifies them after creation."
    PRD §3.3: "The row is immutable once written: it is never edited and, as noted in
    §2.5, it carries no `updated_at` and no `version`."
    PRD §3.3: "A **qualifying result** is filed by a `GamesAdmin` or a
    `RegistrationOfficer` naming the `athlete_id` who produced it, the `sport_id` the
    meet was contested in, the `event_code` used at that meet, the `mark_value` achieved
    — which must be strictly greater than zero — the `meet_date` on which the meet was
    held, a `meet_level` of either `LOCAL` or `STATE`, and a boolean `sanctioned` flag
    recording whether the state association sanctioned the meet."

    A qualifying result exposes only its identifier and its creation instant — no
    updated timestamp and no version — and no endpoint amends it.  A correction is
    therefore a second row: the first still reads back its original mark and both
    rows coexist under the same athlete.

    Design: Corner/entities/corner_entity_immutability_qualifying_result_has_no_update_endpoint
    """
    ctx = setup_open_edition()
    athlete = create_athlete(ctx["edition"]["id"], full_name="Ada Fenn")
    body = {
        "athlete_id": athlete["id"],
        "sport_id": ctx["sport"]["id"],
        "event_code": "T100M",
        "mark_value": 16.4,
        "meet_date": "2026-06-14",
        "meet_level": "STATE",
        "sanctioned": True,
    }

    first = validate_success(
        api_client.create_qualifying_result(body, OFFICER), expected_status=201
    )
    second = validate_success(
        api_client.create_qualifying_result({**body, "mark_value": 16.1}, OFFICER),
        expected_status=201,
    )

    assert_immutable_row_properties(first)
    assert "updated_at" not in first
    assert "version" not in first
    assert second["id"] != first["id"]
    assert validate_success(
        api_client.get_qualifying_result(first["id"], OFFICER)
    )["mark_value"] == 16.4
    _rows, meta = validate_paginated(
        api_client.list_qualifying_results(OFFICER, {"athlete_id": athlete["id"], "limit": 10})
    )
    assert meta["total_count"] == 2


def test_a_body_foreign_key_that_names_no_row_answers_that_resource_s_own_404():
    """PRD §2.6: "Foreign-key identifiers supplied in a request body are resolved after all
    path identifiers, and among themselves they are resolved in the order the endpoint
    declares its input fields — not in alphabetical order and not in whatever order a
    map happens to iterate."
    PRD §2.6: "A body foreign key that does not resolve yields the same dedicated 404
    error as its path counterpart; `submitted_by_personnel_id` resolves against
    `Personnel` and therefore answers `ERR_PERSONNEL_NOT_FOUND`."
    PRD §2.10: "Every foreign-key identifier in the request body resolves, in the order
    the endpoint declares its inputs — otherwise the matching not-found error."

    Each unresolved body reference answers with the dedicated not-found error of
    the resource it points at, and it is answered before any state gate on the
    resolvable half of the payload.  With both references good, the create succeeds.

    Design: Corner/entities/corner_entity_parent_sport_event_unknown_sport_id_not_found
    """
    edition = create_edition()
    sport = create_sport()

    unknown_sport = api_client.create_sport_event(
        sport_event_payload(NON_EXISTENT_UUID, edition["id"]), ADMIN
    )
    unknown_edition = api_client.create_sport_event(
        sport_event_payload(sport["id"], NON_EXISTENT_UUID), ADMIN
    )
    good = api_client.create_sport_event(
        sport_event_payload(sport["id"], edition["id"]), ADMIN
    )

    validate_error(
        unknown_sport, ApiErrorId.ERR_SPORT_NOT_FOUND.value, expected_status=404
    )
    validate_error(
        unknown_edition, ApiErrorId.ERR_GAMES_EDITION_NOT_FOUND.value, expected_status=404
    )
    event = validate_success(good, expected_status=201)
    assert event["games_edition_id"] == edition["id"]
    assert event["sport_id"] == sport["id"]
    _rows, meta = validate_paginated(api_client.list_sport_events(ADMIN, {"limit": 10}))
    assert meta["total_count"] == 1


def test_the_entry_row_is_reachable_from_the_athlete_side_and_the_event_side():
    """PRD §2.6: "A session slot names its `venue_id` and its `sport_event_id`; a sport
    entry names its `athlete_id` and its `sport_event_id`; a competition result names
    its `sport_entry_id`, its `session_slot_id` and its `submitted_by_personnel_id`; an
    age-group record names its `sport_event_id` and its `competition_result_id` and
    derives `holder_athlete_id` and `superseded_record_id`; a village stay names its
    `athlete_id` and its `accommodation_block_id`; and editions own their venues,
    athletes, personnel, accommodation blocks and sponsorship commitments through
    `games_edition_id`."
    PRD §3.3: "It is filed by the `Athlete` themselves or by a `RegistrationOfficer` and
    names the `athlete_id`, the `sport_event_id`, and a `qualification_source` of
    `STATE_QUALIFIER`, `LOCAL_QUALIFIER`, `AGE_EXEMPT` or `ORGANIZER_INVITE`, with
    `qualifying_result_id` supplied only when a qualifying mark is being cited."
    PRD §3.3: "Entries begin `SUBMITTED` with `revision_round` at 0 and `review_note`
    null, and two fields are derived on the spot."
    PRD §3.3: "`ACCEPT` moves it `UNDER_REVIEW` → `ACCEPTED`, and is the transition that
    consumes capacity: it requires the athlete's `registration_status` to be
    `REGISTERED` — otherwise `ERR_ATHLETE_NOT_REGISTERED` — the athlete's
    `medical_status` to be one of `SCREENED_CLEARED`, `SCREENED_RESTRICTED` or
    `CLEARED_BY_APPEAL`, the event's `available_slots` to be greater than zero —
    otherwise `ERR_EVENT_CAPACITY_FULL` — and the athlete's already-scheduled
    competition blocks to still satisfy the recovery-gap rule described in §3.5."

    An entry joins one athlete to one event, and both fan-outs coexist: one
    athlete on two events, one event holding two athletes.  Filtering the list from
    either parent finds the shared row, and none of the three consumes capacity
    while it is still merely submitted.

    Design: Corner/entities/corner_entity_graph_topology_sport_entry_junction_traversable_from_both_parents
    """
    ctx = setup_open_edition()
    edition_id = ctx["edition"]["id"]
    second_event = create_sport_event(
        ctx["sport"]["id"], edition_id, event_code="T200M", capacity=8,
        min_entries_to_stage=1,
    )
    first = create_athlete(edition_id, full_name="Ada Fenn")
    second = create_athlete(edition_id, full_name="Bo Marsh")
    entry_1a = validate_success(
        api_client.create_sport_entry(
            {
                "athlete_id": first["id"],
                "sport_event_id": ctx["event"]["id"],
                "qualification_source": "ORGANIZER_INVITE",
            },
            OFFICER,
        ),
        expected_status=201,
    )
    entry_1b = validate_success(
        api_client.create_sport_entry(
            {
                "athlete_id": first["id"],
                "sport_event_id": second_event["id"],
                "qualification_source": "ORGANIZER_INVITE",
            },
            OFFICER,
        ),
        expected_status=201,
    )
    entry_2a = validate_success(
        api_client.create_sport_entry(
            {
                "athlete_id": second["id"],
                "sport_event_id": ctx["event"]["id"],
                "qualification_source": "ORGANIZER_INVITE",
            },
            OFFICER,
        ),
        expected_status=201,
    )

    by_athlete, athlete_meta = validate_paginated(
        api_client.list_sport_entries(OFFICER, {"athlete_id": first["id"], "limit": 10})
    )
    by_event, event_meta = validate_paginated(
        api_client.list_sport_entries(
            OFFICER, {"sport_event_id": ctx["event"]["id"], "limit": 10}
        )
    )

    assert len({entry_1a["id"], entry_1b["id"], entry_2a["id"]}) == 3
    assert athlete_meta["total_count"] == 2
    assert {row["id"] for row in by_athlete} == {entry_1a["id"], entry_1b["id"]}
    assert event_meta["total_count"] == 2
    assert {row["id"] for row in by_event} == {entry_1a["id"], entry_2a["id"]}
    assert all(row["status"] == "SUBMITTED" for row in by_athlete + by_event)
    assert validate_success(
        api_client.get_sport_event(ctx["event"]["id"], ADMIN)
    )["accepted_entry_count"] == 0
