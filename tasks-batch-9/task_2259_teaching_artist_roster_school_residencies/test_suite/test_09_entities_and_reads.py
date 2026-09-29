"""What a create echoes back, which values the server supplies when the client
stays silent, and how a parent scopes the rows read underneath it."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    OBSERVER_USER_ID,
    PANELIST_1_USER_ID,
    PANELIST_2_USER_ID,
    SCREENING_TYPES,
    TEST_USERS,
    add_blackout,
    advance_vetting,
    api_client,
    assert_append_only_fields,
    assert_envelope_meta,
    attach_observation_rubric,
    attach_teacher_survey,
    create_artist_applicant,
    create_calendar_blackout_payload,
    create_delivered_session,
    create_residency_for_school,
    create_residency_payload,
    create_school,
    create_school_partner_payload,
    create_session_payload,
    create_teaching_artist_payload,
    open_funder_report,
    open_voucher,
    read_artist,
    read_residency,
    read_school,
    record_portfolio_review,
    set_clock_to_default,
    setup_active_residency,
    setup_second_artist,
    submit_lesson_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
RC = TEST_USERS["roster_coordinator_headers"]


# ==========================================================================
# What a creation and a read hand back
# ==========================================================================
def test_registering_a_school_returns_the_created_row_in_the_success_envelope(api):
    """PRD §4: "Creating a new resource returns HTTP 201 with the created object
    in `data`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §3.3: "A newly registered school starts with `partnership_health` of
    `HEALTHY` and `open_residency_count` of zero."

    Design: Corner/Entities/school_partner_creation_returns_envelope_and_all_fields
    """
    set_clock_to_default()

    res = api_client.create_school_partner(create_school_partner_payload(), PD)
    data = validate_success(res, expected_status=201)
    body = res.json()
    assert_envelope_meta(body)
    assert body["response_type"] == "object", (
        f"one school partner is a single resource, got {body['response_type']}"
    )

    assert data["partnership_health"] == "HEALTHY", (
        f"a school with no residencies yet is healthy, got "
        f"{data['partnership_health']}"
    )
    assert data["open_residency_count"] == 0, (
        f"no residency has been scoped at this school, got "
        f"{data['open_residency_count']}"
    )

    # The registration payload is echoed back field for field.
    assert data["name"] == "Riverbend Arts Academy"
    assert data["district_name"] == "Riverbend USD"
    assert data["grade_span"] == "K-8"
    assert data["concurrent_session_capacity"] == 2
    assert data["total_enrollment"] == 600
    assert data["frl_pct"] == 0.62
    assert data["ell_pct"] == 0.28
    assert data["iep_pct"] == 0.14


def test_reading_an_applicant_returns_the_capability_tags_and_both_initial_axes(api):
    """PRD §4: "Reads and operations that modify an existing resource return HTTP
    200 with the affected object in `data`; the clock-control capability returns
    HTTP 200 with an empty `data` object."
    PRD §3.1: "Capability is three-dimensional: a `primary_discipline` drawn from
    `VISUAL_ARTS`, `DANCE`, `MUSIC`, `THEATER`, `MEDIA_ARTS`, and
    `LITERARY_ARTS`; an optional `secondary_disciplines` array drawn from the
    same six values and defaulting to empty; a non-empty `grade_bands` array
    whose elements come from `K_2`, `G3_5`, `G6_8`, and `G9_12`; and a non-empty
    `languages` array of lowercase two-letter ISO 639-1 codes, which must contain
    `en` or the instruction language of any residency the artist is later
    assigned to."
    PRD §3.1: "The recruitment axis, `vetting_status`, starts at `APPLIED` and
    ranges over `APPLIED`, `PORTFOLIO_REVIEW`, `DEMO_SCHEDULED`, `DEMO_FAILED`,
    `DEMO_PASSED`, `SCREENING_PENDING`, `CLEARED`, `DECLINED`, and
    `SCREEN_FAILED`, of which `DECLINED` and `SCREEN_FAILED` are terminal."
    PRD §3.1: "The assignability axis, `roster_status`, starts at `NOT_LISTED`
    and ranges over `NOT_LISTED`, `ACTIVE`, `PROBATION`, `SUSPENDED`, and
    `RETIRED`, of which `RETIRED` is terminal."

    Design: Corner/Entities/teaching_artist_retrieval_returns_stored_row
    """
    set_clock_to_default()
    created = create_artist_applicant(
        secondary_disciplines=["THEATER"],
        grade_bands=["G3_5", "G6_8"],
        languages=["en", "es"],
    )

    data = validate_success(
        api_client.get_teaching_artist(created["id"], PD), expected_status=200
    )
    assert data["id"] == created["id"]
    assert data["vetting_status"] == "APPLIED", (
        f"no vetting step has been taken yet, got {data['vetting_status']}"
    )
    assert data["roster_status"] == "NOT_LISTED", (
        f"an applicant is not assignable yet, got {data['roster_status']}"
    )
    assert data["primary_discipline"] == "DANCE"
    # The PRD fixes the membership of the capability arrays, not their order.
    assert sorted(data["secondary_disciplines"]) == ["THEATER"]
    assert sorted(data["grade_bands"]) == ["G3_5", "G6_8"]
    assert sorted(data["languages"]) == ["en", "es"]


def test_artist_intake_seeds_both_axes_and_the_reliability_figures(api):
    """PRD §3.1: "The recruitment axis, `vetting_status`, starts at `APPLIED` and
    ranges over `APPLIED`, `PORTFOLIO_REVIEW`, `DEMO_SCHEDULED`, `DEMO_FAILED`,
    `DEMO_PASSED`, `SCREENING_PENDING`, `CLEARED`, `DECLINED`, and
    `SCREEN_FAILED`, of which `DECLINED` and `SCREEN_FAILED` are terminal."
    PRD §3.1: "The assignability axis, `roster_status`, starts at `NOT_LISTED`
    and ranges over `NOT_LISTED`, `ACTIVE`, `PROBATION`, `SUSPENDED`, and
    `RETIRED`, of which `RETIRED` is terminal."
    PRD §3.1: "At intake the new row also gets `roster_tier_effective` equal to
    `roster_tier_assigned`, and both reliability figures —
    `reliability_bps_rolling` and `reliability_bps_program_year` — seeded at
    10000 basis points."
    PRD §3.1: "Every other derived field starts empty rather than at a guessed
    value: `portfolio_review_count`, `demo_attempt_count`,
    `lifetime_delivered_count` and `no_show_count` all begin at zero;
    `portfolio_mean_composite`, `demo_rubric_score`, `demo_evaluator_user_id` and
    `clearance_expires_on` all begin null; and `clearance_status` begins at
    `NONE`."

    Design: Corner/Entities/artist_intake_seeds_system_fields_from_the_state_machines
    """
    set_clock_to_default()

    data = validate_success(
        api_client.create_teaching_artist(
            create_teaching_artist_payload(roster_tier_assigned="MASTER"), RC
        ),
        expected_status=201,
    )

    assert data["vetting_status"] == "APPLIED", (
        f"the recruitment axis always opens at APPLIED, got "
        f"{data['vetting_status']}"
    )
    assert data["roster_status"] == "NOT_LISTED", (
        f"the assignability axis always opens at NOT_LISTED, got "
        f"{data['roster_status']}"
    )
    assert data["roster_tier_effective"] == "MASTER", (
        "the effective tier starts equal to the juried assigned tier, got "
        f"{data['roster_tier_effective']}"
    )
    assert data["reliability_bps_rolling"] == 10000, (
        "an artist with no terminal sessions is seeded at a perfect 10000 bps, "
        f"got {data['reliability_bps_rolling']}"
    )
    assert data["reliability_bps_program_year"] == 10000, (
        "both reliability variants are seeded alike, got "
        f"{data['reliability_bps_program_year']}"
    )
    for counter in (
        "portfolio_review_count",
        "demo_attempt_count",
        "lifetime_delivered_count",
        "no_show_count",
    ):
        assert data[counter] == 0, f"{counter} begins at zero, got {data[counter]}"
    for empty in (
        "portfolio_mean_composite",
        "demo_rubric_score",
        "demo_evaluator_user_id",
        "clearance_expires_on",
    ):
        assert data[empty] is None, f"{empty} begins null, got {data[empty]}"
    assert data["clearance_status"] == "NONE", (
        f"no screening is on file yet, got {data['clearance_status']}"
    )


def test_omitted_residency_options_take_their_declared_defaults(api):
    """PRD §3.4: "The payload names the host school through `school_partner_id`,
    gives the residency a `title`, and fixes the artistic and instructional
    frame: a `discipline` from the same six-value domain as artist disciplines, a
    `grade_band` from `K_2`, `G3_5`, `G6_8`, or `G9_12`, and an
    `instruction_language` as a lowercase two-letter code that defaults to `en`."
    PRD §3.4: "It fixes the money with a `budget_cents` of at least 1 and an
    optional `materials_stipend_cents` earmark that defaults to zero and is
    informational only — actual per-session materials reimbursement is capped
    independently, as §3.7 explains."
    PRD §3.4: "It fixes the collaboration frame with a
    `collaboration_expectation` of `CO_TEACH`, `OBSERVE`, or `PLANNING_ONLY` and
    an optional `co_planning_hours_required` between 0 and 20 hours that the
    classroom teacher owes across the residency, defaulting to zero."
    PRD §3.4: "A freshly scoped residency has a `status` of `DRAFT`, a
    `staffing_status` of `LEAD_VACANT`, and every ledger counter and money field
    at zero."

    Design: Corner/Entities/residency_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock_to_default()
    school = create_school()

    payload = create_residency_payload(school["id"])
    for optional in (
        "instruction_language",
        "materials_stipend_cents",
        "co_planning_hours_required",
    ):
        payload.pop(optional)
    data = validate_success(
        api_client.create_residency(payload, PD), expected_status=201
    )

    assert data["instruction_language"] == "en", (
        f"the instruction language defaults to en, got "
        f"{data['instruction_language']}"
    )
    assert data["materials_stipend_cents"] == 0, (
        f"the materials earmark defaults to zero, got "
        f"{data['materials_stipend_cents']}"
    )
    assert data["co_planning_hours_required"] == 0, (
        f"the co-planning obligation defaults to zero hours, got "
        f"{data['co_planning_hours_required']}"
    )
    assert data["status"] == "DRAFT"
    assert data["staffing_status"] == "LEAD_VACANT", (
        f"no lead artist has been nominated, got {data['staffing_status']}"
    )
    assert data["sessions_unscheduled_count"] == 0, (
        "the allotment is only initialized at approval, got "
        f"{data['sessions_unscheduled_count']}"
    )
    assert data["available_cents"] == 0, (
        f"the money ledger opens at zero before approval, got "
        f"{data['available_cents']}"
    )


