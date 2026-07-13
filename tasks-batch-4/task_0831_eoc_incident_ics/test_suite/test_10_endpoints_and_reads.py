"""Computed situation-report snapshot and FK reverse-reachability listings."""
from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_activated_incident,
    create_open_shelter,
    adjust_occupancy,
    create_request,
    create_iap,
    create_task,
)

PLAN = TEST_USERS["planning_chief_headers"]
LOG = TEST_USERS["logistics_chief_headers"]
OPS = TEST_USERS["operations_chief_headers"]


# ─── Corner: endpoints / situation_report_snapshot_reflects_state ───
def test_situation_report_reflects_open_shelter_occupancy(api):
    """PRD §3.1: "It reports the incident's `incident_id`, current `op_status` and
    `activation_level`, the `open_shelter_count` (shelters currently `OPEN`), the
    `total_shelter_occupancy` (the sum of `current_occupancy` across the incident's open
    shelters), the `open_request_count` (resource requests still in flight — those in
    `SUBMITTED`, `NEEDS_INFO`, or `SOURCED`), the `filled_request_count` (requests in `FILLED`),
    the `total_verified_damage`, the `declaration_status`, the `total_committed_cost`, the
    `federal_share_estimated`, and the `federal_share_actual`."

    Design: Corner/endpoints/situation_report_snapshot_reflects_state
    """
    inc = create_activated_incident(name="SitRep Ctx", hazard_type="HURRICANE")
    sh = create_open_shelter(inc["id"], name="Arena", capacity=200)
    adjust_occupancy(sh["id"], check_in=7)
    snapshot = validate_success(api.get_situation_report(inc["id"], PLAN))
    assert snapshot["op_status"] == "ACTIVATED", f"expected ACTIVATED, got {snapshot['op_status']}"
    assert snapshot["open_shelter_count"] == 1, f"expected 1 open shelter, got {snapshot['open_shelter_count']}"
    assert snapshot["total_shelter_occupancy"] == 7, f"expected occupancy 7, got {snapshot['total_shelter_occupancy']}"


# ─── Corner: endpoints / list_incident_resource_requests_reverse_reachability ───
def test_list_incident_resource_requests_contains_request(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list endpoints return their
    resources sorted by creation timestamp (`created_at`) in ascending order. Every list
    response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object
    of the envelope."

    Design: Corner/endpoints/list_incident_resource_requests_reverse_reachability
    """
    inc = create_activated_incident(name="List Ctx", hazard_type="FLOOD")
    req = create_request(inc["id"], resource_type="SUPPLY", requested_quantity=2)
    data, meta = validate_paginated(api.list_incident_resource_requests(inc["id"], LOG))
    ids = [r["id"] for r in data]
    assert req["id"] in ids, f"incident listing must contain request {req['id']}, got {ids}"


# ─── Corner: endpoints / filter_tasks_by_iap_reverse_reachability ───
def test_filter_tasks_by_iap(api):
    """PRD §3.4: "Tasks may be listed and filtered by `iap_id`, `parent_task_id`, or
    `resource_request_id`."

    Design: Corner/endpoints/filter_tasks_by_iap_reverse_reachability
    """
    inc = create_activated_incident(name="Task List Ctx", hazard_type="EARTHQUAKE")
    iap = create_iap(inc["id"])
    task = create_task(iap["id"], title="Survey")
    data, meta = validate_paginated(api.list_tasks(OPS, params={"iap_id": iap["id"]}))
    ids = [t["id"] for t in data]
    assert task["id"] in ids, f"iap-filtered task list must contain task {task['id']}, got {ids}"
