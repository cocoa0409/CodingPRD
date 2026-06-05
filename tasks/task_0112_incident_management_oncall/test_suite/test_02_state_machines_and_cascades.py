"""Parallel/cyclic state machines, transitive cascades, and compensating
invariants (depth: non_linear_state_machine, transitive_cascade,
compensating_invariant).

Every test translates exactly one §1.8 difficulty instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    create_service,
    create_policy,
    create_window,
    setup_pageable_service,
    setup_resolved_incident,
    setup_draft_postmortem,
    setup_postmortem_with_action_item,
    trigger_incident,
    acknowledge,
    resolve,
    TEST_USERS,
    make_responder_headers,
)

COMMANDER = TEST_USERS["incident_commander_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty/non_linear_state_machine/
#   incident_parallel_dimensions_ack_does_not_block_escalation_history
# ===========================================================================
def test_acknowledge_moves_lifecycle_to_acknowledged():
    """PRD §3.7: "On success the lifecycle moves to `ACKNOWLEDGED`,
    `acknowledged_at` is stamped from the clock, `ack_sla_breached` is recomputed
    (true exactly when `acknowledged_at` is later than `ack_deadline_at`), and —
    because acknowledgement halts the ladder — if the escalation status was
    `ESCALATING` it transitions to `EXHAUSTED` and `current_tier_level` is frozen
    at its current value."

    Acknowledging a TRIGGERED incident moves lifecycle_status to ACKNOWLEDGED.

    Design: Difficulty/non_linear_state_machine/incident_parallel_dimensions_ack_does_not_block_escalation_history
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    after = acknowledge(inc["id"], env["responder"]["id"])
    assert after["lifecycle_status"] == "ACKNOWLEDGED", (
        f"acknowledge should move lifecycle to ACKNOWLEDGED, got {after['lifecycle_status']}"
    )