def test_portfolio_composites_and_the_artist_mean_are_derived_per_review(api):
    """PRD §3.1: "The panel weights artistic quality at forty percent (a factor
    of 0.40), pedagogical clarity at thirty-five percent (0.35), and cultural
    responsiveness at twenty-five percent (0.25): the review's `composite_score`
    is the sum of each score multiplied by its weight, rounded half up to two
    decimal places."
    PRD §3.1: "That composite yields a `recommendation` of `ADVANCE` when it is
    at least 3.50, and `DECLINE` otherwise."
    PRD §3.1: "`portfolio_review_count` is the number of distinct
    `reviewer_user_id` values that have scored this artist, and
    `portfolio_mean_composite` is the arithmetic mean of `composite_score` across
    **all** of the artist's reviews, rounded half up to two decimal places; the
    mean is null while the artist has no reviews at all."

    Design: Corner/Entities/portfolio_review_computed_fields_and_artist_rollup
    """
    set_clock_to_default()
    artist = create_artist_applicant()
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")
    assert read_artist(artist["id"])["portfolio_mean_composite"] is None, (
        "the mean stays null until a panelist scores the file"
    )

    first = record_portfolio_review(artist["id"], PANELIST_1_USER_ID, 3.5, 4.0, 3.2)
    assert first["composite_score"] == 3.60, (
        "3.5 at 0.40 plus 4.0 at 0.35 plus 3.2 at 0.25 is 3.60, got "
        f"{first['composite_score']}"
    )
    assert first["recommendation"] == "ADVANCE", (
        f"3.60 clears the 3.50 threshold, got {first['recommendation']}"
    )

    second = record_portfolio_review(artist["id"], PANELIST_2_USER_ID, 3.4, 3.4, 3.4)
    assert second["composite_score"] == 3.40, (
        "a flat 3.4 across all three weighted scores is 3.40, got "
        f"{second['composite_score']}"
    )
    assert second["recommendation"] == "DECLINE", (
        f"3.40 falls short of the 3.50 threshold, got {second['recommendation']}"
    )

    rolled_up = read_artist(artist["id"])
    assert rolled_up["portfolio_review_count"] == 2, (
        f"two distinct panelists have scored the file, got "
        f"{rolled_up['portfolio_review_count']}"
    )
    assert rolled_up["portfolio_mean_composite"] == 3.50, (
        "the mean spans both reviews — (3.60 + 3.40) / 2 — rather than copying "
        f"the latest, got {rolled_up['portfolio_mean_composite']}"
    )


