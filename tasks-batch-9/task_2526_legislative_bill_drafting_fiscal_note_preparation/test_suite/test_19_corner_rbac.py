"""RBAC: the seven role surfaces, seniority, segregation of duties and narrow reads."""

from test_helpers import (
    add_agency,
    add_drafter,
    add_member,
    ADMIN,
    api_client,
    ApiErrorId,
    append_cost_estimates,
    assert_instant,
    assign_payload,
    assign_request,
    certify_draft_payload,
    clarify_payload,
    CLERK,
    complete_research,
    create_agency_payload,
    create_amendment_payload,
    create_bill_payload,
    create_committee_payload,
    create_cost_estimate_payload,
    create_drafter_payload,
    create_drafting_request_payload,
    create_fiscal_note_request_payload,
    create_member_payload,
    create_referral_payload,
    create_session_payload,
    create_technical_correction_payload,
    DEFAULT_CLOCK,
    draft_amendment_payload,
    enroll_bill,
    file_drafting_request,
    file_statutory_conflict,
    FISCAL_OFFICER,
    introduce_bill,
    make_agency_analyst_headers,
    make_drafter_headers,
    make_member_headers,
    make_review_counsel_headers,
    pass_bill,
    read_bill,
    read_committee,
    read_correction,
    read_drafter,
    read_drafting_request,
    read_enrolled_bill,
    read_note,
    read_session,
    refer_bill,
    report_payload,
    report_referral,
    resolve_conflict_payload,
    resolve_statutory_conflict,
    route_fiscal_note,
    set_clock,
    setup_draft_ready_request,
    setup_introduced_bill,
    setup_request_in_drafting,
    setup_world,
    submit_note,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_payload,
)

UNAUTHORIZED = ApiErrorId.ERR_UNAUTHORIZED.value


def test_registry_writes_and_the_clock_belong_to_the_platform_admin_alone():
    """PRD: "**Endpoint role.** The acting role appears in the target
    endpoint's authorized list — otherwise `ERR_UNAUTHORIZED`." and "The clock is
    monotonic: the supplied instant must be greater than or equal to the current
    reading, and a request carrying an earlier instant is refused with
    `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    Design: Corner/rbac/platform_admin_registry_writes_are_forbidden_to_all_six_other_roles
    """
    set_clock(DEFAULT_CLOCK)

    session = validate_success(
        api_client.create_session(create_session_payload(), ADMIN), 201
    )
    admin_committee = validate_success(
        api_client.create_committee(
            session["id"], create_committee_payload(name="House Appropriations"), ADMIN
        ),
        201,
    )
    member = validate_success(api_client.create_member(create_member_payload(), ADMIN), 201)
    drafter = validate_success(
        api_client.create_drafter(create_drafter_payload(), ADMIN), 201
    )
    agency = validate_success(api_client.create_agency(create_agency_payload(), ADMIN), 201)

    member_headers = make_member_headers(member["id"])
    drafter_headers = make_drafter_headers(drafter["id"])
    analyst_headers = make_agency_analyst_headers(agency["id"])

    # Five different roles, five different registry operations, one refusal code.
    refusals = [
        api_client.create_session(create_session_payload(name="Clerk attempt"), CLERK),
        api_client.create_member(
            create_member_payload(full_name="FiscalOfficer attempt", chamber="SENATE"),
            FISCAL_OFFICER,
        ),
        api_client.create_drafter(
            create_drafter_payload(full_name="Member attempt", is_senior=True),
            member_headers,
        ),
        api_client.create_agency(
            create_agency_payload(name="Drafter attempt", agency_code="DOA"),
            drafter_headers,
        ),
        api_client.set_clock_raw({"current_utc": "2026-09-05T00:00:00Z"}, analyst_headers),
    ]
    for response in refusals:
        validate_error(response, UNAUTHORIZED, 403)

    # The refused session write left no row behind.
    _rows, meta = validate_paginated(api_client.list_sessions(ADMIN))
    assert meta["total_count"] == 1

    # The refused attorney registration minted nothing that shadows the real row.
    still_junior = validate_success(api_client.get_drafter(drafter["id"], ADMIN), 200)
    assert still_junior["id"] == drafter["id"]
    assert still_junior["is_senior"] is False

    # The clock is still 2026-09-01T00:00:00Z: only an instant at or after the current
    # reading is accepted, so re-setting the same instant proves it never advanced.
    set_clock(DEFAULT_CLOCK)

    # Committee creation is the one shared registry write, which is what makes the five
    # refusals above operation-scoped rather than role-tier-scoped.
    clerk_committee = validate_success(
        api_client.create_committee(
            session["id"], create_committee_payload(name="House Judiciary"), CLERK
        ),
        201,
    )
    assert clerk_committee["id"] != admin_committee["id"]
    assert clerk_committee["session_id"] == session["id"]


