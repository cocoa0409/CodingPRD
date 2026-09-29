"""Validations: confidentiality, the refusal ladder, shape checks and bounds."""

from test_helpers import (
    ADMIN,
    CLERK,
    ApiErrorId,
    add_drafter,
    add_member,
    api_client,
    append_cost_estimates,
    assert_instant,
    assign_payload,
    certify_draft_payload,
    certify_note,
    complete_research,
    create_amendment_payload,
    create_referral_payload,
    create_session_payload,
    draft_amendment,
    file_drafting_request,
    file_statutory_conflict,
    make_drafter_headers,
    make_review_counsel_headers,
    read_bill,
    read_drafter,
    read_committee,
    read_drafting_request,
    read_note,
    read_session,
    return_note,
    set_clock,
    route_fiscal_note,
    refer_bill,
    reject_amendment_payload,
    request_amendment,
    resolve_statutory_conflict,
    setup_introduced_bill,
    setup_request_in_research,
    setup_submitted_note,
    setup_world,
    submit_note,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_rival_member_is_kept_out_of_a_confidential_file_while_an_analyst_stops_earlier():
    """PRD: "A `CONFIDENTIAL` request, and every statutory conflict recorded beneath
    it, is readable by its sponsoring `Member`, by `Drafter` and `ReviewCounsel`, by
    `FiscalOfficer`, by `Clerk` and by `PlatformAdmin` — but never by a different
    `Member`." and "On the unscoped drafting-request collection read, no error is
    raised at all: the confidential rows the acting member does not sponsor are
    simply **omitted from the page and excluded from `total_count`**, so a browsing
    member cannot infer their existence from a row count." and "An `AgencyAnalyst`
    never reaches this rule at all, since that role holds no drafting-request read
    permission and is stopped earlier with `ERR_UNAUTHORIZED`."

    Design: Corner/validations/confidential_request_and_its_conflicts_are_forbidden_to_a_rival_member_while_an_analyst_is_stopped_earlier
    """
    world = setup_world(with_agency=True)
    _rival, rival_headers = add_member(
        world, full_name="Rep Gamma", chamber="HOUSE", party="IND", priority_slots_total=2
    )
    confidential = setup_request_in_research(
        world,
        subject="Closed caucus redistricting draft",
        summary="Prepare a closed redistricting draft.",
        requested_sections_count=2,
        target_code_chapter="Title 2",
        confidentiality="CONFIDENTIAL",
    )
    public = file_drafting_request(
        world,
        subject="Public notice signage",
        summary="Update public notice signage rules.",
        requested_sections_count=1,
        target_code_chapter="Title 24",
        confidentiality="PUBLIC",
    )
    # An advisory finding never bounces the request out of RESEARCH.
    conflict = file_statutory_conflict(
        world,
        confidential,
        severity="ADVISORY",
        code_citation="2-1-101",
        conflict_type="STYLE_VIOLATION",
    )

    validate_error(
        api_client.get_drafting_request(confidential["id"], rival_headers),
        ApiErrorId.ERR_CONFIDENTIAL_ACCESS_DENIED.value,
        403,
    )
    validate_error(
        api_client.list_request_statutory_conflicts(confidential["id"], rival_headers),
        ApiErrorId.ERR_CONFIDENTIAL_ACCESS_DENIED.value,
        403,
    )
    # The analyst holds no drafting-pipeline read at all, so the role rung fires.
    validate_error(
        api_client.get_statutory_conflict(conflict["id"], world["analyst_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    rows, meta = validate_paginated(
        api_client.list_drafting_requests(
            rival_headers, params={"session_id": world["session"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [public["id"]]

    validate_success(
        api_client.get_drafting_request(confidential["id"], world["member_headers"]), 200
    )
    validate_success(api_client.get_drafting_request(confidential["id"], CLERK), 200)


def test_a_public_file_stays_readable_by_a_rival_member_and_an_unassigned_drafter():
    """PRD: "A drafting request declares its `confidentiality` as either
    `CONFIDENTIAL` or `PUBLIC`, defaulting to `PUBLIC`." and "On the three targeted
    reads — a single drafting request, the statutory-conflict list beneath a request,
    and a single statutory conflict — a `Member` who is not the sponsor of a
    `CONFIDENTIAL` request is refused with `ERR_CONFIDENTIAL_ACCESS_DENIED` (HTTP
    403), because the existence of the row is already implied by the identifier they
    supplied."

    Design: Corner/validations/public_request_stays_readable_by_every_role_when_the_confidentiality_rule_is_satisfied
    """
    world = setup_world(with_agency=True)
    _rival, rival_headers = add_member(
        world, full_name="Rep Gamma", chamber="HOUSE", party="IND", priority_slots_total=2
    )
    unassigned_drafter, _unassigned_headers = add_drafter(
        world, full_name="Drafter Two", is_senior=False, max_concurrent_engagements=2
    )
    public = setup_request_in_research(
        world,
        subject="Public notice signage",
        summary="Update public notice signage rules.",
        requested_sections_count=1,
        target_code_chapter="Title 24",
        confidentiality="PUBLIC",
    )
    conflict = file_statutory_conflict(
        world,
        public,
        severity="ADVISORY",
        code_citation="24-1-101",
        conflict_type="STYLE_VIOLATION",
    )

    seen = validate_success(
        api_client.get_drafting_request(public["id"], rival_headers), 200
    )
    assert seen["confidentiality"] == "PUBLIC"
    validate_paginated(
        api_client.list_request_statutory_conflicts(
            public["id"], world["fiscal_officer_headers"]
        )
    )
    # Read access is not ownership-scoped: an unassigned attorney may look.
    seen_conflict = validate_success(
        api_client.get_statutory_conflict(
            conflict["id"], make_drafter_headers(unassigned_drafter["id"])
        ),
        200,
    )
    assert seen_conflict["id"] == conflict["id"]

    rows, meta = validate_paginated(
        api_client.list_drafting_requests(
            CLERK,
            params={"session_id": world["session"]["id"], "confidentiality": "PUBLIC"},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [public["id"]]


def test_the_blocking_conflict_refusal_outranks_the_style_finding_refusal():
    """PRD: "Second, `open_blocking_conflict_count` must be 0, or the call is
    `ERR_BLOCKING_CONFLICT_UNRESOLVED`." and "Third, `style_findings_count` must be
    exactly 0; a positive count is refused with `ERR_STYLE_NONCOMPLIANT` — and
    uniquely among the refusals in this specification, **the reported count is still
    recorded on the request** even though the state does not advance, so the
    reviewer's finding is preserved for the next attempt." and "Note what a waiver
    does and does not do — the conflict stays on the record and keeps contributing to
    `blocking_conflict_count` and therefore to the complexity score; the waiver only
    stops it from blocking certification."

    Design: Corner/validations/unresolved_blocking_conflict_error_outranks_the_style_finding_error_on_the_same_call
    """
    world = setup_world()
    request = setup_request_in_research(
        world,
        subject="Repeal of the obsolete bonding article",
        summary="Repeal the obsolete bonding article.",
        requested_sections_count=2,
        target_code_chapter="Title 41",
    )
    conflict = file_statutory_conflict(
        world,
        request,
        severity="BLOCKING",
        code_citation="41-3-101",
        conflict_type="REPEALS_ACTIVE",
    )
    in_drafting = complete_research(world, request, affected_sections_count=2)
    assert in_drafting["status"] == "DRAFTING"
    assert in_drafting["open_blocking_conflict_count"] == 1

    first = api_client.certify_draft(
        request["id"], certify_draft_payload(3), world["counsel_headers"]
    )
    validate_error(first, ApiErrorId.ERR_BLOCKING_CONFLICT_UNRESOLVED.value, 409)

    held = read_drafting_request(world, request["id"])
    assert held["status"] == "DRAFTING"
    assert held["style_findings_count"] is None

    resolve_statutory_conflict(
        world,
        conflict,
        resolution_status="WAIVED",
        resolution_note="Repeal is intentional; waiver granted.",
    )

    second = api_client.certify_draft(
        request["id"], certify_draft_payload(3), world["counsel_headers"]
    )
    validate_error(second, ApiErrorId.ERR_STYLE_NONCOMPLIANT.value, 422)

    recorded = read_drafting_request(world, request["id"])
    assert recorded["style_findings_count"] == 3
    assert recorded["status"] == "DRAFTING"
    assert recorded["open_blocking_conflict_count"] == 0
    # The waived finding still counts towards the complexity score.
    assert recorded["blocking_conflict_count"] == 1

    third = validate_success(
        api_client.certify_draft(
            request["id"], certify_draft_payload(0), world["counsel_headers"]
        ),
        200,
    )
    assert third["status"] == "DRAFT_READY"
    assert third["style_findings_count"] == 0
    assert third["open_blocking_conflict_count"] == 0


def test_self_review_is_reported_before_the_open_blocking_conflict():
    """PRD: "When a single request violates several rules at once, exactly one error
    is reported, and which one is determined by a fixed ladder evaluated top to
    bottom." and "And within the business band, segregation of duties precedes the
    drafting-quality gates, so a drafter who tries to certify their own work is told
    about the conflict of interest even when their draft also carries open blocking
    conflicts or positive style findings." and "First, the reviewing counsel must not
    be the attorney who did the work: if `X-User-ID` equals the request's
    `assigned_drafter_id`, the call is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_error_outranks_the_unresolved_blocking_conflict_error
    """
    world = setup_world()
    counsel = world["counsel"]
    counsel_as_drafter = make_drafter_headers(counsel["id"])
    second_counsel, _ignored = add_drafter(
        world, full_name="Senior Counsel Two", is_senior=True, max_concurrent_engagements=2
    )
    request = setup_request_in_research(
        world,
        drafter=counsel,
        subject="Repeal of the obsolete bonding article",
        summary="Repeal the obsolete bonding article.",
        requested_sections_count=2,
        target_code_chapter="Title 41",
    )
    file_statutory_conflict(
        world,
        request,
        severity="BLOCKING",
        code_citation="41-3-101",
        conflict_type="REPEALS_ACTIVE",
        drafter_headers=counsel_as_drafter,
    )
    complete_research(
        world, request, affected_sections_count=2, drafter_headers=counsel_as_drafter
    )

    self_review = api_client.certify_draft(
        request["id"],
        certify_draft_payload(4),
        make_review_counsel_headers(counsel["id"]),
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    independent = api_client.certify_draft(
        request["id"],
        certify_draft_payload(4),
        make_review_counsel_headers(second_counsel["id"]),
    )
    # With the conflict of interest removed the drafting-quality gate surfaces.
    validate_error(independent, ApiErrorId.ERR_BLOCKING_CONFLICT_UNRESOLVED.value, 409)

    unchanged = read_drafting_request(world, request["id"])
    assert unchanged["status"] == "DRAFTING"
    assert unchanged["style_findings_count"] is None


def test_the_seniority_check_is_reported_before_the_requests_own_state():
    """PRD: "On the four `ReviewCounsel`-only operations, the backing `Drafter` row
    has `is_senior` true — otherwise `ERR_SENIOR_COUNSEL_REQUIRED`." and "The target
    row is in a state from which the requested transition is declared — otherwise the
    matching invalid-state identifier for that entity." and "Evaluation stops at the
    first violated rung."

    Design: Corner/validations/non_senior_reviewer_check_outranks_the_target_state_check_on_certify_draft
    """
    world = setup_world()
    request = file_drafting_request(
        world,
        subject="Uniform citation format",
        summary="Adopt a uniform statutory citation format.",
        requested_sections_count=2,
        target_code_chapter="Title 28",
    )
    assert request["status"] == "SUBMITTED"

    junior = api_client.certify_draft(
        request["id"],
        certify_draft_payload(0),
        make_review_counsel_headers(world["drafter"]["id"]),
    )
    validate_error(junior, ApiErrorId.ERR_SENIOR_COUNSEL_REQUIRED.value, 403)
    assert read_drafting_request(world, request["id"])["status"] == "SUBMITTED"

    senior = api_client.certify_draft(
        request["id"], certify_draft_payload(0), world["counsel_headers"]
    )
    # The identical call from a senior reviewer reaches the state rung underneath.
    validate_error(senior, ApiErrorId.ERR_INVALID_DRAFTING_REQUEST_STATE.value, 409)
    assert read_drafting_request(world, request["id"])["status"] == "SUBMITTED"


ROUND_LINE_2027 = {
    "fiscal_year": 2027,
    "scenario": "BASELINE",
    "personnel_cost_cents": 5_000_000,
    "operating_cost_cents": 1_000_000,
    "one_time_cost_cents": 0,
    "fte_count": 1.0,
    "revenue_impact_cents": 0,
    "assumption_note": "Round zero FY2027.",
}

ROUND_LINE_2028 = {
    "fiscal_year": 2028,
    "scenario": "BASELINE",
    "personnel_cost_cents": 3_000_000,
    "operating_cost_cents": 1_000_000,
    "one_time_cost_cents": 0,
    "fte_count": 1.0,
    "revenue_impact_cents": 0,
    "assumption_note": "Round zero FY2028.",
}


def test_the_submission_gates_run_in_order_and_reset_on_every_revision_round():
    """PRD: "At least one cost estimate line of that current round must exist, or the
    call is `ERR_NO_COST_ESTIMATES`." and "The `BASELINE` lines of that current round
    must cover every year listed in the session's `required_fiscal_years`, with no
    year missing, or the call is `ERR_ESTIMATE_YEARS_INCOMPLETE`." and "The note moves
    from `SUBMITTED` to `RETURNED_FOR_REVISION` and its `revision_round` rises by one,
    which flips `included_in_certification` to false on every cost estimate line of
    the prior round and drops them out of every total — the analyst must file a fresh
    set."

    Design: Corner/validations/submission_gates_run_no_estimates_then_missing_year_then_pass_and_reset_on_every_round
    """
    world = setup_world(with_agency=True)
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Ferry terminal repairs",
        summary="Repair the ferry terminals.",
        target_code_chapter="Title 43",
        appropriation_requested_cents=6_000_000,
    )
    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")

    empty = api_client.submit_fiscal_note_request(
        note["id"], {"submission_note": "Nothing filed yet."}, world["analyst_headers"]
    )
    validate_error(empty, ApiErrorId.ERR_NO_COST_ESTIMATES.value, 422)
    assert read_note(world, note["id"])["status"] == "ROUTED"

    append_cost_estimates(world, note, [ROUND_LINE_2027])

    incomplete = api_client.submit_fiscal_note_request(
        note["id"], {"submission_note": "FY2028 still outstanding."}, world["analyst_headers"]
    )
    validate_error(incomplete, ApiErrorId.ERR_ESTIMATE_YEARS_INCOMPLETE.value, 422)
    assert read_note(world, note["id"])["status"] == "ROUTED"

    append_cost_estimates(world, note, [ROUND_LINE_2028])

    submitted = validate_success(
        api_client.submit_fiscal_note_request(
            note["id"], {"submission_note": "Both years filed."}, world["analyst_headers"]
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["direct_cost_cents"] == 10_000_000
    assert float(submitted["contingency_pct"]) == 0.05
    assert submitted["contingency_cents"] == 500_000
    assert submitted["certified_total_cents"] == 10_500_000

    returned = return_note(
        world, note, return_reason="Rebuild the estimate on the revised caseload."
    )
    assert returned["status"] == "RETURNED_FOR_REVISION"
    assert returned["revision_round"] == 1

    prior_rows, prior_meta = validate_paginated(
        api_client.list_cost_estimates(
            note["id"], world["analyst_headers"], params={"revision_round": 0}
        )
    )
    assert prior_meta["total_count"] == 2
    assert all(row["included_in_certification"] is False for row in prior_rows)

    stale = api_client.submit_fiscal_note_request(
        note["id"], {"submission_note": "Resubmitting without refiling."}, world["analyst_headers"]
    )
    # Two complete rows exist, but they belong to the closed round.
    validate_error(stale, ApiErrorId.ERR_NO_COST_ESTIMATES.value, 422)

    _fresh_rows, fresh_meta = validate_paginated(
        api_client.list_cost_estimates(
            note["id"], world["analyst_headers"], params={"revision_round": 1}
        )
    )
    assert fresh_meta["total_count"] == 0


TRIMMED_LINE_2027 = {
    "fiscal_year": 2027,
    "scenario": "BASELINE",
    "personnel_cost_cents": 0,
    "operating_cost_cents": 4_000_000,
    "one_time_cost_cents": 0,
    "fte_count": 0.0,
    "revenue_impact_cents": 0,
    "assumption_note": "Round one FY2027, trimmed.",
}

TRIMMED_LINE_2028 = {
    "fiscal_year": 2028,
    "scenario": "BASELINE",
    "personnel_cost_cents": 0,
    "operating_cost_cents": 5_000_000,
    "one_time_cost_cents": 0,
    "fte_count": 0.0,
    "revenue_impact_cents": 0,
    "assumption_note": "Round one FY2028, trimmed.",
}


def test_the_session_fiscal_cap_refuses_the_crossing_certification_then_admits_a_trim():
    """PRD: "And the posting must fit under the ceiling: the session's
    `certified_fiscal_total_cents` plus this note's `certified_total_cents` must be at
    most the session's `fiscal_cap_cents`, or the call is
    `ERR_SESSION_FISCAL_CAP_EXCEEDED`." and "On success the note moves to `CERTIFIED`,
    `certified_utc` is stamped with the logical clock, the note's
    `certified_total_cents` is added to the session's `certified_fiscal_total_cents`"

    Design: Corner/validations/session_fiscal_cap_refuses_the_certification_that_would_cross_it_then_admits_a_trimmed_revision
    """
    world = setup_world(
        with_agency=True,
        # The cap must itself be at least the constrained threshold, so both sit at
        # 20,000,000: the ledger stays NORMAL below it and the second posting crosses it.
        session_overrides={
            "fiscal_cap_cents": 20_000_000,
            "constrained_threshold_cents": 20_000_000,
        },
    )
    _request_one, bill_one = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Ferry terminal repairs",
        summary="Repair the ferry terminals.",
        target_code_chapter="Title 43",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, bill_two = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Ferry fare schedule",
        summary="Restate the ferry fare schedule.",
        target_code_chapter="Title 43",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    note_one = setup_submitted_note(
        world, bill_one, lines=[ROUND_LINE_2027, ROUND_LINE_2028]
    )
    note_two = setup_submitted_note(
        world, bill_two, lines=[ROUND_LINE_2027, ROUND_LINE_2028]
    )
    assert note_one["certified_total_cents"] == 10_500_000
    assert note_two["certified_total_cents"] == 10_500_000

    certify_note(world, note_one)
    session = read_session(world)
    assert session["certified_fiscal_total_cents"] == 10_500_000
    assert session["fiscal_posture"] == "NORMAL"
    assert read_bill(world, bill_one["id"])["fiscal_status"] == "NOTE_COMPLETE"

    refused = api_client.certify_fiscal_note_request(
        note_two["id"], {"certification_note": "n2 as filed."}, world["fiscal_officer_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_SESSION_FISCAL_CAP_EXCEEDED.value, 409)

    # No partial credit: nothing about the refused posting stuck.
    assert read_session(world)["certified_fiscal_total_cents"] == 10_500_000
    assert read_note(world, note_two["id"])["status"] == "SUBMITTED"
    assert read_bill(world, bill_two["id"])["fiscal_status"] == "NOTE_PENDING"

    return_note(
        world, note_two, return_reason="Re-cost within the remaining session capacity."
    )
    append_cost_estimates(world, note_two, [TRIMMED_LINE_2027, TRIMMED_LINE_2028])
    resubmitted = submit_note(world, note_two, submission_note="n2 round 1 complete.")

    assert resubmitted["direct_cost_cents"] == 9_000_000
    assert float(resubmitted["contingency_pct"]) == 0.05
    assert resubmitted["contingency_cents"] == 450_000
    assert resubmitted["certified_total_cents"] == 9_450_000

    certified = validate_success(
        api_client.certify_fiscal_note_request(
            note_two["id"],
            {"certification_note": "n2 trimmed certification."},
            world["fiscal_officer_headers"],
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    final_session = read_session(world)
    assert final_session["certified_fiscal_total_cents"] == 19_950_000
    assert final_session["fiscal_posture"] == "NORMAL"
    assert read_bill(world, bill_two["id"])["fiscal_status"] == "NOTE_COMPLETE"


def test_pagination_bounds_are_refused_at_zero_at_one_hundred_one_and_below_zero():
    """PRD: "`limit` controls page size: it defaults to 10 when omitted, may be no
    smaller than 1 and no larger than 100." and "A `limit` that is not an integer in
    the range 1 through 100 inclusive, or an `offset` that is not an integer of at
    least 0, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/pagination_bounds_are_rejected_at_zero_at_one_hundred_one_and_at_a_negative_offset
    """
    world = setup_world()
    session_id = world["session"]["id"]
    for index, subject in enumerate(("Measure one", "Measure two"), start=1):
        file_drafting_request(
            world,
            subject=subject,
            summary=f"Filed measure number {index}.",
            requested_sections_count=1,
            target_code_chapter=f"Title {index}",
        )

    for params in (
        {"session_id": session_id, "limit": 0},
        {"session_id": session_id, "limit": 101},
        {"session_id": session_id, "offset": -1},
    ):
        validate_error(
            api_client.list_drafting_requests(CLERK, params=params),
            ApiErrorId.ERR_PAGINATION_INVALID.value,
            400,
        )

    rows, meta = validate_paginated(
        api_client.list_drafting_requests(
            CLERK, params={"session_id": session_id, "limit": 100, "offset": 0}
        )
    )
    # The upper bound is inclusive, so 100 is admitted where 101 was not.
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2

    page, page_meta = validate_paginated(
        api_client.list_drafting_requests(
            CLERK, params={"session_id": session_id, "limit": 1, "offset": 1}
        )
    )
    assert page_meta["total_count"] == 2
    assert page_meta["has_more"] is False
    assert len(page) == 1


def test_an_engagement_window_that_ends_when_it_starts_is_refused_as_invalid_request():
    """PRD: "Every required field present, every enum value declared, every `*_cents`
    value honouring its minimum, every interval ending strictly after it starts, and
    `required_fiscal_years` a non-empty strictly ascending array of integers —
    otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/validations/an_engagement_window_that_ends_when_it_starts_returns_invalid_request
    """
    world = setup_world()
    request = file_drafting_request(
        world,
        subject="Uniform citation format",
        summary="Adopt a uniform statutory citation format.",
        requested_sections_count=2,
        target_code_chapter="Title 28",
    )
    assert world["drafter"]["max_concurrent_engagements"] == 2

    degenerate = api_client.assign_drafting_request(
        request["id"],
        assign_payload(
            world["drafter"]["id"],
            engagement_start_utc="2026-09-03T09:00:00Z",
            engagement_end_utc="2026-09-03T09:00:00Z",
        ),
        world["counsel_headers"],
    )
    validate_error(degenerate, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert read_drafting_request(world, request["id"])["status"] == "SUBMITTED"
    assert read_drafter(world)["active_engagement_count"] == 0

    descending = api_client.create_session(
        create_session_payload(name="Bad fiscal years", required_fiscal_years=[2028, 2027]),
        ADMIN,
    )
    validate_error(descending, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    accepted = validate_success(
        api_client.assign_drafting_request(
            request["id"],
            assign_payload(
                world["drafter"]["id"],
                engagement_start_utc="2026-09-03T09:00:00Z",
                engagement_end_utc="2026-09-03T09:00:01Z",
            ),
            world["counsel_headers"],
        ),
        200,
    )
    # Only the degenerate interval is refused; one second of window is enough.
    assert accepted["status"] == "RESEARCH"
    assert read_drafter(world)["active_engagement_count"] == 1


def test_a_hearing_window_past_the_report_deadline_is_refused_but_the_edge_is_admitted():
    """PRD: "The window must end at or before the session's
    `committee_report_deadline_utc`, since a window ending after the reporting
    deadline could never be reported out; a later end is
    `ERR_HEARING_WINDOW_AFTER_DEADLINE`." and "A successful referral is created in
    `status` `IN_COMMITTEE` with `reported_utc` null." and "The committee's
    `active_referral_count` and the bill's `referral_count` each rise by one, and
    the bill's `version` rises by one." and "The first referral also advances the
    bill from `INTRODUCED` to `REFERRED`; subsequent referrals leave it in
    `REFERRED`, which is how a measure picks up an additional fiscal-committee
    referral under a constrained session posture."

    Design: Corner/validations/hearing_window_ending_after_the_report_deadline_is_rejected_while_the_exact_deadline_is_accepted
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
    assert_instant(read_session(world)["committee_report_deadline_utc"], "2026-11-01T00:00:00Z")
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Uniform bond covenants",
        summary="Standardize the state bond covenants.",
        target_code_chapter="Title 41",
        appropriation_requested_cents=0,
    )
    committee_id = world["committee"]["id"]

    too_late = api_client.create_referral(
        bill["id"],
        create_referral_payload(
            committee_id,
            hearing_window_start_utc="2026-11-01T14:00:00Z",
            hearing_window_end_utc="2026-11-01T16:00:00Z",
        ),
        CLERK,
    )
    validate_error(too_late, ApiErrorId.ERR_HEARING_WINDOW_AFTER_DEADLINE.value, 422)
    assert read_committee(world, committee_id)["active_referral_count"] == 0
    assert read_bill(world, bill["id"])["legislative_status"] == "INTRODUCED"

    on_the_edge = validate_success(
        api_client.create_referral(
            bill["id"],
            create_referral_payload(
                committee_id,
                hearing_window_start_utc="2026-10-31T22:00:00Z",
                hearing_window_end_utc="2026-11-01T00:00:00Z",
            ),
            CLERK,
        ),
        201,
    )
    assert on_the_edge["status"] == "IN_COMMITTEE"
    # The window end plus seven days would be 2026-11-08, so the session clamps it.
    assert_instant(on_the_edge["report_deadline_utc"], "2026-11-01T00:00:00Z")
    assert read_bill(world, bill["id"])["legislative_status"] == "REFERRED"
    assert read_committee(world, committee_id)["active_referral_count"] == 1


def _two_referred_house_bills():
    """Two HOUSE bills, each holding one IN_COMMITTEE referral on its own window."""
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    _request_one, bill_one = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Uniform bond covenants",
        summary="Standardize the state bond covenants.",
        target_code_chapter="Title 41",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, bill_two = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Bond disclosure schedule",
        summary="Restate the bond disclosure schedule.",
        target_code_chapter="Title 41",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    referral_one = refer_bill(world, bill_one)
    referral_two = refer_bill(
        world,
        bill_two,
        hearing_window_start_utc="2026-10-06T14:00:00Z",
        hearing_window_end_utc="2026-10-06T16:00:00Z",
    )
    return world, bill_one, referral_one, referral_two


def test_amendment_stage_must_agree_with_the_bills_posture_and_its_own_referral():
    """PRD: "Stage and referral must agree." and "A `COMMITTEE`-stage amendment must
    supply a `committee_referral_id` naming a referral **of this same bill** that is
    still `IN_COMMITTEE`." and "A `FLOOR`-stage amendment must supply no
    `committee_referral_id` at all and requires the bill's `legislative_status` to be
    `REPORTED`." and "Any mismatch — committee stage without a live referral of this
    bill, floor stage carrying a referral reference, or floor stage on a bill that is
    not `REPORTED` — is `ERR_AMENDMENT_STAGE_MISMATCH`."

    Design: Corner/validations/amendment_stage_rules_bind_the_stage_to_the_bills_posture_and_to_its_own_referral
    """
    world, bill_one, referral_one, referral_two = _two_referred_house_bills()
    version_before = read_bill(world, bill_one["id"])["version"]
    window = {
        "drafting_start_utc": "2026-10-06T00:00:00Z",
        "drafting_due_utc": "2026-10-06T06:00:00Z",
    }

    floor_on_a_referred_bill = api_client.create_amendment(
        create_amendment_payload(
            version_before,
            bill_one["id"],
            stage="FLOOR",
            summary="Floor amendment on a bill that is only referred.",
            fiscal_impact_delta_cents=0,
            **window,
        ),
        world["member_headers"],
    )
    validate_error(
        floor_on_a_referred_bill, ApiErrorId.ERR_AMENDMENT_STAGE_MISMATCH.value, 422
    )

    committee_without_referral = api_client.create_amendment(
        create_amendment_payload(
            version_before,
            bill_one["id"],
            stage="COMMITTEE",
            summary="Committee amendment with no referral named.",
            fiscal_impact_delta_cents=0,
            **window,
        ),
        world["member_headers"],
    )
    validate_error(
        committee_without_referral, ApiErrorId.ERR_AMENDMENT_STAGE_MISMATCH.value, 422
    )

    committee_with_a_siblings_referral = api_client.create_amendment(
        create_amendment_payload(
            version_before,
            bill_one["id"],
            stage="COMMITTEE",
            summary="Committee amendment naming a sibling bill's referral.",
            fiscal_impact_delta_cents=0,
            committee_referral_id=referral_two["id"],
            **window,
        ),
        world["member_headers"],
    )
    validate_error(
        committee_with_a_siblings_referral,
        ApiErrorId.ERR_AMENDMENT_STAGE_MISMATCH.value,
        422,
    )

    accepted = validate_success(
        api_client.create_amendment(
            create_amendment_payload(
                version_before,
                bill_one["id"],
                stage="COMMITTEE",
                summary="Committee amendment naming this bill's own referral.",
                fiscal_impact_delta_cents=0,
                committee_referral_id=referral_one["id"],
                **window,
            ),
            world["member_headers"],
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert accepted["stage"] == "COMMITTEE"
    assert accepted["committee_referral_id"] == referral_one["id"]
    # Only the accepted call wrote to the bill.
    assert read_bill(world, bill_one["id"])["version"] == version_before + 1


def test_a_supersede_target_must_already_be_rejected_or_lapsed():
    """PRD: "When `supersedes_amendment_id` is present it must name an amendment of
    the **same** bill whose `status` is `REJECTED` or `LAPSED`; naming an amendment of
    another bill, or one in any other status, is `ERR_SUPERSEDE_TARGET_INVALID`."

    Design: Corner/validations/supersede_target_must_already_be_rejected_or_lapsed_on_the_same_bill
    """
    world, bill_one, referral_one, _referral_two = _two_referred_house_bills()
    window = {
        "drafting_start_utc": "2026-10-06T00:00:00Z",
        "drafting_due_utc": "2026-10-06T06:00:00Z",
    }
    target = request_amendment(
        world,
        bill_one,
        stage="COMMITTEE",
        committee_referral_id=referral_one["id"],
        fiscal_impact_delta_cents=0,
        summary="Original committee language.",
        **window,
    )
    assert target["status"] == "REQUESTED"

    premature = api_client.create_amendment(
        create_amendment_payload(
            read_bill(world, bill_one["id"])["version"],
            bill_one["id"],
            stage="COMMITTEE",
            summary="Replacement while the target is still requested.",
            fiscal_impact_delta_cents=0,
            committee_referral_id=referral_one["id"],
            supersedes_amendment_id=target["id"],
            **window,
        ),
        world["member_headers"],
    )
    validate_error(premature, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value, 422)

    # Rejection is available only to a DRAFTED amendment, so the target is drafted
    # first and only then rejected into a valid supersession target.
    drafted_target = draft_amendment(world, target)
    assert drafted_target["status"] == "DRAFTED"

    rejected = validate_success(
        api_client.reject_amendment(
            target["id"],
            reject_amendment_payload(rejection_reason="Language withdrawn in committee."),
            CLERK,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    replacement = validate_success(
        api_client.create_amendment(
            create_amendment_payload(
                read_bill(world, bill_one["id"])["version"],
                bill_one["id"],
                stage="COMMITTEE",
                summary="Replacement now that the target is rejected.",
                fiscal_impact_delta_cents=0,
                committee_referral_id=referral_one["id"],
                supersedes_amendment_id=target["id"],
                **window,
            ),
            world["member_headers"],
        ),
        201,
    )
    assert replacement["supersedes_amendment_id"] == target["id"]

    rows, meta = validate_paginated(
        api_client.list_amendments(CLERK, params={"supersedes_amendment_id": target["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [replacement["id"]]


def test_the_logical_clock_refuses_a_rewind_but_accepts_the_instant_it_already_holds():
    """PRD: "The clock is monotonic: the supplied instant must be greater than or
    equal to the current reading, and a request carrying an earlier instant is refused
    with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)." and "Advancing the clock mutates no
    entity and returns no resource body — deadlines are never evaluated
    retroactively, so a drafting service-level target that has quietly passed is
    discovered at the next write against that request, not at the moment the clock
    crosses it."

    Design: Corner/validations/logical_clock_cannot_run_backwards_but_may_be_re_set_to_the_same_instant
    """
    set_clock("2026-09-05T12:00:00Z")

    rewind = api_client.set_clock("2026-09-05T11:59:59Z", ADMIN)
    validate_error(rewind, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value, 422)

    # The comparison is inclusive, so re-setting the held instant is admitted.
    same_instant = api_client.set_clock("2026-09-05T12:00:00Z", ADMIN)
    assert same_instant.status_code == 200, same_instant.text

    # And the refused rewind never moved the clock, which this advance confirms.
    forward = api_client.set_clock("2026-09-05T12:00:01Z", ADMIN)
    assert forward.status_code == 200, forward.text