# ==========================================================================
# Filtering and paging a collection
# ==========================================================================
def _three_applicants_two_of_them_dance() -> dict:
    """Two DANCE applicants and one MUSIC applicant on an otherwise empty roster."""
    set_clock_to_default()
    ana = create_artist_applicant(
        full_name="Ana Reyes",
        email="ana.reyes@arts.org",
        primary_discipline="DANCE",
        secondary_disciplines=[],
    )
    bo = create_artist_applicant(
        full_name="Bo Halvorsen",
        email="bo.halvorsen@arts.org",
        primary_discipline="DANCE",
        secondary_disciplines=[],
    )
    cai = create_artist_applicant(
        full_name="Cai Moreno",
        email="cai.moreno@arts.org",
        primary_discipline="MUSIC",
        secondary_disciplines=[],
    )
    return {"dance": [ana["id"], bo["id"]], "music": cai["id"]}


def test_the_discipline_filter_narrows_the_roster_before_pagination_splits_it(api):
    """PRD §3.1: "The roster is searchable by capability and lifecycle state: a
    `discipline`, `grade_band`, `language`, `vetting_status`, or `roster_status`
    filter may be supplied, alone or in combination."
    PRD §2.3: "`limit` caps the number of records returned; it defaults to 10,
    may not be smaller than 1, and may not be larger than 100."
    PRD §2.3: "`offset` skips a number of leading records and defaults to 0."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/Entities/roster_listing_filters_by_discipline_then_paginates
    """
    roster = _three_applicants_two_of_them_dance()

    first_rows, first_meta = validate_paginated(
        api_client.list_teaching_artists(
            PD, params={"discipline": "DANCE", "limit": 1, "offset": 0}
        )
    )
    assert first_meta["total_count"] == 2, (
        "the discipline filter selects the record set the page is cut from, so "
        f"the MUSIC applicant is not counted, got {first_meta['total_count']}"
    )
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True, (
        "one of the two matching artists is still unread, got "
        f"{first_meta['has_more']}"
    )
    assert len(first_rows) == 1, f"limit 1 returns one row, got {len(first_rows)}"

    second_rows, second_meta = validate_paginated(
        api_client.list_teaching_artists(
            PD, params={"discipline": "DANCE", "limit": 1, "offset": 1}
        )
    )
    assert second_meta["total_count"] == 2, (
        f"the filtered set does not change size between pages, got "
        f"{second_meta['total_count']}"
    )
    assert second_meta["offset"] == 1
    assert second_meta["has_more"] is False, (
        "the second page exhausts the two matching artists, got "
        f"{second_meta['has_more']}"
    )
    assert len(second_rows) == 1

    paged_ids = [first_rows[0]["id"], second_rows[0]["id"]]
    assert paged_ids[0] != paged_ids[1], (
        "the offset must move the window rather than repeat a row, got "
        f"{paged_ids}"
    )
    assert sorted(paged_ids) == sorted(roster["dance"]), (
        f"the two pages together hold exactly the DANCE applicants, got "
        f"{paged_ids}"
    )
    assert roster["music"] not in paged_ids, (
        "the MUSIC applicant must not leak onto either page"
    )


