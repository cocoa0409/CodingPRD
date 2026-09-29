"""Persistence, defaults, retrieval and rejection at the level of a single row.

These tests take one resource at a time and check what the contract promises the
moment it is written or read back: which columns the server mints, which optional
inputs fall back to a declared default, what a list window reports, and which
error a malformed or dangling reference earns.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ARCHIVE_NOT_PACKAGED,
    CALL_SHEET_DRAFT,
    CATEGORY_CREW,
    CATEGORY_LOCATION,
    COORDINATOR,
    DEFAULT_CONTRACTED_REVISION_ROUNDS,
    DEFAULT_MIN_TURNAROUND_HOURS,
    DEFAULT_RAW_FOOTAGE_RETENTION_MONTHS,
    DEFAULT_RAW_FOOTAGE_TERABYTES,
    DEPT_SOUND,
    LINE_PRODUCER,
    POSTURE_BLOCKED,
    POST_SUPERVISOR,
    PROJECT_DRAFT,
    REVIEW_DRAFT,
    REVIEW_GATE_OPEN,
    SHOOT_DAY_PLANNED,
    ApiErrorId,
    add_budget_line,
    add_deliverable,
    assert_common_fields,
    assert_deliverable_state,
    assert_instant_equals,
    assert_ledgers,
    assert_project_state,
    assert_shoot_day_state,
    assert_total_count,
    assert_version_is,
    budget_line_payload,
    created_row,
    crew_booking_payload,
    crew_member_payload,
    deliverable_payload,
    lock_scope,
    ok_row,
    open_project,
    project_payload,
    read_deliverable,
    read_project,
    register_location,
    schedule_shoot_day,
    shoot_day_payload,
    upload_next_cut,
)


def _scoped_project_and_venue(
    api,
    client_name,
    campaign_title,
    creative_brief_summary,
    location_name,
    address,
    permit_authority,
):
    """A `SCOPED` project and a one-stage venue whose day fee is 90,000 cents."""
    project = open_project(
        api,
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=creative_brief_summary,
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    add_deliverable(
        api,
        project["id"],
        title=f"{campaign_title} 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    add_budget_line(
        api,
        project["id"],
        category=CATEGORY_LOCATION,
        description="Venue day fee",
        quantity=1,
        unit_rate_cents=90000,
        markup_pct=0,
    )
    lock_scope(api, project["id"])
    location = register_location(
        api,
        name=location_name,
        address=address,
        stage_count=1,
        daily_fee_cents=90000,
        insurance_minimum_cents=50000000,
        permit_authority=permit_authority,
    )
    return project, location


def test_a_new_project_persists_its_brief_and_opens_both_ledgers_at_zero(api):
    """Every declared input comes back on the created row, with the money at zero.

    PRD §3.1: "A newly opened project starts with `status` `DRAFT`, both
    `provisional_cost_cents` and `committed_cost_cents` at 0,
    `approved_budget_cents` null (so `budget_variance_cents` reads 0),
    `review_gate` `OPEN`, `archive_status` `NOT_PACKAGED`, `handover_at` and
    `handover_recipient` null, `retention_expires_at` null, and
    `round_entitlement_balance` equal to `contracted_revision_rounds`."

    Design: Corner/entities/project_creation_returns_persisted_row_with_zeroed_ledger
    """
    response = api.create_project(
        project_payload(
            client_name="Verity Labs",
            campaign_title="Proof Points",
            creative_brief_summary="Three-film OLV brand series for a diagnostics company.",
            channel_scope=["OLV", "SOCIAL"],
            usage_term_months=24,
            budget_ceiling_cents=40000000,
            contracted_revision_rounds=3,
            raw_footage_retention_months=18,
            raw_footage_terabytes=22.5,
        ),
        headers=LINE_PRODUCER,
    )

    project = get_success_data(response, expected_status=201)

    assert response.json()["response_type"] == "object", response.json()["response_type"]
    assert_common_fields(project)
    assert project["client_name"] == "Verity Labs", project["client_name"]
    assert project["campaign_title"] == "Proof Points", project["campaign_title"]
    assert project["channel_scope"] == ["OLV", "SOCIAL"], project["channel_scope"]
    assert project["usage_term_months"] == 24, project["usage_term_months"]
    assert project["contracted_revision_rounds"] == 3, project["contracted_revision_rounds"]
    assert_project_state(
        project,
        status=PROJECT_DRAFT,
        review_gate=REVIEW_GATE_OPEN,
        archive_status=ARCHIVE_NOT_PACKAGED,
        round_entitlement_balance=3,
    )
    assert_ledgers(
        project,
        provisional_cents=0,
        committed_cents=0,
        approved_cents=None,
        variance_cents=0,
    )
    assert project["handover_at"] is None, project["handover_at"]
    assert project["handover_recipient"] is None, project["handover_recipient"]
    assert project["retention_expires_at"] is None, project["retention_expires_at"]


def test_the_three_silent_inputs_land_on_two_twelve_and_zero(api):
    """A payload silent on all three optional inputs still carries their defaults.

    PRD §3.1: "Three inputs are optional and carry defaults that the contract
    assumes when the payload is silent. `contracted_revision_rounds` is the number
    of client review rounds included per deliverable; it defaults to 2 and must be
    an integer from 0 to 10. `raw_footage_retention_months` is how long the company
    must keep camera negative after handover; it defaults to 12 and must be an
    integer from 0 to 120. `raw_footage_terabytes` declares the raw volume destined
    for the archive package; it defaults to 0 and must be a number of at least 0."

    Design: Corner/entities/project_optional_inputs_fall_back_to_declared_defaults
    """
    project = open_project(
        api,
        client_name="Kestrel Air",
        campaign_title="Tailwind",
        creative_brief_summary="Single OLV brand film with contract defaults.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=10000000,
    )

    assert project["contracted_revision_rounds"] == DEFAULT_CONTRACTED_REVISION_ROUNDS, (
        project["contracted_revision_rounds"]
    )
    assert project["raw_footage_retention_months"] == DEFAULT_RAW_FOOTAGE_RETENTION_MONTHS, (
        project["raw_footage_retention_months"]
    )
    assert project["raw_footage_terabytes"] == DEFAULT_RAW_FOOTAGE_TERABYTES, (
        project["raw_footage_terabytes"]
    )
    assert_project_state(project, round_entitlement_balance=DEFAULT_CONTRACTED_REVISION_ROUNDS)


def test_a_roster_entry_is_minted_with_stamps_a_counter_and_ten_rest_hours(api):
    """The server mints the four system columns and fills the silent rest hours.

    PRD §2.4: "`version` (integer): a counter that starts at 1 on creation and
    increments by 1 on every mutation of the row, including mutations the server
    performs on its own initiative as part of a cascade."

    PRD §3.6: "A roster entry carries the `full_name` as booked (non-blank, up to
    120 characters), the `department` the person is booked into — one of `CAMERA`,
    `GRIP_ELECTRIC`, `SOUND`, `ART`, `PRODUCTION` or `POST` — an
    `hourly_rate_cents` straight-time rate greater than 0, an optional
    `union_local` designation that is null for non-union crew, and an optional
    `min_turnaround_hours` giving the contractual rest hours required between the
    wrap of one booking and the call of the next, which defaults to 10 when omitted
    and must be an integer from 0 to 24."

    Design: Corner/entities/crew_member_creation_stamps_system_fields
    """
    payload = crew_member_payload(
        full_name="Noor Haddad",
        department=DEPT_SOUND,
        hourly_rate_cents=6000,
    )
    payload.pop("min_turnaround_hours")

    crew = created_row(api.create_crew_member(payload, headers=COORDINATOR))

    assert_version_is(crew, 1)
    assert crew["min_turnaround_hours"] == DEFAULT_MIN_TURNAROUND_HOURS, (
        crew["min_turnaround_hours"]
    )
    assert crew["union_local"] is None, crew["union_local"]

    read_back = ok_row(api.get_crew_member(crew["id"], headers=COORDINATOR))

    assert read_back["id"] == crew["id"], read_back["id"]
    assert read_back["full_name"] == "Noor Haddad", read_back["full_name"]
    assert read_back["hourly_rate_cents"] == 6000, read_back["hourly_rate_cents"]


def test_a_planned_day_reads_back_its_window_and_the_bare_venue_fee(api):
    """The stored interval comes back untouched and every derived column is live.

    PRD §3.4: "A new shoot day starts at `status` `PLANNED` with
    `call_sheet_status` `DRAFT`, `call_sheet_published_at` null and
    `cancellation_reason` null."

    PRD §3.6: "A day's `day_cost_cents` is a display-only total, recomputed on every
    shoot-day read and after any booking or reservation status change on that day:
    it is the venue's `daily_fee_cents` plus the `cost_cents` of every crew booking
    on the day whose `status` is `CONFIRMED` or `COMPLETED` plus the
    `total_cost_cents` of every reservation on the day whose `status` is `RESERVED`
    or `RETURNED`."

    Design: Corner/entities/shoot_day_retrieval_returns_window_and_derived_columns
    """
    project, location = _scoped_project_and_venue(
        api,
        client_name="Bell Foundry",
        campaign_title="Cast Iron",
        creative_brief_summary="One-day OLV brand film at a working foundry.",
        location_name="Bell Foundry Floor",
        address="3 Furnace Way, Erie",
        permit_authority="Erie Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )

    response = api.get_shoot_day(day["id"], headers=COORDINATOR)

    read = get_success_data(response, expected_status=200)
    assert read["id"] == day["id"], read["id"]
    assert read["project_id"] == project["id"], read["project_id"]
    assert_instant_equals(read["call_time"], "2026-09-10T06:00:00Z")
    assert_instant_equals(read["wrap_time"], "2026-09-10T16:00:00Z")
    assert_shoot_day_state(
        read,
        status=SHOOT_DAY_PLANNED,
        compliance_posture=POSTURE_BLOCKED,
        call_sheet_status=CALL_SHEET_DRAFT,
        confirmed_crew_count=0,
        day_cost_cents=90000,
    )
    assert read["call_sheet_published_at"] is None, read["call_sheet_published_at"]
    assert read["cancellation_reason"] is None, read["cancellation_reason"]


def test_three_cuts_split_across_two_windows_with_a_stable_total_count(api):
    """The window moves, the total does not, and `has_more` closes on the last page.

    PRD §2.3: "Every list response sets `response_type` to `"array"`, returns the
    rows as the envelope's `data` array, and carries `limit`, `offset`,
    `total_count` and `has_more` inside `meta`."

    PRD §3.8: "The deliverable's `version_count` is recomputed as the number of cuts
    carrying its identifier."

    Design: Corner/entities/deliverable_version_list_paginates_with_total_count_and_has_more
    """
    project = open_project(
        api,
        client_name="Orchard Bank",
        campaign_title="Three Cuts",
        creative_brief_summary="OLV brand film with three offline cuts in the bin.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=50000000,
    )
    deliverable = add_deliverable(
        api,
        project["id"],
        title="Three Cuts 60",
        channel="OLV",
        aspect_ratio="16:9",
        target_duration_seconds=60,
        caption_requirement="NONE",
        usage_rights_months=12,
        air_date="2026-12-01T00:00:00Z",
    )
    for label, size in (("cut A", 8.0), ("cut B", 8.1), ("cut C", 8.2)):
        upload_next_cut(api, deliverable["id"], cut_label=label, file_size_gb=size)

    first = api.list_deliverable_versions(
        headers=POST_SUPERVISOR, deliverable_id=deliverable["id"], limit=2, offset=0
    )
    second = api.list_deliverable_versions(
        headers=POST_SUPERVISOR, deliverable_id=deliverable["id"], limit=2, offset=2
    )

    assert first.json()["response_type"] == "array", first.json()["response_type"]
    first_rows, first_meta = validate_paginated(first)
    assert len(first_rows) == 2, len(first_rows)
    assert first_meta["total_count"] == 3, first_meta["total_count"]
    assert first_meta["limit"] == 2, first_meta["limit"]
    assert first_meta["offset"] == 0, first_meta["offset"]
    assert first_meta["has_more"] is True, first_meta["has_more"]

    second_rows, second_meta = validate_paginated(second)
    assert len(second_rows) == 1, len(second_rows)
    assert second_meta["total_count"] == 3, second_meta["total_count"]
    assert second_meta["offset"] == 2, second_meta["offset"]
    assert second_meta["has_more"] is False, second_meta["has_more"]

    for row in first_rows + second_rows:
        assert row["deliverable_id"] == deliverable["id"], row["deliverable_id"]
        assert row["review_status"] == REVIEW_DRAFT, row["review_status"]
    assert_deliverable_state(read_deliverable(api, deliverable["id"]), version_count=3)


def test_an_unknown_cut_identifier_is_a_404_and_not_an_empty_success(api):
    """A cut identifier nothing carries earns the cut family's own 404.

    PRD §2.11: "The same discipline applies to identifiers supplied in a request
    body: each referenced row must exist, and each family has its own 404 —
    `ERR_PROJECT_NOT_FOUND` for a `project_id`, `ERR_DELIVERABLE_NOT_FOUND` for a
    `deliverable_id`, `ERR_DELIVERABLE_VERSION_NOT_FOUND` for a cut identifier in
    the path or a `supersedes_version_id` in the payload,
    `ERR_CHANGE_ORDER_NOT_FOUND` for a change-order identifier,
    `ERR_SHOOT_DAY_NOT_FOUND` for a `shoot_day_id`, `ERR_LOCATION_NOT_FOUND` for a
    `location_id`, `ERR_CREW_MEMBER_NOT_FOUND` for a `crew_member_id`,
    `ERR_CREW_BOOKING_NOT_FOUND` for a booking identifier,
    `ERR_COMPLIANCE_CERT_NOT_FOUND` for a certificate identifier, and
    `ERR_TALENT_ENGAGEMENT_NOT_FOUND` for an engagement identifier on the
    engagement-confirmation call."

    Design: Corner/entities/deliverable_version_fetch_with_unknown_id_returns_not_found
    """
    open_project(
        api,
        client_name="Solano Wines",
        campaign_title="Old Vines",
        creative_brief_summary="OLV brand film, nothing shot yet.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=10000000,
    )

    response = api.get_deliverable_version(NON_EXISTENT_UUID, headers=POST_SUPERVISOR)

    error = validate_error(response, ApiErrorId.ERR_DELIVERABLE_VERSION_NOT_FOUND)
    assert error["message"].strip(), error["message"]


def test_a_budget_line_without_a_unit_rate_is_refused_and_writes_nothing(api):
    """A required field left out is a request-shape defect, not a partial write.

    PRD §2.12: "Priority 4: **Request shape** — the body parses, every required
    field is present and of the declared type, enum fields carry a declared member,
    monetary and count fields are non-negative integers, and interval fields satisfy
    start strictly before end (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/budget_line_missing_required_unit_rate_rejected
    """
    project = open_project(
        api,
        client_name="Marlow Cycles",
        campaign_title="Cadence",
        creative_brief_summary="OLV brand film being budgeted.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=10000000,
    )
    payload = budget_line_payload(
        project["id"],
        category=CATEGORY_CREW,
        description="Camera package",
        quantity=2,
    )
    payload.pop("unit_rate_cents")

    response = api.create_budget_line(payload, headers=LINE_PRODUCER)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert_total_count(api.list_project_budget_lines(project["id"], headers=LINE_PRODUCER), 0)
    assert_ledgers(read_project(api, project["id"]), provisional_cents=0, committed_cents=0)


def test_an_undeclared_aspect_ratio_loses_before_the_rights_checks_are_reached(api):
    """`21:9` is outside the enum, so the shape rule reports first.

    PRD §3.1: "Registration names the owning project through a `project_id` in the
    payload and describes the format completely: a `title` such as "Hero film 60s"
    (non-blank, 1 to 120 characters), the single `channel` this cut is licensed for,
    the `aspect_ratio` every accepted version must deliver — one of `16:9`, `9:16`,
    `1:1`, `4:5` or `2.39:1` — the contracted `target_duration_seconds` (an integer
    greater than 0 and at most 3600), the `caption_requirement` (`NONE`,
    `CLOSED_SRT`, `BURNED_IN_SUBTITLES` or `OPEN_CAPTIONS`), the deliverable's own
    `usage_rights_months` (1 to 60), and the contracted first-air instant
    `air_date`, which later drives rush tiering on change orders."

    PRD §2.12: "Priority 41: **Channel within scope** (`ERR_CHANNEL_OUT_OF_SCOPE`, HTTP
    422), checked on deliverable creation."

    Design: Corner/entities/deliverable_with_undeclared_aspect_ratio_rejected
    """
    project = open_project(
        api,
        client_name="Perrin Optics",
        campaign_title="Clear Field",
        creative_brief_summary="OLV brand film in a single aspect ratio.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=10000000,
    )

    response = api.create_deliverable(
        deliverable_payload(
            project["id"],
            title="Clear Field ultrawide",
            channel="OLV",
            aspect_ratio="21:9",
            target_duration_seconds=60,
            caption_requirement="NONE",
            usage_rights_months=12,
            air_date="2026-12-01T00:00:00Z",
        ),
        headers=COORDINATOR,
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] != ApiErrorId.ERR_CHANNEL_OUT_OF_SCOPE.value, error["error_id"]
    assert error["error_id"] != ApiErrorId.ERR_USAGE_RIGHTS_EXCEED_TERM.value, error["error_id"]
    assert_total_count(api.list_project_deliverables(project["id"], headers=COORDINATOR), 0)


def test_an_inverted_occupation_window_never_reaches_the_capacity_rule(api):
    """Wrap earlier than call is a shape defect, so no stage is ever counted.

    PRD §3.4: "The request names the project with a `project_id` and the venue with
    a `location_id`, and describes the occupation window: `shoot_date` is the
    calendar date of the shoot as a UTC `YYYY-MM-DD` string and must equal the UTC
    date part of `call_time`; `call_time` is the general crew call and opens the
    occupation interval; `wrap_time` is the planned wrap and closes it, and must be
    strictly later than `call_time`."

    PRD §2.12: "Priority 4: **Request shape** — the body parses, every required
    field is present and of the declared type, enum fields carry a declared member,
    monetary and count fields are non-negative integers, and interval fields satisfy
    start strictly before end (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/entities/shoot_day_with_wrap_before_call_rejected
    """
    project, location = _scoped_project_and_venue(
        api,
        client_name="Halden Homes",
        campaign_title="Groundwork",
        creative_brief_summary="OLV brand film scheduled on one stage day.",
        location_name="Halden Stage 1",
        address="10 Mill Road, Duluth",
        permit_authority="Duluth Film Office",
    )

    response = api.create_shoot_day(
        shoot_day_payload(
            project["id"],
            location["id"],
            call_time="2026-09-10T16:00:00Z",
            wrap_time="2026-09-10T06:00:00Z",
        ),
        headers=COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert_total_count(
        api.list_shoot_days(headers=COORDINATOR, location_id=location["id"]), 0
    )
    venue = ok_row(api.get_location(location["id"], headers=COORDINATOR))
    assert venue["scheduled_shoot_day_count"] == 0, venue["scheduled_shoot_day_count"]


def test_a_budget_line_naming_a_stranger_project_reports_the_project_404(api):
    """The foreign key is resolved before any fiscal or state rule is consulted.

    PRD §2.12: "Priorities 6 through 15: **Existence** of every referenced row, in
    this order of identifier families — project (priority 6), deliverable (7), cut
    (8), change order (9), shoot day (10), location (11), crew member (12), crew
    booking (13), compliance certificate (14), talent engagement (15) — each
    reporting the 404 code listed in §2.11."

    Design: Corner/entities/budget_line_against_unknown_project_returns_not_found
    """
    project = open_project(
        api,
        client_name="Tamarind Foods",
        campaign_title="Slow Simmer",
        creative_brief_summary="OLV brand film with a real project row.",
        channel_scope=["OLV"],
        usage_term_months=12,
        budget_ceiling_cents=10000000,
    )

    response = api.create_budget_line(
        budget_line_payload(
            NON_EXISTENT_UUID,
            category=CATEGORY_CREW,
            description="Ghost crew",
            quantity=1,
            unit_rate_cents=50000,
            markup_pct=0,
        ),
        headers=LINE_PRODUCER,
    )

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND)
    assert_total_count(api.list_project_budget_lines(project["id"], headers=LINE_PRODUCER), 0)


def test_a_booking_with_a_good_day_and_a_ghost_person_reports_the_crew_404(api):
    """Both foreign keys are checked, so the unresolvable one decides the error.

    PRD §2.12: "Priorities 6 through 15: **Existence** of every referenced row, in
    this order of identifier families — project (priority 6), deliverable (7), cut
    (8), change order (9), shoot day (10), location (11), crew member (12), crew
    booking (13), compliance certificate (14), talent engagement (15) — each
    reporting the 404 code listed in §2.11."

    Design: Corner/entities/crew_booking_with_unknown_crew_member_returns_not_found
    """
    project, location = _scoped_project_and_venue(
        api,
        client_name="Ridge Tools",
        campaign_title="Hard Edge",
        creative_brief_summary="One-day OLV brand film with an unstaffed roster.",
        location_name="Ridge Yard",
        address="77 Quarry Lane, Boise",
        permit_authority="Boise Film Office",
    )
    day = schedule_shoot_day(
        api,
        project["id"],
        location["id"],
        call_time="2026-09-10T06:00:00Z",
        wrap_time="2026-09-10T16:00:00Z",
    )

    response = api.create_crew_booking(
        crew_booking_payload(
            day["id"],
            NON_EXISTENT_UUID,
            department_role="Key Grip",
            call_time="2026-09-10T06:00:00Z",
            wrap_time="2026-09-10T16:00:00Z",
        ),
        headers=COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_CREW_MEMBER_NOT_FOUND)
    assert_total_count(api.list_crew_bookings(headers=COORDINATOR, shoot_day_id=day["id"]), 0)
    assert_shoot_day_state(
        ok_row(api.get_shoot_day(day["id"], headers=COORDINATOR)),
        confirmed_crew_count=0,
        day_cost_cents=90000,
    )
