"""Validation-precedence conflicts and close/reopen state guards.

Queue A (Difficulty): state-beats-no-sla-policy at route, owner-beats-window at
reopen, and the request-close-blocked-by-open-escalation dependency. Queue B
(Corner): close-from-submitted invalid state, terminal CLOSED cannot reopen, and
the standalone reopen-window-closed temporal check.

Each precedence conflict is asserted with the single PRD-stated winner, because
PRD §2.6 fixes the global validation order explicitly.
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
    TEST_USERS,
    make_citizen_headers,
    make_agent_headers,
)
from test_helpers.api_errors import ApiErrorId

DISPATCHER = TEST_USERS["dispatcher_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty: state (6) beats no-sla-policy (12) at route
# ---------------------------------------------------------------------------
def test_route_submitted_without_sla_policy_reports_invalid_state(api):
    """PRD §2.6: "(6) that the target resource is in a state from which the requested
    transition is defined, yielding `ERR_INVALID_STATE`. ... Below these sit the
    business-constraint and temporal checks described throughout §3."

    Design: Difficulty/priority_pair_validation_conflict/route_invalid_state_beats_no_sla_policy
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)  # no SLA policy
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])  # left SUBMITTED
    resp = api.route_service_request(request["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_route_submitted_without_sla_policy_does_not_route(api):
    """PRD §3.3: "A dispatcher routes a `TRIAGED` request, advancing it
    `TRIAGED → ROUTED`."
    PRD §2.6: "(6) that the target resource is in a state from which the requested
    transition is defined, yielding `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/route_invalid_state_beats_no_sla_policy
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    api.route_service_request(request["id"], DISPATCHER)
    after = fx.get_request(request["id"])
    assert after["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Queue A — Difficulty: owner (4) beats reopen-window (13) at reopen
# ---------------------------------------------------------------------------
def _setup_resolved_then_window_closed():
    """Request owned by citizen A, RESOLVED at 2026-06-01T10:00:00Z; clock then
    advanced past the 72h window. Returns (request_id, owner_id)."""
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    fx.create_sla_policy(category["id"], resolution_sla_hours=240)
    owner = fx.create_citizen(email="ownerA@x.com")
    agent = fx.create_agent(dept["id"])
    request = fx.create_request(owner["id"], category["id"])
    fx.triage_request(request["id"])
    fx.route_request(request["id"])
    wo = fx.get_work_order_for_request(request["id"])
    fx.assign_and_start(wo["id"], agent["id"])
    fx.set_clock("2026-06-01T10:00:00Z")
    validate_success(
        api_complete(wo["id"], agent["id"]), 200
    )
    fx.set_clock("2026-06-05T00:00:00Z")  # > 72h past resolved_at
    return request["id"], owner["id"]


def api_complete(wo_id, agent_id):
    return fx.api_client.complete_work_order(
        wo_id, {"completion_note": "fixed"}, make_agent_headers(agent_id)
    )


def test_reopen_non_owner_after_window_reports_not_owner(api):
    """PRD §2.6: "(4) citizen ownership of the target request or survey for
    citizen-scoped actions, yielding `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.5: "only by the citizen who owns it (the acting `X-User-ID` must equal the
    request's `citizen_id`, else `ERR_NOT_RESOURCE_OWNER`)."

    Design: Difficulty/priority_pair_validation_conflict/reopen_owner_beats_reopen_window
    """
    request_id, _owner_id = _setup_resolved_then_window_closed()
    non_owner = fx.create_citizen(email="strangerB@x.com")
    resp = api.reopen_service_request(request_id, make_citizen_headers(non_owner["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_reopen_non_owner_after_window_not_reopened(api):
    """PRD §2.6: "ownership and state, which precede the concurrency check, which
    precede domain business rules."
    PRD §3.5: "only by the citizen who owns it (the acting `X-User-ID` must equal the
    request's `citizen_id`, else `ERR_NOT_RESOURCE_OWNER`)."

    Design: Difficulty/priority_pair_validation_conflict/reopen_owner_beats_reopen_window
    """
    request_id, _owner_id = _setup_resolved_then_window_closed()
    non_owner = fx.create_citizen(email="strangerC@x.com")
    api.reopen_service_request(request_id, make_citizen_headers(non_owner["id"]))
    after = fx.get_request(request_id)
    assert after["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Queue A — Difficulty: request close blocked by open escalation
# ---------------------------------------------------------------------------
def test_close_blocked_by_open_escalation(api):
    """PRD §3.6: "Closing requires the request to be `RESOLVED` and to have no open
    escalation; a close attempted while an escalation remains open is rejected with
    `ERR_OPEN_ESCALATION_BLOCKS_CLOSE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/request_close_blocked_by_open_escalation
    """
    env = fx.setup_resolved_request()
    # Raise a MANUAL escalation after resolution so the request has an OPEN escalation.
    validate_success(api.create_escalation({"request_id": env["request"]["id"]}, DISPATCHER), 201)
    resp = api.close_service_request(env["request"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_OPEN_ESCALATION_BLOCKS_CLOSE.value, 409)


def test_close_blocked_request_stays_resolved(api):
    """PRD §3.6: "a close attempted while an escalation remains open is rejected with
    `ERR_OPEN_ESCALATION_BLOCKS_CLOSE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/request_close_blocked_by_open_escalation
    """
    env = fx.setup_resolved_request()
    validate_success(api.create_escalation({"request_id": env["request"]["id"]}, DISPATCHER), 201)
    api.close_service_request(env["request"]["id"], DISPATCHER)
    after = fx.get_request(env["request"]["id"])
    assert after["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Queue B — Corner: close from SUBMITTED is invalid
# ---------------------------------------------------------------------------
def test_close_from_submitted_returns_invalid_state(api):
    """PRD §3.6: "A dispatcher closes a `RESOLVED` request, moving it
    `RESOLVED → CLOSED`. Closing requires the request to be `RESOLVED`."

    Design: Corner/state_machines/close_from_submitted_returns_invalid_state
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    resp = api.close_service_request(request["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ---------------------------------------------------------------------------
# Queue B — Corner: terminal CLOSED cannot reopen
# ---------------------------------------------------------------------------
def test_terminal_closed_request_cannot_reopen(api):
    """PRD §3.6: "`CLOSED` is terminal: a closed request carries no further
    transitions."
    PRD §3.5: "Reopen is permitted only while the request is `RESOLVED`."

    Design: Corner/state_machines/terminal_closed_request_cannot_reopen
    """
    env = fx.setup_resolved_request()
    validate_success(api.close_service_request(env["request"]["id"], DISPATCHER), 200)
    resp = api.reopen_service_request(
        env["request"]["id"], make_citizen_headers(env["citizen"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = fx.get_request(env["request"]["id"])
    assert after["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Queue B — Corner: reopen window closed (owner passes, window fails)
# ---------------------------------------------------------------------------
def test_reopen_window_closed_standalone(api):
    """PRD §3.5: "only while the reopen window is still open — that is, the request's
    `resolved_at` plus the system-wide reopen window of 72 hours must be at or after
    the current instant; a reopen attempted after that window has elapsed is rejected
    with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/reopen_window_closed_standalone
    """
    request_id, owner_id = _setup_resolved_then_window_closed()
    resp = api.reopen_service_request(request_id, make_citizen_headers(owner_id))
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_CLOSED.value, 409)