# ==========================================================================
# Unresolved identifiers, in the path and in the body
# ==========================================================================
def test_reading_a_residency_that_does_not_exist_names_the_residency_type(api):
    """PRD §2.8: "For any request whose path contains identifiers, the server
    resolves them strictly left to right and rejects on the **first** identifier
    that does not resolve, before evaluating anything else about the request."
    PRD §2.8: "The not-found code always names the entity type of the unresolved
    identifier: `ERR_SCHOOL_PARTNER_NOT_FOUND`, `ERR_TEACHING_ARTIST_NOT_FOUND`,
    `ERR_RESIDENCY_NOT_FOUND`, `ERR_LESSON_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, or
    `ERR_FUNDER_REPORT_NOT_FOUND`."
    PRD §2.9: "3. Path identifiers resolve, left to right — the entity-specific
    not-found codes."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/Entities/residency_get_with_unknown_id_returns_not_found
    """
    set_clock_to_default()

    res = api_client.get_residency(NON_EXISTENT_UUID, PD)
    validate_error(
        res, ApiErrorId.ERR_RESIDENCY_NOT_FOUND.value, expected_status=404
    )
    body = res.json()
    assert_envelope_meta(body)
    assert sorted(body["meta"].keys()) == [
        "api_request_id",
        "api_request_timestamp",
    ], f"a refusal carries no pagination fields, got {sorted(body['meta'].keys())}"


