"""Punch list, final walkthrough, warranty coverage, callbacks and the client portal."""

from test_helpers import (
    ApiErrorId,
    assert_defect_ticket,
    assert_instant_equals,
    assert_photo_document,
    create_defect_ticket_payload,
    file_defect_ticket,
    list_photo_documents,
    read_defect_ticket,
    read_photo_document,
    read_project,
    set_clock,
    setup_build_with_completed_plumbing_task,
    setup_job,
    setup_substantial_completion,
    upload_photo_document,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Warranty coverage: the two anchors ───────────────────────────────────
def test_callback_without_a_source_task_uses_the_whole_house_anchor(api):
    """PRD §3.9: "When the ticket carries no `source_schedule_task_id`, the **whole-house
    anchor** applies: `coverage_anchor` is `WHOLE_HOUSE` and `coverage_end_at` is the project's
    `warranty_starts_at` advanced by a full year of 365 days, regardless of which trade caused
    the defect."
    PRD §3.9: "Finally, `coverage_result` is `COVERED` when the ticket's `reported_at` is at or
    before `coverage_end_at` — the upper boundary is inclusive, so a claim reported at exactly
    the coverage end instant is covered — and `OUT_OF_COVERAGE` when it falls after."

    Design: Difficulty/dual_variant_calc/warranty_coverage_whole_house_vs_trade_anchor_diverge
    """
    ctx = setup_build_with_completed_plumbing_task()
    set_clock("2028-06-01T00:00:00.000Z")

    ticket = validate_success(
        api.create_defect_ticket(
            create_defect_ticket_payload(
                ctx["project"]["id"],
                phase="WARRANTY",
                room="Kitchen",
                description="Slow drain at island sink",
                severity="FUNCTIONAL",
                category="SYSTEMS",
            ),
            ctx["client_headers"],
        ),
        201,
    )

    assert_defect_ticket(ticket)
    assert ticket["coverage_anchor"] == "WHOLE_HOUSE"
    assert_instant_equals(
        ticket["coverage_end_at"], "2028-02-29T00:00:00.000Z", "coverage_end_at"
    )
    assert ticket["coverage_result"] == "OUT_OF_COVERAGE"
    assert_instant_equals(ticket["reported_at"], "2028-06-01T00:00:00.000Z", "reported_at")
    assert ticket["status"] == "OPEN"


def test_callback_naming_a_plumbing_task_uses_the_trade_anchor(api):
    """PRD §3.9: "When the ticket does name a `source_schedule_task_id`, the **trade anchor**
    applies: `coverage_anchor` is `TRADE`, and the window runs from that source task's
    `actual_finish` for a term that depends on the task's trade — the mechanical systems trades
    `PLUMBING`, `ELECTRICAL`, and `HVAC` carry an extended two-year term of 730 days, while every
    other trade carries the same 365-day term as the whole house."
    PRD §3.9: "`coverage_end_at` is that source task's `actual_finish` advanced by the applicable
    term. Because the trade anchor starts at the task's own finish rather than at substantial
    completion, a claim the whole-house anchor would call out of coverage can legitimately be
    covered under the trade anchor."

    Design: Difficulty/dual_variant_calc/warranty_coverage_whole_house_vs_trade_anchor_diverge
    """
    ctx = setup_build_with_completed_plumbing_task()
    set_clock("2028-06-01T00:00:00.000Z")

    ticket = validate_success(
        api.create_defect_ticket(
            create_defect_ticket_payload(
                ctx["project"]["id"],
                phase="WARRANTY",
                room="Kitchen",
                description="Slow drain at island sink",
                severity="FUNCTIONAL",
                category="SYSTEMS",
                source_schedule_task_id=ctx["task_plumb"]["id"],
            ),
            ctx["client_headers"],
        ),
        201,
    )

    assert ticket["coverage_anchor"] == "TRADE"
    assert_instant_equals(
        ticket["coverage_end_at"], "2029-01-14T00:00:00.000Z", "coverage_end_at"
    )
    assert ticket["coverage_result"] == "COVERED"
    assert_instant_equals(ticket["reported_at"], "2028-06-01T00:00:00.000Z", "reported_at")
    assert ticket["status"] == "OPEN"


def test_callback_reported_exactly_at_the_coverage_end_is_covered(api):
    """PRD §3.9: "Finally, `coverage_result` is `COVERED` when the ticket's `reported_at` is at
    or before `coverage_end_at` — the upper boundary is inclusive, so a claim reported at exactly
    the coverage end instant is covered — and `OUT_OF_COVERAGE` when it falls after."

    Design: Corner/calculations/warranty_claim_reported_exactly_at_coverage_end_is_covered
    """
    ctx = setup_substantial_completion()
    set_clock("2027-10-20T00:00:00.000Z")

    ticket = validate_success(
        api.create_defect_ticket(
            create_defect_ticket_payload(
                ctx["project"]["id"],
                phase="WARRANTY",
                room="Garage",
                description="Overhead door spring failed",
                severity="FUNCTIONAL",
                category="MATERIAL_DEFECT",
            ),
            ctx["client_headers"],
        ),
        201,
    )

    assert_instant_equals(ticket["reported_at"], "2027-10-20T00:00:00.000Z", "reported_at")
    assert_instant_equals(
        ticket["coverage_end_at"], "2027-10-20T00:00:00.000Z", "coverage_end_at"
    )
    assert ticket["coverage_result"] == "COVERED"
    assert ticket["coverage_anchor"] == "WHOLE_HOUSE"


def test_excluded_category_short_circuits_the_coverage_dates(api):
    """PRD §3.9: "For a `WARRANTY` ticket the evaluation runs in a pinned order, and the
    **exclusion test comes first**: if the ticket's `category` is `HOMEOWNER_DAMAGE` or
    `NORMAL_WEAR`, the ticket is excluded outright — `coverage_anchor` is `NONE`,
    `coverage_end_at` is null, and `coverage_result` is `EXCLUDED` — and no anchor is selected
    and no date arithmetic is performed, no matter how recently the house was accepted."

    Design: Corner/calculations/warranty_excluded_category_short_circuits_before_the_date_check
    """
    ctx = setup_substantial_completion()
    set_clock("2026-12-01T00:00:00.000Z")

    ticket = validate_success(
        api.create_defect_ticket(
            create_defect_ticket_payload(
                ctx["project"]["id"],
                phase="WARRANTY",
                room="Mudroom",
                description="Dog chewed the door casing",
                severity="COSMETIC",
                category="HOMEOWNER_DAMAGE",
            ),
            ctx["client_headers"],
        ),
        201,
    )

    assert ticket["coverage_result"] == "EXCLUDED"
    assert ticket["coverage_anchor"] == "NONE"
    assert ticket["coverage_end_at"] is None
    assert ticket["status"] == "OPEN"


def test_punch_ticket_skips_the_coverage_evaluation_entirely(api):
    """PRD §3.9: "For a `PUNCH` ticket the answer is trivial: `coverage_anchor` is `NONE`,
    `coverage_end_at` is null, and `coverage_result` is `NOT_APPLICABLE`; no further evaluation
    happens."
    PRD §3.9: "The ticket lands in `OPEN` with `reported_at` stamped at the logical clock now,
    `rework_count` at zero, and `responsible_subcontractor_id`, `response_due_at`,
    `completion_note`, `assigned_at`, and `resolved_at` all null."

    Design: Corner/calculations/punch_phase_ticket_gets_not_applicable_coverage
    """
    ctx = setup_job()

    ticket = validate_success(
        api.create_defect_ticket(
            create_defect_ticket_payload(
                ctx["project"]["id"],
                phase="PUNCH",
                room="Foyer",
                description="Scuffed base trim",
                severity="COSMETIC",
                category="WORKMANSHIP",
            ),
            ctx["pm_headers"],
        ),
        201,
    )

    assert ticket["coverage_result"] == "NOT_APPLICABLE"
    assert ticket["coverage_anchor"] == "NONE"
    assert ticket["coverage_end_at"] is None
    assert_instant_equals(ticket["reported_at"], "2026-08-01T00:00:00.000Z", "reported_at")


# ─── Triage ───────────────────────────────────────────────────────────────
def test_life_safety_assignment_starts_a_one_day_response_clock(api):
    """PRD §3.9: "Assignment stamps `assigned_at` with the logical clock now and sets
    `response_due_at` to `assigned_at` advanced by a severity-driven number of whole days: a
    `LIFE_SAFETY` defect must be answered within a single day, a `FUNCTIONAL` defect within one
    week of 7 days, and a `COSMETIC` defect within 30 days."

    Design: Corner/calculations/defect_response_due_uses_life_safety_one_day_constant
    """
    ctx = setup_job()
    ticket = file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Stairwell",
        description="Guardrail spacing exceeds code",
        severity="LIFE_SAFETY",
        category="WORKMANSHIP",
    )

    assigned = validate_success(
        api.triage_defect_ticket(
            ticket["id"],
            {"decision": "ASSIGN", "responsible_subcontractor_id": ctx["sub_frame"]["id"]},
            ctx["pm_headers"],
        ),
        200,
    )

    assert assigned["status"] == "ASSIGNED"
    assert assigned["responsible_subcontractor_id"] == ctx["sub_frame"]["id"]
    assert_instant_equals(assigned["assigned_at"], "2026-08-01T00:00:00.000Z", "assigned_at")
    assert_instant_equals(
        assigned["response_due_at"], "2026-08-02T00:00:00.000Z", "response_due_at"
    )
    assert assigned["rework_count"] == 0


