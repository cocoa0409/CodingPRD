"""Counsel capacity checks, workload utilization, and close-release cascade."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_assignment,
    assert_utilization,
    close_matter,
    create_active_matter,
    create_assignment,
    create_matter,
    get_success_data,
    setup_matter_graph,
    validate_success,
    validate_error,
    ANALYST,
)


def test_capacity_exactly_at_limit_allowed_one_over_rejected(api):
    """PRD §3.3: "Capacity is enforced at write time: if the counsel's
    capacity-consuming load — hours already committed through active assignments —
    plus the newly requested hours would exceed that counsel's
    `annual_capacity_hours`, creation is rejected with `ERR_CAPACITY_EXCEEDED`
    (HTTP 422); landing exactly at capacity is allowed."

    Design: Difficulty/boundary_precision_check/capacity_over_capacity_strict_greater_than
    """
    graph = setup_matter_graph(
        activate=False, assignment_hours=None, counsel_overrides={"annual_capacity_hours": 100}
    )
    counsel_id = graph["counsel"]["id"]

    m1 = graph["matter"]
    create_assignment(m1["id"], counsel_id, 60)
    get_success_data(api_client.activate_matter(m1["id"], ANALYST))

    create_active_matter(graph, allocated_hours=40)
    # 60 + 40 == 100 == annual_capacity_hours — exactly at capacity, allowed.

    m3 = create_matter(
        graph["practice_area"]["id"],
        graph["matter_type"]["id"],
        graph["fiscal_period"]["id"],
        counsel_id,
        primary_firm_id=graph["firm"]["id"],
    )
    res = api_client.create_assignment(
        m3["id"], {"counsel_id": counsel_id, "allocated_hours": 1}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_released_assignment_frees_capacity(api):
    """PRD §3.3: "An analyst may also release an active assignment manually while
    its matter is `ACTIVE` or `ON_HOLD`, moving it to `RELEASED` and bumping its
    `version`"
    PRD §3.3: "Capacity is enforced at write time: if the counsel's
    capacity-consuming load — hours already committed through active assignments —
    plus the newly requested hours would exceed that counsel's
    `annual_capacity_hours`, creation is rejected with `ERR_CAPACITY_EXCEEDED`
    (HTTP 422); landing exactly at capacity is allowed."

    Design: Difficulty/boundary_precision_check/capacity_over_capacity_strict_greater_than
    """
    graph = setup_matter_graph(
        activate=False, assignment_hours=None, counsel_overrides={"annual_capacity_hours": 100}
    )
    counsel_id = graph["counsel"]["id"]

    m1 = graph["matter"]
    big = create_assignment(m1["id"], counsel_id, 100)
    get_success_data(api_client.activate_matter(m1["id"], ANALYST))

    m2 = create_matter(
        graph["practice_area"]["id"],
        graph["matter_type"]["id"],
        graph["fiscal_period"]["id"],
        counsel_id,
        primary_firm_id=graph["firm"]["id"],
    )
    # Counsel is fully loaded (100/100): even one more hour overflows.
    res = api_client.create_assignment(
        m2["id"], {"counsel_id": counsel_id, "allocated_hours": 1}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    released = validate_success(api_client.release_assignment(big["id"], ANALYST), 200)
    assert released["status"] == "RELEASED"

    # After release the load is zero; a fresh 100-hour allocation lands exactly
    # at capacity and is allowed.
    ok = api_client.create_assignment(
        m2["id"], {"counsel_id": counsel_id, "allocated_hours": 100}, ANALYST
    )
    assignment = validate_success(ok, 201)
    assert_assignment(assignment)
    assert assignment["allocated_hours"] == 100


def test_utilization_excludes_assignments_on_closed_matters(api):
    """PRD §3.8: "The input set is precise: active assignments whose parent matter
    is `ACTIVE` or `ON_HOLD` consume capacity, while assignments sitting on
    `INTAKE`, `CLOSED`, `REOPENED`, or `ARCHIVED` matters do not."

    Design: Corner/calculations/workload_utilization_excludes_closed_matters
    """
    graph = setup_matter_graph(
        activate=False, assignment_hours=None, counsel_overrides={"annual_capacity_hours": 100}
    )
    counsel_id = graph["counsel"]["id"]
    m1 = graph["matter"]

    # m1 starts in INTAKE with no staffing; give it 60 hours and activate
    create_assignment(m1["id"], counsel_id, 60)
    get_success_data(api_client.activate_matter(m1["id"], ANALYST))

    create_active_matter(graph, allocated_hours=30)

    close_matter(m1["id"])

    util = validate_success(api_client.get_counsel_utilization(counsel_id, ANALYST), 200)
    assert_utilization(util)
    assert util["total_allocated_hours"] == 30


def test_close_releases_active_assignments_and_returns_capacity(api):
    """PRD §3.6: "A successful close stamps `cycle_days` as the number of days
    between the matter's original `INTAKE` → `ACTIVE` transition timestamp and
    this close transition's timestamp, releases every still-`ACTIVE` assignment on
    the matter — each moving to `RELEASED` — and bumps the matter's `version`."

    Design: Corner/state_machines/matter_close_cascades_release_assignments
    """
    graph = setup_matter_graph(
        activate=False, assignment_hours=None, counsel_overrides={"annual_capacity_hours": 100}
    )
    counsel_id = graph["counsel"]["id"]
    m1 = graph["matter"]
    a1 = create_assignment(m1["id"], counsel_id, 60)
    get_success_data(api_client.activate_matter(m1["id"], ANALYST))
    create_active_matter(graph, allocated_hours=40)

    pre = validate_success(api_client.get_counsel_utilization(counsel_id, ANALYST), 200)
    assert pre["total_allocated_hours"] == 100

    close_matter(m1["id"])

    a1_after = validate_success(api_client.get_assignment(a1["id"], ANALYST), 200)
    assert a1_after["status"] == "RELEASED"

    post = validate_success(api_client.get_counsel_utilization(counsel_id, ANALYST), 200)
    assert post["total_allocated_hours"] == 40