def test_adding_a_blackout_under_an_unknown_school_names_the_school_type(api):
    """PRD §2.8: "For any request whose path contains identifiers, the server
    resolves them strictly left to right and rejects on the **first** identifier
    that does not resolve, before evaluating anything else about the request."
    PRD §2.8: "The not-found code always names the entity type of the unresolved
    identifier: `ERR_SCHOOL_PARTNER_NOT_FOUND`, `ERR_TEACHING_ARTIST_NOT_FOUND`,
    `ERR_RESIDENCY_NOT_FOUND`, `ERR_LESSON_PLAN_NOT_FOUND`,
    `ERR_SESSION_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, or
    `ERR_FUNDER_REPORT_NOT_FOUND`."
    PRD §2.9: "3. Path identifiers resolve, left to right — the entity-specific
    not-found codes."

    Design: Corner/Entities/calendar_blackout_requires_an_existing_parent_school
    """
    set_clock_to_default()
    school = create_school()

    res = api_client.create_calendar_blackout(
        NON_EXISTENT_UUID,
        create_calendar_blackout_payload(
            blackout_type="HOLIDAY", start_date="2026-11-25", end_date="2026-11-27"
        ),
        RC,
    )
    validate_error(
        res, ApiErrorId.ERR_SCHOOL_PARTNER_NOT_FOUND.value, expected_status=404
    )

    rows, meta = validate_paginated(
        api_client.list_calendar_blackouts(school["id"], PD)
    )
    assert meta["total_count"] == 0, (
        "the window addressed to an unknown school must not land on the real "
        f"school's calendar, got {meta['total_count']}"
    )
    assert rows == []


def test_scheduling_a_session_for_an_unknown_artist_is_refused_before_the_ledger(api):
    """PRD §2.8: "Identifiers supplied in a request **body** are resolved in the
    same style and with the same codes, once path resolution has succeeded and
    the payload has passed type and range checking."
    PRD §2.8: "This covers `school_partner_id`, `lead_artist_id` and
    `teaching_artist_id`, `residency_id`, `lesson_plan_id`, `assigned_artist_id`,
    `substitute_artist_id`, `makeup_for_session_id`, every element of
    `session_ids`, and every element of `scope_residency_ids`."
    PRD §2.9: "5. Body-supplied identifiers resolve, and every standards code
    resolves — the entity-specific not-found codes, or
    `ERR_UNKNOWN_STANDARD_CODE`."
    PRD §2.9: "Checks are therefore evaluated in a fixed global order, and the
    **first** violated check decides the response."

    Design: Corner/Entities/session_body_reference_to_unknown_artist_is_rejected
    """
    set_clock_to_default()
    school = create_school()
    residency = create_residency_for_school(school["id"])

    # The residency is still DRAFT and holds no allotment, so a resolvable
    # artist would have run into the allotment guard instead.
    version = read_residency(residency["id"])["version"]
    payload = create_session_payload(
        residency["id"], NON_EXISTENT_UUID, version, session_date="2026-09-15"
    )
    validate_error(
        api_client.create_session(payload, RC),
        ApiErrorId.ERR_TEACHING_ARTIST_NOT_FOUND.value,
        expected_status=404,
    )

    after = read_residency(residency["id"])
    assert after["sessions_open_count"] == 0, (
        f"the refused request opened no session, got {after['sessions_open_count']}"
    )
    assert after["sessions_unscheduled_count"] == 0
    assert after["version"] == version, (
        f"a refusal mutates no row, got version {after['version']}"
    )


