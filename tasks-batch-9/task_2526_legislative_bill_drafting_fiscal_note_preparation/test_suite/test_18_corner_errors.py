"""Errors: the not-found family, the authentication and authorization rungs."""

from test_helpers import (
    add_agency,
    add_committee,
    add_drafter,
    add_member,
    ADMIN,
    api_client,
    ApiErrorId,
    append_cost_estimate,
    apply_correction,
    assert_instant,
    certify_draft,
    CLERK,
    complete_research_payload,
    create_agency,
    create_agency_payload,
    create_committee_payload,
    create_cost_estimate_payload,
    create_drafting_request_payload,
    create_fiscal_note_request_payload,
    create_member,
    create_member_payload,
    create_referral_payload,
    create_session,
    create_session_payload,
    create_statutory_conflict_payload,
    create_technical_correction_payload,
    draft_amendment_payload,
    enroll_bill,
    file_statutory_conflict,
    FISCAL_OFFICER,
    get_success_data,
    introduce_bill,
    make_agency_analyst_headers,
    make_member_headers,
    NON_EXISTENT_UUID,
    pass_bill,
    propose_correction,
    read_agency,
    read_amendment,
    read_bill,
    read_committee,
    read_correction,
    read_drafter,
    read_drafting_request,
    read_enrolled_bill,
    read_note,
    read_referral,
    read_session,
    refer_bill,
    report_payload,
    report_referral,
    request_amendment,
    resolve_conflict_payload,
    resolve_statutory_conflict,
    return_note,
    route_fiscal_note,
    set_clock,
    setup_certified_note,
    setup_introduced_bill,
    setup_request_in_drafting,
    setup_request_in_research,
    setup_world,
    sign_enrollment,
    submit_note,
    submit_note_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

CANONICAL_CLOCK = "2026-09-01T00:00:00Z"


def test_every_path_identifier_has_its_own_not_found_code_on_its_own_read_route():
    """PRD: "Identifiers that appear in a URL path are resolved strictly from left to
    right, and the first unresolvable segment decides the error." and "Each entity has
    its own not-found identifier, all of them HTTP 404: `ERR_SESSION_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_DRAFTER_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`,
    `ERR_COMMITTEE_NOT_FOUND`, `ERR_DRAFTING_REQUEST_NOT_FOUND`,
    `ERR_STATUTORY_CONFLICT_NOT_FOUND`, `ERR_BILL_NOT_FOUND`,
    `ERR_COMMITTEE_REFERRAL_NOT_FOUND`, `ERR_FISCAL_NOTE_REQUEST_NOT_FOUND`,
    `ERR_AMENDMENT_NOT_FOUND`, `ERR_ENROLLED_BILL_NOT_FOUND` and
    `ERR_TECHNICAL_CORRECTION_NOT_FOUND`." and "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/errors/all_thirteen_path_id_not_found_codes_are_reachable_on_their_own_read_route
    """
    probes = [
        (api_client.get_session(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_SESSION_NOT_FOUND),
        (api_client.get_member(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api_client.get_drafter(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_DRAFTER_NOT_FOUND),
        (api_client.get_agency(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_AGENCY_NOT_FOUND),
        (
            api_client.get_committee(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_COMMITTEE_NOT_FOUND,
        ),
        (
            api_client.get_drafting_request(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_DRAFTING_REQUEST_NOT_FOUND,
        ),
        (
            api_client.get_statutory_conflict(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_STATUTORY_CONFLICT_NOT_FOUND,
        ),
        (api_client.get_bill(NON_EXISTENT_UUID, CLERK), ApiErrorId.ERR_BILL_NOT_FOUND),
        (
            api_client.get_committee_referral(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_COMMITTEE_REFERRAL_NOT_FOUND,
        ),
        (
            api_client.get_fiscal_note_request(NON_EXISTENT_UUID, FISCAL_OFFICER),
            ApiErrorId.ERR_FISCAL_NOTE_REQUEST_NOT_FOUND,
        ),
        (
            api_client.get_amendment(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_AMENDMENT_NOT_FOUND,
        ),
        (
            api_client.get_enrolled_bill(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_ENROLLED_BILL_NOT_FOUND,
        ),
        (
            api_client.get_technical_correction(NON_EXISTENT_UUID, CLERK),
            ApiErrorId.ERR_TECHNICAL_CORRECTION_NOT_FOUND,
        ),
    ]
    assert len(probes) == 13

    seen = []
    for response, expected in probes:
        body = validate_error(response, expected.value, 404)
        assert isinstance(body["message"], str) and body["message"], (
            f"{expected.value} must carry a non-empty human-readable message"
        )
        seen.append(body["error_id"])

    # None of the thirteen was aliased onto a shared generic not-found code.
    assert len(set(seen)) == 13


def test_a_missing_or_unknown_role_is_refused_before_the_path_is_even_resolved():
    """PRD: "Every request — reads included — must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the capacity in which
    that principal is acting." and "If either header is absent, or if `X-User-Role` is
    not one of the seven declared role names, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)." and "Evaluation stops at the first violated
    rung." and "**Path existence.** Every identifier in the path resolves, left to
    right — otherwise the matching not-found identifier."

    Design: Corner/errors/absent_or_unknown_role_header_returns_unauthenticated_before_anything_else
    """
    # No role header at all, aimed at an identifier that could never resolve.
    no_role = api_client.get_session(NON_EXISTENT_UUID, {"X-User-ID": "test-clerk-1"})
    validate_error(no_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    undeclared_role = api_client.list_sessions(
        {"X-User-ID": "test-governor-staff-1", "X-User-Role": "GovernorStaff"}
    )
    # An undeclared role name is unauthenticated, never merely unauthorized.
    validate_error(undeclared_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    no_user_id = api_client.create_session(
        create_session_payload(name="Unauthenticated attempt"),
        {"X-User-Role": "PlatformAdmin"},
    )
    validate_error(no_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    rows, meta = validate_paginated(api_client.list_sessions(ADMIN))
    assert meta["total_count"] == 0
    assert rows == []


def test_a_declared_role_outside_the_endpoints_list_is_refused_and_writes_nothing():
    """PRD: "**Endpoint role.** The acting role appears in the target endpoint's
    authorized list — otherwise `ERR_UNAUTHORIZED`." and "This role cannot read the
    drafting pipeline at all — no drafting-request or statutory-conflict read is
    granted to it, so such an attempt is stopped by the endpoint role check with
    `ERR_UNAUTHORIZED` rather than by any confidentiality rule." and "When a single
    request violates several rules at once, exactly one error is reported, and which one
    is determined by a fixed ladder evaluated top to bottom."

    Design: Corner/errors/role_outside_an_endpoints_declared_set_returns_unauthorized_and_writes_nothing
    """
    set_clock(CANONICAL_CLOCK)
    session = create_session()
    member = create_member()
    agency = create_agency()

    convene = api_client.convene_session(session["id"], FISCAL_OFFICER)
    validate_error(convene, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert get_success_data(api_client.get_session(session["id"], CLERK))["status"] == "PENDING"

    register = api_client.create_member(
        create_member_payload(full_name="Clerk attempt"), CLERK
    )
    validate_error(register, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    advance = api_client.set_clock("2026-09-02T00:00:00Z", make_member_headers(member["id"]))
    validate_error(advance, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    # Monotonicity is inclusive, so re-setting the canonical instant only succeeds
    # if the refused advance really left the clock where it was.
    set_clock(CANONICAL_CLOCK)

    # The endpoint role rung outranks path existence: an agency analyst reading the
    # drafting pipeline is refused before the nil identifier is ever looked up.
    pipeline = api_client.get_drafting_request(
        NON_EXISTENT_UUID, make_agency_analyst_headers(agency["id"])
    )
    validate_error(pipeline, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_a_pending_session_and_an_adjourned_session_refuse_a_filing_differently():
    """PRD: "The session-lifecycle rung sits **above** the target-state rung, so a
    write attempted against a still-`PENDING` session reports `ERR_SESSION_NOT_CONVENED`
    rather than an invalid-state error, and any business write attempted after
    adjournment reports `ERR_SESSION_ADJOURNED` — including a second adjournment
    attempt." and "A `Clerk` adjourns a `CONVENED` session — adjourning one that is not
    `CONVENED` is `ERR_INVALID_SESSION_STATE`, and a second adjournment of an
    already-`ADJOURNED` session is `ERR_SESSION_ADJOURNED`." and "The session's `status`
    becomes `ADJOURNED` and `adjourned_utc` is stamped from the logical clock." and
    "Every drafting request of this session in `SUBMITTED`, `RESEARCH`, `DRAFTING`,
    `RETURNED_FOR_CLARIFICATION` or `DRAFT_READY` moves to `LAPSED` with `sla_due_utc`
    cleared to null."

    Design: Corner/errors/session_not_convened_and_session_adjourned_are_two_distinct_conflicts
    """
    set_clock(CANONICAL_CLOCK)
    session = create_session()
    member = create_member()
    member_headers = make_member_headers(member["id"])

    def file(subject, summary):
        return api_client.create_drafting_request(
            create_drafting_request_payload(
                session["id"],
                subject=subject,
                summary=summary,
                requested_sections_count=1,
                target_code_chapter="Title 1",
                confidentiality="PUBLIC",
                priority_flag=False,
                appropriation_requested_cents=0,
            ),
            member_headers,
        )

    too_early = file("Filed too early", "Filed before convening.")
    validate_error(too_early, ApiErrorId.ERR_SESSION_NOT_CONVENED.value, 409)

    get_success_data(api_client.convene_session(session["id"], CLERK))
    accepted = validate_success(file("Filed in session", "Filed while convened."), 201)
    assert accepted["status"] == "SUBMITTED"

    adjourned = validate_success(api_client.adjourn_session(session["id"], CLERK), 200)
    assert adjourned["status"] == "ADJOURNED"
    assert_instant(adjourned["adjourned_utc"], CANONICAL_CLOCK)
    lapsed = get_success_data(api_client.get_drafting_request(accepted["id"], CLERK))
    assert lapsed["status"] == "LAPSED"
    assert lapsed["sla_due_utc"] is None

    too_late = file("Filed too late", "Filed after sine die adjournment.")
    # A different code from the pending refusal, on the very same endpoint.
    validate_error(too_late, ApiErrorId.ERR_SESSION_ADJOURNED.value, 409)

    again = api_client.adjourn_session(session["id"], CLERK)
    validate_error(again, ApiErrorId.ERR_SESSION_ADJOURNED.value, 409)


def test_ownership_is_checked_against_the_sponsor_the_assignee_and_the_routed_agency():
    """PRD: "Ownership is enforced on exactly seven operations: withdrawing a drafting
    request and completing its research; recording a statutory conflict; appending a
    cost estimate line; submitting a fiscal note; drafting an amendment; and reading a
    single agency record when the acting role is `AgencyAnalyst`." and "A `Member` acts
    only on their own drafting requests and amendments; an `AgencyAnalyst` files and
    submits only notes routed to their own agency and reads only their own `Agency` row;
    a `Drafter` acts only where assigned." and "Any breach is `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)." and "**Ownership.** An entity-backed role acts only on what it owns —
    otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/errors/acting_on_another_owners_resource_returns_not_resource_owner
    """
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _rival, rival_headers = add_member(
        world, full_name="Rep Delta", chamber="HOUSE", party="IND", priority_slots_total=2
    )
    _idle_drafter, idle_drafter_headers = add_drafter(world, full_name="Drafter Two")
    uninvolved_agency = add_agency(
        world,
        name="Dept of Health",
        agency_code="DOH",
        status="ACTIVE",
        max_open_requests=3,
    )
    outsider_analyst = make_agency_analyst_headers(uninvolved_agency["id"])

    request = setup_request_in_research(
        world,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    _second, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-06T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )
    note = route_fiscal_note(world, bill)

    wrong_sponsor = api_client.withdraw_drafting_request(
        request["id"],
        withdraw_payload(
            withdrawal_reason="Withdrawn by a member who does not sponsor it."
        ),
        rival_headers,
    )
    validate_error(wrong_sponsor, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert read_drafting_request(world, request["id"])["status"] == "RESEARCH"

    wrong_drafter = api_client.complete_research(
        request["id"], complete_research_payload(2), idle_drafter_headers
    )
    validate_error(wrong_drafter, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    wrong_filer = api_client.create_statutory_conflict(
        create_statutory_conflict_payload(
            request["id"],
            code_citation="6-1-101",
            conflict_type="STYLE_VIOLATION",
            severity="ADVISORY",
        ),
        idle_drafter_headers,
    )
    validate_error(wrong_filer, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert read_drafting_request(world, request["id"])["advisory_conflict_count"] == 0

    wrong_agency_line = api_client.create_cost_estimate(
        note["id"],
        create_cost_estimate_payload(
            note["version"],
            personnel_cost_cents=1_000_000,
            operating_cost_cents=1_000_000,
            assumption_note="Filed by the wrong agency.",
        ),
        outsider_analyst,
    )
    validate_error(wrong_agency_line, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert read_note(world, note["id"])["version"] == note["version"]

    # Ownership sits far above the cost-estimate presence gate, so the outsider is
    # told about ownership even though this note carries no estimate lines at all.
    wrong_agency_submit = api_client.submit_fiscal_note_request(
        note["id"],
        submit_note_payload(submission_note="Submitted by the wrong agency."),
        outsider_analyst,
    )
    validate_error(wrong_agency_submit, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert read_note(world, note["id"])["status"] == "ROUTED"

    rightful = validate_success(
        api_client.complete_research(
            request["id"], complete_research_payload(2), world["drafter_headers"]
        ),
        200,
    )
    assert rightful["status"] == "DRAFTING"


def test_referral_refuses_a_foreign_session_a_foreign_chamber_then_a_full_committee():
    """PRD: "The committee must belong to the bill's own session, or the call is
    `ERR_COMMITTEE_SESSION_MISMATCH`, and to the bill's own `chamber`, or it is
    `ERR_COMMITTEE_CHAMBER_MISMATCH`." and "The committee's `active_referral_count` must
    be strictly below its `max_concurrent_referrals`, or the call is
    `ERR_COMMITTEE_REFERRAL_CAPACITY_EXCEEDED`." and "A successful referral is created
    in `status` `IN_COMMITTEE` with `reported_utc` null."

    Design: Corner/errors/referral_creation_refuses_a_foreign_session_a_foreign_chamber_and_a_full_committee
    """
    world = setup_world(session_overrides={"name": "2027 Regular Session"})
    house_committee = add_committee(
        world,
        chamber="HOUSE",
        name="House Appropriations",
        is_fiscal_committee=True,
        max_concurrent_referrals=1,
    )
    senate_committee = add_committee(
        world,
        chamber="SENATE",
        name="Senate Finance",
        is_fiscal_committee=True,
        max_concurrent_referrals=2,
    )
    _request_one, first_bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, second_bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Public notice consolidation",
        summary="Consolidate statutory public notices.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )

    other_world = setup_world(session_overrides={"name": "2027 Special Session"})
    foreign_committee = add_committee(
        other_world,
        chamber="HOUSE",
        name="House Appropriations",
        is_fiscal_committee=True,
        max_concurrent_referrals=2,
    )

    foreign_session = api_client.create_referral(
        first_bill["id"],
        create_referral_payload(foreign_committee["id"]),
        CLERK,
    )
    validate_error(foreign_session, ApiErrorId.ERR_COMMITTEE_SESSION_MISMATCH.value, 422)

    foreign_chamber = api_client.create_referral(
        first_bill["id"],
        create_referral_payload(senate_committee["id"]),
        CLERK,
    )
    validate_error(foreign_chamber, ApiErrorId.ERR_COMMITTEE_CHAMBER_MISMATCH.value, 422)

    accepted = validate_success(
        api_client.create_referral(
            first_bill["id"], create_referral_payload(house_committee["id"]), CLERK
        ),
        201,
    )
    assert accepted["status"] == "IN_COMMITTEE"
    assert accepted["reported_utc"] is None
    filled = read_committee(world, house_committee["id"])
    assert filled["active_referral_count"] == filled["max_concurrent_referrals"] == 1

    # A window a fortnight clear of the occupied one, so only capacity can explain it.
    over_capacity = api_client.create_referral(
        second_bill["id"],
        create_referral_payload(
            house_committee["id"],
            hearing_window_start_utc="2026-10-19T14:00:00Z",
            hearing_window_end_utc="2026-10-19T16:00:00Z",
        ),
        CLERK,
    )
    validate_error(
        over_capacity, ApiErrorId.ERR_COMMITTEE_REFERRAL_CAPACITY_EXCEEDED.value, 409
    )
    assert read_bill(world, second_bill["id"])["legislative_status"] == "INTRODUCED"
    assert read_committee(world, house_committee["id"])["active_referral_count"] == 1


def test_the_fiscal_lane_reaches_both_uniqueness_guards_and_the_one_open_note_rule():
    """PRD: "An agency carries a `name`, a short `agency_code` that must be unique
    across all agencies — a repeat is `ERR_DUPLICATE_AGENCY_CODE` — an optional `status`
    of `ACTIVE` or `INACTIVE` defaulting to `ACTIVE`, and an optional
    `max_open_requests` defaulting to 3 and required to be at least 1." and "And no
    other note of this same bill may already be in `ROUTED`, `SUBMITTED` or
    `RETURNED_FOR_REVISION`, or the call is `ERR_FISCAL_NOTE_ALREADY_OPEN`; one open
    pricing exercise per bill at a time." and "A line duplicating an existing line's
    combination of `fiscal_year`, `scenario` and `revision_round` on the same note is
    refused with `ERR_DUPLICATE_COST_ESTIMATE`." and "The note moves from `SUBMITTED` to
    `RETURNED_FOR_REVISION` and its `revision_round` rises by one, which flips
    `included_in_certification` to false on every cost estimate line of the prior round
    and drops them out of every total — the analyst must file a fresh set."

    Design: Corner/errors/duplicate_and_already_open_guards_are_each_reachable_on_the_fiscal_lane
    """
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    spare_agency = add_agency(
        world,
        name="Dept of Health",
        agency_code="DOH",
        status="ACTIVE",
        max_open_requests=3,
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
    )
    note = route_fiscal_note(world, bill)

    duplicate_code = api_client.create_agency(
        create_agency_payload(
            name="Department of Revenue (duplicate registration)",
            agency_code="DOR",
            status="ACTIVE",
            max_open_requests=3,
        ),
        ADMIN,
    )
    validate_error(duplicate_code, ApiErrorId.ERR_DUPLICATE_AGENCY_CODE.value, 409)

    second_note = api_client.create_fiscal_note_request(
        bill["id"],
        create_fiscal_note_request_payload(spare_agency["id"], methodology="FULL_ABSORPTION"),
        world["fiscal_officer_headers"],
    )
    validate_error(second_note, ApiErrorId.ERR_FISCAL_NOTE_ALREADY_OPEN.value, 409)
    assert read_agency(world, spare_agency["id"])["open_request_count"] == 0

    baseline_2027 = {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 5_000_000,
        "operating_cost_cents": 1_000_000,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "Round 0 FY2027 baseline.",
    }
    append_cost_estimate(world, note, **baseline_2027)

    held_version = read_note(world, note["id"])["version"]
    duplicate_line = api_client.create_cost_estimate(
        note["id"],
        create_cost_estimate_payload(
            held_version,
            **dict(baseline_2027, personnel_cost_cents=5_500_000,
                   assumption_note="Second round 0 FY2027 baseline."),
        ),
        world["analyst_headers"],
    )
    validate_error(duplicate_line, ApiErrorId.ERR_DUPLICATE_COST_ESTIMATE.value, 409)
    assert read_note(world, note["id"])["version"] == held_version

    # The scenario coordinate of the key makes the same year legal again.
    append_cost_estimate(
        world,
        note,
        **dict(baseline_2027, scenario="HIGH", personnel_cost_cents=5_500_000,
               assumption_note="Round 0 FY2027 high scenario."),
    )
    append_cost_estimate(
        world,
        note,
        **dict(baseline_2027, fiscal_year=2028, personnel_cost_cents=3_000_000,
               assumption_note="Round 0 FY2028 baseline."),
    )

    submitted = submit_note(world, note, submission_note="Round 0 complete.")
    assert submitted["status"] == "SUBMITTED"
    returned = return_note(world, note, return_reason="Refile on the revised caseload.")
    assert returned["status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == 1

    # And the revision_round coordinate makes it legal a third time.
    refiled = append_cost_estimate(
        world,
        note,
        **dict(baseline_2027, personnel_cost_cents=5_200_000,
               assumption_note="Round 1 FY2027 baseline."),
    )
    assert refiled["revision_round"] == 1
    assert refiled["included_in_certification"] is True

    rows, meta = validate_paginated(
        api_client.list_cost_estimates(note["id"], world["analyst_headers"])
    )
    assert meta["total_count"] == 4
    keys = [(row["fiscal_year"], row["scenario"], row["revision_round"]) for row in rows]
    assert len(set(keys)) == 4


def test_the_four_remaining_invalid_state_codes_each_answer_a_repeated_settled_action():
    """PRD: "A conflict already in `RESOLVED` or `WAIVED` cannot be revisited: a second
    attempt is `ERR_INVALID_CONFLICT_STATE`." and "The referral must still be
    `IN_COMMITTEE`, or the call is `ERR_INVALID_REFERRAL_STATE`, and the logical clock
    must be at or before that referral's `report_deadline_utc` regardless of outcome, or
    the call is `ERR_COMMITTEE_REPORT_DEADLINE_PASSED`." and "The correction must be
    `PROPOSED` — one already `APPLIED` or `REJECTED` yields
    `ERR_INVALID_CORRECTION_STATE` — and the enrollment must not have reached
    `TRANSMITTED`." and "The enrollment must be in `PREPARED`, `ORIGIN_SIGNED` or
    `SECOND_SIGNED`; a correction against a `TRANSMITTED` enrollment is
    `ERR_INVALID_ENROLLMENT_STATE`."

    Design: Corner/errors/the_four_remaining_invalid_state_codes_are_each_reachable_by_repeating_a_settled_action
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Judiciary",
            "is_fiscal_committee": False,
            "max_concurrent_referrals": 2,
        },
    )
    request = setup_request_in_drafting(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Guardianship notice reform",
        summary="Modernize guardianship notice.",
        target_code_chapter="Title 15",
        appropriation_requested_cents=0,
    )
    conflict = file_statutory_conflict(
        world, request, severity="ADVISORY", code_citation="15-3-204"
    )
    settled_conflict = resolve_statutory_conflict(world, conflict)
    assert settled_conflict["resolution_status"] == "RESOLVED"

    certify_draft(world, request)
    bill = introduce_bill(world, request)
    referral = refer_bill(world, bill)
    settled_referral = report_referral(world, referral, "FAVORABLE")
    assert settled_referral["status"] == "REPORTED_FAVORABLE"
    pass_bill(world, bill)
    enrolled = enroll_bill(world, bill)

    correction = propose_correction(world, enrolled, correction_type="CITATION")
    applied = apply_correction(world, correction)
    assert applied["status"] == "APPLIED"

    # 1. The correction is settled while the enrollment is still PREPARED, so only the
    #    correction's own status can explain the refusal.
    reapplied = api_client.apply_technical_correction(
        correction["id"], world["counsel_headers"]
    )
    validate_error(reapplied, ApiErrorId.ERR_INVALID_CORRECTION_STATE.value, 409)
    assert read_correction(world, correction["id"])["status"] == "APPLIED"

    for role in ("SPEAKER", "SENATE_PRESIDENT", "GOVERNOR_TRANSMITTAL"):
        step = sign_enrollment(world, enrolled, role)
    assert step["status"] == "TRANSMITTED"
    assert step["expected_next_signature"] == "NONE"
    assert step["open_corrections_count"] == 0

    # 2. A second correction is now refused by the enrollment rather than by itself.
    transmitted_version = read_enrolled_bill(world, enrolled["id"])["version"]
    late_correction = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            transmitted_version,
            correction_type="NUMBERING",
            description="Renumber a subsection after transmittal.",
        ),
        world["drafter_headers"],
    )
    validate_error(late_correction, ApiErrorId.ERR_INVALID_ENROLLMENT_STATE.value, 409)
    unchanged_enrollment = read_enrolled_bill(world, enrolled["id"])
    assert unchanged_enrollment["version"] == transmitted_version
    assert unchanged_enrollment["open_corrections_count"] == 0
    assert unchanged_enrollment["expected_next_signature"] == "NONE"

    # 3. The conflict was disposed of before the bill even existed.
    rework = api_client.resolve_statutory_conflict(
        conflict["id"], resolve_conflict_payload("WAIVED"), world["counsel_headers"]
    )
    validate_error(rework, ApiErrorId.ERR_INVALID_CONFLICT_STATE.value, 409)
    assert read_drafting_request(world, request["id"])["open_blocking_conflict_count"] == 0

    # 4. The report deadline is still 2026-10-12T16:00:00Z and the clock has not moved,
    #    so the referral's own status is the only live gate.
    assert_instant(settled_referral["report_deadline_utc"], "2026-10-12T16:00:00Z")
    rereport = api_client.report_referral(
        referral["id"], report_payload("UNFAVORABLE"), world["clerk_headers"]
    )
    validate_error(rereport, ApiErrorId.ERR_INVALID_REFERRAL_STATE.value, 409)
    survivor = read_bill(world, bill["id"])
    assert survivor["legislative_status"] == "TRANSMITTED"
    assert read_referral(world, referral["id"])["status"] == "REPORTED_FAVORABLE"


def test_each_deadline_code_fires_when_the_clock_passes_its_own_boundary():
    """PRD: "Its `report_deadline_utc` is the earlier of the hearing window's end plus
    seven days and the session's `committee_report_deadline_utc`." and "A
    `COMMITTEE`-stage amendment is allowed a base window of four hours; a `FLOOR`-stage
    amendment is allowed one hour." and "If the interval from `requested_utc` to the
    session's `sine_die_utc` is 48 hours or less, that base window is halved and then
    floored to whole minutes; otherwise the base window stands unchanged. The result is
    added to `requested_utc` to give `turnaround_deadline_utc`." and "The logical clock
    must be at or before `turnaround_deadline_utc`, or the call is
    `ERR_AMENDMENT_TURNAROUND_EXPIRED`." and "the logical clock must be at or before that
    referral's `report_deadline_utc` regardless of outcome, or the call is
    `ERR_COMMITTEE_REPORT_DEADLINE_PASSED`." and "And the logical clock must be at or
    before the session's `sine_die_utc`, or the call is `ERR_SINE_DIE_PASSED`."

    Design: Corner/errors/each_deadline_code_fires_when_the_clock_passes_its_own_boundary
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Judiciary",
            "is_fiscal_committee": False,
            "max_concurrent_referrals": 2,
        },
    )
    _request_one, early_bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Guardianship notice reform",
        summary="Modernize guardianship notice.",
        target_code_chapter="Title 15",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, late_bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Probate filing fees",
        summary="Restate the probate filing fee schedule.",
        target_code_chapter="Title 15",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    early_referral = refer_bill(world, early_bill)
    assert_instant(early_referral["report_deadline_utc"], "2026-10-12T16:00:00Z")
    late_referral = refer_bill(
        world,
        late_bill,
        hearing_window_start_utc="2026-10-20T14:00:00Z",
        hearing_window_end_utc="2026-10-20T16:00:00Z",
    )
    assert_instant(late_referral["report_deadline_utc"], "2026-10-27T16:00:00Z")

    # Requested well clear of sine die, so the committee window keeps its full four hours.
    set_clock("2026-10-06T00:00:00Z")
    amendment = request_amendment(
        world,
        early_bill,
        stage="COMMITTEE",
        committee_referral_id=early_referral["id"],
        summary="Narrow the notice exemption.",
        fiscal_impact_delta_cents=0,
        drafting_start_utc="2026-10-07T00:00:00Z",
        drafting_due_utc="2026-10-07T04:00:00Z",
    )
    assert_instant(amendment["requested_utc"], "2026-10-06T00:00:00Z")
    assert_instant(amendment["turnaround_deadline_utc"], "2026-10-06T04:00:00Z")

    set_clock("2026-10-06T04:00:01Z")
    expired = api_client.draft_amendment(
        amendment["id"], draft_amendment_payload(), world["drafter_headers"]
    )
    validate_error(expired, ApiErrorId.ERR_AMENDMENT_TURNAROUND_EXPIRED.value, 409)
    stalled = read_amendment(world, amendment["id"])
    assert stalled["status"] == "REQUESTED"
    assert stalled["drafted_utc"] is None
    assert read_drafter(world)["active_engagement_count"] == 0

    # Inside the later referral's own deadline, the very same report call is admitted.
    set_clock("2026-10-21T00:00:00Z")
    reported = validate_success(
        api_client.report_referral(
            late_referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
        ),
        200,
    )
    assert reported["status"] == "REPORTED_FAVORABLE"
    assert read_bill(world, late_bill["id"])["legislative_status"] == "REPORTED"

    set_clock("2026-11-20T18:00:01Z")
    too_late = api_client.report_referral(
        early_referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
    )
    validate_error(too_late, ApiErrorId.ERR_COMMITTEE_REPORT_DEADLINE_PASSED.value, 409)
    assert read_referral(world, early_referral["id"])["status"] == "IN_COMMITTEE"
    assert read_bill(world, early_bill["id"])["legislative_status"] == "REFERRED"

    # The reported bill has nothing outstanding but one second of session left over.
    adjourned_out = api_client.pass_bill(late_bill["id"], world["clerk_headers"])
    validate_error(adjourned_out, ApiErrorId.ERR_SINE_DIE_PASSED.value, 409)
    assert read_bill(world, late_bill["id"])["legislative_status"] == "REPORTED"
    assert read_session(world)["status"] == "CONVENED"


def test_the_fiscal_committee_guard_reads_the_session_posture_and_the_bills_own_note():
    """PRD: "At the low boundary, a direct subtotal of exactly 10,000,000 yields a
    contingency of 500,000 and a certified total of 10,500,000." and "It additionally
    enforces the constrained-posture rule: while the session's `fiscal_posture` is
    `CONSTRAINED`, a bill carrying a `CERTIFIED` fiscal note whose `certified_total_cents`
    is strictly greater than 0 may only be reported out by a committee whose
    `is_fiscal_committee` is true." and "Stated as the precondition the report action
    evaluates: the session's posture is `NORMAL`, or the bill has no `CERTIFIED` note
    with a positive `certified_total_cents`, or the reporting committee is a fiscal
    committee. A report that satisfies none of those three is refused with
    `ERR_FISCAL_COMMITTEE_REFERRAL_REQUIRED`." and "If — and only if — no referral of
    that bill remains `IN_COMMITTEE`, the bill advances from `REFERRED` to `REPORTED`; a
    bill with a second committee still holding it stays in `REFERRED`."

    Design: Corner/errors/fiscal_committee_referral_is_required_only_once_the_session_posture_turns_constrained
    """
    boundary_lines = [
        {
            "fiscal_year": 2027,
            "scenario": "BASELINE",
            "personnel_cost_cents": 5_000_000,
            "operating_cost_cents": 1_000_000,
            "one_time_cost_cents": 0,
            "fte_count": 1.0,
            "revenue_impact_cents": 0,
            "assumption_note": "FY2027 sits the subtotal on the contingency boundary.",
        },
        {
            "fiscal_year": 2028,
            "scenario": "BASELINE",
            "personnel_cost_cents": 3_000_000,
            "operating_cost_cents": 1_000_000,
            "one_time_cost_cents": 0,
            "fte_count": 1.0,
            "revenue_impact_cents": 0,
            "assumption_note": "FY2028 completes the required years.",
        },
    ]
    world = setup_world(
        with_agency=True,
        session_overrides={"constrained_threshold_cents": 10_000_000},
    )
    fiscal_committee = add_committee(
        world,
        chamber="HOUSE",
        name="House Appropriations",
        is_fiscal_committee=True,
        max_concurrent_referrals=2,
    )
    policy_committee = add_committee(
        world,
        chamber="HOUSE",
        name="House Judiciary",
        is_fiscal_committee=False,
        max_concurrent_referrals=2,
    )
    _request_one, priced_bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Guardianship caseload relief",
        summary="Fund additional guardianship staff.",
        target_code_chapter="Title 15",
        appropriation_requested_cents=5_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, free_bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Probate form simplification",
        summary="Simplify the probate inventory form.",
        target_code_chapter="Title 15",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    policy_referral = refer_bill(world, priced_bill, policy_committee)
    fiscal_referral = refer_bill(
        world,
        priced_bill,
        fiscal_committee,
        hearing_window_start_utc="2026-10-07T14:00:00Z",
        hearing_window_end_utc="2026-10-07T16:00:00Z",
    )
    assert fiscal_referral["referral_order"] == 2
    free_referral = refer_bill(
        world,
        free_bill,
        policy_committee,
        hearing_window_start_utc="2026-10-09T14:00:00Z",
        hearing_window_end_utc="2026-10-09T16:00:00Z",
    )

    assert read_session(world)["fiscal_posture"] == "NORMAL"
    note = setup_certified_note(world, priced_bill, lines=boundary_lines)
    assert note["direct_cost_cents"] == 10_000_000
    assert note["contingency_cents"] == 500_000
    assert note["certified_total_cents"] == 10_500_000
    constrained = read_session(world)
    assert constrained["certified_fiscal_total_cents"] == 10_500_000
    assert constrained["fiscal_posture"] == "CONSTRAINED"

    refused = api_client.report_referral(
        policy_referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
    )
    validate_error(
        refused, ApiErrorId.ERR_FISCAL_COMMITTEE_REFERRAL_REQUIRED.value, 409
    )
    assert read_referral(world, policy_referral["id"])["status"] == "IN_COMMITTEE"
    assert read_committee(world, policy_committee["id"])["active_referral_count"] == 2

    # Same constrained posture, same non-fiscal committee — but this bill has no note.
    free_reported = validate_success(
        api_client.report_referral(
            free_referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
        ),
        200,
    )
    assert free_reported["status"] == "REPORTED_FAVORABLE"
    assert read_bill(world, free_bill["id"])["fiscal_status"] == "NOT_REQUIRED"
    assert read_bill(world, free_bill["id"])["legislative_status"] == "REPORTED"

    fiscal_reported = validate_success(
        api_client.report_referral(
            fiscal_referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
        ),
        200,
    )
    assert fiscal_reported["status"] == "REPORTED_FAVORABLE"
    assert read_committee(world, fiscal_committee["id"])["active_referral_count"] == 0
    # The policy committee still holds a referral, so the bill cannot bubble up.
    assert read_bill(world, priced_bill["id"])["legislative_status"] == "REFERRED"


def test_the_error_envelope_is_shaped_identically_across_every_status_class():
    """PRD: "All error API responses (4xx status codes) follow this standard envelope
    format:" and "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`." and "The `error_id` is a unique, machine-readable
    string that identifies the specific error." and "The `message` provides a
    human-readable explanation of what went wrong." and "**Payload shape.** Every
    required field present, every enum value declared, every `*_cents` value honouring
    its minimum, every interval ending strictly after it starts, and
    `required_fiscal_years` a non-empty strictly ascending array of integers — otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/errors/the_error_envelope_is_byte_shaped_the_same_for_every_status_class_including_unauthenticated
    """
    world = setup_world()
    session_id = world["session"]["id"]

    probes = [
        (
            api_client.create_committee(
                session_id, create_committee_payload(chamber="TRIBUNAL"), CLERK
            ),
            400,
            ApiErrorId.ERR_INVALID_REQUEST,
        ),
        (
            api_client.get_session(session_id, {"X-User-ID": "test-clerk-1"}),
            401,
            ApiErrorId.ERR_UNAUTHENTICATED,
        ),
        (
            api_client.convene_session(session_id, FISCAL_OFFICER),
            403,
            ApiErrorId.ERR_UNAUTHORIZED,
        ),
        (
            api_client.get_session(NON_EXISTENT_UUID, CLERK),
            404,
            ApiErrorId.ERR_SESSION_NOT_FOUND,
        ),
        (
            api_client.convene_session(session_id, CLERK),
            409,
            ApiErrorId.ERR_INVALID_SESSION_STATE,
        ),
        (
            api_client.set_clock_raw({"current_utc": "2026-08-31T00:00:00Z"}, ADMIN),
            422,
            ApiErrorId.ERR_CLOCK_NOT_MONOTONIC,
        ),
    ]
    assert len({status for _response, status, _code in probes}) == 6

    request_ids = []
    for response, status, code in probes:
        validate_error(response, code.value, status)
        body = response.json()
        assert set(body) == {"meta", "response_type", "data"}, (
            f"{code.value} envelope carried top-level keys {sorted(body)}"
        )
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
            f"{code.value} meta carried keys {sorted(body['meta'])}"
        )
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert set(body["data"]) == {"error_id", "message"}, (
            f"{code.value} data carried keys {sorted(body['data'])}"
        )
        assert body["data"]["message"].strip()
        request_ids.append(body["meta"]["api_request_id"])

    # A unique correlation identifier per request, not a constant stamped in a template.
    assert len(set(request_ids)) == 6
    # Nothing above was allowed to land: the session is still exactly as it was.
    assert read_session(world)["status"] == "CONVENED"
