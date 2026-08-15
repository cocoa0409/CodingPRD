"""Routing policies, OCC on activation, and the deterministic agent selector."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_policy,
    assert_instant_equals,
    create_agent,
    create_draft_policy,
    create_lead_source,
    create_team,
    ctx_routing,
    get_agent,
    get_lead,
    get_team,
    intake_lead,
    lead_payload,
    manual_route,
    post_event,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["team_admin_headers"]


# ─── Policy activation preconditions and OCC (Corner) ────────────────────────


def test_policy_double_activate_rejected(api):
    """PRD §3.2: "Activation, also `TeamAdmin`-only, is the optimistic-concurrency-guarded transition of §2.7: the policy must be `DRAFT` (activation attempted from `ACTIVE` or `SUPERSEDED` is rejected with `ERR_POLICY_NOT_ACTIVATABLE`), and the request's `expected_team_version` must match the team's current `version`."

    Design: Corner/state_machines/policy_double_activate_rejected
    """
    team = create_team()
    policy = create_draft_policy(team["id"], "ROUND_ROBIN")
    activate_policy(policy["id"], team["version"])  # team version advances to 2
    fresh_version = get_team(team["id"])["version"]

    res = api.activate_routing_policy(
        policy["id"], {"expected_team_version": fresh_version}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_POLICY_NOT_ACTIVATABLE, expected_status=409)
    p1_after = validate_success(api.get_routing_policy(policy["id"], ADMIN), 200)
    assert p1_after["status"] == "ACTIVE"


def test_occ_stale_team_version_rejected_then_fresh_succeeds(api):
    """PRD §2.7: "If that value does not equal the team's current `version` — because another activation has advanced it since the client read the team — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than superseding a policy the client never saw."
    PRD §3.2: "On success the policy becomes `ACTIVE` with `activated_at` stamped, the team's previously `ACTIVE` policy — if any — becomes `SUPERSEDED`, and the team's `version` increments by 1."

    Design: Corner/complexity_layers/occ_stale_team_version_rejected_then_fresh_succeeds
    """
    team = create_team()
    p1 = create_draft_policy(team["id"], "ROUND_ROBIN")
    activate_policy(p1["id"], team["version"])  # team version: 1 -> 2
    p2 = create_draft_policy(team["id"], "PERFORMANCE_WEIGHTED")
    fresh_version = get_team(team["id"])["version"]
    assert fresh_version == 2

    stale = api.activate_routing_policy(
        p2["id"], {"expected_team_version": team["version"]}, ADMIN
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    activated = validate_success(
        api.activate_routing_policy(p2["id"], {"expected_team_version": fresh_version}, ADMIN),
        200,
    )
    assert activated["status"] == "ACTIVE"
    p1_after = validate_success(api.get_routing_policy(p1["id"], ADMIN), 200)
    assert p1_after["status"] == "SUPERSEDED"
    assert get_team(team["id"])["version"] == 3


# ─── Round-robin selector determinism (Corner) ───────────────────────────────


def test_selector_round_robin_nulls_first_then_created_at_tiebreak(api):
    """PRD §3.2: "Under `ROUND_ROBIN`, eligible agents are ordered by `last_assigned_at` ascending with never-assigned agents first, ties broken by the agent's `created_at` ascending, and the first agent wins."

    Design: Corner/complexity_layers/selector_round_robin_nulls_first_then_created_at_tiebreak
    """
    ctx = ctx_routing(
        source_type="SPHERE",
        auto_route=False,
        agents=(
            {"display_name": "Agent M", "license_number": "LIC-M", "max_active_leads": 5},
            {"display_name": "Agent N", "license_number": "LIC-N", "max_active_leads": 5},
        ),
    )
    m, n = ctx["agents"]
    l1 = intake_lead(ctx["team"]["id"], ctx["source"]["id"], "+15125550145", contact_email="1@x.com")
    l2 = intake_lead(ctx["team"]["id"], ctx["source"]["id"], "+15125550146", contact_email="2@x.com")

    a1 = manual_route(l1["id"])
    assert a1["agent_id"] == m["id"], "Both never assigned: earlier created_at wins"
    a2 = manual_route(l2["id"])
    assert a2["agent_id"] == n["id"], "Never-assigned N sorts before M's set last_assigned_at"


# ─── Routing requires an ACTIVE policy; intake pools silently (Corner) ───────


def test_route_without_active_policy_rejected_and_intake_pools(api):
    """PRD §3.2: "Routing from any other lead status is `ERR_INVALID_STATE`; routing when the team has no `ACTIVE` policy is `ERR_NO_ACTIVE_POLICY`; and an empty eligibility pool is `ERR_NO_ELIGIBLE_AGENT`."
    PRD §3.3: "When the source's `auto_route` is true, an `ACTIVE` policy exists, and the eligibility pool is non-empty, the lead is routed immediately — its first `OFFERED` assignment created and the lead flipped to `OFFERED` — otherwise it pools in `NEW` until routed manually."

    Design: Corner/endpoints/route_without_active_policy_rejected_and_intake_pools
    """
    team = create_team()
    policy = create_draft_policy(team["id"], "ROUND_ROBIN")  # left DRAFT
    source = create_lead_source(team["id"], auto_route=True)
    agent = create_agent(team["id"], "LIC-A")

    lead = intake_lead(team["id"], source["id"], "+15125550133", contact_name="Pooled")
    assert lead["status"] == "NEW", "No ACTIVE policy: auto-route fails silently into the pool"

    rejected = api.route_lead(lead["id"], ADMIN)
    validate_error(rejected, ApiErrorId.ERR_NO_ACTIVE_POLICY, expected_status=409)

    activate_policy(policy["id"], team["version"])
    asg = manual_route(lead["id"])
    assert asg["agent_id"] == agent["id"]
    assert get_lead(lead["id"])["status"] == "OFFERED"


# ─── Immediate consistency of intake auto-route (Corner) ─────────────────────


def test_intake_response_reflects_autoroute_immediately(api):
    """PRD §2.5: "Consistency is immediate: every mutation's side effects, cascades, and recomputed fields are reflected in that mutation's own response and in every subsequent read."
    PRD §3.4: "Routing — automatic at intake or manual — creates an `OFFERED` assignment with `offered_at` stamped and `claim_deadline_at` set to `offered_at` plus the effective claim window."
    PRD §3.4: "The chosen agent's `active_lead_count` increments and `last_assigned_at` moves to the offer instant."

    Design: Corner/consistency_model/intake_response_reflects_autoroute_immediately
    """
    ctx = ctx_routing()  # default claim window 7200s; clock at 2026-08-01T00:00:00Z
    agent = ctx["agents"][0]

    res = api.create_lead(
        lead_payload(ctx["team"]["id"], ctx["source"]["id"], "+15125550147"), ADMIN
    )
    lead = validate_success(res, 201)
    assert lead["status"] == "OFFERED"
    assert lead["assigned_agent_id"] == agent["id"]
    assert_instant_equals(lead["claim_deadline_at"], "2026-08-01T02:00:00Z")

    agent_after = get_agent(agent["id"])
    assert agent_after["active_lead_count"] == 1
    assert_instant_equals(agent_after["last_assigned_at"], "2026-08-01T00:00:00Z")


# ─── Performance-weighted selector, multi-input score (Difficulty) ───────────


def _performance_weighted_setup(api):
    """PERFORMANCE_WEIGHTED policy; A seeded GOLD (cap 5), B seeded PLATINUM
    (cap 3); one COLD and one HOT (80 points) lead pooled."""
    ctx = ctx_routing(
        mode="PERFORMANCE_WEIGHTED",
        source_type="SPHERE",
        auto_route=False,
        agents=(
            {
                "display_name": "Agent A",
                "license_number": "LIC-A",
                "max_active_leads": 5,
                "import_stats": {
                    "trailing_90d_conversions": 4,
                    "trailing_90d_claimed": 10,
                    "trailing_90d_offered": 12,
                    "avg_first_response_seconds": 600,
                },
            },
            {
                "display_name": "Agent B",
                "license_number": "LIC-B",
                "max_active_leads": 3,
                "import_stats": {
                    "trailing_90d_conversions": 9,
                    "trailing_90d_claimed": 20,
                    "trailing_90d_offered": 22,
                    "avg_first_response_seconds": 200,
                },
            },
        ),
    )
    a, b = ctx["agents"]
    lead_cold = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550010",
        contact_name="Cold Lead", contact_email="cold@x.com",
    )
    lead_hot = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550011",
        contact_name="Hot Lead", contact_email="hot@x.com",
    )
    set_clock("2026-08-02T00:00:00Z")
    post_event(lead_hot["id"], "SHOWING_ATTENDED", "2026-08-01T06:00:00Z")
    post_event(lead_hot["id"], "REPLIED", "2026-08-01T06:30:00Z")
    post_event(lead_hot["id"], "LINK_CLICK", "2026-08-01T07:00:00Z")
    assert get_lead(lead_hot["id"])["temperature"] == "HOT"
    return ctx, a, b, lead_cold, lead_hot


def test_performance_weighted_cold_lead_picks_highest_tier_times_capacity(api):
    """PRD §3.2: "Under `PERFORMANCE_WEIGHTED`, each eligible agent's score is the `tier_weight_bps` multiplier for the agent's current `performance_tier` multiplied by the agent's remaining capacity (`max_active_leads` minus `active_lead_count`); when the lead's `temperature` is `HOT` and the agent's `trailing_90d_conversions` is at least 5, the score is doubled."
    PRD §3.2: "Creating a policy — a `TeamAdmin` operation — takes `team_id`, a `mode` of `ROUND_ROBIN` or `PERFORMANCE_WEIGHTED`, and optional tuning: `tier_weight_bps`, the per-tier multipliers in basis points used by performance weighting, defaulting to 10000 for `BRONZE`, 11000 for `SILVER`, 12500 for `GOLD`, and 15000 for `PLATINUM`; `source_mode_overrides`, a map from lead-source `type` to mode that overrides the policy's default mode for leads arriving from those source types, defaulting to empty; and optional `claim_window_seconds` and `speed_to_lead_window_seconds` overrides that replace the team defaults for leads routed under this policy."

    Design: Difficulty/combinatorial_formula/performance_weighted_selector_multi_input_score
    """
    _ctx, a, b, lead_cold, _lead_hot = _performance_weighted_setup(api)
    assert get_agent(a["id"])["performance_tier"] == "GOLD"
    assert get_agent(b["id"])["performance_tier"] == "PLATINUM"

    asg_cold = manual_route(lead_cold["id"])
    assert asg_cold["agent_id"] == a["id"], (
        "COLD: A scores 12500*5=62500 vs B 15000*3=45000 (no HOT boost branch)"
    )
    assert asg_cold["policy_mode_snapshot"] == "PERFORMANCE_WEIGHTED"


def test_performance_weighted_hot_lead_triggers_doubling_branch(api):
    """PRD §3.2: "Under `PERFORMANCE_WEIGHTED`, each eligible agent's score is the `tier_weight_bps` multiplier for the agent's current `performance_tier` multiplied by the agent's remaining capacity (`max_active_leads` minus `active_lead_count`); when the lead's `temperature` is `HOT` and the agent's `trailing_90d_conversions` is at least 5, the score is doubled."

    Design: Difficulty/combinatorial_formula/performance_weighted_selector_multi_input_score
    """
    _ctx, a, b, lead_cold, lead_hot = _performance_weighted_setup(api)
    manual_route(lead_cold["id"])  # consumes one unit of A's capacity

    asg_hot = manual_route(lead_hot["id"])
    assert asg_hot["agent_id"] == b["id"], (
        "HOT: A 12500*4=50000 (4 conversions < 5, no boost) vs B 15000*3*2=90000"
    )


# ─── Capacity boundary (Difficulty) ──────────────────────────────────────────


def _capacity_setup(api):
    """Agent A (created first, capacity 1) and Agent B (capacity 5); lead1."""
    ctx = ctx_routing(
        source_type="SPHERE",
        auto_route=False,
        agents=(
            {"display_name": "Agent A", "license_number": "LIC-A", "max_active_leads": 1},
            {"display_name": "Agent B", "license_number": "LIC-B", "max_active_leads": 5},
        ),
    )
    a, b = ctx["agents"]
    lead1 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550072",
        contact_name="Lead One", contact_email="l1@x.com",
    )
    lead2 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550073",
        contact_name="Lead Two", contact_email="l2@x.com",
    )
    return ctx, a, b, lead1, lead2


def test_agent_below_capacity_remains_eligible(api):
    """PRD §3.2: "The selector considers only the lead's team roster, and an agent is eligible only when all of the following hold: the agent's `status` is `ACTIVE`; the agent's `active_lead_count` is strictly below `max_active_leads`; no time-off block covers the current instant under closed-interval semantics (a block whose `starts_at` equals now, or whose `ends_at` equals now, still excludes the agent); and the agent is not in the retry-exclusion set — the agent whose assignment for this lead just expired or was released is excluded from that lead's immediate re-route."

    Design: Difficulty/boundary_precision_check/agent_at_exact_capacity_excluded_from_pool
    """
    _ctx, a, _b, lead1, _lead2 = _capacity_setup(api)
    asg1 = manual_route(lead1["id"])
    assert asg1["agent_id"] == a["id"], "0 < 1: A eligible below capacity; created_at tie-break"
    assert get_agent(a["id"])["active_lead_count"] == 1


def test_agent_at_exact_capacity_excluded_from_pool(api):
    """PRD §3.2: "The selector considers only the lead's team roster, and an agent is eligible only when all of the following hold: the agent's `status` is `ACTIVE`; the agent's `active_lead_count` is strictly below `max_active_leads`; no time-off block covers the current instant under closed-interval semantics (a block whose `starts_at` equals now, or whose `ends_at` equals now, still excludes the agent); and the agent is not in the retry-exclusion set — the agent whose assignment for this lead just expired or was released is excluded from that lead's immediate re-route."

    Design: Difficulty/boundary_precision_check/agent_at_exact_capacity_excluded_from_pool
    """
    _ctx, a, b, lead1, lead2 = _capacity_setup(api)
    manual_route(lead1["id"])  # A reaches exactly active_lead_count == max_active_leads

    asg2 = manual_route(lead2["id"])
    assert asg2["agent_id"] == b["id"], "1 == 1 fails the strict-less-than capacity check"
    assert get_lead(lead2["id"])["status"] == "OFFERED"
    assert get_agent(a["id"])["active_lead_count"] == 1


# ─── Cross-entity gate: routing blocked while every agent is paused ──────────


def _paused_roster_setup(api):
    ctx = ctx_routing(
        source_type="SPHERE",
        auto_route=False,
        agents=({"display_name": "Agent A", "license_number": "LIC-A", "max_active_leads": 5},),
    )
    a = ctx["agents"][0]
    validate_success(api.pause_agent(a["id"], ADMIN), 200)
    lead = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550080",
        contact_name="Pooled", contact_email="p@x.com",
    )
    return ctx, a, lead


def test_route_blocked_when_all_agents_paused(api):
    """PRD §3.2: "When no agent survives the eligibility filters, behavior depends on how routing was triggered: a manual route or reassignment is rejected with `ERR_NO_ELIGIBLE_AGENT` (HTTP 409), while intake auto-route fails silently and the lead simply remains pooled in `NEW`."
    PRD §3.1: "A `PAUSED` agent is excluded from the selector until resumed."

    Design: Difficulty/cross_entity_state_dependency/lead_route_blocked_when_all_agents_paused
    """
    _ctx, _a, lead = _paused_roster_setup(api)
    res = api.route_lead(lead["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_AGENT, expected_status=409)
    assert get_lead(lead["id"])["status"] == "NEW"


def test_route_unblocked_after_agent_resume(api):
    """PRD §3.1: "A `PAUSED` agent is excluded from the selector until resumed."
    PRD §3.1: "Resuming returns the agent to `ACTIVE` and resets `consecutive_missed_claims` to zero."

    Design: Difficulty/cross_entity_state_dependency/lead_route_blocked_when_all_agents_paused
    """
    _ctx, a, lead = _paused_roster_setup(api)
    validate_success(api.resume_agent(a["id"], ADMIN), 200)

    asg = manual_route(lead["id"])
    assert asg["agent_id"] == a["id"]
    assert get_lead(lead["id"])["status"] == "OFFERED"