def test_scheduling_a_session_without_an_end_time_fails_the_shape_check(api):
    """PRD §3.6: "The payload names the `residency_id` and the
    `assigned_artist_id`, fixes the `session_date` as an ISO 8601 calendar date,
    fixes the local time window with a `start_time` and `end_time` in 24-hour
    `HH:MM` form where the start must be a multiple of 5 minutes and the end must
    be strictly after the start, and carries the `expected_residency_version`
    described in §2.6."
    PRD §2.9: "4. Required body fields are present, and every supplied value
    satisfies its declared type, enum domain, numeric range, date or time format,
    and array constraints including non-emptiness and absence of duplicates —
    `ERR_INVALID_REQUEST`."
    PRD §2.9: "Checks are therefore evaluated in a fixed global order, and the
    **first** violated check decides the response."
    PRD §3.4: "A freshly scoped residency has a `status` of `DRAFT`, a
    `staffing_status` of `LEAD_VACANT`, and every ledger counter and money field
    at zero."

    Design: Corner/Entities/session_create_without_end_time_returns_invalid_request
    """
    set_clock_to_default()
    school = create_school()
    # An applicant artist who is nowhere near cleared, so the clearance and
    # allotment guards would both bite if the shape check ever let the request by.
    artist = create_artist_applicant()
    residency = create_residency_for_school(school["id"])

    version = read_residency(residency["id"])["version"]
    payload = create_session_payload(
        residency["id"], artist["id"], version, session_date="2026-09-15"
    )
    payload.pop("end_time")
    validate_error(
        api_client.create_session(payload, RC),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    after = read_residency(residency["id"])
    assert after["sessions_open_count"] == 0, (
        f"no session row was written, got {after['sessions_open_count']}"
    )
    assert after["version"] == version, (
        f"a refusal mutates no row, got version {after['version']}"
    )


def test_a_bad_grade_band_and_a_reversed_term_are_both_shape_failures(api):
    """PRD §2.9: "4. Required body fields are present, and every supplied value
    satisfies its declared type, enum domain, numeric range, date or time format,
    and array constraints including non-emptiness and absence of duplicates —
    `ERR_INVALID_REQUEST`."
    PRD §3.4: "The payload names the host school through `school_partner_id`,
    gives the residency a `title`, and fixes the artistic and instructional
    frame: a `discipline` from the same six-value domain as artist disciplines, a
    `grade_band` from `K_2`, `G3_5`, `G6_8`, or `G9_12`, and an
    `instruction_language` as a lowercase two-letter code that defaults to `en`."
    PRD §3.4: "It fixes the calendar with a `term_start_date` and a
    `term_end_date` no earlier than the start, both inclusive bounds on session
    dates."
    PRD §3.3: "A newly registered school starts with `partnership_health` of
    `HEALTHY` and `open_residency_count` of zero."

    Design: Corner/Entities/residency_type_constraints_reject_bad_enum_and_reversed_term
    """
    set_clock_to_default()
    school = create_school()

    out_of_domain_band = create_residency_payload(
        school["id"], title="Bad Band", grade_band="G13"
    )
    validate_error(
        api_client.create_residency(out_of_domain_band, PD),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    reversed_term = create_residency_payload(
        school["id"],
        title="Bad Term",
        term_start_date="2026-12-18",
        term_end_date="2026-09-08",
    )
    validate_error(
        api_client.create_residency(reversed_term, PD),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=400,
    )

    assert read_school(school["id"])["open_residency_count"] == 0, (
        "neither malformed payload reached the residency table"
    )


# ==========================================================================
# The school calendar: append-only windows hanging off their school
# ==========================================================================
def test_a_blackout_window_carries_no_version_and_takes_its_school_from_the_path(api):
    """PRD §2.4: "Four record types are append-only observations rather than
    living resources, and they carry only `id` and `created_at` — both
    `updated_at` and `version` are absent from them: calendar blackout windows,
    portfolio reviews, background screenings, and evaluation records."
    PRD §2.8: "When a child record is created under a parent path, the parent
    link is taken from the path and never from the body."
    PRD §2.8: "A blackout window's `school_partner_id`, a portfolio review's and
    a screening's `teaching_artist_id`, and an evaluation record's `session_id`
    are all set this way."
    PRD §3.3: "A `RosterCoordinator` or the school's own `SchoolLiaison` adds a
    window with a `blackout_type` of `HOLIDAY`, `TESTING_WINDOW`,
    `PROFESSIONAL_DEVELOPMENT`, or `CLOSURE`, a `start_date`, an `end_date` no
    earlier than the start, and an optional free-text `note` that defaults to
    null."

    Design: Corner/Entities/calendar_blackout_is_immutable_and_carries_no_version
    """
    set_clock_to_default()
    school = create_school()

    recess = add_blackout(
        school["id"],
        blackout_type="HOLIDAY",
        start_date="2026-11-25",
        end_date="2026-11-27",
    )
    assert_append_only_fields(recess)
    assert recess["school_partner_id"] == school["id"], (
        "the parent school comes from the path, got "
        f"{recess['school_partner_id']}"
    )
    assert recess["blackout_type"] == "HOLIDAY"
    assert recess["start_date"] == "2026-11-25"
    assert recess["end_date"] == "2026-11-27"
    assert recess["note"] is None, (
        f"an unsupplied note defaults to null, got {recess['note']}"
    )

    # With no update or delete capability, correcting the calendar means adding
    # a further window rather than editing this one.
    testing = add_blackout(
        school["id"],
        blackout_type="TESTING_WINDOW",
        start_date="2026-12-07",
        end_date="2026-12-11",
    )
    rows, meta = validate_paginated(
        api_client.list_calendar_blackouts(school["id"], PD)
    )
    assert meta["total_count"] == 2, (
        f"both windows sit on this school's calendar, got {meta['total_count']}"
    )
    assert sorted(row["id"] for row in rows) == sorted([recess["id"], testing["id"]])
    for row in rows:
        assert_append_only_fields(row)
        assert row["school_partner_id"] == school["id"]


# ==========================================================================
# Reading children under their parent, and filtering the top-level collections
# ==========================================================================
def _two_vetted_artists_and_one_evaluated_delivery() -> dict:
    """A vetted artist with a panel and screenings on file, a second vetted
    artist beside her, and one delivered session carrying two kinds of evidence."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["second_artist"] = setup_second_artist()
    session = create_delivered_session(
        scenario, session_date="2026-09-15", students_present_count=22
    )
    attach_observation_rubric(session["id"], OBSERVER_USER_ID, 4, 3, 4)
    attach_teacher_survey(
        session["id"],
        scenario["school"]["id"],
        evaluator_user_id="teacher-delgado",
        teacher_survey_score=5,
    )
    scenario["session"] = session
    return scenario


def test_artist_and_session_sub_collections_return_only_their_own_parents_rows(api):
    """PRD §3.1: "An artist's screenings and portfolio reviews are each listable
    under the artist."
    PRD §2.10: "Three screening types are required for a complete clearance set:
    `STATE_CRIMINAL`, `FBI_FINGERPRINT`, and `CHILD_ABUSE_REGISTRY`."
    PRD §3.9: "Evaluations of a session are listable under it, optionally
    filtered by `evaluation_type`."
    PRD §3.9: "For an observation rubric the server derives `rubric_composite` as
    the three rubric scores added together, divided by three, rounded half up to
    two decimal places; for the other two types `rubric_composite` stays null."

    Design: Corner/Entities/every_sub_collection_and_filtered_list_read_is_scoped_to_its_parent
    """
    scenario = _two_vetted_artists_and_one_evaluated_delivery()
    artist_id = scenario["artist"]["id"]
    assert scenario["second_artist"]["id"] != artist_id, (
        "a second vetted artist supplies the sibling rows that must not leak"
    )

    reviews, reviews_meta = validate_paginated(
        api_client.list_portfolio_reviews(artist_id, PD)
    )
    assert reviews_meta["total_count"] == 2, (
        "only the two panelists who scored this artist are listed under her, "
        f"got {reviews_meta['total_count']}"
    )
    assert sorted(row["reviewer_user_id"] for row in reviews) == sorted(
        [PANELIST_1_USER_ID, PANELIST_2_USER_ID]
    )
    for row in reviews:
        assert row["teaching_artist_id"] == artist_id

    screenings, screenings_meta = validate_paginated(
        api_client.list_screenings(artist_id, PD)
    )
    assert screenings_meta["total_count"] == 3, (
        "one screening per required type belongs to this artist, got "
        f"{screenings_meta['total_count']}"
    )
    assert sorted(row["screening_type"] for row in screenings) == sorted(
        SCREENING_TYPES
    )
    for row in screenings:
        assert row["teaching_artist_id"] == artist_id

    rubrics, rubrics_meta = validate_paginated(
        api_client.list_evaluations(
            scenario["session"]["id"], PD,
            params={"evaluation_type": "OBSERVATION_RUBRIC"},
        )
    )
    assert rubrics_meta["total_count"] == 1, (
        "the teacher survey shares the parent session but not the requested "
        f"type, got {rubrics_meta['total_count']}"
    )
    assert rubrics[0]["evaluation_type"] == "OBSERVATION_RUBRIC"
    assert rubrics[0]["session_id"] == scenario["session"]["id"]
    assert rubrics[0]["rubric_composite"] == 3.67, (
        "scores of 4, 3 and 4 sum to 11, and 11 divided by 3 rounds half up to "
        f"3.67, got {rubrics[0]['rubric_composite']}"
    )


def _one_claimed_delivery_beside_rows_the_filters_must_exclude() -> dict:
    """An active residency whose single delivery is claimed by a draft voucher
    and scoped by a draft funder report, alongside a draft residency, an
    unaligned plan and a report on another grant."""
    set_clock_to_default()
    scenario = setup_active_residency()
    session = create_delivered_session(
        scenario, session_date="2026-09-15", students_present_count=22
    )
    attach_observation_rubric(session["id"], OBSERVER_USER_ID, 4, 3, 4)
    scenario["session"] = session
    scenario["voucher"] = open_voucher(
        scenario["artist"]["id"], scenario["residency"]["id"], [session["id"]]
    )
    scenario["report"] = open_funder_report(
        [scenario["residency"]["id"]], grant_code="CAT-2026-14"
    )
    scenario["other_plan"] = submit_lesson_plan(
        scenario["residency"]["id"],
        [standard["code"] for standard in scenario["standards"].values()],
        2,
        title="Story in Motion, Week Two",
    )
    scenario["other_report"] = open_funder_report(
        [scenario["residency"]["id"]], grant_code="CAT-2099-01"
    )
    scenario["other_residency"] = create_residency_for_school(
        scenario["school"]["id"], title="Rhythm Lab"
    )
    return scenario


def test_the_four_top_level_collections_honour_their_declared_filters(api):
    """PRD §3.4: "Residencies are listable with `school_partner_id`,
    `lead_artist_id`, `status`, and `staffing_status` filters."
    PRD §3.5: "Plans are listable with `residency_id`, `author_artist_id`, and
    `status` filters, and a plan read exposes `reviewer_note`,
    `reviewer_user_id`, and `aligned_on` alongside its coverage."
    PRD §3.8: "Vouchers are listable with `teaching_artist_id`, `residency_id`,
    `session_ids`, and `status` filters."
    PRD §3.9: "Reports are listable with `grant_code`, `status`, and
    `scope_residency_ids` filters."

    Design: Corner/Entities/every_sub_collection_and_filtered_list_read_is_scoped_to_its_parent
    """
    scenario = _one_claimed_delivery_beside_rows_the_filters_must_exclude()
    residency_id = scenario["residency"]["id"]

    residencies, residencies_meta = validate_paginated(
        api_client.list_residencies(
            PD,
            params={
                "school_partner_id": scenario["school"]["id"],
                "status": "ACTIVE",
            },
        )
    )
    assert residencies_meta["total_count"] == 1, (
        "the second residency at this school is still DRAFT, got "
        f"{residencies_meta['total_count']}"
    )
    assert residencies[0]["id"] == residency_id
    assert scenario["other_residency"]["status"] == "DRAFT"

    plans, plans_meta = validate_paginated(
        api_client.list_lesson_plans(
            PD, params={"residency_id": residency_id, "status": "ALIGNED"}
        )
    )
    assert plans_meta["total_count"] == 1, (
        f"the second plan of this residency is only SUBMITTED, got "
        f"{plans_meta['total_count']}"
    )
    assert plans[0]["id"] == scenario["lesson_plan"]["id"]
    assert scenario["other_plan"]["status"] == "SUBMITTED"

    vouchers, vouchers_meta = validate_paginated(
        api_client.list_payment_vouchers(
            PD, params={"residency_id": residency_id, "status": "DRAFT"}
        )
    )
    assert vouchers_meta["total_count"] == 1, (
        f"one voucher has been opened against this residency, got "
        f"{vouchers_meta['total_count']}"
    )
    assert vouchers[0]["id"] == scenario["voucher"]["id"]

    reports, reports_meta = validate_paginated(
        api_client.list_funder_reports(
            PD, params={"grant_code": "CAT-2026-14", "status": "DRAFT"}
        )
    )
    assert reports_meta["total_count"] == 1, (
        "the report on the other grant code is filtered out, got "
        f"{reports_meta['total_count']}"
    )
    assert reports[0]["id"] == scenario["report"]["id"]
    assert scenario["other_report"]["grant_code"] == "CAT-2099-01"
