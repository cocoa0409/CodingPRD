"""Refusal precedence: the ladder stops at the first violated rung."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_bill_payload,
    create_drafting_request_payload,
    file_drafting_request,
    file_statutory_conflict,
    read_drafting_request,
    read_member,
    read_session,
    set_clock,
    setup_draft_ready_request,
    setup_request_in_drafting,
    setup_world,
    validate_error,
)


def test_drafting_request_state_error_outranks_the_introduction_deadline_error():
    """PRD: "The payload names a single field, `drafting_request_id`, and that
    request must be in `DRAFT_READY`; any other state is
    `ERR_INVALID_DRAFTING_REQUEST_STATE`." and "11. **Target state.** The target
    row is in a state from which the requested transition is declared —
    otherwise the matching invalid-state identifier for that entity." and "20.
    **Temporal deadlines.** Introduction deadline, committee report deadline,
    amendment turnaround, sine die, and the hearing-window-after-deadline
    check."

    Design: Difficulty/priority_pair_validation_conflict/bill_introduction_state_error_outranks_introduction_deadline_error
    """
    world = setup_world()
    request = setup_request_in_drafting(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Municipal annexation procedure",
        summary="Modernize annexation procedure.",
        target_code_chapter="Title 7",
        appropriation_requested_cents=0,
    )
    # The file never reached DRAFT_READY, and the clock is now past the deadline.
    set_clock("2026-10-16T00:00:00Z")

    response = api_client.create_bill(
        create_bill_payload(request["id"]), world["clerk_headers"]
    )

    body = validate_error(
        response, ApiErrorId.ERR_INVALID_DRAFTING_REQUEST_STATE.value, 409
    )
    assert body["error_id"] != ApiErrorId.ERR_INTRODUCTION_DEADLINE_PASSED.value

    after = read_drafting_request(world, request["id"])
    assert after["status"] == "DRAFTING"
    session = read_session(world)
    assert session["bills_introduced_count"] == 0
    assert session["next_house_bill_number"] == 1


def test_member_intake_hold_error_outranks_priority_slots_exhausted():
    """PRD: "Evaluation stops at the first violated rung." and "19. **Member
    intake hold.** `ERR_MEMBER_INTAKE_HOLD`." and "23. **Fiscal.** Member
    priority slots, the session fiscal cap, and the constrained-posture
    fiscal-committee requirement."

    Design: Difficulty/priority_pair_validation_conflict/drafting_request_intake_hold_error_outranks_priority_slots_exhausted_error
    """
    world = setup_world(
        member_overrides={
            "full_name": "Rep Beta",
            "chamber": "HOUSE",
            "party": "IND",
            "priority_slots_total": 1,
        }
    )
    request_a = setup_request_in_drafting(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Fire district consolidation",
        summary="Allow fire district consolidation.",
        target_code_chapter="Title 32",
        priority_flag=True,
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-10T00:00:00Z",
    )
    request_b = setup_request_in_drafting(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Library district boundaries",
        summary="Redraw library district boundaries.",
        target_code_chapter="Title 33",
        priority_flag=False,
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-03T00:00:00Z",
        engagement_end_utc="2026-09-11T00:00:00Z",
    )
    file_statutory_conflict(
        world,
        request_a,
        severity="BLOCKING",
        code_citation="32-1-301",
        conflict_type="AMENDS_SAME_SECTION",
    )
    file_statutory_conflict(
        world,
        request_b,
        severity="BLOCKING",
        code_citation="33-2-118",
        conflict_type="DUPLICATE_ENACTMENT",
    )
    # The member's single priority slot is already spent, and both of their
    # files are now awaiting clarification.
    on_hold = read_member(world)
    assert on_hold["intake_hold"] is True
    assert on_hold["clarification_pending_count"] == 2
    assert on_hold["priority_slots_used"] == 1

    response = api_client.create_drafting_request(
        create_drafting_request_payload(
            world["session"]["id"],
            subject="Water district audits",
            summary="Require annual water district audits.",
            requested_sections_count=2,
            target_code_chapter="Title 37",
            confidentiality="PUBLIC",
            priority_flag=True,
            appropriation_requested_cents=0,
        ),
        world["member_headers"],
    )

    body = validate_error(response, ApiErrorId.ERR_MEMBER_INTAKE_HOLD.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_PRIORITY_SLOTS_EXHAUSTED.value

    after = read_member(world)
    assert after["intake_hold"] is True
    assert after["clarification_pending_count"] == 2
    assert after["priority_slots_used"] == 1


def test_introduction_deadline_error_does_fire_once_the_request_reaches_draft_ready():
    """PRD: "The session must be `CONVENED`, the logical clock must be at or
    before the session's `introduction_deadline_utc` — a later clock is
    `ERR_INTRODUCTION_DEADLINE_PASSED` — and the request's
    `open_blocking_conflict_count`, the number of its `BLOCKING` findings still
    sitting in `resolution_status` `OPEN`, must be 0, or introduction is refused
    with `ERR_BLOCKING_CONFLICT_UNRESOLVED` even though style certification
    already passed."

    Design: Difficulty/priority_pair_validation_conflict/bill_introduction_state_error_outranks_introduction_deadline_error
    """
    world = setup_world()
    request = setup_draft_ready_request(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Municipal annexation procedure",
        summary="Modernize annexation procedure.",
        target_code_chapter="Title 7",
        appropriation_requested_cents=0,
    )
    assert request["status"] == "DRAFT_READY"
    set_clock("2026-10-16T00:00:00Z")

    response = api_client.create_bill(
        create_bill_payload(request["id"]), world["clerk_headers"]
    )

    validate_error(response, ApiErrorId.ERR_INTRODUCTION_DEADLINE_PASSED.value, 409)
    assert read_drafting_request(world, request["id"])["status"] == "DRAFT_READY"
    assert read_session(world)["bills_introduced_count"] == 0


def test_priority_slots_exhausted_fires_when_the_member_is_not_on_intake_hold():
    """PRD: "Separately, a request that declares `priority_flag` true is refused
    with `ERR_PRIORITY_SLOTS_EXHAUSTED` unless the member's
    `priority_slots_used` is strictly less than their `priority_slots_total`."

    Design: Difficulty/priority_pair_validation_conflict/drafting_request_intake_hold_error_outranks_priority_slots_exhausted_error
    """
    world = setup_world(
        member_overrides={
            "full_name": "Rep Beta",
            "chamber": "HOUSE",
            "party": "IND",
            "priority_slots_total": 1,
        }
    )
    file_drafting_request(
        world,
        subject="Fire district consolidation",
        summary="Allow fire district consolidation.",
        requested_sections_count=3,
        target_code_chapter="Title 32",
        priority_flag=True,
        appropriation_requested_cents=0,
    )
    clean = read_member(world)
    assert clean["intake_hold"] is False
    assert clean["priority_slots_used"] == 1

    response = api_client.create_drafting_request(
        create_drafting_request_payload(
            world["session"]["id"],
            subject="Water district audits",
            summary="Require annual water district audits.",
            requested_sections_count=2,
            target_code_chapter="Title 37",
            confidentiality="PUBLIC",
            priority_flag=True,
            appropriation_requested_cents=0,
        ),
        world["member_headers"],
    )

    validate_error(response, ApiErrorId.ERR_PRIORITY_SLOTS_EXHAUSTED.value, 409)
    assert read_member(world)["priority_slots_used"] == 1
