"""State machines: transitions, preconditions, terminal states and cascades."""

from test_helpers import (
    ADMIN,
    CLERK,
    STANDARD_COST_LINES,
    ApiErrorId,
    add_committee,
    api_client,
    assert_drafting_request,
    assert_instant,
    assign_request,
    assert_session,
    certify_draft_payload,
    clarify_payload,
    complete_research_payload,
    complete_research,
    create_bill_payload,
    create_drafting_request_payload,
    create_member_payload,
    create_session_payload,
    create_statutory_conflict_payload,
    file_drafting_request,
    file_statutory_conflict,
    get_success_data,
    make_member_headers,
    read_agency,
    read_amendment,
    read_bill,
    read_committee,
    read_drafter,
    read_drafting_request,
    read_member,
    read_note,
    read_referral,
    read_session,
    refer_bill,
    report_payload,
    request_amendment,
    rescind_amendment_payload,
    resolve_statutory_conflict,
    set_clock,
    setup_adopted_amendment,
    setup_bill_with_certified_note,
    setup_certified_note,
    setup_draft_ready_request,
    setup_introduced_bill,
    setup_request_in_research,
    setup_world,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

CANONICAL_CLOCK = "2026-09-01T00:00:00Z"


def test_convening_a_pending_session_opens_it_for_business_writes():
    """PRD: "A `Clerk` convenes the session, moving `status` from `PENDING` to
    `CONVENED` and stamping `convened_utc` with the logical clock." and "The
    distinction matters operationally: committees, members, drafting attorneys and
    agencies may all be registered while the session is still `PENDING`, but no
    drafting request, bill, referral, fiscal note or amendment may be written until
    the session is `CONVENED`." and "The session's `version` rises by one on both
    convening and adjournment."

    Design: Corner/state_machines/session_convene_moves_pending_to_convened_and_stamps_convened_utc
    """
    set_clock(CANONICAL_CLOCK)
    session = get_success_data(api_client.create_session(create_session_payload(), ADMIN))
    member = get_success_data(api_client.create_member(create_member_payload(), ADMIN))

    convened = validate_success(api_client.convene_session(session["id"], CLERK), 200)

    assert_session(convened)
    assert convened["status"] == "CONVENED"
    assert_instant(convened["convened_utc"], CANONICAL_CLOCK)
    assert convened["adjourned_utc"] is None
    assert convened["version"] == 2

    filed = validate_success(
        api_client.create_drafting_request(
            create_drafting_request_payload(
                session["id"],
                subject="Post-convene measure",
                summary="Filed after convening.",
                requested_sections_count=2,
                target_code_chapter="Title 7",
            ),
            make_member_headers(member["id"]),
        ),
        201,
    )
    assert filed["status"] == "SUBMITTED"


def test_a_drafting_request_filed_against_a_pending_session_is_refused_before_intake():
    """PRD: "The session-lifecycle rung sits **above** the target-state rung, so a
    write attempted against a still-`PENDING` session reports
    `ERR_SESSION_NOT_CONVENED` rather than an invalid-state error, and any business
    write attempted after adjournment reports `ERR_SESSION_ADJOURNED` — including a
    second adjournment attempt." and "`priority_slots_used` is defined as the count
    of that member's drafting requests, across every session, whose `priority_flag`
    is true and whose `status` is neither `WITHDRAWN` nor `LAPSED`; when a priority
    request is accepted, that count rises by one."

    Design: Corner/state_machines/drafting_request_cannot_be_filed_while_the_session_is_still_pending
    """
    set_clock(CANONICAL_CLOCK)
    session = get_success_data(api_client.create_session(create_session_payload(), ADMIN))
    member = get_success_data(api_client.create_member(create_member_payload(), ADMIN))

    response = api_client.create_drafting_request(
        create_drafting_request_payload(
            session["id"],
            subject="Premature filing",
            summary="Filed before convening.",
            requested_sections_count=2,
            target_code_chapter="Title 7",
            priority_flag=True,
        ),
        make_member_headers(member["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SESSION_NOT_CONVENED.value, 409)
    # The slot ledger is untouched because the request never landed.
    assert get_success_data(api_client.get_member(member["id"], ADMIN))["priority_slots_used"] == 0
    _rows, meta = validate_paginated(
        api_client.list_drafting_requests(CLERK, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 0


def test_style_certification_waits_for_the_open_blocking_conflict_to_be_waived():
    """PRD: "Second, `open_blocking_conflict_count` must be 0, or the call is
    `ERR_BLOCKING_CONFLICT_UNRESOLVED`." and "Note what a waiver does and does not
    do — the conflict stays on the record and keeps contributing to
    `blocking_conflict_count` and therefore to the complexity score; the waiver only
    stops it from blocking certification." and "When all three pass, the request
    moves from `DRAFTING` to `DRAFT_READY`, `style_findings_count` is stored,
    `sla_due_utc` is cleared to null, and the attorney's `active_engagement_count`
    is recomputed downward by one as the request leaves the occupancy set."

    Design: Corner/state_machines/certify_draft_refused_while_an_open_blocking_conflict_remains
    """
    world = setup_world()
    request = setup_request_in_research(
        world,
        subject="Dormant board repeal",
        summary="Repeal a dormant licensing board.",
        target_code_chapter="Title 12",
        requested_sections_count=2,
    )
    conflict = file_statutory_conflict(
        world, request, severity="BLOCKING", code_citation="12-1-101",
        conflict_type="REPEALS_ACTIVE",
    )
    request = complete_research(world, request, affected_sections_count=2)
    assert request["status"] == "DRAFTING"

    refused = api_client.certify_draft(
        request["id"], certify_draft_payload(0), world["counsel_headers"]
    )

    validate_error(refused, ApiErrorId.ERR_BLOCKING_CONFLICT_UNRESOLVED.value, 409)
    assert read_drafting_request(world, request["id"])["status"] == "DRAFTING"

    waived = resolve_statutory_conflict(
        world,
        conflict,
        resolution_status="WAIVED",
        resolution_note="Dormant board repeal is intentional; waiver granted.",
    )
    assert waived["resolution_status"] == "WAIVED"
    after_waiver = read_drafting_request(world, request["id"])
    assert after_waiver["open_blocking_conflict_count"] == 0
    # The waiver clears the gate without erasing the finding from the record.
    assert after_waiver["blocking_conflict_count"] == 1

    accepted = validate_success(
        api_client.certify_draft(
            request["id"], certify_draft_payload(0), world["counsel_headers"]
        ),
        200,
    )
    assert_drafting_request(accepted)
    assert accepted["status"] == "DRAFT_READY"
    assert accepted["sla_due_utc"] is None
    assert read_drafter(world)["active_engagement_count"] == 0


def test_introduction_converts_the_request_without_refunding_its_priority_slot():
    """PRD: "The originating request simultaneously moves from `DRAFT_READY` to
    `CONVERTED` without refunding its priority slot, and the session's
    `bills_introduced_count` rises by one." and "Conversion, by contrast, refunds
    nothing. When a `DRAFT_READY` request is introduced as a bill it moves to
    `CONVERTED`, and a converted priority request keeps consuming its slot for the
    remainder of the session: the slot is spent on the bill, not merely on the
    drafting queue." and "A `HOUSE` bill takes the current value of
    `next_house_bill_number`, renders `bill_number` as the two characters `HB`, a
    single space, and that number in decimal with no zero padding, and then raises
    `next_house_bill_number` by one."

    Design: Corner/state_machines/bill_introduction_side_effects_convert_the_request_and_advance_the_session_counters
    """
    world = setup_world()
    request = setup_draft_ready_request(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Historic tax credit",
        summary="Extend the historic tax credit.",
        target_code_chapter="Title 44",
        priority_flag=True,
        appropriation_requested_cents=0,
    )
    assert read_member(world)["priority_slots_used"] == 1

    bill = validate_success(
        api_client.create_bill(create_bill_payload(request["id"]), CLERK), 201
    )

    assert bill["bill_number"] == "HB 1"
    assert bill["priority_bill"] is True
    assert bill["fiscal_status"] == "NOT_REQUIRED"
    assert read_drafting_request(world, request["id"])["status"] == "CONVERTED"

    session = read_session(world)
    assert session["next_house_bill_number"] == 2
    assert session["next_senate_bill_number"] == 1
    assert session["bills_introduced_count"] == 1
    assert session["bills_enrolled_count"] == 0
    # The slot is spent on the bill, so conversion refunds nothing.
    assert read_member(world)["priority_slots_used"] == 1


def test_adopt_and_rescind_are_both_refused_while_the_amendment_is_only_requested():
    """PRD: "The amendment must actually be in `REQUESTED`; drafting one that is
    already `DRAFTED`, `ADOPTED`, `REJECTED` or `LAPSED` is
    `ERR_INVALID_AMENDMENT_STATE`, and the same error answers an adopt, reject or
    rescind call whose amendment is not in the status that operation requires." and
    "Adoption is a `Clerk` act taking no input fields. The amendment must be
    `DRAFTED`." and "On success `adopted_utc` is stamped with the logical clock, the
    bill's `adopted_amendment_count` rises by one, the amendment's
    `fiscal_impact_delta_cents` is added to the bill's `adopted_fiscal_delta_cents`,
    and the attorney's `active_engagement_count` drops by one as the amendment leaves
    the occupancy set."

    Design: Corner/state_machines/amendment_adopt_from_requested_is_rejected_as_invalid_amendment_state
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
    )
    referral = refer_bill(world, bill)
    amendment = request_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        summary="Sunset the schedule in 2032.",
        fiscal_impact_delta_cents=0,
        drafting_start_utc="2026-09-02T00:00:00Z",
        drafting_due_utc="2026-09-03T00:00:00Z",
    )
    assert amendment["status"] == "REQUESTED"

    adopt_refused = api_client.adopt_amendment(amendment["id"], CLERK)
    rescind_refused = api_client.rescind_amendment(
        amendment["id"],
        rescind_amendment_payload(
            rescission_reason="Attempted rescission of a never-adopted amendment."
        ),
        CLERK,
    )

    validate_error(adopt_refused, ApiErrorId.ERR_INVALID_AMENDMENT_STATE.value, 409)
    validate_error(rescind_refused, ApiErrorId.ERR_INVALID_AMENDMENT_STATE.value, 409)

    held = read_amendment(world, amendment["id"])
    assert held["status"] == "REQUESTED"
    assert held["adopted_utc"] is None
    assert held["rescind_count"] == 0
    unchanged = read_bill(world, bill["id"])
    assert unchanged["adopted_amendment_count"] == 0
    assert unchanged["adopted_fiscal_delta_cents"] == 0


def test_every_newly_created_child_opens_in_its_declared_initial_state():
    """PRD: "The new row lands in `status` `SUBMITTED` with `assigned_drafter_id`,
    `engagement_start_utc`, `engagement_end_utc`, `affected_sections_count`,
    `research_completed_utc`, `sla_due_utc`, `actual_complexity_score` and
    `style_findings_count` all null, `revision_round` at 0, and all three conflict
    counters at 0." and "The new finding lands with `resolution_status` `OPEN`,
    `resolution_note` null and `resolved_utc` null." and "A successful referral is
    created in `status` `IN_COMMITTEE` with `reported_utc` null. Its
    `referral_order` is a 1-based sequence within the bill, computed as the bill's
    `referral_count` plus one at creation time." and "A new amendment lands in
    `status` `REQUESTED` with `requested_by_member_id` stamped from `X-User-ID`,
    `requested_utc` stamped from the logical clock, `drafted_by_drafter_id`,
    `drafted_utc` and `adopted_utc` all null, and `rescind_count` at 0."

    Design: Corner/state_machines/newly_created_children_start_in_their_declared_initial_states
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    request = file_drafting_request(
        world,
        subject="Historic tax credit",
        summary="Extend the historic tax credit.",
        requested_sections_count=2,
        target_code_chapter="Title 44",
    )
    assert request["status"] == "SUBMITTED"

    request = assign_request(
        world,
        request,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    conflict = validate_success(
        api_client.create_statutory_conflict(
            create_statutory_conflict_payload(
                request["id"],
                code_citation="44-3-101",
                conflict_type="STYLE_VIOLATION",
                severity="ADVISORY",
            ),
            world["drafter_headers"],
        ),
        201,
    )
    assert conflict["resolution_status"] == "OPEN"
    assert conflict["resolution_note"] is None
    assert conflict["resolved_utc"] is None

    request = complete_research(world, request, affected_sections_count=2)
    request = get_success_data(
        api_client.certify_draft(request["id"], certify_draft_payload(0), world["counsel_headers"])
    )
    bill = validate_success(api_client.create_bill(create_bill_payload(request["id"]), CLERK), 201)
    assert bill["legislative_status"] == "INTRODUCED"
    assert bill["fiscal_status"] == "NOT_REQUIRED"

    referral = refer_bill(world, bill)
    assert referral["status"] == "IN_COMMITTEE"
    assert referral["referral_order"] == 1
    assert referral["reported_utc"] is None

    amendment = request_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        summary="Sunset the credit in 2032.",
        fiscal_impact_delta_cents=0,
        drafting_start_utc="2026-09-02T00:00:00Z",
        drafting_due_utc="2026-09-03T00:00:00Z",
    )
    assert amendment["status"] == "REQUESTED"
    assert amendment["drafted_utc"] is None
    assert amendment["adopted_utc"] is None
    assert amendment["rescind_count"] == 0
    assert amendment["requested_by_member_id"] == world["member"]["id"]


def test_a_withdrawn_request_admits_no_further_transition_and_refunds_only_once():
    """PRD: "Withdrawal is available from `SUBMITTED`, `RESEARCH`, `DRAFTING`,
    `RETURNED_FOR_CLARIFICATION` and `DRAFT_READY`; attempting it on a request
    already in `CONVERTED`, `WITHDRAWN` or `LAPSED` is
    `ERR_INVALID_DRAFTING_REQUEST_STATE`, and only the sponsoring member may do it."
    and "`sla_due_utc` is cleared to null. When `priority_flag` is true,
    `priority_slots_used` drops by one, returning the ledger to precisely the value
    it held before the request was filed." and "A request releases its interval the
    moment it leaves `RESEARCH` or `DRAFTING` — `RETURNED_FOR_CLARIFICATION`,
    `DRAFT_READY`, `CONVERTED`, `WITHDRAWN` and `LAPSED` all free it — and an
    amendment releases its interval on adoption, rejection or lapse and re-acquires
    it on rescission."

    Design: Corner/state_machines/withdrawn_drafting_request_is_terminal_and_admits_no_further_transition
    """
    world = setup_world()
    request = setup_request_in_research(
        world,
        subject="Broadband grant program",
        summary="Create a rural broadband grant program.",
        requested_sections_count=2,
        target_code_chapter="Title 40",
        priority_flag=True,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    withdrawn = get_success_data(
        api_client.withdraw_drafting_request(
            request["id"],
            withdraw_payload(withdrawal_reason="Sponsor withdrew the measure."),
            world["member_headers"],
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    research_again = api_client.complete_research(
        request["id"], complete_research_payload(2), world["drafter_headers"]
    )
    clarify_again = api_client.clarify_drafting_request(
        request["id"],
        clarify_payload(clarification_note="Attempt to revive a withdrawn request."),
        world["member_headers"],
    )
    withdraw_again = api_client.withdraw_drafting_request(
        request["id"],
        withdraw_payload(withdrawal_reason="Second withdrawal attempt."),
        world["member_headers"],
    )

    for refused in (research_again, clarify_again, withdraw_again):
        validate_error(refused, ApiErrorId.ERR_INVALID_DRAFTING_REQUEST_STATE.value, 409)

    settled = read_drafting_request(world, request["id"])
    assert settled["status"] == "WITHDRAWN"
    assert settled["sla_due_utc"] is None
    # The compensating action ran exactly once, not once per refused retry.
    assert read_member(world)["priority_slots_used"] == 0
    assert read_drafter(world)["active_engagement_count"] == 0


def test_a_second_convene_is_refused_and_leaves_the_original_stamp_in_place():
    """PRD: "Convening a session that is not `PENDING` is
    `ERR_INVALID_SESSION_STATE`." and "A `Clerk` convenes the session, moving
    `status` from `PENDING` to `CONVENED` and stamping `convened_utc` with the
    logical clock."

    Design: Corner/state_machines/second_convene_of_the_same_session_returns_invalid_session_state
    """
    world = setup_world()
    assert_instant(world["session"]["convened_utc"], CANONICAL_CLOCK)
    set_clock("2026-09-05T00:00:00Z")

    response = api_client.convene_session(world["session"]["id"], CLERK)

    validate_error(response, ApiErrorId.ERR_INVALID_SESSION_STATE.value, 409)
    session = read_session(world)
    assert session["status"] == "CONVENED"
    # The later clock reading never overwrote the original convening instant.
    assert_instant(session["convened_utc"], CANONICAL_CLOCK)
    assert session["version"] == 2


def test_a_second_certification_is_refused_and_the_ledger_is_never_double_counted():
    """PRD: "Certification is the `FiscalOfficer`'s final act on a note and accepts
    an optional `certification_note`. The note must be `SUBMITTED`." and "The target
    row is in a state from which the requested transition is declared — otherwise
    the matching invalid-state identifier for that entity." and "The ledger is
    maintained by exact addition when a note is certified and exact subtraction when
    a certified note is re-opened, and the incrementally maintained value must equal
    a full recomputation of that sum at every observable instant."

    Design: Corner/state_machines/second_certification_of_the_same_note_is_refused_and_never_double_counts_the_ledger
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
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Fuel tax indexing",
        summary="Index the fuel tax.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
    )
    note = setup_certified_note(world, bill, lines=STANDARD_COST_LINES)
    assert note["certified_total_cents"] == 26_568_000

    response = api_client.certify_fiscal_note_request(
        note["id"],
        {"certification_note": "Duplicate certification attempt."},
        world["fiscal_officer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_FISCAL_NOTE_STATE.value, 409)
    settled = read_note(world, note["id"])
    assert settled["status"] == "CERTIFIED"
    assert settled["certified_total_cents"] == 26_568_000
    assert_instant(settled["certified_utc"], CANONICAL_CLOCK)

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 26_568_000
    assert session["certified_fiscal_total_cents"] != 53_136_000
    assert session["fiscal_posture"] == "NORMAL"
    assert read_agency(world)["open_request_count"] == 0
    assert read_bill(world, bill["id"])["fiscal_status"] == "NOTE_COMPLETE"


def test_adjournment_reaches_every_open_child_and_leaves_the_certified_note_alone():
    """PRD: "Every drafting request of this session in `SUBMITTED`, `RESEARCH`,
    `DRAFTING`, `RETURNED_FOR_CLARIFICATION` or `DRAFT_READY` moves to `LAPSED` with
    `sla_due_utc` cleared to null." and "Every committee referral on a bill of this
    session still `IN_COMMITTEE` moves to `DIED_IN_COMMITTEE`, and each affected
    committee's `active_referral_count` is recomputed." and "Every bill of this
    session whose `legislative_status` is `INTRODUCED`, `REFERRED`, `REPORTED` or
    `PASSED_CHAMBER` moves to `DEAD`, and its `fiscal_status` is left exactly as it
    was." and "The session's `certified_fiscal_total_cents` and `fiscal_posture` are
    **not** changed: certified notes survive adjournment, and the ledger is a
    historical record rather than a work queue."

    Design: Corner/state_machines/adjournment_cascades_down_to_every_open_child_and_leaves_certified_notes_alone
    """
    world = setup_world(
        with_committee=True,
        with_agency=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    converted_request, bill, note, referral = setup_bill_with_certified_note(
        world,
        appropriation_requested_cents=6_000_000,
        lines=STANDARD_COST_LINES,
        refer=True,
        subject="Fuel tax indexing",
        summary="Index the fuel tax.",
        target_code_chapter="Title 39",
    )
    assert note["certified_total_cents"] == 26_568_000
    open_request = setup_request_in_research(
        world,
        subject="Rail crossing safety",
        summary="Improve rail crossing safety.",
        requested_sections_count=2,
        target_code_chapter="Title 40",
        priority_flag=True,
        engagement_start_utc="2026-09-06T00:00:00Z",
        engagement_end_utc="2026-09-08T00:00:00Z",
    )
    assert read_member(world)["priority_slots_used"] == 1

    adjourned = validate_success(
        api_client.adjourn_session(world["session"]["id"], CLERK), 200
    )

    assert adjourned["status"] == "ADJOURNED"
    assert_instant(adjourned["adjourned_utc"], CANONICAL_CLOCK)

    lapsed = read_drafting_request(world, open_request["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["sla_due_utc"] is None
    assert read_member(world)["priority_slots_used"] == 0
    assert read_drafter(world)["active_engagement_count"] == 0

    assert read_referral(world, referral["id"])["status"] == "DIED_IN_COMMITTEE"
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 0

    dead = read_bill(world, bill["id"])
    assert dead["legislative_status"] == "DEAD"
    assert dead["fiscal_status"] == "NOTE_COMPLETE"
    assert read_note(world, note["id"])["status"] == "CERTIFIED"

    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 26_568_000
    assert session["fiscal_posture"] == "NORMAL"
    # A child already in a terminal state is not dragged through a second exit.
    assert read_drafting_request(world, converted_request["id"])["status"] == "CONVERTED"


def _bill_referred_to_two_committees():
    """A note-free bill sitting in two committees, with the clock at reporting time."""
    world = setup_world()
    first_committee = add_committee(
        world,
        chamber="HOUSE",
        name="House Judiciary",
        is_fiscal_committee=False,
        max_concurrent_referrals=2,
    )
    second_committee = add_committee(
        world,
        chamber="HOUSE",
        name="House Local Government",
        is_fiscal_committee=False,
        max_concurrent_referrals=2,
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
    )
    first_referral = refer_bill(world, bill, committee=first_committee)
    second_referral = refer_bill(world, bill, committee=second_committee)
    set_clock("2026-10-06T00:00:00Z")
    return world, bill, first_committee, second_committee, first_referral, second_referral


def test_the_bill_bubbles_up_to_reported_only_when_the_last_referral_clears():
    """PRD: "If — and only if — no referral of that bill remains `IN_COMMITTEE`, the
    bill advances from `REFERRED` to `REPORTED`; a bill with a second committee
    still holding it stays in `REFERRED`." and "Its `referral_order` is a 1-based
    sequence within the bill, computed as the bill's `referral_count` plus one at
    creation time." and "On success the referral moves from `IN_COMMITTEE` to
    `REPORTED_FAVORABLE`, `reported_utc` is stamped with the logical clock, and the
    committee's `active_referral_count` drops by one."

    Design: Corner/state_machines/bill_reaches_reported_only_when_the_last_in_committee_referral_clears
    """
    (
        world,
        bill,
        first_committee,
        second_committee,
        first_referral,
        second_referral,
    ) = _bill_referred_to_two_committees()

    assert first_referral["referral_order"] == 1
    assert second_referral["referral_order"] == 2
    assert read_bill(world, bill["id"])["referral_count"] == 2

    first_reported = validate_success(
        api_client.report_referral(first_referral["id"], report_payload("FAVORABLE"), CLERK), 200
    )
    assert first_reported["status"] == "REPORTED_FAVORABLE"
    assert_instant(first_reported["reported_utc"], "2026-10-06T00:00:00Z")
    # A sibling is still holding the measure, so the bill does not advance.
    assert read_bill(world, bill["id"])["legislative_status"] == "REFERRED"

    second_reported = validate_success(
        api_client.report_referral(second_referral["id"], report_payload("FAVORABLE"), CLERK), 200
    )
    assert second_reported["status"] == "REPORTED_FAVORABLE"
    assert_instant(second_reported["reported_utc"], "2026-10-06T00:00:00Z")
    assert read_bill(world, bill["id"])["legislative_status"] == "REPORTED"
    assert read_committee(world, first_committee["id"])["active_referral_count"] == 0
    assert read_committee(world, second_committee["id"])["active_referral_count"] == 0


def test_one_unfavorable_report_kills_the_bill_and_dies_every_sibling_referral():
    """PRD: "Then the cascade fires: the bill's `legislative_status` becomes `DEAD`
    immediately, irrespective of how many other referrals it still has in
    `IN_COMMITTEE`, and every one of those sibling referrals moves to
    `DIED_IN_COMMITTEE`, with each affected committee's `active_referral_count`
    recomputed downward accordingly." and "The referral moves from `IN_COMMITTEE` to
    `REPORTED_UNFAVORABLE`, `reported_utc` is stamped with the logical clock, and the
    committee's `active_referral_count` drops by one — exactly as in the favourable
    branch."

    Design: Corner/state_machines/unfavorable_report_kills_the_bill_and_dies_every_sibling_referral
    """
    (
        world,
        bill,
        first_committee,
        second_committee,
        first_referral,
        second_referral,
    ) = _bill_referred_to_two_committees()

    reported = validate_success(
        api_client.report_referral(
            first_referral["id"], report_payload("UNFAVORABLE"), CLERK
        ),
        200,
    )

    assert reported["status"] == "REPORTED_UNFAVORABLE"
    assert_instant(reported["reported_utc"], "2026-10-06T00:00:00Z")
    assert read_bill(world, bill["id"])["legislative_status"] == "DEAD"

    sibling = read_referral(world, second_referral["id"])
    assert sibling["status"] == "DIED_IN_COMMITTEE"
    assert sibling["reported_utc"] is None
    assert read_committee(world, first_committee["id"])["active_referral_count"] == 0
    assert read_committee(world, second_committee["id"])["active_referral_count"] == 0
    # referral_count is a lifetime tally, not a gauge of open referrals.
    assert read_bill(world, bill["id"])["referral_count"] == 2


def test_rescinding_a_zero_delta_amendment_unwinds_only_the_non_fiscal_counters():
    """PRD: "The amendment returns from `ADOPTED` to `DRAFTED`, its `rescind_count`
    rises by one to record how often this has happened, and `adopted_utc` is cleared
    to null." and "The bill's `adopted_amendment_count` drops by one and its
    `fiscal_impact_delta_cents` is subtracted from the bill's
    `adopted_fiscal_delta_cents`." and "The attorney's `active_engagement_count`
    rises by one again, because a `DRAFTED` amendment re-enters the occupancy set."
    and "When the adopted amendment's `fiscal_impact_delta_cents` is exactly 0, that
    is the whole story."

    Design: Corner/state_machines/amendment_rescission_reverses_the_bills_adoption_counters_and_restores_drafter_occupancy
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
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
    )
    referral = refer_bill(world, bill)
    amendment = setup_adopted_amendment(
        world,
        bill,
        stage="COMMITTEE",
        committee_referral_id=referral["id"],
        fiscal_impact_delta_cents=0,
        summary="Trim the retention schedule by one year.",
    )
    assert amendment["status"] == "ADOPTED"
    adopted_bill = read_bill(world, bill["id"])
    assert adopted_bill["adopted_amendment_count"] == 1
    assert adopted_bill["fiscal_status"] == "NOT_REQUIRED"
    assert read_drafter(world)["active_engagement_count"] == 0

    response = api_client.rescind_amendment(
        amendment["id"],
        rescind_amendment_payload(
            rescission_reason="Committee reversed itself on the retention schedule."
        ),
        CLERK,
    )

    rescinded = validate_success(response, 200)
    assert rescinded["status"] == "DRAFTED"
    assert rescinded["adopted_utc"] is None
    assert rescinded["rescind_count"] == 1

    unwound = read_bill(world, bill["id"])
    assert unwound["adopted_amendment_count"] == 0
    assert unwound["adopted_fiscal_delta_cents"] == 0
    # A zero-delta amendment never created a note obligation to unwind.
    assert unwound["fiscal_status"] == "NOT_REQUIRED"
    assert read_drafter(world)["active_engagement_count"] == 1

    notes, notes_meta = validate_paginated(
        api_client.list_fiscal_note_requests(world["fiscal_officer_headers"])
    )
    assert notes_meta["total_count"] == 0
    assert notes == []
    assert read_session(world)["certified_fiscal_total_cents"] == 0


def test_only_the_blocking_conflict_filed_during_drafting_bounces_the_request():
    """PRD: "A `BLOCKING` finding raises both `blocking_conflict_count` and
    `open_blocking_conflict_count` by one; an `ADVISORY` finding raises
    `advisory_conflict_count` by one." and "The cascade is strictly conditional: an
    `ADVISORY` finding, or a `BLOCKING` finding recorded while the request is still
    in `RESEARCH`, updates the counters and stops there, leaving the status, the
    service target, the occupancy set and the member's counters untouched." and "At
    the second level, caused by the status leaving `DRAFTING` for
    `RETURNED_FOR_CLARIFICATION`, three further things happen: `sla_due_utc` is
    cleared to null, the assigned attorney's `active_engagement_count` is recomputed
    downward by one as the request leaves the occupancy set, and the sponsoring
    member's `clarification_pending_count` rises by one."

    Design: Corner/state_machines/only_a_blocking_conflict_filed_during_drafting_bounces_the_request
    """
    world = setup_world()
    request = setup_request_in_research(
        world,
        subject="Uniform citation format",
        summary="Adopt a uniform statutory citation format.",
        requested_sections_count=3,
        target_code_chapter="Title 28",
    )

    file_statutory_conflict(
        world,
        request,
        severity="BLOCKING",
        code_citation="28-9-101",
        conflict_type="AMENDS_SAME_SECTION",
    )

    in_research = read_drafting_request(world, request["id"])
    assert in_research["status"] == "RESEARCH"
    assert in_research["blocking_conflict_count"] == 1
    assert in_research["open_blocking_conflict_count"] == 1
    assert read_member(world)["clarification_pending_count"] == 0

    complete_research(world, request, affected_sections_count=4)
    file_statutory_conflict(
        world,
        request,
        severity="ADVISORY",
        code_citation="28-9-102",
        conflict_type="STYLE_VIOLATION",
    )

    in_drafting = read_drafting_request(world, request["id"])
    # An advisory finding moves its own counter and nothing else.
    assert in_drafting["status"] == "DRAFTING"
    assert in_drafting["advisory_conflict_count"] == 1
    assert in_drafting["blocking_conflict_count"] == 1

    file_statutory_conflict(
        world,
        request,
        severity="BLOCKING",
        code_citation="28-9-103",
        conflict_type="DUPLICATE_ENACTMENT",
    )

    bounced = read_drafting_request(world, request["id"])
    assert bounced["status"] == "RETURNED_FOR_CLARIFICATION"
    assert bounced["sla_due_utc"] is None
    assert bounced["blocking_conflict_count"] == 2
    assert bounced["open_blocking_conflict_count"] == 2

    sponsor = read_member(world)
    assert sponsor["clarification_pending_count"] == 1
    # The hold only arms at two pending clarifications.
    assert sponsor["intake_hold"] is False
    assert read_drafter(world)["active_engagement_count"] == 0
