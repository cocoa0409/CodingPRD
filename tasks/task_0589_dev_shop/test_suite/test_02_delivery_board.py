"""The delivery plan and the ticket board: milestone ceilings, half-open sprint
windows, the sprint-close sweep, the blocker graph, and the ticket's rework cycle.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as F,
)

DL = TEST_USERS["delivery_lead_headers"]
ENG = TEST_USERS["engineer_headers"]  # eng-001
ENG2 = TEST_USERS["engineer_2_headers"]  # eng-002


def test_list_tickets_filtered_by_sprint_with_pagination(api):
    """PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records remain beyond the current page)."
    PRD 3.2: "The sprint's `committed_hours` is at all times the sum of `estimated_hours` across every ticket of that sprint whose status is not `CANCELLED`."

    Design: Corner/entities/list_tickets_filtered_by_sprint_with_pagination
    """
    ctx = fixtures.setup_planned_sprint()
    sprint_id = ctx["sprint"]["id"]
    fixtures.create_ticket(sprint_id, title="T1", estimated_hours=3, assignee_user_id="eng-001")
    fixtures.create_ticket(sprint_id, title="T2", estimated_hours=4, assignee_user_id="eng-001")
    fixtures.create_ticket(sprint_id, title="T3", estimated_hours=5, assignee_user_id="eng-002")

    resp = api.list_tickets(DL, params={"sprint_id": sprint_id, "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"limit 2 must return 2 tickets, got {len(data)}"
    assert meta["total_count"] == 3, f"total_count counts all matches, got {meta['total_count']}"
    assert meta["has_more"] is True, "one ticket remains beyond the page"

    sprint = validate_success(api.get_sprint(sprint_id, DL))
    assert sprint["committed_hours"] == 12, (
        f"committed_hours sums 3 + 4 + 5 over the uncancelled tickets, got "
        f"{sprint['committed_hours']}"
    )


def test_sprint_referencing_milestone_of_another_engagement_is_rejected(api):
    """PRD 3.2: "If the supplied `milestone_id` names a milestone belonging to a different engagement, the create is rejected with `ERR_MILESTONE_ENGAGEMENT_MISMATCH` (HTTP 422) — the same rule guards release creation and invoice creation."

    Design: Corner/entities/sprint_referencing_milestone_of_another_engagement_is_rejected
    """
    ctx_a = fixtures.setup_active_engagement(
        billing_model="FIXED", contract_value=50000.00, budget_hours_cap=200, title="Engagement A"
    )
    ctx_b = fixtures.setup_active_engagement(
        billing_model="FIXED",
        contract_value=50000.00,
        budget_hours_cap=200,
        title="Engagement B",
        client=ctx_a["client"],
    )
    milestone_b = fixtures.create_milestone(ctx_b["engagement"]["id"], title="B Phase 1")

    resp = api.create_sprint(
        F.create_sprint_payload(
            engagement_id=ctx_a["engagement"]["id"],
            name="A Sprint 1",
            milestone_id=milestone_b["id"],
        ),
        DL,
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_ENGAGEMENT_MISMATCH.value)

    sprints = validate_success(
        api.list_sprints(DL, params={"engagement_id": ctx_a["engagement"]["id"]})
    )
    assert len(sprints) == 0, "the rejected create must not persist a sprint"


def test_milestone_amounts_exceeding_contract_value_are_rejected(api):
    """PRD 3.2: "There is a hard fiscal ceiling: the sum of `amount` across all milestones of an engagement may never exceed that engagement's `contract_value`. A milestone whose addition would push the sum over the contract value is refused with `ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT` (HTTP 422)."

    Design: Corner/validations/milestone_amounts_exceeding_contract_value_are_rejected
    """
    ctx = fixtures.setup_active_engagement(
        billing_model="FIXED", contract_value=50000.00, budget_hours_cap=200
    )
    engagement_id = ctx["engagement"]["id"]
    fixtures.create_milestone(engagement_id, sequence=1, title="Phase 1", amount=30000.00)

    resp = api.create_milestone(
        F.create_milestone_payload(
            engagement_id=engagement_id,
            sequence=2,
            title="Phase 2",
            amount=30000.00,
            due_date="2026-07-01",
        ),
        DL,
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT.value)

    milestones = validate_success(
        api.list_milestones(DL, params={"engagement_id": engagement_id})
    )
    assert len(milestones) == 1, "30000 + 30000 breaches the 50000 contract; only one survives"


def test_sprint_close_cancels_todo_tickets_and_recomputes_committed_hours(api):
    """PRD 3.2: "A `target_status` of `CLOSED` moves an `ACTIVE` sprint to `CLOSED`, cancelling every ticket of that sprint still in `TODO` and recomputing `committed_hours` over the tickets that remain uncancelled."

    Design: Corner/state_machines/sprint_close_cancels_todo_tickets_and_recomputes_committed_hours
    """
    ctx = fixtures.setup_active_sprint()
    sprint_id = ctx["sprint"]["id"]
    ticket_a = fixtures.create_ticket(
        sprint_id, title="A", estimated_hours=4, assignee_user_id="eng-001"
    )
    ticket_b = fixtures.create_ticket(
        sprint_id, title="B", estimated_hours=3, assignee_user_id="eng-001"
    )
    ticket_c = fixtures.create_ticket(
        sprint_id, title="C", estimated_hours=5, assignee_user_id="eng-002"
    )
    fixtures.start_ticket(ticket_a["id"], "eng-001")

    closed = validate_success(api.transition_sprint(sprint_id, "CLOSED", DL))
    assert closed["status"] == "CLOSED"

    assert validate_success(api.get_ticket(ticket_b["id"], DL))["status"] == "CANCELLED"
    assert validate_success(api.get_ticket(ticket_c["id"], DL))["status"] == "CANCELLED"
    assert validate_success(api.get_ticket(ticket_a["id"], DL))["status"] == "IN_PROGRESS", (
        "only TODO tickets are swept by the close"
    )
    assert closed["committed_hours"] == 4, (
        f"committed_hours drops to the 4 hours of the surviving ticket, got "
        f"{closed['committed_hours']}"
    )


def test_ticket_blocked_by_unfinished_blocker_cannot_start(api):
    """PRD 3.3: "It requires the sprint to be `ACTIVE`; it requires the sprint's `spend_frozen` to be false, failing with `ERR_SPRINT_SPEND_FROZEN` (HTTP 409) when the engagement's posture has frozen the sprint; and, when the ticket declares a `blocking_ticket_id`, it requires that blocker to have reached `DONE`, failing with `ERR_TICKET_BLOCKED` (HTTP 409) otherwise."

    Design: Corner/validations/ticket_blocked_by_unfinished_blocker_cannot_start
    """
    ctx = fixtures.setup_active_sprint()
    sprint_id = ctx["sprint"]["id"]
    ticket_a = fixtures.create_ticket(
        sprint_id, title="Schema migration", estimated_hours=4, assignee_user_id="eng-001"
    )
    ticket_b = fixtures.create_ticket(
        sprint_id,
        title="Backfill job",
        estimated_hours=4,
        assignee_user_id="eng-001",
        blocking_ticket_id=ticket_a["id"],
    )

    blocked = api.transition_ticket(ticket_b["id"], "IN_PROGRESS", ENG)
    validate_error(blocked, ApiErrorId.ERR_TICKET_BLOCKED.value)

    # Drive the blocker to DONE (sign-off by a non-assignee), then retry.
    fixtures.start_ticket(ticket_a["id"], "eng-001")
    validate_success(api.transition_ticket(ticket_a["id"], "IN_QA", ENG))
    done = validate_success(api.transition_ticket(ticket_a["id"], "DONE", ENG2))
    assert done["status"] == "DONE"

    started = validate_success(api.transition_ticket(ticket_b["id"], "IN_PROGRESS", ENG))
    assert started["status"] == "IN_PROGRESS", "a DONE blocker releases the blocked ticket"

    listed = validate_success(
        api.list_tickets(DL, params={"blocking_ticket_id": ticket_a["id"]})
    )
    assert len(listed) == 1 and listed[0]["id"] == ticket_b["id"]


def test_blocker_graph_cycle_is_rejected_on_block(api):
    """PRD 3.3: "Whether it arrives at creation or through a later re-pointing, a `blocking_ticket_id` that names the ticket itself, or that would close a loop reachable by walking the chain of `blocking_ticket_id` links, is rejected with `ERR_TICKET_CYCLE` (HTTP 422); the re-pointing is applied only after the cycle check clears."

    Design: Corner/validations/blocker_graph_cycle_is_rejected_on_block
    """
    ctx = fixtures.setup_active_sprint()
    sprint_id = ctx["sprint"]["id"]
    ticket_a = fixtures.create_ticket(
        sprint_id, title="A", estimated_hours=4, assignee_user_id="eng-001"
    )
    ticket_b = fixtures.create_ticket(
        sprint_id,
        title="B",
        estimated_hours=4,
        assignee_user_id="eng-001",
        blocking_ticket_id=ticket_a["id"],
    )

    self_block = api.block_ticket(ticket_a["id"], ticket_a["id"], DL)
    validate_error(self_block, ApiErrorId.ERR_TICKET_CYCLE.value)

    transitive = api.block_ticket(ticket_a["id"], ticket_b["id"], DL)
    validate_error(transitive, ApiErrorId.ERR_TICKET_CYCLE.value)

    after_a = validate_success(api.get_ticket(ticket_a["id"], DL))
    assert after_a.get("blocking_ticket_id") is None, (
        "neither rejected re-pointing may mutate the blocker graph"
    )
    after_b = validate_success(api.get_ticket(ticket_b["id"], DL))
    assert after_b["blocking_ticket_id"] == ticket_a["id"]


# ---------------------------------------------------------------------------
# Half-open sprint windows
# ---------------------------------------------------------------------------
def test_sprint_starting_on_an_existing_end_date_is_accepted(api):
    """PRD 3.2: "Two sprints of the same engagement overlap when the new sprint's `start_date` falls strictly before the existing sprint's `end_date` *and* the existing sprint's `start_date` falls strictly before the new sprint's `end_date`; exact adjacency — a new sprint starting on the very date an old one ends — is therefore permitted and is the normal way to chain sprints back to back."

    Design: Difficulty/resource_temporal_overlap/sprint_half_open_interval_adjacency_allowed_overlap_rejected
    """
    ctx = fixtures.setup_active_engagement()
    engagement_id = ctx["engagement"]["id"]
    fixtures.create_sprint(
        engagement_id, name="Sprint 1", start_date="2026-05-04", end_date="2026-05-18"
    )

    resp = api.create_sprint(
        F.create_sprint_payload(
            engagement_id=engagement_id,
            name="Sprint 2",
            start_date="2026-05-18",
            end_date="2026-06-01",
        ),
        DL,
    )
    adjacent = validate_success(resp, expected_status=201)
    assert adjacent["status"] == "PLANNED"
    assert adjacent["start_date"] == "2026-05-18", (
        "a sprint starting on the exclusive end_date of its predecessor only touches it"
    )


def test_sprint_starting_one_day_before_an_existing_end_date_overlaps(api):
    """PRD 3.2: "Two sprints of the same engagement overlap when the new sprint's `start_date` falls strictly before the existing sprint's `end_date` *and* the existing sprint's `start_date` falls strictly before the new sprint's `end_date`; exact adjacency — a new sprint starting on the very date an old one ends — is therefore permitted and is the normal way to chain sprints back to back."
    PRD 3.2: "A collision is rejected with `ERR_SPRINT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sprint_half_open_interval_adjacency_allowed_overlap_rejected
    """
    ctx = fixtures.setup_active_engagement()
    engagement_id = ctx["engagement"]["id"]
    fixtures.create_sprint(
        engagement_id, name="Sprint 1", start_date="2026-05-04", end_date="2026-05-18"
    )
    fixtures.create_sprint(
        engagement_id, name="Sprint 2", start_date="2026-05-18", end_date="2026-06-01"
    )

    resp = api.create_sprint(
        F.create_sprint_payload(
            engagement_id=engagement_id,
            name="Sprint 3",
            start_date="2026-05-17",
            end_date="2026-05-31",
        ),
        DL,
    )
    validate_error(resp, ApiErrorId.ERR_SPRINT_OVERLAP.value)

    sprints = validate_success(api.list_sprints(DL, params={"engagement_id": engagement_id}))
    assert len(sprints) == 2, (
        f"2026-05-17 falls strictly before 2026-05-18, so the third sprint must not "
        f"be created; got {len(sprints)} sprints"
    )


# ---------------------------------------------------------------------------
# The ticket depends on its sprint's state
# ---------------------------------------------------------------------------
def test_ticket_cannot_start_while_its_sprint_is_planned(api):
    """PRD 3.3: "Every ticket transition other than the two cancellations requires the owning sprint to be `ACTIVE` — a transition attempted while the sprint is `PLANNED` or `CLOSED` is refused with `ERR_SPRINT_NOT_ACTIVE`."
    PRD 3.3: "Tickets may be added to a sprint that is `PLANNED` or `ACTIVE`; only a `CLOSED` sprint refuses them, with `ERR_SPRINT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ticket_start_requires_active_sprint_cross_entity_ticket_sprint
    """
    ctx = fixtures.setup_planned_sprint()
    ticket = fixtures.create_ticket(
        ctx["sprint"]["id"], title="Compression kernel", assignee_user_id="eng-001"
    )

    resp = api.transition_ticket(ticket["id"], "IN_PROGRESS", ENG)
    validate_error(resp, ApiErrorId.ERR_SPRINT_NOT_ACTIVE.value)

    after = validate_success(api.get_ticket(ticket["id"], DL))
    assert after["status"] == "TODO", "the ticket's own machine is untouched by the refusal"


def test_the_same_ticket_start_succeeds_once_the_sprint_is_active(api):
    """PRD 3.3: "Every ticket transition other than the two cancellations requires the owning sprint to be `ACTIVE` — a transition attempted while the sprint is `PLANNED` or `CLOSED` is refused with `ERR_SPRINT_NOT_ACTIVE`."
    PRD 3.2: "A `target_status` of `ACTIVE` advances a `PLANNED` sprint to `ACTIVE`, and at that instant the sprint's `spend_frozen` is seeded from the parent engagement's current `budget_posture`: it is set true when the posture is anything other than `HEALTHY`, and false when the posture is `HEALTHY`."

    Design: Difficulty/cross_entity_state_dependency/ticket_start_requires_active_sprint_cross_entity_ticket_sprint
    """
    ctx = fixtures.setup_planned_sprint()
    sprint_id = ctx["sprint"]["id"]
    ticket = fixtures.create_ticket(
        sprint_id, title="Compression kernel", assignee_user_id="eng-001"
    )
    validate_error(
        api.transition_ticket(ticket["id"], "IN_PROGRESS", ENG),
        ApiErrorId.ERR_SPRINT_NOT_ACTIVE.value,
    )

    sprint = validate_success(api.transition_sprint(sprint_id, "ACTIVE", DL))
    assert sprint["status"] == "ACTIVE"
    assert sprint["spend_frozen"] is False, "a HEALTHY engagement seeds an unfrozen sprint"

    started = validate_success(api.transition_ticket(ticket["id"], "IN_PROGRESS", ENG))
    assert started["status"] == "IN_PROGRESS", (
        "the identical transition succeeds once the sibling sprint is ACTIVE"
    )


# ---------------------------------------------------------------------------
# The ticket's rework cycle
# ---------------------------------------------------------------------------
def test_ticket_rework_cycle_reaches_done_with_one_rework_round(api):
    """PRD 3.3: "A failed review sends it back with `IN_QA → REWORK`, which increments `rework_rounds` by 1 and is the entry point of the board's cycle: `IN_QA → REWORK → IN_PROGRESS → IN_QA`, repeatable without limit."
    PRD 3.3: "Signing off moves the ticket `IN_QA → DONE` and requires an `ACTIVE` sprint plus a signer who is not the ticket's own `assignee_user_id`, as described in §2.10; on success the ticket's `variance_ratio` is recomputed."

    Design: Difficulty/non_linear_state_machine/ticket_rework_cycle_in_qa_to_rework_to_in_progress_to_in_qa
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides={
            "contract_value": 2000.00,
            "budget_hours_cap": 10,
            "standard_hourly_rate": 200.00,
        },
        ticket_overrides={"title": "Checkout flow", "estimated_hours": 8},
    )
    ticket_id = ctx["ticket"]["id"]

    validate_success(api.transition_ticket(ticket_id, "IN_QA", ENG))
    reworked = validate_success(
        api.transition_ticket(ticket_id, "REWORK", ENG2, note="2 defects found in staging")
    )
    assert reworked["rework_rounds"] == 1, "entering REWORK increments rework_rounds"
    validate_success(api.transition_ticket(ticket_id, "IN_PROGRESS", ENG))
    validate_success(api.transition_ticket(ticket_id, "IN_QA", ENG))
    done = validate_success(api.transition_ticket(ticket_id, "DONE", ENG2))

    assert done["status"] == "DONE"
    assert done["rework_rounds"] == 1, (
        f"the ticket revisited IN_QA once after a single rework round, got "
        f"{done['rework_rounds']}"
    )
    assert done["actual_hours"] == 0, "no time was approved during the cycle"
    assert done["variance_ratio"] == 0.0


