"""SLA breach sweep, tiered auto-escalation, and escalation resolution.

Queue A (Difficulty): the tiered branch selection (overdue 6h -> TIER2 not TIER1)
and the strict at-deadline boundary (no breach at the exact deadline tick). Queue
B (Corner): TIER1 selection at 3h overdue, manual escalation create + dispatcher
resolve, and the non-supervisor TIER2 resolve rejection.
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
    TEST_USERS,
    make_agent_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
from test_helpers.api_errors import ApiErrorId


# ---------------------------------------------------------------------------
# Queue A — Difficulty: tiered branch (TIER2 at 6h overdue)
# ---------------------------------------------------------------------------
def test_breach_six_hours_overdue_fires_tier2(api):
    """PRD §3.9: "if the overdue hours are at least `escalation_tier2_hours` and the
    request has no open `TIER2` escalation, it creates a `TIER2` escalation whose
    `reason` notes the hours breached; otherwise, if the overdue hours are at least
    `escalation_tier1_hours` and the request has no open escalation at all, it creates
    a `TIER1` escalation with a similar reason."

    Design: Difficulty/combinatorial_formula/sla_breach_sweep_tiered_branch_mode_a
    """
    env = fx.setup_routed_request(resolution_sla_hours=24, escalation_tier1_hours=2,
                                  escalation_tier2_hours=6)
    fx.advance_clock(30)  # 30h - 24h SLA = 6h overdue -> TIER2
    escalations = fx.get_escalations_for_request(env["request"]["id"])
    tier2 = [e for e in escalations if e["tier"] == "TIER2"]
    tier1 = [e for e in escalations if e["tier"] == "TIER1"]
    assert len(tier2) == 1, f"expected exactly one TIER2, got {escalations}"
    assert len(tier1) == 0, "no TIER1 fires when TIER2 threshold is met"


def test_breach_six_hours_overdue_sets_sla_breached(api):
    """PRD §3.9: "if the current instant is strictly greater than `sla_deadline_at` ...
    the request's `sla_breached` is set to true and stays true thereafter for breach
    accounting."

    Design: Difficulty/combinatorial_formula/sla_breach_sweep_tiered_branch_mode_a
    """
    env = fx.setup_routed_request(resolution_sla_hours=24, escalation_tier1_hours=2,
                                  escalation_tier2_hours=6)
    fx.advance_clock(30)
    request = fx.get_request(env["request"]["id"])
    assert request["sla_breached"] is True


# ---------------------------------------------------------------------------
# Queue A — Difficulty: strict at-deadline boundary
# ---------------------------------------------------------------------------
def test_no_breach_exactly_at_deadline(api):
    """PRD §3.9: "if the current instant is strictly greater than `sla_deadline_at` —
    exactly at the deadline the request is not yet breached and no escalation fires —
    the request's `sla_breached` is set to true."

    Design: Difficulty/boundary_precision_check/sla_not_breached_exactly_at_deadline
    """
    env = fx.setup_routed_request(resolution_sla_hours=24, escalation_tier1_hours=2,
                                  escalation_tier2_hours=6)
    advance = fx.advance_clock(24)  # clock_now == sla_deadline_at
    request = fx.get_request(env["request"]["id"])
    assert request["sla_breached"] is False
    assert advance["escalations_created"] == 0


def test_no_escalations_at_exact_deadline(api):
    """PRD §3.9: "exactly at the deadline the request is not yet breached and no
    escalation fires."

    Design: Difficulty/boundary_precision_check/sla_not_breached_exactly_at_deadline
    """
    env = fx.setup_routed_request(resolution_sla_hours=24, escalation_tier1_hours=2,
                                  escalation_tier2_hours=6)
    fx.advance_clock(24)
    escalations = fx.get_escalations_for_request(env["request"]["id"])
    assert escalations == [], "no escalation may exist at the exact deadline tick"


# ---------------------------------------------------------------------------
# Queue B — Corner: TIER1 at 3h overdue
# ---------------------------------------------------------------------------
def test_breach_three_hours_overdue_fires_tier1(api):
    """PRD §3.9: "otherwise, if the overdue hours are at least `escalation_tier1_hours`
    and the request has no open escalation at all, it creates a `TIER1` escalation with
    a similar reason."

    Design: Corner/calculations/sla_breach_tier1_at_three_hours_overdue
    """
    env = fx.setup_routed_request(resolution_sla_hours=24, escalation_tier1_hours=2,
                                  escalation_tier2_hours=6)
    fx.advance_clock(27)  # 27h - 24h = 3h overdue -> TIER1 (>=2, <6)
    escalations = fx.get_escalations_for_request(env["request"]["id"])
    tier1 = [e for e in escalations if e["tier"] == "TIER1"]
    assert len(tier1) == 1, f"expected exactly one TIER1, got {escalations}"
    request = fx.get_request(env["request"]["id"])
    assert request["sla_breached"] is True


# ---------------------------------------------------------------------------
# Queue B — Corner: manual escalation then dispatcher resolve
# ---------------------------------------------------------------------------
def test_manual_escalation_then_resolve_by_dispatcher(api):
    """PRD §3.9: "A dispatcher may manually raise one against a request by supplying its
    `request_id`; this creates an `Escalation` of tier `MANUAL` in `OPEN` status."
    PRD §3.9: "Resolution requires the escalation to be `OPEN` and moves it
    `OPEN → RESOLVED`, recording the acting role in `resolved_by_role`."

    Design: Corner/endpoints/manual_escalation_then_resolve_by_dispatcher
    """
    dept = fx.create_department(backlog_threshold=5)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category["id"])
    created = validate_success(
        api.create_escalation({"request_id": request["id"]}, DISPATCHER), 201
    )
    assert created["tier"] == "MANUAL"
    assert created["status"] == "OPEN"
    resolved = validate_success(
        api.resolve_escalation(created["id"], DISPATCHER), 200
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_by_role"] == "Dispatcher"


# ---------------------------------------------------------------------------
# Queue B — Corner: non-supervisor agent cannot resolve TIER2
# ---------------------------------------------------------------------------
def test_tier2_escalation_non_supervisor_agent_rejected(api):
    """PRD §3.9: "Resolving a `TIER2` escalation is restricted: only a supervisor agent
    (an `Agent` whose `is_supervisor` is true) or an actor whose role is `Dispatcher`
    or `SystemAdmin` may do so; a non-supervisor agent attempting it is rejected with
    `ERR_TIER2_REQUIRES_SUPERVISOR` (HTTP 403)."

    Design: Corner/rbac/tier2_escalation_non_supervisor_agent_rejected
    """
    env = fx.setup_started_request(resolution_sla_hours=24, escalation_tier1_hours=2,
                                   escalation_tier2_hours=6)
    fx.advance_clock(30)  # 6h overdue -> TIER2
    escalations = fx.get_escalations_for_request(env["request"]["id"])
    tier2 = [e for e in escalations if e["tier"] == "TIER2"]
    assert tier2, "setup must produce a TIER2 escalation"
    resp = api.resolve_escalation(tier2[0]["id"], make_agent_headers(env["agent"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TIER2_REQUIRES_SUPERVISOR.value, 403)