def test_denied_callback_engages_no_trade_and_starts_no_clock(api):
    """PRD §3.9: "**Denying** advances `OPEN → DENIED` and is legal only for a `WARRANTY` ticket
    whose `coverage_result` is `OUT_OF_COVERAGE` or `EXCLUDED`; it stamps `resolved_at` with the
    logical clock now and, unlike assignment, leaves both `responsible_subcontractor_id` and
    `response_due_at` null, because no trade was engaged and no response clock ever started."

    Design: Corner/state_machines/warranty_triage_deny_branch_leaves_no_subcontractor_assigned
    """
    ctx = setup_substantial_completion()
    set_clock("2027-12-01T00:00:00.000Z")
    ticket = file_defect_ticket(
        ctx,
        as_role="client",
        phase="WARRANTY",
        room="Great room",
        description="Hairline drywall crack over the header",
        severity="COSMETIC",
        category="WORKMANSHIP",
    )
    assert ticket["coverage_anchor"] == "WHOLE_HOUSE"
    assert_instant_equals(
        ticket["coverage_end_at"], "2027-10-20T00:00:00.000Z", "coverage_end_at"
    )
    assert ticket["coverage_result"] == "OUT_OF_COVERAGE"

    denied = validate_success(
        api.triage_defect_ticket(ticket["id"], {"decision": "DENY"}, ctx["pm_headers"]), 200
    )

    assert denied["status"] == "DENIED"
    assert denied["responsible_subcontractor_id"] is None
    assert denied["response_due_at"] is None
    assert_instant_equals(denied["resolved_at"], "2027-12-01T00:00:00.000Z", "resolved_at")