def test_ticket_rework_cycle_is_repeatable_and_counts_every_round(api):
    """PRD 3.3: "A failed review sends it back with `IN_QA → REWORK`, which increments `rework_rounds` by 1 and is the entry point of the board's cycle: `IN_QA → REWORK → IN_PROGRESS → IN_QA`, repeatable without limit."

    Design: Difficulty/non_linear_state_machine/ticket_rework_cycle_in_qa_to_rework_to_in_progress_to_in_qa
    """
    ctx = fixtures.setup_ticket_in_progress(
        ticket_overrides={"title": "Checkout flow", "estimated_hours": 8}
    )
    ticket_id = ctx["ticket"]["id"]

    for expected_rounds in (1, 2):
        validate_success(api.transition_ticket(ticket_id, "IN_QA", ENG))
        reworked = validate_success(api.transition_ticket(ticket_id, "REWORK", ENG2))
        assert reworked["status"] == "REWORK"
        assert reworked["rework_rounds"] == expected_rounds, (
            f"round {expected_rounds}: rework_rounds must be {expected_rounds}, got "
            f"{reworked['rework_rounds']}"
        )
        back = validate_success(api.transition_ticket(ticket_id, "IN_PROGRESS", ENG))
        assert back["status"] == "IN_PROGRESS", "REWORK -> IN_PROGRESS reopens the cycle"

    validate_success(api.transition_ticket(ticket_id, "IN_QA", ENG))
    done = validate_success(api.transition_ticket(ticket_id, "DONE", ENG2))
    assert done["status"] == "DONE"
    assert done["rework_rounds"] == 2, (
        f"two full cycles leave rework_rounds at 2, got {done['rework_rounds']}"
    )
