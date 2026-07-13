"""Deployment-window capacity, the demobilization cascade, and the pool
conserved-quantity invariant across FILL and DEMOBILIZE.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    create_jurisdiction_and_pool,
    create_request,
    submit_request,
    source_request,
    fill_request,
    get_pool,
    setup_assigned_task_backed_by_filled_request,
    setup_filled_request_scenario,
    assert_pool_conserved,
)

LOG = TEST_USERS["logistics_chief_headers"]
EOC = TEST_USERS["eoc_manager_headers"]
PLAN = TEST_USERS["planning_chief_headers"]


# ─── Difficulty: resource_temporal_overlap / pool_deployment_window_buffer_capacity ───
def test_fill_exceeding_buffered_surge_capacity_rejected(api):
    """PRD §3.3: "It sums the `requested_quantity` of those overlapping filled requests,
    adds the candidate request's own `requested_quantity`, and permits the fill only if that
    total is at most the effective surge capacity; otherwise it rejects with
    `ERR_DEPLOYMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pool_deployment_window_buffer_capacity
    """
    inc = create_activated_incident(name="Levee Deploy", hazard_type="FLOOD")
    _, pool = create_jurisdiction_and_pool(
        resource_type="VEHICLE", total_units=10, surge_cap=5, turnaround_hours=2
    )
    r1 = create_request(inc["id"], resource_type="VEHICLE", requested_quantity=3)
    submit_request(r1["id"])
    source_request(r1["id"], pool["id"])
    fill_request(r1["id"], "2026-03-01T08:00:00Z", "2026-03-01T12:00:00Z")
    r2 = create_request(inc["id"], resource_type="VEHICLE", requested_quantity=3)
    submit_request(r2["id"])
    source_request(r2["id"], pool["id"])
    validate_error(
        api.transition_resource_request(
            r2["id"],
            {"to_status": "FILLED", "deploy_start": "2026-03-01T13:00:00Z", "deploy_end": "2026-03-01T16:00:00Z"},
            LOG,
        ),
        ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT.value,
    )


def test_fill_window_conflict_leaves_request_sourced(api):
    """PRD §3.3: "It sums the `requested_quantity` of those overlapping filled requests,
    adds the candidate request's own `requested_quantity`, and permits the fill only if that
    total is at most the effective surge capacity; otherwise it rejects with
    `ERR_DEPLOYMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pool_deployment_window_buffer_capacity
    """
    inc = create_activated_incident(name="Levee Deploy", hazard_type="FLOOD")
    _, pool = create_jurisdiction_and_pool(
        resource_type="VEHICLE", total_units=10, surge_cap=5, turnaround_hours=2
    )
    r1 = create_request(inc["id"], resource_type="VEHICLE", requested_quantity=3)
    submit_request(r1["id"])
    source_request(r1["id"], pool["id"])
    fill_request(r1["id"], "2026-03-01T08:00:00Z", "2026-03-01T12:00:00Z")
    r2 = create_request(inc["id"], resource_type="VEHICLE", requested_quantity=3)
    submit_request(r2["id"])
    source_request(r2["id"], pool["id"])
    api.transition_resource_request(
        r2["id"],
        {"to_status": "FILLED", "deploy_start": "2026-03-01T13:00:00Z", "deploy_end": "2026-03-01T16:00:00Z"},
        LOG,
    )
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_pool_resource_requests(pool["id"], LOG))
    target = next(r for r in data if r["id"] == r2["id"])
    assert target["status"] == "SOURCED", f"expected SOURCED after rejected fill, got {target['status']}"


# ─── Difficulty: transitive_cascade / demobilize_incident_three_hop_release ───
def test_demobilize_incident_cancels_task_and_demobilizes_request(api):
    """PRD §3.9: "When the `EOCManager` advances an incident from `ACTIVATED` to
    `DEMOBILIZING`, the first hop cancels work: every task under the incident's plans whose
    status is `PLANNED` or `ASSIGNED` is transitioned to `CANCELLED`. Each such cancellation
    triggers the second hop: if the cancelled task names a backing `resource_request_id`
    whose request is in `SOURCED` or `FILLED`, that request is transitioned to `DEMOBILIZED`."

    Design: Difficulty/transitive_cascade/demobilize_incident_three_hop_release
    """
    scenario = setup_assigned_task_backed_by_filled_request()
    inc = scenario["incident"]
    get_success_data(api.transition_incident(inc["id"], {"to_status": "DEMOBILIZING"}, EOC))
    task = get_success_data(api.get_task(scenario["task"]["id"], PLAN))
    assert task["status"] == "CANCELLED", f"task must cancel on demobilize, got {task['status']}"
    from test_helpers import validate_paginated
    reqs, _ = validate_paginated(api.list_incident_resource_requests(inc["id"], EOC))
    req = next(r for r in reqs if r["id"] == scenario["request"]["id"])
    assert req["status"] == "DEMOBILIZED", f"backing request must demobilize, got {req['status']}"


def test_demobilize_incident_releases_pool_commitment(api):
    """PRD §3.9: "That demobilization triggers the third hop against the pool: a request
    demobilized from `SOURCED` releases its reservation, decreasing the pool's `units_reserved`
    by `requested_quantity`; a request demobilized from `FILLED` releases its commitment,
    decreasing the pool's `units_committed` by `requested_quantity`. In both cases the pool's
    `units_available` is restored so that `total_units` is conserved, and the request stamps
    `demobilized_at`."

    Design: Difficulty/transitive_cascade/demobilize_incident_three_hop_release
    """
    scenario = setup_assigned_task_backed_by_filled_request()
    inc = scenario["incident"]
    pool_id = scenario["pool"]["id"]
    get_success_data(api.transition_incident(inc["id"], {"to_status": "DEMOBILIZING"}, EOC))
    pool = get_pool(pool_id)
    assert pool["units_committed"] == 0, f"commitment must release to 0, got {pool['units_committed']}"
    assert pool["units_available"] == 10, f"availability must restore to 10, got {pool['units_available']}"
    assert_pool_conserved(pool)


# ─── Difficulty: compensating_invariant / pool_units_conserved_on_demobilize ───
def test_direct_demobilize_of_filled_request_conserves_pool(api):
    """PRD §3.9: "A `LogisticsChief` may also demobilize an individual `SOURCED` or `FILLED`
    request directly, driving the same pool-release effects."
    PRD §2.8: "The invariant that `total_units` equals `units_available` plus `units_reserved`
    plus `units_committed` holds at every moment; reservations and commitments move units
    between the three buckets but never create or destroy them."

    Design: Difficulty/compensating_invariant/pool_units_conserved_on_demobilize
    """
    scenario = setup_filled_request_scenario(
        quantity=4, total_units=10, deploy_start="2026-03-01T08:00:00Z", deploy_end="2026-03-01T18:00:00Z"
    )
    req = scenario["request"]
    pool_id = scenario["pool"]["id"]
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "DEMOBILIZED"}, LOG))
    pool = get_pool(pool_id)
    assert pool["units_committed"] == 0, f"expected committed 0, got {pool['units_committed']}"
    assert pool["units_reserved"] == 0, f"expected reserved 0, got {pool['units_reserved']}"


def test_direct_demobilize_restores_available_units(api):
    """PRD §2.8: "The invariant that `total_units` equals `units_available` plus
    `units_reserved` plus `units_committed` holds at every moment; reservations and
    commitments move units between the three buckets but never create or destroy them."

    Design: Difficulty/compensating_invariant/pool_units_conserved_on_demobilize
    """
    scenario = setup_filled_request_scenario(
        quantity=4, total_units=10, deploy_start="2026-03-01T08:00:00Z", deploy_end="2026-03-01T18:00:00Z"
    )
    req = scenario["request"]
    pool_id = scenario["pool"]["id"]
    get_success_data(api.transition_resource_request(req["id"], {"to_status": "DEMOBILIZED"}, LOG))
    pool = get_pool(pool_id)
    assert pool["units_available"] == 10, f"expected available restored to 10, got {pool['units_available']}"
    assert_pool_conserved(pool)