def test_assigning_an_out_of_coverage_callback_is_refused(api):
    """PRD §3.9: "**Assigning** advances `OPEN → ASSIGNED` and requires the request to supply a
    `responsible_subcontractor_id`; it is legal for any `PUNCH` ticket, and for a `WARRANTY`
    ticket only when its `coverage_result` reads `COVERED` — a warranty ticket that is
    `OUT_OF_COVERAGE` or `EXCLUDED` cannot be handed to a trade, and the attempt earns
    `ERR_DEFECT_NOT_COVERED`."

    Design: Corner/errors/assigning_an_out_of_coverage_warranty_ticket_returns_not_covered
    """
    ctx = setup_substantial_completion()
    set_clock("2027-12-01T00:00:00.000Z")
    ticket = file_defect_ticket(
        ctx,
        as_role="client",
        phase="WARRANTY",
        room="Great room",
        description="Hairline drywall crack",
        severity="COSMETIC",
        category="WORKMANSHIP",
    )
    assert ticket["coverage_result"] == "OUT_OF_COVERAGE"

    response = api.triage_defect_ticket(
        ticket["id"],
        {"decision": "ASSIGN", "responsible_subcontractor_id": ctx["sub_frame"]["id"]},
        ctx["pm_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DEFECT_NOT_COVERED, 422)

    stored = read_defect_ticket(ticket["id"])
    assert stored["status"] == "OPEN"
    assert stored["responsible_subcontractor_id"] is None


def test_denying_a_punch_ticket_is_refused(api):
    """PRD §3.9: "A denial aimed at a punch ticket is refused with
    `ERR_DEFECT_PHASE_MISMATCH`."
    PRD §3.9: "For a `PUNCH` ticket the answer is trivial: `coverage_anchor` is `NONE`,
    `coverage_end_at` is null, and `coverage_result` is `NOT_APPLICABLE`; no further evaluation
    happens."

    Design: Corner/errors/deny_decision_on_a_punch_ticket_returns_phase_mismatch
    """
    ctx = setup_job()
    ticket = file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Primary bath",
        description="Shower valve leaks",
        severity="FUNCTIONAL",
        category="WORKMANSHIP",
    )

    response = api.triage_defect_ticket(
        ticket["id"], {"decision": "DENY"}, ctx["pm_headers"]
    )
    validate_error(response, ApiErrorId.ERR_DEFECT_PHASE_MISMATCH, 422)

    stored = read_defect_ticket(ticket["id"])
    assert stored["status"] == "OPEN"
    assert stored["coverage_result"] == "NOT_APPLICABLE"


# ─── The final walkthrough ────────────────────────────────────────────────
def test_final_walkthrough_is_blocked_by_an_open_functional_punch_item(api):
    """PRD §3.9: "No punch-phase defect of severity `FUNCTIONAL` or `LIFE_SAFETY` may remain in
    `OPEN`, `ASSIGNED`, `READY_FOR_REVIEW`, or `REJECTED`; an unresolved one earns
    `ERR_BLOCKING_PUNCH_ITEMS`."

    Design: Difficulty/cross_entity_state_dependency/final_walkthrough_gated_by_open_functional_punch_ticket
    """
    ctx = setup_substantial_completion()
    file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Primary bath",
        description="Shower valve leaks under pressure",
        severity="FUNCTIONAL",
        category="WORKMANSHIP",
    )

    response = api.final_walkthrough(
        ctx["project"]["id"],
        {"acknowledged_open_cosmetic_count": 0},
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_BLOCKING_PUNCH_ITEMS, 409)


