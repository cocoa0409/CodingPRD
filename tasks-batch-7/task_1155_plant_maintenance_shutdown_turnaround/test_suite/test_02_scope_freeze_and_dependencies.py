"""Scope freeze ranking, critical-path float, dependency DAG guards, planning
surface lockdown after freeze, estimate OCC, and freeze-scope role gating."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    create_turnaround,
    create_turnaround_with_item,
    create_work_item_payload,
    freeze_turnaround,
)


def test_freeze_scope_applies_rank_constants_and_inclusive_cutoff(
    api, manager_headers, planner_headers
):
    """PRD §3.1: "The item's `rank_score` is its risk weight multiplied by one
    thousand — five for `A`, three for `B`, one for `C` — plus twenty-five for
    each reachable downstream item, plus the cost term."
    PRD §3.1: "Its cost term is five hundred minus the whole-number floor
    division of its `estimated_cost_cents` by ten thousand, floored at zero so
    cheap items earn the full five hundred and sufficiently expensive items
    earn nothing from this term."
    PRD §3.1: "Items are then ordered by `rank_score` from highest to lowest,
    with ties broken by `created_at` ascending, and assigned a one-based
    `rank_position`. Every item whose `rank_position` is less than or equal to
    `scope_cutoff_count` — the cutoff is inclusive — transitions from
    `PROPOSED` to `FROZEN` and enters the committed scope; all remaining
    `PROPOSED` items become `DEFERRED`."

    Design: Corner/calculations/freeze_rank_score_constants_and_cutoff
    """
    ta = create_turnaround(name="TA-RK")
    a1 = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="A1", system_area="A", work_type="CORRECTIVE",
                risk_class="A", estimated_hours=10, estimated_cost_cents=120000,
            ),
            planner_headers,
        ),
        201,
    )
    b1 = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="B1", system_area="B", work_type="PREVENTIVE",
                risk_class="C", estimated_hours=20, estimated_cost_cents=40000,
            ),
            planner_headers,
        ),
        201,
    )
    c1 = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="C1", system_area="C", work_type="INSPECTION",
                risk_class="C", estimated_hours=30, estimated_cost_cents=40000,
            ),
            planner_headers,
        ),
        201,
    )

    validate_success(
        api.freeze_scope(ta["id"], {"scope_cutoff_count": 2}, manager_headers)
    )

    a1 = validate_success(api.get_work_item(a1["id"], planner_headers))
    b1 = validate_success(api.get_work_item(b1["id"], planner_headers))
    c1 = validate_success(api.get_work_item(c1["id"], planner_headers))

    # A1: 5*1000 + 25*0 + max(0, 500 - floor(120000/10000)) = 5000 + 488
    assert a1["rank_score"] == 5488, f"A1 rank_score {a1['rank_score']} != 5488"
    assert a1["rank_position"] == 1
    assert a1["status"] == "FROZEN"
    # B1: 1*1000 + 0 + max(0, 500 - 4) = 1496
    assert b1["rank_score"] == 1496, f"B1 rank_score {b1['rank_score']} != 1496"
    assert b1["rank_position"] == 2
    assert b1["status"] == "FROZEN", "inclusive cutoff: position 2 <= cutoff 2"
    # C1 ties B1 at 1496 but loses the created_at tie-break
    assert c1["rank_score"] == 1496
    assert c1["rank_position"] == 3
    assert c1["status"] == "DEFERRED"


def test_freeze_scope_marks_zero_float_chain_critical(api, manager_headers, planner_headers):
    """PRD §3.1: "Working in topological order — successors evaluated before
    their predecessors — each item's path length is its own `estimated_hours`
    plus, for each outgoing edge, the edge's `lag_hours` plus the successor's
    path length, taking the maximum over successors; an item with no successors
    contributes simply its own `estimated_hours`. The project length is the
    greatest path length across all items, an item's total float is the project
    length minus its own path length, and an item whose total float is exactly
    zero is marked `is_critical_path`."

    Design: Corner/calculations/critical_path_zero_float_chain
    """
    ta = create_turnaround(name="TA-CP", authorized_budget_cents=900000000)
    x = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="X", system_area="A", work_type="CORRECTIVE",
                risk_class="A", estimated_hours=40, estimated_cost_cents=80000,
            ),
            planner_headers,
        ),
        201,
    )
    m = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="M", system_area="A", work_type="CORRECTIVE",
                risk_class="B", estimated_hours=24, estimated_cost_cents=60000,
            ),
            planner_headers,
        ),
        201,
    )
    n = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="N", system_area="A", work_type="CORRECTIVE",
                risk_class="C", estimated_hours=16, estimated_cost_cents=30000,
            ),
            planner_headers,
        ),
        201,
    )
    y = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="Y", system_area="B", work_type="INSPECTION",
                risk_class="C", estimated_hours=4, estimated_cost_cents=8000,
            ),
            planner_headers,
        ),
        201,
    )
    validate_success(
        api.add_dependency(
            m["id"], {"predecessor_work_item_id": x["id"], "lag_hours": 0},
            planner_headers,
        ),
        201,
    )
    validate_success(
        api.add_dependency(
            n["id"], {"predecessor_work_item_id": m["id"], "lag_hours": 0},
            planner_headers,
        ),
        201,
    )

    validate_success(
        api.freeze_scope(ta["id"], {"scope_cutoff_count": 4}, manager_headers)
    )

    x = validate_success(api.get_work_item(x["id"], planner_headers))
    m = validate_success(api.get_work_item(m["id"], planner_headers))
    n = validate_success(api.get_work_item(n["id"], planner_headers))
    y = validate_success(api.get_work_item(y["id"], planner_headers))

    # path lengths: N=16, M=24+16=40, X=40+40=80, Y=4; project length 80.
    # PRD: total float = project length minus the item's own path length, so
    # only the chain head X sits at float exactly zero.
    assert x["is_critical_path"] is True, (
        "X path_length 80 == project length 80 -> float 0, critical"
    )
    for item, label, fl in ((m, "M", 40), (n, "N", 64), (y, "Y", 76)):
        assert item["is_critical_path"] is False, (
            f"{label} float {fl} (project 80 minus its path length), not critical"
        )
    # X rank: 5*1000 + 25*2 downstream (M and N) + max(0, 500 - 8)
    assert x["rank_score"] == 5542, f"X rank_score {x['rank_score']} != 5542"


def test_scope_frozen_edits_are_rejected(api, manager_headers, planner_headers):
    """PRD §3.1: "The scope-freeze rule is absolute: creating a work item,
    re-estimating one, and adding a dependency edge are all legal only while
    the turnaround remains `PLANNING`; once the scope is frozen any of these
    edits is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/scope_frozen_edits_rejected
    """
    ta, item = create_turnaround_with_item()
    freeze_turnaround(ta["id"], scope_cutoff_count=1)

    resp_create = api.create_work_item(
        ta["id"],
        create_work_item_payload(
            title="Late scope", system_area="B", risk_class="B",
            estimated_hours=5, estimated_cost_cents=9000,
        ),
        planner_headers,
    )
    validate_error(resp_create, ApiErrorId.ERR_INVALID_STATE)

    fresh = validate_success(api.get_work_item(item["id"], planner_headers))
    resp_estimate = api.estimate_work_item(
        item["id"],
        {
            "estimated_hours": 12,
            "estimated_cost_cents": 12000,
            "risk_class": "B",
            "expected_work_item_version": fresh["version"],
        },
        planner_headers,
    )
    validate_error(resp_estimate, ApiErrorId.ERR_INVALID_STATE)


def test_dependency_cycle_and_self_loop_rejected(api, manager_headers, planner_headers):
    """PRD §3.1: "The network is a directed acyclic graph; any edge that would
    close a cycle is rejected with `ERR_DEPENDENCY_CYCLE`, and a self-loop — an
    item depending on itself — counts as a cycle."

    Design: Corner/errors/dependency_cycle_and_self_loop_rejected
    """
    ta = create_turnaround(name="TA-CYC2")
    x = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="X", system_area="A", risk_class="A",
                estimated_hours=10, estimated_cost_cents=10000,
            ),
            planner_headers,
        ),
        201,
    )
    m = validate_success(
        api.create_work_item(
            ta["id"],
            create_work_item_payload(
                title="M", system_area="A", risk_class="B",
                estimated_hours=20, estimated_cost_cents=20000,
            ),
            planner_headers,
        ),
        201,
    )
    validate_success(
        api.add_dependency(
            m["id"], {"predecessor_work_item_id": x["id"], "lag_hours": 0},
            planner_headers,
        ),
        201,
    )

    # M -> X would close the two-node cycle (X already reaches M)
    resp_cycle = api.add_dependency(
        x["id"], {"predecessor_work_item_id": m["id"], "lag_hours": 0},
        planner_headers,
    )
    validate_error(resp_cycle, ApiErrorId.ERR_DEPENDENCY_CYCLE)

    # self-loop counts as a cycle
    resp_self = api.add_dependency(
        x["id"], {"predecessor_work_item_id": x["id"], "lag_hours": 0},
        planner_headers,
    )
    validate_error(resp_self, ApiErrorId.ERR_DEPENDENCY_CYCLE)


def test_estimate_with_stale_version_rejected_after_fresh_write(
    api, manager_headers, planner_headers
):
    """PRD §2.7: "A request to re-estimate a work item must carry
    `expected_work_item_version`, holding the `version` of the work item as the
    planner last observed it. If that value no longer matches the work item's
    current `version` — because another estimate has already been applied since
    the client last read the item — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the planner from overwriting an
    estimate it has not observed."

    Design: Corner/cross_cutting_layers/occ_work_item_estimate_stale_then_fresh
    """
    ta, item = create_turnaround_with_item()
    observed_version = item["version"]
    assert observed_version == 1

    first = validate_success(
        api.estimate_work_item(
            item["id"],
            {
                "estimated_hours": 12,
                "estimated_cost_cents": 12000,
                "risk_class": "B",
                "expected_work_item_version": observed_version,
            },
            planner_headers,
        )
    )
    assert first["version"] == 2, "accepted estimate bumps version 1 -> 2"

    resp_stale = api.estimate_work_item(
        item["id"],
        {
            "estimated_hours": 14,
            "estimated_cost_cents": 14000,
            "risk_class": "C",
            "expected_work_item_version": observed_version,
        },
        planner_headers,
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_work_item(item["id"], planner_headers))
    assert after["estimated_hours"] == 12, "stale estimate must not overwrite"
    assert after["estimated_cost_cents"] == 12000


def test_planner_cannot_freeze_scope(api, manager_headers, planner_headers):
    """PRD §2.1: "A request whose role is not permitted for the endpoint, or
    that fails an entity-backed ownership check, is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: "| POST | `/turnarounds/{id}/freeze-scope` | Freeze scope: rank
    `PROPOSED` items, freeze up to the inclusive cutoff, defer the rest |
    TurnaroundManager |"

    Design: Corner/validations/planner_cannot_freeze_scope_returns_forbidden
    """
    ta, _item = create_turnaround_with_item()
    resp = api.freeze_scope(ta["id"], {"scope_cutoff_count": 1}, planner_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_turnaround(ta["id"], manager_headers))
    assert after["status"] == "PLANNING", "forbidden freeze must not move the machine"
