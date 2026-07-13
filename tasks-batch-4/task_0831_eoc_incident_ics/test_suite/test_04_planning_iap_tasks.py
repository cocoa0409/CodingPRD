"""Incident Action Plans and Tasks: operational-period overlap, publication
side effects, and the task-assignment precondition gates.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    create_iap,
    publish_iap,
    create_published_iap,
    create_task,
    assign_task,
    incident_version,
    get_incident,
    create_jurisdiction_and_pool,
    create_filled_request,
)

EOC = TEST_USERS["eoc_manager_headers"]
PLAN = TEST_USERS["planning_chief_headers"]
OPS = TEST_USERS["operations_chief_headers"]


# ─── Difficulty: resource_temporal_overlap / iap_operational_period_overlap ───
def test_publish_overlapping_iap_rejected(api):
    """PRD §3.4: "Publication is allowed only if no other already-published IAP for the same
    incident has an operational period that overlaps this one; because periods are half-open,
    a plan whose start equals the immediately prior plan's end is adjacent, not overlapping,
    and is permitted. An overlap is rejected with `ERR_OPERATIONAL_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/iap_operational_period_overlap
    """
    inc = create_activated_incident(name="Storm Ops", hazard_type="HURRICANE")
    create_published_iap(
        inc["id"],
        operational_period_start="2026-03-01T06:00:00Z",
        operational_period_end="2026-03-02T06:00:00Z",
    )
    iap2 = create_iap(
        inc["id"],
        operational_period_start="2026-03-01T18:00:00Z",
        operational_period_end="2026-03-02T18:00:00Z",
    )
    validate_error(
        api.transition_iap(iap2["id"], {"to_status": "PUBLISHED"}, PLAN),
        ApiErrorId.ERR_OPERATIONAL_PERIOD_OVERLAP.value,
    )


def test_publish_overlapping_iap_leaves_it_draft(api):
    """PRD §3.4: "Publication is allowed only if no other already-published IAP for the same
    incident has an operational period that overlaps this one; because periods are half-open,
    a plan whose start equals the immediately prior plan's end is adjacent, not overlapping,
    and is permitted. An overlap is rejected with `ERR_OPERATIONAL_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/iap_operational_period_overlap
    """
    inc = create_activated_incident(name="Storm Ops", hazard_type="HURRICANE")
    create_published_iap(
        inc["id"],
        operational_period_start="2026-03-01T06:00:00Z",
        operational_period_end="2026-03-02T06:00:00Z",
    )
    iap2 = create_iap(
        inc["id"],
        operational_period_start="2026-03-01T18:00:00Z",
        operational_period_end="2026-03-02T18:00:00Z",
    )
    api.transition_iap(iap2["id"], {"to_status": "PUBLISHED"}, PLAN)
    from test_helpers import validate_paginated
    iaps, _ = validate_paginated(api.list_incident_iaps(inc["id"], PLAN))
    target = next(p for p in iaps if p["id"] == iap2["id"])
    assert target["status"] == "DRAFT", f"expected DRAFT after rejected publish, got {target['status']}"


# ─── Corner: state_machines / iap_adjacent_operational_periods_allowed ───
def test_adjacent_operational_periods_both_publish(api):
    """PRD §3.4: "because periods are half-open, a plan whose start equals the immediately
    prior plan's end is adjacent, not overlapping, and is permitted."
    PRD §3.4: "On publication the plan stamps `published_at`, and the incident's
    `current_iap_id` is set to this plan's id, making it the incident's current operational plan."

    Design: Corner/state_machines/iap_adjacent_operational_periods_allowed
    """
    inc = create_activated_incident(name="Adjacency Ctx", hazard_type="HURRICANE")
    create_published_iap(
        inc["id"],
        operational_period_start="2026-03-01T06:00:00Z",
        operational_period_end="2026-03-02T06:00:00Z",
    )
    iap2 = create_iap(
        inc["id"],
        operational_period_start="2026-03-02T06:00:00Z",
        operational_period_end="2026-03-03T06:00:00Z",
    )
    published = validate_success(api.transition_iap(iap2["id"], {"to_status": "PUBLISHED"}, PLAN))
    assert published["status"] == "PUBLISHED", "adjacent period must publish"
    assert get_incident(inc["id"])["current_iap_id"] == iap2["id"], "current_iap_id must advance to iap2"


# ─── Difficulty: cross_entity_state_dependency / assign_task_requires_iap_published ───
def test_assign_task_under_draft_iap_rejected(api):
    """PRD §3.4: "Assigning a task advances it from `PLANNED` to `ASSIGNED` and stamps
    `assigned_at`, subject to several gates: the task's IAP must be `PUBLISHED` (otherwise
    `ERR_IAP_NOT_PUBLISHED`); and when the task names a backing `resource_request_id`, that
    request must belong to the same incident as the task's IAP (otherwise
    `ERR_CROSS_INCIDENT_REFERENCE`), that request's `deploy_end` must be at or after the IAP's
    `operational_period_start` (otherwise `ERR_RESOURCE_WINDOW_MISMATCH`), and that request's
    `status` must be `FILLED` (otherwise `ERR_REQUEST_NOT_FILLED`)."

    Design: Difficulty/cross_entity_state_dependency/assign_task_requires_iap_published
    """
    inc = create_activated_incident(name="Quake Response", hazard_type="EARTHQUAKE")
    iap = create_iap(inc["id"])  # left DRAFT
    task = create_task(iap["id"], title="Assess bridges")
    validate_error(
        api.transition_task(task["id"], {"to_status": "ASSIGNED"}, OPS),
        ApiErrorId.ERR_IAP_NOT_PUBLISHED.value,
    )


def test_assign_task_under_draft_iap_leaves_planned(api):
    """PRD §3.4: "Assigning a task advances it from `PLANNED` to `ASSIGNED` and stamps
    `assigned_at`, subject to several gates: the task's IAP must be `PUBLISHED` (otherwise
    `ERR_IAP_NOT_PUBLISHED`); and when the task names a backing `resource_request_id`, that
    request must belong to the same incident as the task's IAP (otherwise
    `ERR_CROSS_INCIDENT_REFERENCE`), that request's `deploy_end` must be at or after the IAP's
    `operational_period_start` (otherwise `ERR_RESOURCE_WINDOW_MISMATCH`), and that request's
    `status` must be `FILLED` (otherwise `ERR_REQUEST_NOT_FILLED`)."

    Design: Difficulty/cross_entity_state_dependency/assign_task_requires_iap_published
    """
    inc = create_activated_incident(name="Quake Response", hazard_type="EARTHQUAKE")
    iap = create_iap(inc["id"])
    task = create_task(iap["id"], title="Assess bridges")
    api.transition_task(task["id"], {"to_status": "ASSIGNED"}, OPS)
    fetched = get_success_data(api.get_task(task["id"], OPS))
    assert fetched["status"] == "PLANNED", f"expected PLANNED retained, got {fetched['status']}"


# ─── Difficulty: priority_pair_validation_conflict / assign_referential_beats_temporal ───
def test_assign_cross_incident_backing_reports_reference_over_window(api):
    """PRD §2.7: "Cross-aggregate reference integrity (`ERR_CROSS_INCIDENT_REFERENCE`)
    follows. Temporal-window checks come next (operational-period overlap, deployment-window
    capacity, and resource-window mismatch)."
    PRD §3.4: "that request must belong to the same incident as the task's IAP (otherwise
    `ERR_CROSS_INCIDENT_REFERENCE`), that request's `deploy_end` must be at or after the IAP's
    `operational_period_start` (otherwise `ERR_RESOURCE_WINDOW_MISMATCH`)"

    Design: Difficulty/priority_pair_validation_conflict/assign_referential_beats_temporal
    """
    inc_a = create_activated_incident(name="Incident A", hazard_type="FLOOD")
    iap_a = create_published_iap(
        inc_a["id"],
        operational_period_start="2026-03-05T06:00:00Z",
        operational_period_end="2026-03-06T06:00:00Z",
    )
    inc_b = create_activated_incident(name="Incident B", hazard_type="HAZMAT")
    _, pool = create_jurisdiction_and_pool(resource_type="VEHICLE", total_units=4)
    # Request under incident B, deploy_end before IAP-A start (would also mismatch the window).
    req_b = create_filled_request(
        inc_b["id"], pool["id"], quantity=2,
        deploy_start="2026-03-01T08:00:00Z", deploy_end="2026-03-01T12:00:00Z",
    )
    task = create_task(iap_a["id"], title="Cross-linked task", resource_request_id=req_b["id"])
    validate_error(
        api.transition_task(task["id"], {"to_status": "ASSIGNED"}, OPS),
        ApiErrorId.ERR_CROSS_INCIDENT_REFERENCE.value,
    )


def test_assign_cross_incident_backing_leaves_task_planned(api):
    """PRD §2.7: "Cross-aggregate reference integrity (`ERR_CROSS_INCIDENT_REFERENCE`)
    follows. Temporal-window checks come next (operational-period overlap, deployment-window
    capacity, and resource-window mismatch)."

    Design: Difficulty/priority_pair_validation_conflict/assign_referential_beats_temporal
    """
    inc_a = create_activated_incident(name="Incident A", hazard_type="FLOOD")
    iap_a = create_published_iap(
        inc_a["id"],
        operational_period_start="2026-03-05T06:00:00Z",
        operational_period_end="2026-03-06T06:00:00Z",
    )
    inc_b = create_activated_incident(name="Incident B", hazard_type="HAZMAT")
    _, pool = create_jurisdiction_and_pool(resource_type="VEHICLE", total_units=4)
    req_b = create_filled_request(
        inc_b["id"], pool["id"], quantity=2,
        deploy_start="2026-03-01T08:00:00Z", deploy_end="2026-03-01T12:00:00Z",
    )
    task = create_task(iap_a["id"], title="Cross-linked task", resource_request_id=req_b["id"])
    api.transition_task(task["id"], {"to_status": "ASSIGNED"}, OPS)
    fetched = get_success_data(api.get_task(task["id"], OPS))
    assert fetched["status"] == "PLANNED", f"expected PLANNED retained, got {fetched['status']}"


# ─── Corner: state_machines / cancel_task_from_completed_returns_invalid_state ───
def test_cancel_completed_task_rejected(api):
    """PRD §3.4: "A task may also be cancelled from either `PLANNED` or `ASSIGNED`, moving it
    to the terminal `CANCELLED` state; cancellation carries a resource-release cascade
    detailed in §3.9."
    PRD §2.7: "the system verifies that the target resource is in a valid originating state
    for the requested transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/cancel_task_from_completed_returns_invalid_state
    """
    inc = create_activated_incident(name="SM Ctx", hazard_type="EARTHQUAKE")
    iap = create_published_iap(inc["id"])
    task = create_task(iap["id"], title="Recon")
    assign_task(task["id"])
    get_success_data(api.transition_task(task["id"], {"to_status": "COMPLETED"}, OPS))
    validate_error(
        api.transition_task(task["id"], {"to_status": "CANCELLED"}, OPS),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