def test_blocked_walkthrough_leaves_the_project_and_the_ticket_alone(api):
    """PRD §3.9: "The final walkthrough is the homeowner's own act and the last transition the
    project row ever makes, advancing it `SUBSTANTIAL_COMPLETION → FINAL_ACCEPTED`."
    PRD §3.9: "Acceptance stamps `final_accepted_at` with the logical clock now and increments
    the project's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/final_walkthrough_gated_by_open_functional_punch_ticket
    """
    ctx = setup_substantial_completion()
    ticket = file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Primary bath",
        description="Shower valve leaks under pressure",
        severity="FUNCTIONAL",
        category="WORKMANSHIP",
    )

    validate_error(
        api.final_walkthrough(
            ctx["project"]["id"],
            {"acknowledged_open_cosmetic_count": 0},
            ctx["client_headers"],
        ),
        ApiErrorId.ERR_BLOCKING_PUNCH_ITEMS,
        409,
    )

    project = read_project(ctx["project"]["id"])
    assert project["status"] == "SUBSTANTIAL_COMPLETION"
    assert project["final_accepted_at"] is None
    assert read_defect_ticket(ticket["id"])["status"] == "OPEN"


def test_walkthrough_with_a_wrong_cosmetic_acknowledgement_is_refused(api):
    """PRD §3.9: "The request must carry `acknowledged_open_cosmetic_count`, and that number
    must equal exactly the count of punch-phase defects of severity `COSMETIC` on the project
    sitting in `OPEN`, `ASSIGNED`, `READY_FOR_REVIEW`, or `REJECTED` — the homeowner is signing
    that they know precisely how much cosmetic work they are accepting, and a mismatch earns
    `ERR_PUNCH_ACK_COUNT_MISMATCH`."

    Design: Corner/validations/final_walkthrough_with_wrong_cosmetic_ack_count_returns_mismatch
    """
    ctx = setup_substantial_completion()
    first = file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Foyer",
        description="Scuffed base trim",
        severity="COSMETIC",
        category="WORKMANSHIP",
    )
    second = file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Study",
        description="Paint holiday on the north wall",
        severity="COSMETIC",
        category="WORKMANSHIP",
    )

    response = api.final_walkthrough(
        ctx["project"]["id"],
        {"acknowledged_open_cosmetic_count": 1},
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PUNCH_ACK_COUNT_MISMATCH, 422)

    assert read_project(ctx["project"]["id"])["status"] == "SUBSTANTIAL_COMPLETION"
    assert read_defect_ticket(first["id"])["status"] == "OPEN"
    assert read_defect_ticket(second["id"])["status"] == "OPEN"