def test_the_procedural_spine_belongs_to_the_clerk_on_resources_that_are_otherwise_ripe():
    """PRD: "**Endpoint role.** The acting role appears in the target endpoint's
    authorized list — otherwise `ERR_UNAUTHORIZED`." and "Evaluation stops at the first
    violated rung." and "On success the referral moves from `IN_COMMITTEE` to
    `REPORTED_FAVORABLE`, `reported_utc` is stamped with the logical clock, and the
    committee's `active_referral_count` drops by one."

    Design: Corner/rbac/clerk_procedural_actions_are_forbidden_to_the_fiscal_and_drafting_roles
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
    )
    request = setup_draft_ready_request(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
    )

    # The request is DRAFT_READY, so introduction would succeed for the right role.
    validate_error(
        api_client.create_bill(
            create_bill_payload(request["id"]), world["drafter_headers"]
        ),
        UNAUTHORIZED,
        403,
    )
    bill = validate_success(
        api_client.create_bill(create_bill_payload(request["id"]), CLERK), 201
    )
    referral = validate_success(
        api_client.create_referral(
            bill["id"], create_referral_payload(world["committee"]["id"]), CLERK
        ),
        201,
    )

    # The committee has a free slot and the window is clear, so only identity is wrong.
    validate_error(
        api_client.create_referral(
            bill["id"],
            create_referral_payload(
                world["committee"]["id"],
                hearing_window_start_utc="2026-10-08T14:00:00Z",
                hearing_window_end_utc="2026-10-08T16:00:00Z",
            ),
            world["counsel_headers"],
        ),
        UNAUTHORIZED,
        403,
    )

    set_clock("2026-10-06T00:00:00Z")
    validate_error(
        api_client.report_referral(
            referral["id"], report_payload("FAVORABLE"), world["analyst_headers"]
        ),
        UNAUTHORIZED,
        403,
    )
    reported = validate_success(
        api_client.report_referral(referral["id"], report_payload("FAVORABLE"), CLERK),
        200,
    )
    assert reported["status"] == "REPORTED_FAVORABLE"
    assert_instant(reported["reported_utc"], "2026-10-06T00:00:00Z")

    validate_error(
        api_client.pass_bill(bill["id"], world["member_headers"]), UNAUTHORIZED, 403
    )
    validate_error(api_client.enroll_bill(bill["id"], FISCAL_OFFICER), UNAUTHORIZED, 403)
    validate_error(
        api_client.adjourn_session(world["session"]["id"], FISCAL_OFFICER),
        UNAUTHORIZED,
        403,
    )

    # The refused referral was never created and the successful report closed the one
    # that was, so the counter lands on zero either way.
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 0
    assert read_bill(world, bill["id"])["legislative_status"] == "REPORTED"
    assert read_session(world)["status"] == "CONVENED"


BOUNDARY_LINES = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 5_000_000,
        "operating_cost_cents": 1_000_000,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "Year one of the round.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 3_000_000,
        "operating_cost_cents": 1_000_000,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "Year two of the round.",
    },
]


def test_the_two_note_review_verbs_are_the_fiscal_officers_alone():
    """PRD: "**Endpoint role.** The acting role appears in the target endpoint's
    authorized list — otherwise `ERR_UNAUTHORIZED`." and "The note moves from
    `SUBMITTED` to `RETURNED_FOR_REVISION` and its `revision_round` rises by one, which
    flips `included_in_certification` to false on every cost estimate line of the prior
    round and drops them out of every total — the analyst must file a fresh set." and
    "At the low boundary, a direct subtotal of exactly 10,000,000 yields a contingency of
    500,000 and a certified total of 10,500,000." and "The ledger is maintained by
    exact addition when a note is certified and exact subtraction when a certified note
    is re-opened, and the incrementally maintained value must equal a full recomputation
    of that sum at every observable instant."

    Design: Corner/rbac/fiscal_officer_review_actions_are_forbidden_to_the_clerk_and_to_the_filing_analyst
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
    _request_one, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    # Routing itself is the shared operation, so the fiscal officer opens the note.
    note = route_fiscal_note(world, bill)
    append_cost_estimates(world, note, BOUNDARY_LINES)
    submitted = submit_note(world, note, submission_note="Round zero filed.")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_round"] == 0

    review_refusals = [
        api_client.return_fiscal_note_request(
            note["id"], {"return_reason": "Clerk trying to bounce the note."}, CLERK
        ),
        api_client.return_fiscal_note_request(
            note["id"],
            {"return_reason": "Analyst trying to bounce its own note."},
            world["analyst_headers"],
        ),
        api_client.certify_fiscal_note_request(
            note["id"], {"certification_note": "Clerk trying to certify."}, CLERK
        ),
        api_client.certify_fiscal_note_request(
            note["id"],
            {"certification_note": "Analyst trying to certify its own filing."},
            world["analyst_headers"],
        ),
    ]
    for response in review_refusals:
        validate_error(response, UNAUTHORIZED, 403)

    held = read_note(world, note["id"])
    assert held["status"] == "SUBMITTED"
    assert held["revision_round"] == 0

    returned = validate_success(
        api_client.return_fiscal_note_request(
            note["id"],
            {"return_reason": "Operating assumption understated."},
            world["fiscal_officer_headers"],
        ),
        200,
    )
    assert returned["status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == 1

    # Filing and submitting are the analyst's exclusives, and they still work.
    refiled = append_cost_estimates(world, note, BOUNDARY_LINES)
    assert [line["revision_round"] for line in refiled] == [1, 1]
    resubmitted = submit_note(world, note, submission_note="Round one filed.")
    assert resubmitted["status"] == "SUBMITTED"

    certified = validate_success(
        api_client.certify_fiscal_note_request(
            note["id"],
            {"certification_note": "Accepted on round one."},
            world["fiscal_officer_headers"],
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_total_cents"] == 10_500_000
    assert read_bill(world, bill["id"])["fiscal_status"] == "NOTE_COMPLETE"
    assert read_session(world)["certified_fiscal_total_cents"] == 10_500_000

    # Routing is genuinely shared: the identical call issued as Clerk also lands.
    _request_two, second_bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Tax form consolidation",
        summary="Consolidate the excise tax forms.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=2_000_000,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    clerk_note = validate_success(
        api_client.create_fiscal_note_request(
            second_bill["id"],
            create_fiscal_note_request_payload(world["agency"]["id"]),
            CLERK,
        ),
        201,
    )
    assert clerk_note["status"] == "ROUTED"


def test_the_analyst_lane_is_owner_scoped_on_writes_and_closed_on_the_drafting_pipeline():
    """PRD: "Ownership is enforced on exactly seven operations: withdrawing a drafting
    request and completing its research; recording a statutory conflict; appending a
    cost estimate line; submitting a fiscal note; drafting an amendment; and reading a
    single agency record when the acting role is `AgencyAnalyst`." and "Any breach is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)." and "This role cannot read the drafting
    pipeline at all — no drafting-request or statutory-conflict read is granted to it,
    so such an attempt is stopped by the endpoint role check with `ERR_UNAUTHORIZED`
    rather than by any confidentiality rule." and "**Ownership.** An entity-backed role
    acts only on what it owns — otherwise `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/agency_analyst_touches_only_its_own_lane_and_every_foreign_touch_is_rejected
    """
    not_owner = ApiErrorId.ERR_NOT_RESOURCE_OWNER.value
    world = setup_world(
        with_agency=True,
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    owning_agency = world["agency"]
    owning_analyst = world["analyst_headers"]
    rival_agency = add_agency(
        world,
        name="Dept of Transportation",
        agency_code="DOT",
        status="ACTIVE",
        max_open_requests=3,
    )
    rival_analyst = make_agency_analyst_headers(rival_agency["id"])

    request, bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
    )
    note = route_fiscal_note(world, bill)
    note_version = note["version"]

    # The rival's role IS on both endpoints; it simply does not own this note.
    validate_error(
        api_client.create_cost_estimate(
            note["id"],
            create_cost_estimate_payload(
                note_version,
                assumption_note="Rival agency filing on someone else's note.",
            ),
            rival_analyst,
        ),
        not_owner,
        403,
    )
    # Ownership outranks the cost-estimate presence check that also applied here.
    validate_error(
        api_client.submit_fiscal_note_request(
            note["id"],
            {"submission_note": "Rival agency submitting someone else's note."},
            rival_analyst,
        ),
        not_owner,
        403,
    )

    validate_error(
        api_client.get_agency(owning_agency["id"], rival_analyst), not_owner, 403
    )
    own_row = validate_success(api_client.get_agency(rival_agency["id"], rival_analyst), 200)
    assert own_row["responsiveness_score"] == 100
    assert own_row["open_request_count"] == 0

    # The note read itself is not owner-scoped, which is what makes the two write
    # refusals specific to the write verbs rather than to the lane as a whole.
    visible = validate_success(
        api_client.get_fiscal_note_request(note["id"], rival_analyst), 200
    )
    assert visible["agency_id"] == owning_agency["id"]

    # The owning analyst is absent from all three drafting-pipeline read endpoints.
    for response in (
        api_client.get_drafting_request(request["id"], owning_analyst),
        api_client.list_drafting_requests(
            owning_analyst, params={"session_id": world["session"]["id"]}
        ),
        api_client.list_request_statutory_conflicts(request["id"], owning_analyst),
    ):
        validate_error(response, UNAUTHORIZED, 403)

    landed = validate_success(
        api_client.create_cost_estimate(
            note["id"],
            create_cost_estimate_payload(
                note_version, assumption_note="Owning agency filing on its own note."
            ),
            owning_analyst,
        ),
        201,
    )
    assert landed["revision_round"] == 0
    assert landed["included_in_certification"] is True

    rows, meta = validate_paginated(
        api_client.list_cost_estimates(note["id"], owning_analyst)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == landed["id"]


def test_the_member_surface_is_four_write_verbs_and_stops_at_its_own_files():
    """PRD: "**Endpoint role.** The acting role appears in the target endpoint's
    authorized list — otherwise `ERR_UNAUTHORIZED`." and "A `Member` acts only on their
    own drafting requests and amendments; an `AgencyAnalyst` files and submits only
    notes routed to their own agency and reads only their own `Agency` row; a `Drafter`
    acts only where assigned." and "The sponsoring member answers a bounced file by
    supplying a `clarification_note`, which returns the request from
    `RETURNED_FOR_CLARIFICATION` to `DRAFTING`." and "On success, `revision_round` rises
    by one, recording how many clarification loops the file has completed" and "A new
    amendment lands in `status` `REQUESTED` with `requested_by_member_id` stamped from
    `X-User-ID`, `requested_utc` stamped from the logical clock, `drafted_by_drafter_id`,
    `drafted_utc` and `adopted_utc` all null, and `rescind_count` at 0."

    Design: Corner/rbac/member_writes_are_four_verbs_wide_and_every_other_write_is_rejected
    """
    not_owner = ApiErrorId.ERR_NOT_RESOURCE_OWNER.value
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    sponsor = world["member"]
    _rival, rival_headers = add_member(
        world, full_name="Rep Beta", chamber="HOUSE", party="IND", priority_slots_total=2
    )
    _request_one, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Bridge rehabilitation program",
        summary="Create a bridge rehabilitation program.",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    referral = refer_bill(world, bill)

    second = setup_request_in_drafting(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Culvert replacement study",
        summary="Study culvert replacement priorities.",
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    # A blocking finding in DRAFTING bounces the file back to its sponsor.
    bounced = file_statutory_conflict(
        world, second, severity="BLOCKING", code_citation="23-1-207"
    )
    assert read_drafting_request(world, second["id"])["status"] == "RETURNED_FOR_CLARIFICATION"
    resolve_statutory_conflict(world, bounced)

    # Intake is the member's verb, so the drafting bench is refused on the endpoint.
    validate_error(
        api_client.create_drafting_request(
            create_drafting_request_payload(
                world["session"]["id"],
                subject="Drafter attempting intake",
                summary="Not a member.",
                requested_sections_count=1,
                target_code_chapter="Title 3",
            ),
            world["drafter_headers"],
        ),
        UNAUTHORIZED,
        403,
    )

    # The rival member is on the endpoint but does not own the file.
    validate_error(
        api_client.withdraw_drafting_request(
            second["id"],
            withdraw_payload(
                withdrawal_reason="Rival member trying to withdraw someone else's request."
            ),
            rival_headers,
        ),
        not_owner,
        403,
    )
    assert read_drafting_request(world, second["id"])["status"] == "RETURNED_FOR_CLARIFICATION"

    # Assignment, drafting and adoption belong to other roles entirely.
    validate_error(
        api_client.assign_drafting_request(
            second["id"],
            assign_payload(
                world["drafter"]["id"],
                engagement_start_utc="2026-09-03T06:00:00Z",
                engagement_end_utc="2026-09-03T12:00:00Z",
            ),
            world["member_headers"],
        ),
        UNAUTHORIZED,
        403,
    )

    clarified = validate_success(
        api_client.clarify_drafting_request(
            second["id"],
            clarify_payload(clarification_note="Please narrow the target chapter."),
            world["member_headers"],
        ),
        200,
    )
    assert clarified["status"] == "DRAFTING"
    assert clarified["revision_round"] == 1

    withdrawn = validate_success(
        api_client.withdraw_drafting_request(
            second["id"],
            withdraw_payload(withdrawal_reason="Sponsor withdrawing their own request."),
            world["member_headers"],
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"

    amendment = validate_success(
        api_client.create_amendment(
            create_amendment_payload(
                read_bill(world, bill["id"])["version"],
                bill["id"],
                stage="COMMITTEE",
                committee_referral_id=referral["id"],
                summary="Sponsor requesting a committee amendment.",
                fiscal_impact_delta_cents=0,
                drafting_start_utc="2026-09-01T13:00:00Z",
                drafting_due_utc="2026-09-01T15:00:00Z",
            ),
            world["member_headers"],
        ),
        201,
    )
    assert amendment["status"] == "REQUESTED"
    assert amendment["requested_by_member_id"] == sponsor["id"]

    validate_error(
        api_client.draft_amendment(
            amendment["id"],
            draft_amendment_payload(
                draft_text="Member attempting to draft their own amendment."
            ),
            world["member_headers"],
        ),
        UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.adopt_amendment(amendment["id"], world["member_headers"]),
        UNAUTHORIZED,
        403,
    )

    still_requested = validate_success(
        api_client.get_amendment(amendment["id"], world["member_headers"]), 200
    )
    assert still_requested["status"] == "REQUESTED"
    assert still_requested["drafted_by_drafter_id"] is None
    assert still_requested["rescind_count"] == 0


def test_seniority_is_a_separate_rung_from_the_role_label_on_the_four_counsel_verbs():
    """PRD: "Four operations are reserved to that role — drafter assignment, draft
    certification, applying a technical correction, and resolving a statutory conflict
    with the disposition `WAIVED` — and on each of them the `Drafter` row named by
    `X-User-ID` must exist and carry `is_senior` set to true. A junior attorney who
    presents `X-User-Role: ReviewCounsel` is refused with `ERR_SENIOR_COUNSEL_REQUIRED`
    (HTTP 403)." and "**Seniority.** On the four `ReviewCounsel`-only operations, the
    backing `Drafter` row has `is_senior` true — otherwise
    `ERR_SENIOR_COUNSEL_REQUIRED`." and "Resolving a conflict supplies a
    `resolution_status` of `RESOLVED` together with a `resolution_note`, and the assigned
    attorney may do it themselves." and "**Segregation of duties.**
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/seniority_not_the_role_label_gates_the_four_counsel_operations_and_a_junior_is_rejected
    """
    senior_required = ApiErrorId.ERR_SENIOR_COUNSEL_REQUIRED.value
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    junior = world["drafter"]
    senior = world["counsel"]
    assert junior["is_senior"] is False
    assert senior["is_senior"] is True
    # Both roles resolve X-User-ID against the same Drafter table.
    junior_as_counsel = make_review_counsel_headers(junior["id"])
    senior_as_drafter = make_drafter_headers(senior["id"])

    ripe = setup_request_in_drafting(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Bridge rehabilitation program",
        summary="Create a bridge rehabilitation program.",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    waiting = file_drafting_request(
        world,
        subject="Culvert replacement study",
        summary="Study culvert replacement priorities.",
        requested_sections_count=2,
    )
    assignment = assign_payload(
        junior["id"],
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )

    validate_error(
        api_client.assign_drafting_request(
            waiting["id"], assignment, junior_as_counsel
        ),
        senior_required,
        403,
    )
    assigned = validate_success(
        api_client.assign_drafting_request(
            waiting["id"], assignment, world["counsel_headers"]
        ),
        200,
    )
    assert assigned["status"] == "RESEARCH"
    assert assigned["assigned_drafter_id"] == junior["id"]

    waived_target = file_statutory_conflict(
        world, waiting, severity="ADVISORY", code_citation="23-1-101"
    )
    resolved_target = file_statutory_conflict(
        world, waiting, severity="ADVISORY", code_citation="23-1-102"
    )

    validate_error(
        api_client.resolve_statutory_conflict(
            waived_target["id"],
            resolve_conflict_payload(
                "WAIVED", resolution_note="Junior attempting a waiver."
            ),
            junior_as_counsel,
        ),
        senior_required,
        403,
    )
    waived = validate_success(
        api_client.resolve_statutory_conflict(
            waived_target["id"],
            resolve_conflict_payload(
                "WAIVED", resolution_note="Senior counsel waives the advisory overlap."
            ),
            world["counsel_headers"],
        ),
        200,
    )
    assert waived["resolution_status"] == "WAIVED"

    # The same endpoint under the RESOLVED disposition needs no seniority at all, which
    # is why the refusal above cannot be explained by the endpoint's role list.
    plainly_resolved = validate_success(
        api_client.resolve_statutory_conflict(
            resolved_target["id"],
            resolve_conflict_payload("RESOLVED"),
            world["drafter_headers"],
        ),
        200,
    )
    assert plainly_resolved["resolution_status"] == "RESOLVED"

    # The senior person under the wrong label is stopped one rung earlier.
    validate_error(
        api_client.certify_draft(ripe["id"], certify_draft_payload(0), senior_as_drafter),
        UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.certify_draft(ripe["id"], certify_draft_payload(0), junior_as_counsel),
        senior_required,
        403,
    )
    certified = validate_success(
        api_client.certify_draft(
            ripe["id"], certify_draft_payload(0), world["counsel_headers"]
        ),
        200,
    )
    assert certified["status"] == "DRAFT_READY"
    assert certified["style_findings_count"] == 0
    assert certified["sla_due_utc"] is None

    bill = introduce_bill(world, ripe)
    referral = refer_bill(world, bill)
    set_clock("2026-10-06T00:00:00Z")
    report_referral(world, referral, "FAVORABLE")
    pass_bill(world, bill)
    enrolled = enroll_bill(world, bill)

    # Proposal is shared with the plain Drafter role and carries no seniority test.
    correction = validate_success(
        api_client.create_technical_correction(
            enrolled["id"],
            create_technical_correction_payload(
                enrolled["version"],
                correction_type="CITATION",
                description="Junior drafter proposes a citation fix.",
            ),
            world["drafter_headers"],
        ),
        201,
    )
    assert correction["proposed_by_drafter_id"] == junior["id"]

    # The junior proposed it, so segregation of duties applied too — but seniority is
    # the earlier rung, so that is the code that comes back.
    validate_error(
        api_client.apply_technical_correction(correction["id"], junior_as_counsel),
        senior_required,
        403,
    )
    applied = validate_success(
        api_client.apply_technical_correction(correction["id"], world["counsel_headers"]),
        200,
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_drafter_id"] == senior["id"]

    # No refusal mutated the identity row; the one live engagement is the RESEARCH file.
    still_junior = read_drafter(world, junior["id"])
    assert still_junior["is_senior"] is False
    assert still_junior["active_engagement_count"] == 1


def test_segregation_of_duties_keys_on_the_identity_and_not_on_the_permission_set():
    """PRD: "First, the reviewing counsel must not be the attorney who did the work: if
    `X-User-ID` equals the request's `assigned_drafter_id`, the call is
    `ERR_SEGREGATION_OF_DUTIES`." and "Applying a correction belongs to `ReviewCounsel`,
    and the same segregation of duties that governs draft certification governs it here:
    `X-User-ID` must differ from the correction's `proposed_by_drafter_id`, or the call is
    `ERR_SEGREGATION_OF_DUTIES`." and "On success the correction moves to `APPLIED` with
    `applied_by_drafter_id` set from `X-User-ID` and `applied_utc` stamped from the
    logical clock, the enrollment's `corrections_applied_count` rises by one, its
    `open_corrections_count` drops by one, and its `version` rises by one." and "When all
    three pass, the request moves from `DRAFTING` to `DRAFT_READY`,
    `style_findings_count` is stored, `sla_due_utc` is cleared to null, and the
    attorney's `active_engagement_count` is recomputed downward by one as the request
    leaves the occupancy set."

    Design: Corner/rbac/segregation_of_duties_keys_on_identity_so_the_same_person_cannot_review_their_own_work
    """
    segregation = ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    first_counsel = world["counsel"]
    second_counsel, _ = add_drafter(
        world, full_name="Senior Counsel Two", is_senior=True, max_concurrent_engagements=2
    )
    assert second_counsel["is_senior"] is True
    second_as_counsel = make_review_counsel_headers(second_counsel["id"])

    request = file_drafting_request(
        world,
        subject="Bridge rehabilitation program",
        summary="Create a bridge rehabilitation program.",
        requested_sections_count=2,
        appropriation_requested_cents=0,
    )
    # Assigning oneself the work is allowed; only reviewing it is not.
    assigned = assign_request(
        world,
        request,
        drafter=first_counsel,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    assert assigned["assigned_drafter_id"] == first_counsel["id"]
    complete_research(
        world,
        request,
        affected_sections_count=2,
        drafter_headers=make_drafter_headers(first_counsel["id"]),
    )

    # Authorized, senior, and targeting a ripe request — and still refused, with 409.
    validate_error(
        api_client.certify_draft(
            request["id"], certify_draft_payload(0), world["counsel_headers"]
        ),
        segregation,
        409,
    )
    blocked = read_drafting_request(world, request["id"])
    assert blocked["status"] == "DRAFTING"
    # Only ERR_STYLE_NONCOMPLIANT records the reported count; a segregation refusal
    # leaves the never-reviewed request's style_findings_count null.
    assert blocked["style_findings_count"] is None

    certified = validate_success(
        api_client.certify_draft(
            request["id"], certify_draft_payload(0), second_as_counsel
        ),
        200,
    )
    assert certified["status"] == "DRAFT_READY"
    assert certified["style_findings_count"] == 0
    assert certified["sla_due_utc"] is None

    bill = introduce_bill(world, request)
    referral = refer_bill(world, bill)
    set_clock("2026-10-06T00:00:00Z")
    report_referral(world, referral, "FAVORABLE")
    pass_bill(world, bill)
    enrolled = enroll_bill(world, bill)

    correction = validate_success(
        api_client.create_technical_correction(
            enrolled["id"],
            create_technical_correction_payload(
                enrolled["version"],
                correction_type="TYPO",
                description="Senior counsel one proposes a typo fix.",
            ),
            world["counsel_headers"],
        ),
        201,
    )
    assert correction["proposed_by_drafter_id"] == first_counsel["id"]

    validate_error(
        api_client.apply_technical_correction(
            correction["id"], world["counsel_headers"]
        ),
        segregation,
        409,
    )
    assert read_correction(world, correction["id"])["status"] == "PROPOSED"

    applied = validate_success(
        api_client.apply_technical_correction(correction["id"], second_as_counsel), 200
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_drafter_id"] == second_counsel["id"]

    settled = read_enrolled_bill(world, enrolled["id"])
    assert settled["corrections_applied_count"] == 1
    assert settled["open_corrections_count"] == 0


def test_the_three_narrow_single_reads_close_only_the_roles_left_off_their_lists():
    """PRD: "**Endpoint role.** The acting role appears in the target endpoint's
    authorized list — otherwise `ERR_UNAUTHORIZED`." and "A new member starts with
    `priority_slots_used` at 0, `clarification_pending_count` at 0 and `intake_hold`
    false." and "A new attorney starts with `active_engagement_count` at 0." and "An
    agency carries a `name`, a short `agency_code` that must be unique across all
    agencies — a repeat is `ERR_DUPLICATE_AGENCY_CODE` — an optional `status` of `ACTIVE`
    or `INACTIVE` defaulting to `ACTIVE`, and an optional `max_open_requests` defaulting
    to 3 and required to be at least 1."

    Design: Corner/rbac/the_two_narrow_reads_are_forbidden_outside_their_lane_while_the_shared_reads_stay_open_to_all
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
            "name": "Dept of Transportation",
            "agency_code": "DOT",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    agency_id = world["agency"]["id"]
    drafter_id = world["drafter"]["id"]
    member_id = world["member"]["id"]

    # The agency row is closed to the drafting bench and to legislators.
    for headers in (
        world["drafter_headers"],
        world["counsel_headers"],
        world["member_headers"],
    ):
        validate_error(api_client.get_agency(agency_id, headers), UNAUTHORIZED, 403)
    for headers in (CLERK, FISCAL_OFFICER):
        visible_agency = validate_success(api_client.get_agency(agency_id, headers), 200)
        assert visible_agency["responsiveness_score"] == 100
        assert visible_agency["open_request_count"] == 0

    # The attorney row is closed to legislators and to agency analysts.
    for headers in (world["member_headers"], world["analyst_headers"]):
        validate_error(api_client.get_drafter(drafter_id, headers), UNAUTHORIZED, 403)
    visible_drafter = validate_success(
        api_client.get_drafter(drafter_id, world["drafter_headers"]), 200
    )
    assert visible_drafter["is_senior"] is False
    assert visible_drafter["active_engagement_count"] == 0

    # The member row is closed to agency analysts only.
    validate_error(
        api_client.get_member(member_id, world["analyst_headers"]), UNAUTHORIZED, 403
    )
    visible_member = validate_success(
        api_client.get_member(member_id, world["drafter_headers"]), 200
    )
    assert visible_member["priority_slots_used"] == 0
    assert visible_member["intake_hold"] is False

    # The reference reads really are open to every role, which rules out a blanket gate.
    open_session = validate_success(
        api_client.get_session(world["session"]["id"], world["analyst_headers"]), 200
    )
    committees, meta = validate_paginated(
        api_client.list_session_committees(
            world["session"]["id"], world["analyst_headers"], params={"chamber": "HOUSE"}
        )
    )
    assert meta["total_count"] == 1
    assert committees[0]["id"] == world["committee"]["id"]
    open_committee = validate_success(
        api_client.get_committee(world["committee"]["id"], world["member_headers"]), 200
    )

    # Nothing above was a write: every version is exactly where the fixture left it.
    assert open_session["version"] == world["session"]["version"]
    assert open_committee["version"] == world["committee"]["version"]
    assert visible_member["version"] == world["member"]["version"]
    assert visible_drafter["version"] == world["drafter"]["version"]
    assert visible_agency["version"] == world["agency"]["version"]
