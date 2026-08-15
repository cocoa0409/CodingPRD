"""Roster lifecycle: agent defaults, license uniqueness, offboarding lockdown,
pause/resume cycles, deadline-expiry auto-pause cascade, and time-off overlap."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    agent_payload,
    assert_agent,
    create_agent,
    create_team,
    create_time_off,
    ctx_routing,
    get_agent,
    get_assignment,
    get_lead,
    intake_lead,
    manual_route,
    set_clock,
    claim_as,
    time_off_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["team_admin_headers"]


# ─── Agent creation defaults (Corner) ────────────────────────────────────────


def test_agent_create_applies_defaults_and_initial_state(api):
    """PRD §3.1: "New agents are born `ONBOARDING` with `performance_tier` `BRONZE` and every counter zeroed, and they are invisible to the routing selector until activation."
    PRD §3.1: "A `TeamAdmin` adds an agent with `team_id`, `display_name`, a `license_number` that must be unique within the team (a duplicate is rejected with `ERR_DUPLICATE_LICENSE_NUMBER`), a `role_on_team` of `MEMBER` or `LEADER` (defaulting to `MEMBER`; the `LEADER` value is what backs the `TeamLeader` request role), and a `max_active_leads` capacity ceiling of at least 1."
    PRD §2.5: "Mutable resources additionally carry `updated_at`, refreshed on every mutation, and an integer `version` that starts at 1 at creation and increments by 1 on every mutation."
    PRD §3.1: "The `avg_first_response_seconds` is the mean gap between a lead's `created_at` and its `first_response_at` across the agent's leads answered in the trailing ninety days, and stays null until the agent has answered at least one lead."

    Design: Corner/entities/agent_create_applies_defaults_and_initial_state
    """
    team = create_team()
    res = api.create_agent(
        agent_payload(team["id"], "LIC-N", display_name="New Agent", max_active_leads=4),
        ADMIN,
    )
    agent = validate_success(res, 201)
    assert_agent(agent)
    assert agent["role_on_team"] == "MEMBER", "role_on_team must default to MEMBER"
    assert agent["status"] == "ONBOARDING"
    assert agent["performance_tier"] == "BRONZE"
    assert agent["active_lead_count"] == 0
    assert agent["version"] == 1

    fresh = get_agent(agent["id"])
    assert fresh["trailing_90d_conversions"] == 0
    assert fresh["trailing_90d_claimed"] == 0
    assert fresh["trailing_90d_offered"] == 0
    assert fresh["avg_first_response_seconds"] is None
    assert fresh["consecutive_missed_claims"] == 0


def test_duplicate_license_number_rejected_per_team(api):
    """PRD §3.1: "A `TeamAdmin` adds an agent with `team_id`, `display_name`, a `license_number` that must be unique within the team (a duplicate is rejected with `ERR_DUPLICATE_LICENSE_NUMBER`), a `role_on_team` of `MEMBER` or `LEADER` (defaulting to `MEMBER`; the `LEADER` value is what backs the `TeamLeader` request role), and a `max_active_leads` capacity ceiling of at least 1."

    Design: Corner/errors/duplicate_license_number_rejected_per_team
    """
    t1 = create_team(name="Alpha")
    t2 = create_team(name="Beta", market="Dallas")
    first = validate_success(
        api.create_agent(agent_payload(t1["id"], "LIC-DUP", display_name="Agent One"), ADMIN), 201
    )
    assert_agent(first)

    dup = api.create_agent(agent_payload(t1["id"], "LIC-DUP", display_name="Agent Two"), ADMIN)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_LICENSE_NUMBER, expected_status=409)

    other_team = validate_success(
        api.create_agent(agent_payload(t2["id"], "LIC-DUP", display_name="Agent Three"), ADMIN), 201
    )
    assert_agent(other_team)


# ─── Offboarding terminal lockdown (Corner) ──────────────────────────────────


def test_offboarded_agent_terminal_lockdown(api):
    """PRD §3.1: "Only a `TeamAdmin` offboards, and only from `ACTIVE` or `PAUSED` — an `ONBOARDING` or `OFFBOARDED` agent rejects with `ERR_INVALID_STATE`."
    PRD §3.1: "The moment the agent's `active_lead_count` reaches zero, the agent transitions to terminal `OFFBOARDED` and is permanently excluded from the selector and from claim, release, and log-response operations."
    PRD §3.1: "A `TeamAdmin` or `TeamLeader` pauses an `ACTIVE` agent; pausing from any other status, or resuming from any status other than `PAUSED`, is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/offboarded_agent_terminal_lockdown
    """
    team = create_team()
    agent = create_agent(team["id"], "LIC-A")

    drained = validate_success(api.offboard_agent(agent["id"], ADMIN), 200)
    assert drained["status"] == "OFFBOARDED", (
        "With no active leads the drain completes inside the offboard call"
    )

    res_resume = api.resume_agent(agent["id"], ADMIN)
    validate_error(res_resume, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    res_pause = api.pause_agent(agent["id"], ADMIN)
    validate_error(res_pause, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─── Pause / resume cycle (Difficulty) ───────────────────────────────────────


def _pause_resume_setup(api):
    """Two ACTIVE agents; lead1 offered to the first-created; clock advanced;
    lead2 pooled. Returns (ctx_ids...)."""
    ctx = ctx_routing(
        source_type="SPHERE",
        auto_route=False,
        agents=(
            {"display_name": "Agent One", "license_number": "LIC-A1", "max_active_leads": 10},
            {"display_name": "Agent Two", "license_number": "LIC-A2", "max_active_leads": 10},
        ),
    )
    a1, a2 = ctx["agents"]
    lead1 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550041",
        contact_name="Lead One", contact_email="l1@x.com",
    )
    asg1 = manual_route(lead1["id"])
    assert asg1["agent_id"] == a1["id"], (
        "Round-robin tie-break: both never assigned, earlier created_at wins"
    )
    set_clock("2026-08-01T01:00:00Z")
    lead2 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550042",
        contact_name="Lead Two", contact_email="l2@x.com",
    )
    return ctx, a1, a2, lead1, lead2, asg1


def test_pause_cascade_expires_offered_assignments_and_reroutes(api):
    """PRD §3.1: "When a pause takes effect — manual or automatic — every `OFFERED` assignment of that agent expires with `outcome_reason` `AUTO_PAUSE`, and these cascade expirations do not increment `consecutive_missed_claims`."
    PRD §3.1: "Each lead whose assignment was cascade-expired returns to `NEW` and is immediately re-routed through the selector with the paused agent excluded; if no eligible agent remains, the lead stays pooled in `NEW` with `assigned_agent_id` null."

    Design: Difficulty/non_linear_state_machine/agent_pause_resume_cycle_restores_routing_eligibility
    """
    _ctx, a1, a2, lead1, _lead2, asg1 = _pause_resume_setup(api)

    paused = validate_success(api.pause_agent(a1["id"], ADMIN), 200)
    assert paused["status"] == "PAUSED"

    asg1_after = get_assignment(asg1["id"])
    assert asg1_after["status"] == "EXPIRED"
    assert asg1_after["outcome_reason"] == "AUTO_PAUSE"

    lead1_after = get_lead(lead1["id"])
    assert lead1_after["assigned_agent_id"] == a2["id"], (
        "Cascade re-route excludes the paused agent; the peer receives the lead"
    )
    assert lead1_after["status"] == "OFFERED"


def test_resume_restores_round_robin_eligibility(api):
    """PRD §3.1: "Resuming returns the agent to `ACTIVE` and resets `consecutive_missed_claims` to zero."
    PRD §3.2: "Under `ROUND_ROBIN`, eligible agents are ordered by `last_assigned_at` ascending with never-assigned agents first, ties broken by the agent's `created_at` ascending, and the first agent wins."

    Design: Difficulty/non_linear_state_machine/agent_pause_resume_cycle_restores_routing_eligibility
    """
    _ctx, a1, a2, _lead1, lead2, _asg1 = _pause_resume_setup(api)
    validate_success(api.pause_agent(a1["id"], ADMIN), 200)

    resumed = validate_success(api.resume_agent(a1["id"], ADMIN), 200)
    assert resumed["status"] == "ACTIVE"
    assert resumed["consecutive_missed_claims"] == 0

    asg2 = manual_route(lead2["id"])
    assert asg2["agent_id"] == a1["id"], (
        "A1 last assigned at 00:00:00 vs A2 at 01:00:00 — ascending order picks A1"
    )


# ─── Deadline-expiry → auto-pause → cascade re-route (Difficulty) ────────────


def _expiry_cascade_setup(api):
    """X seeded with 2 missed claims and holding two OFFERED leads (deadline
    02:00:00); Y (capacity 3) holding one CLAIMED lead. Returns context."""
    ctx = ctx_routing(
        source_type="SPHERE",
        auto_route=False,
        agents=(
            {
                "display_name": "Agent X",
                "license_number": "LIC-X",
                "max_active_leads": 10,
                "import_stats": {"consecutive_missed_claims": 2},
            },
            {"display_name": "Agent Y", "license_number": "LIC-Y", "max_active_leads": 3},
        ),
    )
    x, y = ctx["agents"]
    lead1 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550050",
        contact_name="Lead One", contact_email="l1@x.com",
    )
    a1 = manual_route(lead1["id"])
    assert a1["agent_id"] == x["id"]
    leady0 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550051",
        contact_name="Lead Y Zero", contact_email="ly0@x.com",
    )
    ay0 = manual_route(leady0["id"])
    assert ay0["agent_id"] == y["id"], "Never-assigned Y sorts before X's set last_assigned_at"
    claim_as(leady0["id"], y["id"])
    lead2 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550052",
        contact_name="Lead Two", contact_email="l2@x.com",
    )
    a2 = manual_route(lead2["id"])
    assert a2["agent_id"] == x["id"], "Tie on last_assigned_at breaks by earlier created_at"
    return ctx, x, y, lead1, lead2, leady0, a1, a2


def test_deadline_expiry_third_miss_auto_pauses_and_cascade_expires(api):
    """PRD §3.1: "Finally, `consecutive_missed_claims` tracks the deadline-expiry streak: it increments when one of the agent's offers expires unclaimed, resets to zero on any successful claim and on resume, and reaching three pauses the agent automatically."
    PRD §2.4: "Sweep ordering is pinned: expired `OFFERED` assignments are processed in ascending `claim_deadline_at` order with ties broken by ascending assignment `created_at`, and when one expiry pushes an agent to three consecutive misses, that agent's auto-pause cascade executes immediately inside the triggering expiry's processing, before the next expired assignment is handled."
    PRD §2.4: "The response reports the new logical time `now_utc` together with `expired_assignment_count`, `auto_paused_agent_count`, `expired_agreement_count`, and `advanced_enrollment_count`."

    Design: Difficulty/transitive_cascade/claim_expiry_auto_pause_cascade_reroutes_pool
    """
    _ctx, x, _y, _lead1, _lead2, _leady0, a1, a2 = _expiry_cascade_setup(api)

    sweep = set_clock("2026-08-01T02:00:01Z")
    assert sweep["auto_paused_agent_count"] == 1

    x_after = get_agent(x["id"])
    assert x_after["status"] == "PAUSED"
    assert x_after["consecutive_missed_claims"] == 3, (
        "Only the DEADLINE expiry increments; the AUTO_PAUSE cascade expiry does not"
    )

    a1_after = get_assignment(a1["id"])
    assert a1_after["status"] == "EXPIRED"
    assert a1_after["outcome_reason"] == "DEADLINE", "First expiry in sweep order is a deadline expiry"
    a2_after = get_assignment(a2["id"])
    assert a2_after["status"] == "EXPIRED"
    assert a2_after["outcome_reason"] == "AUTO_PAUSE", "Cascade expiry inside the triggering expiry's processing"


def test_expiry_cascade_reroutes_both_leads_to_surviving_agent(api):
    """PRD §3.4: "The lead is then immediately re-routed through the selector with the missed agent excluded, remaining pooled in `NEW` if the pool is empty."
    PRD §3.1: "When a pause takes effect — manual or automatic — every `OFFERED` assignment of that agent expires with `outcome_reason` `AUTO_PAUSE`, and these cascade expirations do not increment `consecutive_missed_claims`."

    Design: Difficulty/transitive_cascade/claim_expiry_auto_pause_cascade_reroutes_pool
    """
    _ctx, x, y, lead1, lead2, leady0, _a1, _a2 = _expiry_cascade_setup(api)

    set_clock("2026-08-01T02:00:01Z")

    assert get_lead(lead1["id"])["assigned_agent_id"] == y["id"]
    assert get_lead(lead2["id"])["assigned_agent_id"] == y["id"]
    assert get_agent(y["id"])["active_lead_count"] == 3, (
        "One CLAIMED lead plus two re-routed OFFERED leads fill Y's capacity of 3"
    )
    ly0 = get_lead(leady0["id"])
    assert ly0["status"] == "CLAIMED"
    assert ly0["assigned_agent_id"] == y["id"], "The cascade touches only OFFERED assignments"


# ─── Time-off closed-interval overlap (Difficulty) ───────────────────────────


def test_time_off_touching_endpoints_conflict(api):
    """PRD §3.1: "Both bounds are inclusive — the block is a closed interval — and blocks are approved on creation. Creation is rejected with `ERR_TIME_OFF_OVERLAP` (HTTP 409) when the new block intersects any existing block of the same agent under closed-interval semantics: blocks that merely touch at an endpoint still conflict."

    Design: Difficulty/resource_temporal_overlap/time_off_closed_interval_touching_endpoints_conflict
    """
    team = create_team()
    agent = create_agent(team["id"], "LIC-A", max_active_leads=10)
    create_time_off(agent["id"], "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z", "conference")

    res = api.create_time_off(
        agent["id"],
        time_off_payload("2026-08-12T00:00:00Z", "2026-08-14T00:00:00Z", "touching"),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_TIME_OFF_OVERLAP, expected_status=409)


def test_time_off_one_second_past_endpoint_allowed(api):
    """PRD §3.1: "Both bounds are inclusive — the block is a closed interval — and blocks are approved on creation. Creation is rejected with `ERR_TIME_OFF_OVERLAP` (HTTP 409) when the new block intersects any existing block of the same agent under closed-interval semantics: blocks that merely touch at an endpoint still conflict."

    Design: Difficulty/resource_temporal_overlap/time_off_closed_interval_touching_endpoints_conflict
    """
    team = create_team()
    agent = create_agent(team["id"], "LIC-A", max_active_leads=10)
    create_time_off(agent["id"], "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z", "conference")

    created = validate_success(
        api.create_time_off(
            agent["id"],
            time_off_payload("2026-08-12T00:00:01Z", "2026-08-14T00:00:00Z", "one second later"),
            ADMIN,
        ),
        201,
    )
    assert created["agent_id"] == agent["id"]
    assert created["reason"] == "one second later"
