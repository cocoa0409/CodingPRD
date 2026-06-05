"""RBAC gating, optimistic-concurrency on work-order assign, and list pagination.

Queue B (Corner): unauthenticated header rejection, citizen-cannot-triage forbidden
role, agent-wrong-department rejection on start, stale work-order version on
re-assign, and the service-request listing pagination envelope.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    fixtures as fx,
    factories as fac,
    TEST_USERS,
    make_agent_headers,
    make_citizen_headers,
)
from test_helpers.api_errors import ApiErrorId

DISPATCHER = TEST_USERS["dispatcher_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Queue B — Corner: missing/unknown headers -> unauthenticated
# ---------------------------------------------------------------------------
def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of these
    known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.list_work_orders({})  # no auth headers at all
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ---------------------------------------------------------------------------
# Queue B — Corner: citizen cannot triage (forbidden role)
# ---------------------------------------------------------------------------
def test_citizen_cannot_triage_forbidden_role(api):
    """PRD §2.1: "When the headers are present and valid but the named role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/citizen_cannot_triage_forbidden_role
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    resp = api.triage_service_request(request["id"], {}, make_citizen_headers(citizen["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ---------------------------------------------------------------------------
# Queue B — Corner: agent of wrong department cannot start
# ---------------------------------------------------------------------------
def test_agent_wrong_department_cannot_start(api):
    """PRD §3.4: "The agent named must belong to the work order's department, and only
    an agent of that department may later act on it; an agent acting outside their
    department is rejected with `ERR_AGENT_WRONG_DEPARTMENT` (HTTP 403)."

    Design: Corner/rbac/agent_wrong_department_cannot_start
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    dept_a = fx.create_department(backlog_threshold=5, name="DeptA")
    dept_b = fx.create_department(backlog_threshold=5, name="DeptB")
    category = fx.create_category(dept_a["id"], requires_geolocation=False)
    fx.create_sla_policy(category["id"])
    citizen = fx.create_citizen()
    agent_a = fx.create_agent(dept_a["id"])
    agent_b = fx.create_agent(dept_b["id"])
    request = fx.create_request(citizen["id"], category["id"])
    fx.triage_request(request["id"])
    fx.route_request(request["id"])
    wo = fx.get_work_order_for_request(request["id"])
    # Assign the A-agent (valid), then a B-agent attempts to start.
    validate_success(
        api.assign_work_order(
            wo["id"], fac.assign_work_order_payload(agent_a["id"], wo["version"]), DISPATCHER
        ),
        200,
    )
    resp = api.start_work_order(wo["id"], make_agent_headers(agent_b["id"]))
    validate_error(resp, ApiErrorId.ERR_AGENT_WRONG_DEPARTMENT.value, 403)


# ---------------------------------------------------------------------------
# Queue B — Corner: OCC stale work-order version on re-assign
# ---------------------------------------------------------------------------
def test_occ_stale_workorder_version_on_assign(api):
    """PRD §2.7: "When a dispatcher assigns an agent to a work order, the assign request
    must carry `expected_work_order_version`, and that value must equal the current
    `version` of the target `WorkOrder`. A prior assignment legitimately overwrites
    `assigned_agent_id` and advances the work order's `version`; a dispatcher acting on
    a stale snapshot must therefore re-read before reassigning. A mismatch is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_workorder_version_on_assign
    """
    env = fx.setup_routed_request()
    dept_id = env["dept"]["id"]
    agent1 = fx.create_agent(dept_id)
    agent2 = fx.create_agent(dept_id)
    wo = env["work_order"]
    stale_version = wo["version"]
    validate_success(
        api.assign_work_order(
            wo["id"], fac.assign_work_order_payload(agent1["id"], stale_version), DISPATCHER
        ),
        200,
    )
    resp = api.assign_work_order(
        wo["id"], fac.assign_work_order_payload(agent2["id"], stale_version), DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ---------------------------------------------------------------------------
# Queue B — Corner: list service requests pagination envelope
# ---------------------------------------------------------------------------
def test_list_service_requests_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the size of the full filtered
    result set and `has_more` indicates whether items remain beyond the current page."

    Design: Corner/endpoints/list_service_requests_pagination_envelope
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    fx.create_request(citizen["id"], category["id"], description="r1")
    fx.create_request(citizen["id"], category["id"], description="r2")
    data, meta = validate_paginated(
        api.list_service_requests(DISPATCHER, params={"citizen_id": citizen["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
