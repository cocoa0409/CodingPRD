"""Entity surface: creation defaults, retrieval, listing, and the not-found shape."""

from test_helpers import (
    ADMIN,
    CLERK,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    append_cost_estimate,
    assert_agency,
    assert_bill,
    assert_committee,
    assert_common_properties,
    assert_cost_estimate,
    assert_drafting_request,
    assert_instant,
    assert_member,
    assert_session,
    companion_payload,
    create_bill_payload,
    create_drafting_request_payload,
    create_session_payload,
    file_statutory_conflict,
    get_success_data,
    read_bill,
    read_drafting_request,
    return_note,
    route_fiscal_note,
    set_clock,
    setup_draft_ready_request,
    setup_introduced_bill,
    setup_request_in_research,
    setup_world,
    submit_note,
    validate_error,
    validate_paginated,
    validate_success,
)

CANONICAL_CLOCK = "2026-09-01T00:00:00Z"


def test_session_creation_seeds_every_declared_and_system_field():
    """PRD: "A newly created session opens in `status` `PENDING` with
    `convened_utc` and `adjourned_utc` both null, `certified_fiscal_total_cents`
    at 0, `fiscal_posture` `NORMAL`, `bills_introduced_count` and
    `bills_enrolled_count` at 0, and both numbering counters —
    `next_house_bill_number` and `next_senate_bill_number` — at 1." and "Most
    resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the
    same format that is refreshed on every mutation of the row, and `version`, an
    integer that begins at 1 when the row is created and increases by exactly 1
    on each mutation."

    Design: Corner/entities/session_creation_returns_every_declared_field_with_system_defaults_seeded
    """
    set_clock(CANONICAL_CLOCK)

    response = api_client.create_session(create_session_payload(), ADMIN)

    # validate_success also proves meta.api_request_id and meta.api_request_timestamp
    # are on the envelope and that response_type is the single-object form.
    session = validate_success(response, 201)
    assert_session(session)
    assert_common_properties(session, "session")
    assert session["name"] == "2027 Regular Session"
    assert session["required_fiscal_years"] == [2027, 2028]
    assert session["status"] == "PENDING"
    assert session["convened_utc"] is None
    assert session["adjourned_utc"] is None
    assert session["next_house_bill_number"] == 1
    assert session["next_senate_bill_number"] == 1
    assert session["certified_fiscal_total_cents"] == 0
    assert session["fiscal_posture"] == "NORMAL"
    assert session["bills_introduced_count"] == 0
    assert session["bills_enrolled_count"] == 0
    assert session["version"] == 1


def test_session_retrieval_returns_the_stored_row_without_bumping_the_version():
    """PRD: "An optional `fiscal_note_default_days` sets the baseline number of
    days an agency is granted for a fiscal note; it defaults to 21 and must be at
    least 1." and "Finally `required_fiscal_years` is a non-empty array of
    integers in strictly ascending order — the fiscal years every baseline cost
    estimate set must cover, for example the two years 2027 and 2028."

    Design: Corner/entities/session_retrieval_returns_the_stored_row_unchanged
    """
    set_clock(CANONICAL_CLOCK)
    created = get_success_data(api_client.create_session(create_session_payload(), ADMIN))

    response = api_client.get_session(created["id"], CLERK)

    fetched = validate_success(response, 200)
    assert_session(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "PENDING"
    assert fetched["fiscal_note_default_days"] == 21
    assert fetched["required_fiscal_years"] == [2027, 2028]
    assert_instant(fetched["sine_die_utc"], "2026-11-20T18:00:00Z")
    # A read is not a mutation, so nothing about the row has moved.
    assert fetched["version"] == 1
    assert fetched["version"] == created["version"]
    assert fetched["created_at"] == created["created_at"]
    assert fetched["constrained_threshold_cents"] == created["constrained_threshold_cents"]


def test_drafting_request_listing_paginates_with_total_count_and_has_more():
    """PRD: "All four pagination fields — `limit`, `offset`, `total_count` and
    `has_more` — appear in the `meta` object of every list response, where
    `total_count` is the number of rows matching the filter before the page window
    is applied and `has_more` is true when rows remain beyond the current window."
    and "List responses are ordered by `created_at` ascending, oldest row first."

    Design: Corner/entities/drafting_requests_listing_paginates_with_total_count_and_has_more
    """
    world = setup_world()
    session_id = world["session"]["id"]
    for index, subject in enumerate(("Request one", "Request two", "Request three"), start=1):
        payload = create_drafting_request_payload(
            session_id,
            subject=subject,
            summary=f"Measure number {index}.",
            requested_sections_count=1,
            target_code_chapter=f"Title {index}",
        )
        get_success_data(api_client.create_drafting_request(payload, world["member_headers"]))

    first_rows, first_meta = validate_paginated(
        api_client.list_drafting_requests(
            CLERK, params={"session_id": session_id, "limit": 2, "offset": 0}
        )
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_drafting_requests(
            CLERK, params={"session_id": session_id, "limit": 2, "offset": 2}
        )
    )

    assert len(first_rows) == 2
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_rows) == 1
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    # Oldest row first, so the page window slices a stable created_at ordering.
    assert [row["subject"] for row in first_rows] == ["Request one", "Request two"]
    assert second_rows[0]["subject"] == "Request three"