def test_acknowledge_drives_escalation_to_exhausted_on_parallel_dimension():
    """PRD §3.7: "because acknowledgement halts the ladder — if the escalation
    status was `ESCALATING` it transitions to `EXHAUSTED` and `current_tier_level`
    is frozen at its current value."
    PRD §3.4: "The escalation dimension is independent of the lifecycle dimension.
    An incident can be `ACKNOWLEDGED` while its escalation status is `EXHAUSTED`,
    or `ESCALATING` while its lifecycle is still `TRIGGERED`."

    The same acknowledge that moves lifecycle to ACKNOWLEDGED simultaneously moves
    escalation_status from ESCALATING to EXHAUSTED — two independent dimensions on
    one row.

    Design: Difficulty/non_linear_state_machine/incident_parallel_dimensions_ack_does_not_block_escalation_history
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    assert inc["escalation_status"] == "ESCALATING", "first page should set ESCALATING"
    after = acknowledge(inc["id"], env["responder"]["id"])
    assert after["lifecycle_status"] == "ACKNOWLEDGED"
    assert after["escalation_status"] == "EXHAUSTED", (
        f"ack should halt the ladder to EXHAUSTED on the escalation dimension, "
        f"got {after['escalation_status']}"
    )


# ===========================================================================
# Difficulty/non_linear_state_machine/postmortem_cyclic_revert_in_review_to_draft
# ===========================================================================
def test_postmortem_submit_moves_draft_to_in_review():
    """PRD §3.10: "From `DRAFT` an `IncidentCommander` submits it for review,
    moving it to `IN_REVIEW`, permitted only while the status is `DRAFT` (else
    `ERR_POSTMORTEM_NOT_DRAFT`, HTTP 409)."

    Submitting a DRAFT postmortem moves it to IN_REVIEW (the forward leg of the
    revision loop).

    Design: Difficulty/non_linear_state_machine/postmortem_cyclic_revert_in_review_to_draft
    """
    env, incident, pm = setup_draft_postmortem(severity="SEV2")
    assert pm["status"] == "DRAFT"
    after = validate_success(api_client.submit_postmortem(pm["id"], COMMANDER), 200)
    assert after["status"] == "IN_REVIEW", (
        f"submit should move DRAFT -> IN_REVIEW, got {after['status']}"
    )


def test_postmortem_return_reverts_in_review_to_draft():
    """PRD §3.10: "From `IN_REVIEW` the commander may return it to `DRAFT` for
    further authoring — the revision loop — permitted only while the status is
    `IN_REVIEW` (else `ERR_POSTMORTEM_NOT_IN_REVIEW`, HTTP 409)."

    Returning an IN_REVIEW postmortem reverts it to DRAFT (A -> B -> A loop), not a
    one-way pipeline.

    Design: Difficulty/non_linear_state_machine/postmortem_cyclic_revert_in_review_to_draft
    """
    env, incident, pm = setup_draft_postmortem(severity="SEV2")
    validate_success(api_client.submit_postmortem(pm["id"], COMMANDER), 200)
    after = validate_success(api_client.return_postmortem(pm["id"], COMMANDER), 200)
    assert after["status"] == "DRAFT", (
        f"return should revert IN_REVIEW -> DRAFT (loop back), got {after['status']}"
    )


# ===========================================================================
# Difficulty/transitive_cascade/
#   resolve_recompute_consumed_then_remaining_then_budget_status
# ===========================================================================
def test_resolve_cascade_recomputes_consumed_and_remaining():
    """PRD §3.7: "Resolution then triggers a multi-hop cascade onto the parent
    service: `error_budget_consumed_minutes` is recomputed by the time-based
    aggregation of Section 3.5, `error_budget_remaining_minutes` is recomputed
    from it, and `budget_status` is re-derived."
    PRD §3.5: "The service's `error_budget_remaining_minutes` is then the larger
    of zero and `error_budget_minutes` minus `error_budget_consumed_minutes`."

    Resolving a SEV4 incident open 90s on a 2-minute budget drives consumed=2 and
    remaining=0 (hop 1 -> hop 2 of the cascade).

    Design: Difficulty/transitive_cascade/resolve_recompute_consumed_then_remaining_then_budget_status
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=2)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV4")
    acknowledge(inc["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:01:30Z")
    inc = resolve(inc["id"], env["responder"]["id"])
    assert inc["downtime_minutes"] == 2

    svc = validate_success(api_client.get_service(env["service"]["id"], COMMANDER), 200)
    assert svc["error_budget_consumed_minutes"] == 2, (
        f"consumed should be 2 after resolve, got {svc['error_budget_consumed_minutes']}"
    )
    assert svc["error_budget_remaining_minutes"] == 0, (
        f"remaining should be max(0, 2-2)=0, got {svc['error_budget_remaining_minutes']}"
    )


def test_resolve_cascade_third_hop_flips_budget_status_to_exhausted():
    """PRD §3.7: "`budget_status` is re-derived — and if that re-derivation
    crosses the service to `EXHAUSTED`, that is a genuine third-hop state change
    on the service."
    PRD §3.5: "If consumed is greater than or equal to budget, the status is
    `EXHAUSTED`."

    When the recomputed consumed (2) reaches the budget (2), budget_status flips
    HEALTHY -> EXHAUSTED — the third hop, caused by the consumed recompute, not the
    resolve directly.

    Design: Difficulty/transitive_cascade/resolve_recompute_consumed_then_remaining_then_budget_status
    """
    set_clock("2026-06-01T00:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=2)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV4")
    acknowledge(inc["id"], env["responder"]["id"])
    set_clock("2026-06-01T00:01:30Z")
    resolve(inc["id"], env["responder"]["id"])

    svc = validate_success(api_client.get_service(env["service"]["id"], COMMANDER), 200)
    assert svc["budget_status"] == "EXHAUSTED", (
        f"budget_status should flip to EXHAUSTED when consumed 2 >= budget 2, "
        f"got {svc['budget_status']}"
    )


# ===========================================================================
# Difficulty/transitive_cascade/window_activation_suppresses_triggered_incident_depth2
# ===========================================================================
def test_window_activation_suppresses_triggered_incident():
    """PRD §3.8: "Activation cascades suppression: every incident on the window's
    service whose `lifecycle_status` is `TRIGGERED` is transitioned to
    `SUPPRESSED`, with `counts_against_budget` set to false and `escalation_status`
    driven to `EXHAUSTED` so paging halts — a second-hop change on each such
    incident caused by the window activation."

    Activating a window (hop 1: window -> ACTIVE) cascades to suppress the
    TRIGGERED incident on the same service (hop 2).

    Design: Difficulty/transitive_cascade/window_activation_suppresses_triggered_incident_depth2
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    window = create_window(
        env["service"]["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z", reason="deploy"
    )
    activated = validate_success(
        api_client.activate_maintenance_window(window["id"], ADMIN), 200
    )
    assert activated["status"] == "ACTIVE"

    after = validate_success(api_client.get_incident(inc["id"], COMMANDER), 200)
    assert after["lifecycle_status"] == "SUPPRESSED", (
        f"window activation should suppress the TRIGGERED incident, "
        f"got {after['lifecycle_status']}"
    )


def test_window_activation_suppression_clears_budget_and_escalation():
    """PRD §3.8: "every incident on the window's service whose `lifecycle_status`
    is `TRIGGERED` is transitioned to `SUPPRESSED`, with `counts_against_budget`
    set to false and `escalation_status` driven to `EXHAUSTED` so paging halts."

    The suppressed incident also gets counts_against_budget=false and
    escalation_status=EXHAUSTED as part of the cascade.

    Design: Difficulty/transitive_cascade/window_activation_suppresses_triggered_incident_depth2
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV2")
    window = create_window(
        env["service"]["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z", reason="deploy"
    )
    validate_success(api_client.activate_maintenance_window(window["id"], ADMIN), 200)

    after = validate_success(api_client.get_incident(inc["id"], COMMANDER), 200)
    assert after["counts_against_budget"] is False, (
        "suppressed incident must have counts_against_budget=false"
    )
    assert after["escalation_status"] == "EXHAUSTED", (
        f"suppression must drive escalation_status to EXHAUSTED, got {after['escalation_status']}"
    )


# ===========================================================================
# Difficulty/compensating_invariant/suppression_conserves_service_error_budget_minutes
# ===========================================================================
def test_suppression_conserves_consumed_minutes_at_zero():
    """PRD §3.8: "suppressed incidents never consume error budget because their
    `counts_against_budget` is false and they are excluded from every budget
    aggregation."
    PRD §3.5: "Incidents whose `counts_against_budget` is false (the suppressed
    ones) contribute zero and are excluded from the set entirely."

    Triggering then suppressing an incident leaves the service's
    error_budget_consumed_minutes at its pre-incident value of 0 — the conserved
    quantity does not drift.

    Design: Difficulty/compensating_invariant/suppression_conserves_service_error_budget_minutes
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV1")
    window = create_window(
        env["service"]["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z"
    )
    validate_success(api_client.activate_maintenance_window(window["id"], ADMIN), 200)

    suppressed = validate_success(api_client.get_incident(inc["id"], COMMANDER), 200)
    assert suppressed["lifecycle_status"] == "SUPPRESSED"
    assert suppressed["counts_against_budget"] is False

    svc = validate_success(api_client.get_service(env["service"]["id"], COMMANDER), 200)
    assert svc["error_budget_consumed_minutes"] == 0, (
        f"suppressed incident must conserve consumed at 0, got "
        f"{svc['error_budget_consumed_minutes']}"
    )


def test_suppressed_incident_excluded_from_event_cost_too():
    """PRD §3.5: "The `event_cost_minutes` is the sum of those fixed per-incident
    costs over the same set of resolved, budget-counting incidents."
    PRD §3.8: "suppressed incidents never consume error budget because their
    `counts_against_budget` is false and they are excluded from every budget
    aggregation."

    A suppressed (never-resolved, non-budget-counting) incident contributes 0 to
    consumed AND to the event-based cost — the conserved budget quantity stays at
    its pre-incident value across both accountings.

    Design: Difficulty/compensating_invariant/suppression_conserves_service_error_budget_minutes
    """
    set_clock("2026-06-01T12:00:00Z")
    env = setup_pageable_service(tier="TIER_2", error_budget_minutes=1000)
    inc = trigger_incident(env["service"]["id"], env["policy"]["id"], severity="SEV1")
    window = create_window(
        env["service"]["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z"
    )
    validate_success(api_client.activate_maintenance_window(window["id"], ADMIN), 200)

    summary = validate_success(
        api_client.get_budget_summary(env["service"]["id"], COMMANDER), 200
    )
    assert summary["consumed_minutes"] == 0, (
        f"suppressed incident must contribute 0 to consumed, got {summary['consumed_minutes']}"
    )
    assert summary["event_cost_minutes"] == 0, (
        f"suppressed incident must contribute 0 to event cost, got {summary['event_cost_minutes']}"
    )


# ===========================================================================
# Difficulty/compensating_invariant/action_item_cancel_conserves_open_count
# ===========================================================================
def test_action_item_cancel_restores_open_count_to_zero():
    """PRD §3.10: "An `IncidentCommander` may cancel an item from either `OPEN` or
    `IN_PROGRESS` ... and moves the item to `CANCELLED`, decrementing the parent's
    `open_action_item_count` by 1 as a compensating adjustment that restores it
    toward the value before the item was created."

    Creating an action item bumps open_action_item_count to 1; cancelling it
    restores the count to its pre-creation value of 0.

    Design: Difficulty/compensating_invariant/action_item_cancel_conserves_open_count
    """
    env, incident, pm, ai = setup_postmortem_with_action_item(severity="SEV2")
    pm_before = validate_success(api_client.get_postmortem(pm["id"], COMMANDER), 200)
    assert pm_before["open_action_item_count"] == 1, "creating an item must bump count to 1"

    cancelled = validate_success(api_client.cancel_action_item(ai["id"], COMMANDER), 200)
    assert cancelled["status"] == "CANCELLED"

    pm_after = validate_success(api_client.get_postmortem(pm["id"], COMMANDER), 200)
    assert pm_after["open_action_item_count"] == 0, (
        f"cancel must restore open_action_item_count to pre-creation 0, got "
        f"{pm_after['open_action_item_count']}"
    )


def test_action_item_cancel_marks_item_cancelled():
    """PRD §3.10: "cancellation is permitted only while the status is one of
    `OPEN` or `IN_PROGRESS` (else `ERR_ACTION_ITEM_TERMINAL`, HTTP 409) and moves
    the item to `CANCELLED`."

    The cancelled action item itself reaches the CANCELLED terminal state (the
    compensating action's direct effect, complementing the count restoration).

    Design: Difficulty/compensating_invariant/action_item_cancel_conserves_open_count
    """
    env, incident, pm, ai = setup_postmortem_with_action_item(severity="SEV2")
    cancelled = validate_success(api_client.cancel_action_item(ai["id"], COMMANDER), 200)
    assert cancelled["status"] == "CANCELLED", (
        f"cancel must move the item to CANCELLED, got {cancelled['status']}"
    )