def test_acceptance_waives_the_open_cosmetic_punch_item(api):
    """PRD §3.9: "Acceptance stamps `final_accepted_at` with the logical clock now and
    increments the project's `version` by one. It also performs one narrowly-scoped cascade:
    every punch-phase `COSMETIC` defect still sitting in `OPEN` advances to `WAIVED` with
    `resolved_at` stamped."
    PRD §3.1: "On success the logical clock now is written into `substantial_completion_at`;
    `warranty_starts_at` is set equal to `substantial_completion_at`; `warranty_expires_at` is
    set to `warranty_starts_at` advanced by a full year of 365 days"

    Design: Corner/state_machines/final_walkthrough_auto_waives_open_cosmetic_punch_tickets
    """
    ctx = setup_substantial_completion()
    ticket = file_defect_ticket(
        ctx,
        phase="PUNCH",
        room="Foyer",
        description="Scuffed base trim",
        severity="COSMETIC",
        category="WORKMANSHIP",
    )

    accepted = validate_success(
        api.final_walkthrough(
            ctx["project"]["id"],
            {"acknowledged_open_cosmetic_count": 1},
            ctx["client_headers"],
        ),
        200,
    )

    assert accepted["status"] == "FINAL_ACCEPTED"
    assert_instant_equals(
        accepted["final_accepted_at"], "2026-10-20T00:00:00.000Z", "final_accepted_at"
    )
    assert_instant_equals(
        accepted["warranty_starts_at"], "2026-10-20T00:00:00.000Z", "warranty_starts_at"
    )
    assert_instant_equals(
        accepted["warranty_expires_at"], "2027-10-20T00:00:00.000Z", "warranty_expires_at"
    )

    waived = read_defect_ticket(ticket["id"])
    assert waived["status"] == "WAIVED"
    assert_instant_equals(waived["resolved_at"], "2026-10-20T00:00:00.000Z", "resolved_at")


# ─── Photo documentation ──────────────────────────────────────────────────
def test_publication_moves_a_photo_onto_the_client_portal(api):
    """PRD §3.8: "The record lands with `visibility` of `INTERNAL` and a null `published_at`,
    which means the homeowner cannot see it. Publication is a separate, deliberate act, also
    reserved to a `ProjectManager`: it sets `visibility` to `CLIENT_PORTAL` and stamps
    `published_at` with the logical clock now."
    PRD §3.8: "Photo documents for a project are listed with an optional `visibility` filter."

    Design: Corner/endpoints/publish_action_switches_photo_visibility_to_client_portal
    """
    ctx = setup_job()
    photo_a = upload_photo_document(ctx, caption="Footings poured")
    photo_b = upload_photo_document(ctx, caption="Rebar inspection")
    assert_photo_document(photo_a)
    assert photo_a["visibility"] == "INTERNAL"

    published = validate_success(
        api.publish_photo_document(photo_a["id"], ctx["pm_headers"]), 200
    )

    assert published["visibility"] == "CLIENT_PORTAL"
    assert_instant_equals(
        published["published_at"], "2026-08-01T00:00:00.000Z", "published_at"
    )

    stored_b = read_photo_document(ctx["project"]["id"], photo_b["id"])
    assert stored_b["visibility"] == "INTERNAL"
    assert stored_b["published_at"] is None

    rows, meta = validate_paginated(
        api.list_photo_documents(
            ctx["project"]["id"],
            ctx["pm_headers"],
            params={"visibility": "CLIENT_PORTAL", "limit": 100},
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [photo_a["id"]]


def test_publishing_the_same_photo_twice_is_refused(api):
    """PRD §3.8: "Publishing a document whose `visibility` already reads `CLIENT_PORTAL` is
    refused with `ERR_PHOTO_ALREADY_PUBLISHED`."
    PRD §3.8: "Publication is a separate, deliberate act, also reserved to a `ProjectManager`:
    it sets `visibility` to `CLIENT_PORTAL` and stamps `published_at` with the logical clock
    now."

    Design: Corner/state_machines/second_publish_of_the_same_photo_document_is_rejected
    """
    ctx = setup_job()
    photo = upload_photo_document(ctx, caption="Footings poured")
    validate_success(api.publish_photo_document(photo["id"], ctx["pm_headers"]), 200)

    response = api.publish_photo_document(photo["id"], ctx["pm_headers"])
    validate_error(response, ApiErrorId.ERR_PHOTO_ALREADY_PUBLISHED, 409)

    stored = read_photo_document(ctx["project"]["id"], photo["id"])
    assert stored["visibility"] == "CLIENT_PORTAL"
    assert_instant_equals(
        stored["published_at"], "2026-08-01T00:00:00.000Z", "published_at"
    )

    published_rows = list_photo_documents(
        ctx["project"]["id"], ctx["pm_headers"], visibility="CLIENT_PORTAL"
    )
    assert len(published_rows) == 1