def test_bill_read_with_an_unknown_id_returns_the_error_envelope():
    """PRD: "Identifiers that appear in a URL path are resolved strictly from left
    to right, and the first unresolvable segment decides the error." and "Each
    entity has its own not-found identifier, all of them HTTP 404:
    `ERR_SESSION_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_DRAFTER_NOT_FOUND`,
    `ERR_AGENCY_NOT_FOUND`, `ERR_COMMITTEE_NOT_FOUND`,
    `ERR_DRAFTING_REQUEST_NOT_FOUND`, `ERR_STATUTORY_CONFLICT_NOT_FOUND`,
    `ERR_BILL_NOT_FOUND`, `ERR_COMMITTEE_REFERRAL_NOT_FOUND`,
    `ERR_FISCAL_NOTE_REQUEST_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
    `ERR_ENROLLED_BILL_NOT_FOUND` and `ERR_TECHNICAL_CORRECTION_NOT_FOUND`." and
    "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/bill_get_with_unknown_id_returns_not_found
    """
    set_clock(CANONICAL_CLOCK)

    response = api_client.get_bill(NON_EXISTENT_UUID, CLERK)

    body = validate_error(response, ApiErrorId.ERR_BILL_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(body["message"], str)
    assert body["message"] != ""
    # A missing row is never dressed up as an empty success payload.
    assert "id" not in body


def test_drafting_request_without_target_code_chapter_is_refused_and_creates_no_row():
    """PRD: "The body carries the `session_id`, a short `subject`, a narrative
    `summary` of the legislation wanted, a `requested_sections_count` of at least 1
    recording how many statute sections the member believes must be touched, and a
    `target_code_chapter` retained for audit only." and "Every required field
    present, every enum value declared, every `*_cents` value honouring its
    minimum, every interval ending strictly after it starts, and
    `required_fiscal_years` a non-empty strictly ascending array of integers —
    otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/drafting_request_missing_required_target_code_chapter_returns_invalid_request
    """
    world = setup_world()
    payload = create_drafting_request_payload(
        world["session"]["id"],
        subject="Missing chapter",
        summary="No target chapter supplied.",
        requested_sections_count=2,
    )
    payload.pop("target_code_chapter")
    payload.pop("appropriation_requested_cents")

    response = api_client.create_drafting_request(payload, world["member_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(
        api_client.list_drafting_requests(CLERK, params={"session_id": world["session"]["id"]})
    )
    assert meta["total_count"] == 0
    member = get_success_data(api_client.get_member(world["member"]["id"], ADMIN))
    assert member["priority_slots_used"] == 0


def test_omitted_optional_inputs_fall_back_to_the_declared_defaults():
    """PRD: "Either a `Clerk` or a `PlatformAdmin` may create one, supplying its
    `chamber` (`HOUSE` or `SENATE`), its `name`, an optional `is_fiscal_committee`
    flag defaulting to false, and an optional `max_concurrent_referrals`
    defaulting to 2 and required to be at least 1." and "Legislators are
    registered by a `PlatformAdmin` with a `full_name`, a `chamber` of `HOUSE` or
    `SENATE` that fixes the chamber of every bill they sponsor, a `party` label
    kept purely for audit, and an optional `priority_slots_total` defaulting to 2
    and permitted to be 0 or more." and "An agency carries a `name`, a short
    `agency_code` that must be unique across all agencies — a repeat is
    `ERR_DUPLICATE_AGENCY_CODE` — an optional `status` of `ACTIVE` or `INACTIVE`
    defaulting to `ACTIVE`, and an optional `max_open_requests` defaulting to 3 and
    required to be at least 1." and "Committees are created beneath their session,
    so a committee's `session_id` comes from the path and is never read from the
    body."

    Design: Corner/entities/member_and_agency_and_committee_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(CANONICAL_CLOCK)
    session_payload = create_session_payload()
    session_payload.pop("fiscal_note_default_days")
    session = get_success_data(api_client.create_session(session_payload, ADMIN))

    member = validate_success(
        api_client.create_member(
            {"full_name": "Rep Default", "chamber": "SENATE", "party": "IND"}, ADMIN
        ),
        201,
    )
    agency = validate_success(
        api_client.create_agency({"name": "Dept of Defaults", "agency_code": "DOD"}, ADMIN), 201
    )
    committee = validate_success(
        api_client.create_committee(
            session["id"], {"chamber": "SENATE", "name": "Senate Rules"}, CLERK
        ),
        201,
    )

    assert_member(member)
    assert member["priority_slots_total"] == 2
    assert member["priority_slots_used"] == 0
    assert member["clarification_pending_count"] == 0
    assert member["intake_hold"] is False

    assert_agency(agency)
    assert agency["status"] == "ACTIVE"
    assert agency["max_open_requests"] == 3
    assert agency["responsiveness_score"] == 100
    assert agency["open_request_count"] == 0
    assert agency["late_submission_count"] == 0
    assert agency["revision_count"] == 0

    assert_committee(committee)
    assert committee["is_fiscal_committee"] is False
    assert committee["max_concurrent_referrals"] == 2
    assert committee["active_referral_count"] == 0
    # The parent link is path-derived, and the omitted session default holds.
    assert committee["session_id"] == session["id"]
    assert session["fiscal_note_default_days"] == 21


def test_intake_complexity_estimate_is_computed_from_the_four_declared_terms():
    """PRD: "A confidential priority request naming six sections and asking for
    12,000,000 cents therefore scores twenty-four for its sections, twelve for
    confidentiality, eight for priority and fifteen for the top appropriation band,
    for an `intake_complexity_estimate` of 59." and "The request's `member_id` is
    stamped from `X-User-ID` and is never accepted from the body." and "The new row
    lands in `status` `SUBMITTED` with `assigned_drafter_id`,
    `engagement_start_utc`, `engagement_end_utc`, `affected_sections_count`,
    `research_completed_utc`, `sla_due_utc`, `actual_complexity_score` and
    `style_findings_count` all null, `revision_round` at 0, and all three conflict
    counters at 0."

    Design: Corner/entities/drafting_request_computed_intake_estimate_ignores_any_client_supplied_value_input_ignored
    """
    world = setup_world()
    payload = create_drafting_request_payload(
        world["session"]["id"],
        subject="Confidential caucus measure",
        summary="Sensitive drafting request.",
        requested_sections_count=6,
        target_code_chapter="Title 11",
        confidentiality="CONFIDENTIAL",
        priority_flag=True,
        appropriation_requested_cents=12_000_000,
    )

    response = api_client.create_drafting_request(payload, world["member_headers"])

    request = validate_success(response, 201)
    assert_drafting_request(request)
    assert request["intake_complexity_estimate"] == 59
    assert request["actual_complexity_score"] is None
    assert request["status"] == "SUBMITTED"
    assert request["sla_due_utc"] is None
    assert request["revision_round"] == 0
    # Sponsorship comes from the acting principal, not from anything in the body.
    assert request["member_id"] == world["member"]["id"]
    member = get_success_data(api_client.get_member(world["member"]["id"], ADMIN))
    assert member["priority_slots_used"] == 1


def test_bill_fields_are_all_derived_from_the_originating_request_and_the_clock():
    """PRD: "The rest of the new bill is copied rather than supplied. Its
    `session_id`, `sponsor_member_id`, `chamber`, `appropriation_requested_cents`
    and `priority_bill` are all taken from the originating drafting request —
    `priority_bill` mirroring that request's `priority_flag`, and
    `appropriation_requested_cents` frozen at its introduction value thereafter."
    and "`introduced_utc` is stamped with the logical clock." and
    "`legislative_status` opens at `INTRODUCED`; `companion_bill_id` is null;
    `adopted_fiscal_delta_cents`, `adopted_amendment_count` and `referral_count`
    all start at 0."

    Design: Corner/entities/bill_system_fields_are_server_generated_and_client_input_ignored
    """
    world = setup_world()
    request = setup_draft_ready_request(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Ferry service subsidy",
        summary="Subsidize rural ferry service.",
        target_code_chapter="Title 46",
        appropriation_requested_cents=7_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )

    # The introduction payload names exactly one field; everything else is derived.
    response = api_client.create_bill(create_bill_payload(request["id"]), CLERK)

    bill = validate_success(response, 201)
    assert_bill(bill)
    assert_common_properties(bill, "bill")
    assert bill["bill_number"] == "HB 1"
    assert bill["chamber"] == "HOUSE"
    assert_instant(bill["introduced_utc"], CANONICAL_CLOCK)
    assert bill["sponsor_member_id"] == world["member"]["id"]
    assert bill["appropriation_requested_cents"] == 7_000_000
    assert bill["session_id"] == world["session"]["id"]
    assert bill["priority_bill"] is False
    assert bill["version"] == 1
    assert bill["legislative_status"] == "INTRODUCED"
    assert bill["fiscal_status"] == "NOTE_PENDING"
    assert bill["companion_bill_id"] is None
    assert bill["referral_count"] == 0
    assert bill["adopted_amendment_count"] == 0
    assert bill["adopted_fiscal_delta_cents"] == 0

    session = get_success_data(api_client.get_session(world["session"]["id"], CLERK))
    assert session["next_house_bill_number"] == 2
    assert session["bills_introduced_count"] == 1


def test_an_undeclared_confidentiality_value_is_refused_rather_than_coerced():
    """PRD: "Three optional fields shape the request further: `confidentiality`,
    which is `CONFIDENTIAL` or `PUBLIC` and defaults to `PUBLIC`; `priority_flag`,
    defaulting to false, which declares that the request should consume one of the
    member's priority slots; and `appropriation_requested_cents`, defaulting to 0
    and never negative, the appropriation the member is asking for." and "Every
    required field present, every enum value declared, every `*_cents` value
    honouring its minimum, every interval ending strictly after it starts, and
    `required_fiscal_years` a non-empty strictly ascending array of integers —
    otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/drafting_request_invalid_confidentiality_enum_returns_invalid_request
    """
    world = setup_world()
    payload = create_drafting_request_payload(
        world["session"]["id"],
        subject="Bad enum",
        summary="Enum probe.",
        requested_sections_count=2,
        target_code_chapter="Title 9",
        confidentiality="SECRET",
    )

    response = api_client.create_drafting_request(payload, world["member_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(
        api_client.list_drafting_requests(CLERK, params={"session_id": world["session"]["id"]})
    )
    assert meta["total_count"] == 0


def _note_with_two_rounds_of_lines():
    """Two round-0 lines, a return for revision, then a replacement round-1 line."""
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Fuel tax indexing",
        summary="Index the fuel tax.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
    )
    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")
    round_zero_2027 = append_cost_estimate(
        world,
        note,
        fiscal_year=2027,
        personnel_cost_cents=14_000_000,
        operating_cost_cents=4_100_000,
        one_time_cost_cents=3_000_000,
        fte_count=1.0,
        revenue_impact_cents=0,
        assumption_note="Round zero FY2027 crew.",
    )
    append_cost_estimate(
        world,
        note,
        fiscal_year=2028,
        personnel_cost_cents=10_400_000,
        operating_cost_cents=3_500_000,
        one_time_cost_cents=0,
        fte_count=1.0,
        revenue_impact_cents=0,
        assumption_note="Round zero FY2028 crew.",
    )
    submitted = submit_note(world, note)
    returned = return_note(world, submitted)
    round_one_2027 = append_cost_estimate(
        world,
        returned,
        fiscal_year=2027,
        personnel_cost_cents=15_000_000,
        operating_cost_cents=4_100_000,
        one_time_cost_cents=3_000_000,
        fte_count=1.0,
        revenue_impact_cents=0,
        assumption_note="Round one FY2027 crew, restated.",
    )
    return world, note, round_zero_2027, round_one_2027


def test_a_superseded_cost_estimate_line_survives_as_a_row_with_no_version_field():
    """PRD: "One resource is deliberately leaner. A cost estimate line is
    append-only: it is never edited and never deleted, so it carries only `id` and
    `created_at`. Neither `updated_at` nor `version` exists on a cost estimate
    line, and neither field appears in its response payload." and "Every submission
    and resubmission recomputes the cost totals and all three projections from
    scratch; lines filed under earlier rounds stay on the record with
    `included_in_certification` false and are excluded from every total."

    Design: Corner/entities/cost_estimate_rows_are_append_only_and_carry_no_version_field
    """
    world, note, round_zero_2027, round_one_2027 = _note_with_two_rounds_of_lines()

    rows, meta = validate_paginated(
        api_client.list_cost_estimates(note["id"], world["analyst_headers"])
    )

    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in rows}
    superseded = by_id[round_zero_2027["id"]]
    replacement = by_id[round_one_2027["id"]]

    # A correction is a new row, never an edit of the old one.
    assert superseded["revision_round"] == 0
    assert superseded["personnel_cost_cents"] == 14_000_000
    assert superseded["included_in_certification"] is False
    assert replacement["revision_round"] == 1
    assert replacement["personnel_cost_cents"] == 15_000_000
    assert replacement["included_in_certification"] is True

    for row in rows:
        assert_cost_estimate(row)
        assert "version" not in row
        assert "updated_at" not in row
        assert "id" in row
        assert "created_at" in row


def test_creating_a_committee_beneath_an_unknown_session_reports_the_session_failure():
    """PRD: "Identifiers that appear in a URL path are resolved strictly from left
    to right, and the first unresolvable segment decides the error." and
    "Committees are created beneath their session, so a committee's `session_id`
    comes from the path and is never read from the body."

    Design: Corner/entities/committee_creation_under_unknown_session_returns_session_not_found
    """
    set_clock(CANONICAL_CLOCK)

    response = api_client.create_committee(
        NON_EXISTENT_UUID,
        {
            "chamber": "HOUSE",
            "name": "Orphan Committee",
            "is_fiscal_committee": False,
            "max_concurrent_referrals": 2,
        },
        CLERK,
    )

    body = validate_error(response, ApiErrorId.ERR_SESSION_NOT_FOUND.value, 404)
    assert body["error_id"] != ApiErrorId.ERR_COMMITTEE_NOT_FOUND.value
    # There is nowhere for the row to have landed: the parent never resolved.
    assert validate_error(
        api_client.list_session_committees(NON_EXISTENT_UUID, CLERK),
        ApiErrorId.ERR_SESSION_NOT_FOUND.value,
        404,
    )


def test_a_companion_link_to_an_unknown_bill_leaves_the_link_null():
    """PRD: "A `companion_bill_id` that resolves to nothing is
    `ERR_BILL_NOT_FOUND`; a `supersedes_amendment_id` that resolves to nothing is
    `ERR_AMENDMENT_NOT_FOUND`." and "A `Clerk` supplies `companion_bill_id`, and
    the link is written reciprocally: this bill's `companion_bill_id` is set to the
    named bill and the named bill's `companion_bill_id` is set back to this one,
    with the `version` of **both** rows rising by one."

    Design: Corner/entities/bill_companion_link_to_unknown_bill_returns_not_found
    """
    world = setup_world()
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Open meetings notice reform",
        summary="Standardize open meetings notice.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
    )
    assert bill["version"] == 1

    response = api_client.link_companion(
        bill["id"], companion_payload(NON_EXISTENT_UUID), CLERK
    )

    validate_error(response, ApiErrorId.ERR_BILL_NOT_FOUND.value, 404)
    unchanged = read_bill(world, bill["id"])
    assert unchanged["companion_bill_id"] is None
    # A refused write is not a mutation, so the reciprocal bump never happened.
    assert unchanged["version"] == 1


def test_the_conflict_sub_resource_listing_is_scoped_to_its_parent_request():
    """PRD: "The statutory-conflicts-of-a-request list accepts `severity` and
    `resolution_status`." and "Every filing updates the parent request's counters. A
    `BLOCKING` finding raises both `blocking_conflict_count` and
    `open_blocking_conflict_count` by one; an `ADVISORY` finding raises
    `advisory_conflict_count` by one." and "The cascade is strictly conditional: an
    `ADVISORY` finding, or a `BLOCKING` finding recorded while the request is still
    in `RESEARCH`, updates the counters and stops there, leaving the status, the
    service target, the occupancy set and the member's counters untouched."

    Design: Corner/entities/statutory_conflict_sub_resource_listing_returns_only_the_parent_requests_rows
    """
    world = setup_world()
    request_a = setup_request_in_research(
        world,
        subject="Water quality standards",
        summary="Revise water quality standards.",
        target_code_chapter="Title 25",
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    request_b = setup_request_in_research(
        world,
        subject="Air permit fees",
        summary="Revise air permit fees.",
        target_code_chapter="Title 25",
        engagement_start_utc="2026-09-06T00:00:00Z",
        engagement_end_utc="2026-09-08T00:00:00Z",
    )
    file_statutory_conflict(world, request_a, severity="ADVISORY", code_citation="25-1-101")
    file_statutory_conflict(world, request_a, severity="ADVISORY", code_citation="25-1-102")
    file_statutory_conflict(world, request_a, severity="BLOCKING", code_citation="25-1-103")
    sibling = file_statutory_conflict(
        world, request_b, severity="ADVISORY", code_citation="25-2-201"
    )

    all_rows, all_meta = validate_paginated(
        api_client.list_request_statutory_conflicts(request_a["id"], CLERK)
    )
    blocking_rows, blocking_meta = validate_paginated(
        api_client.list_request_statutory_conflicts(
            request_a["id"], CLERK, params={"severity": "BLOCKING"}
        )
    )

    assert all_meta["total_count"] == 3
    assert all(row["drafting_request_id"] == request_a["id"] for row in all_rows)
    assert blocking_meta["total_count"] == 1
    assert blocking_rows[0]["severity"] == "BLOCKING"
    assert blocking_rows[0]["resolution_status"] == "OPEN"
    # The sibling request's finding never leaks through either read.
    assert sibling["id"] not in {row["id"] for row in all_rows}
    assert sibling["id"] not in {row["id"] for row in blocking_rows}

    parent = read_drafting_request(world, request_a["id"])
    assert parent["advisory_conflict_count"] == 2
    assert parent["blocking_conflict_count"] == 1
    assert parent["open_blocking_conflict_count"] == 1
    # Filed during RESEARCH, so the bounce-back cascade stayed dormant.
    assert parent["status"] == "RESEARCH"
