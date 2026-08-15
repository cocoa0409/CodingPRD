"""Lead and assignment lifecycle: claims, first response, release/re-route,
phone uniqueness, listing/pagination, parallel status/temperature dimensions,
and the speed-to-lead boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    claim_as,
    create_lead_source,
    create_team,
    ctx_routing,
    get_agent,
    get_assignment,
    get_lead,
    intake_lead,
    lead_payload,
    list_assignments,
    make_agent_headers,
    manual_route,
    post_event,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["team_admin_headers"]


# ─── Claim preconditions (Corner) ────────────────────────────────────────────


def test_claim_pooled_new_lead_returns_invalid_state(api):
    """PRD §3.4: "A successful claim moves the lead `OFFERED → CLAIMED` and the assignment to `CLAIMED`, resets the claimant's `consecutive_missed_claims` to zero, and recomputes `trailing_90d_claimed`."
    PRD §2.8: "Sixth, state preconditions on the target resource — the generic `ERR_INVALID_STATE` and its specialized siblings `ERR_SOURCE_NOT_ACTIVE`, `ERR_NO_ACTIVE_POLICY`, `ERR_POLICY_NOT_ACTIVATABLE`, `ERR_DEAL_NOT_APPROVABLE`, `ERR_ENROLLMENT_NOT_ACTIVE`, and `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/claim_pooled_new_lead_returns_invalid_state
    """
    ctx = ctx_routing(
        source_type="SPHERE",
        auto_route=False,
        agents=({"display_name": "Agent A", "license_number": "LIC-A", "max_active_leads": 5},),
    )
    agent = ctx["agents"][0]
    lead = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550101",
        contact_name="Pooled", contact_email="p@x.com",
    )
    assert lead["status"] == "NEW"

    res = api.claim_lead(lead["id"], make_agent_headers(agent["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_lead(lead["id"])["status"] == "NEW"
    assert list_assignments({"lead_id": lead["id"]}) == []


def test_second_log_response_rejected_idempotency(api):
    """PRD §3.4: "The lead's `first_response_at` is stamped exactly once (a second log-response is `ERR_INVALID_STATE`), `within_speed_sla` is computed as whether `first_response_at` fell at or before `speed_deadline_at`, the current assignment's `responded_at` is set, and the agent's `avg_first_response_seconds` is recomputed and `performance_tier` re-evaluated."

    Design: Corner/state_machines/second_log_response_rejected_idempotency
    """
    ctx = ctx_routing()  # default speed window 900s
    agent = ctx["agents"][0]
    lead = intake_lead(ctx["team"]["id"], ctx["source"]["id"], "+15125550102")
    claim_as(lead["id"], agent["id"])
    set_clock("2026-08-01T00:05:00Z")
    first = validate_success(api.log_response(lead["id"], make_agent_headers(agent["id"])), 200)
    assert first["within_speed_sla"] is True, "300s <= 900s window"

    set_clock("2026-08-01T01:00:00Z")
    res = api.log_response(lead["id"], make_agent_headers(agent["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    after = get_lead(lead["id"])
    assert_instant_equals(after["first_response_at"], "2026-08-01T00:05:00Z")
    assert after["within_speed_sla"] is True
    assert after["status"] == "WORKING"


# ─── Phone uniqueness scoped to non-terminal leads (Corner) ──────────────────


def test_duplicate_open_lead_phone_rejected_then_freed_by_close(api):
    """PRD §3.3: "The `contact_phone` must be unique per team among leads whose status is neither `CLOSED_WON` nor `CLOSED_LOST`; a duplicate open phone is `ERR_DUPLICATE_OPEN_LEAD`."
    PRD §3.4: "The assigned agent, a `TeamLeader`, or a `TeamAdmin` may close a `CLAIMED` or `WORKING` lead as lost with a required `reason`, which is recorded into `close_reason`; any other status is `ERR_INVALID_STATE`, and agent callers must be the assigned agent."

    Design: Corner/validations/duplicate_open_lead_phone_rejected_then_freed_by_close
    """
    ctx = ctx_routing()  # auto-route PORTAL, one ACTIVE agent C
    agent = ctx["agents"][0]
    lead1 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550123",
        contact_name="First", contact_email="f@x.com",
    )
    dup = api.create_lead(
        lead_payload(
            ctx["team"]["id"], ctx["source"]["id"], "+15125550123",
            contact_name="Dup", contact_email="d@x.com",
        ),
        ADMIN,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_OPEN_LEAD, expected_status=409)

    claim_as(lead1["id"], agent["id"])
    validate_success(
        api.close_lost(lead1["id"], {"reason": "not interested"}, make_agent_headers(agent["id"])),
        200,
    )

    again = validate_success(
        api.create_lead(
            lead_payload(
                ctx["team"]["id"], ctx["source"]["id"], "+15125550123",
                contact_name="Again", contact_email="a@x.com",
            ),
            ADMIN,
        ),
        201,
    )
    assert again["status"] == "OFFERED"


# ─── Lead listing: filters + pagination (Corner) ─────────────────────────────


def test_lead_list_pagination_and_source_filter(api):
    """PRD §2.3: "List endpoints paginate through the `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; it defaults to 10 and accepts values from a minimum of 1 to a maximum of 100. `offset` specifies the number of items to skip and defaults to 0."
    PRD §3.3: "Leads list with `team_id`, `source_id`, `assigned_agent_id`, `referral_partner_id`, `status`, and `temperature` filters."

    Design: Corner/endpoints/lead_list_pagination_and_source_filter
    """
    team = create_team()
    portal = create_lead_source(team["id"], name="Zillow", type="PORTAL", auto_route=False)
    sphere = create_lead_source(team["id"], name="Sphere", type="SPHERE", auto_route=False)
    intake_lead(team["id"], portal["id"], "+15125550130", contact_name="L1", contact_email="1@x.com")
    intake_lead(team["id"], portal["id"], "+15125550131", contact_name="L2", contact_email="2@x.com")
    intake_lead(team["id"], sphere["id"], "+15125550132", contact_name="L3", contact_email="3@x.com")

    data, meta = validate_paginated(api.list_leads(ADMIN, params={"team_id": team["id"]}))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10, "default limit"
    assert len(data) == 3

    data, meta = validate_paginated(
        api.list_leads(ADMIN, params={"team_id": team["id"], "source_id": portal["id"]})
    )
    assert meta["total_count"] == 2
    assert all(row["source_id"] == portal["id"] for row in data)

    data, meta = validate_paginated(
        api.list_leads(ADMIN, params={"team_id": team["id"], "limit": 2})
    )
    assert len(data) == 2
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_leads(ADMIN, params={"team_id": team["id"], "limit": 2, "offset": 2})
    )
    assert len(data) == 1
    assert meta["has_more"] is False


# ─── Parallel status x temperature dimensions (Difficulty) ───────────────────


def _parallel_dims_setup(api):
    """Auto-routed OFFERED lead; three events (40+25+10) posted under an
    advanced clock so the events are less than 30 days old."""
    ctx = ctx_routing()  # PORTAL auto_route, single ACTIVE agent C
    agent = ctx["agents"][0]
    set_clock("2026-08-02T00:00:00Z")
    lead = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550040", contact_email="b@x.com"
    )
    assert lead["status"] == "OFFERED"
    post_event(lead["id"], "SHOWING_ATTENDED", "2026-08-01T06:00:00Z")
    post_event(lead["id"], "FORM_SUBMIT", "2026-08-01T06:30:00Z")
    post_event(lead["id"], "LINK_CLICK", "2026-08-01T07:00:00Z")
    return ctx, agent, lead


def test_engagement_events_flip_temperature_without_touching_status(api):
    """PRD §3.5: "The `temperature` dimension is independent of lifecycle status: a lead is `HOT` when its `engagement_score` is at least 75, `WARM` when the score is at least 40 but below 75, and `COLD` below 40 — a score of exactly 40 is `WARM` and exactly 75 is `HOT`."
    PRD §3.5: "Temperature changes never alter status, and status changes never alter temperature."

    Design: Difficulty/non_linear_state_machine/lead_parallel_status_and_temperature_dimensions
    """
    _ctx, _agent, lead = _parallel_dims_setup(api)
    after = get_lead(lead["id"])
    assert after["engagement_score"] == 75, "40+25+10 at full weight (age < 30 days)"
    assert after["temperature"] == "HOT", "Exactly 75 qualifies as HOT (inclusive)"
    assert after["status"] == "OFFERED"


def test_claim_flips_status_without_touching_temperature(api):
    """PRD §3.5: "Temperature changes never alter status, and status changes never alter temperature."
    PRD §3.4: "A successful claim moves the lead `OFFERED → CLAIMED` and the assignment to `CLAIMED`, resets the claimant's `consecutive_missed_claims` to zero, and recomputes `trailing_90d_claimed`."

    Design: Difficulty/non_linear_state_machine/lead_parallel_status_and_temperature_dimensions
    """
    _ctx, agent, lead = _parallel_dims_setup(api)
    claimed = claim_as(lead["id"], agent["id"])
    assert claimed["status"] == "CLAIMED"
    assert claimed["temperature"] == "HOT"
    assert claimed["engagement_score"] == 75


# ─── Speed-to-lead exact-deadline boundary (Difficulty) ──────────────────────


def _speed_boundary_setup(api):
    """lead1 created 00:00:00 (deadline 00:15:00) and claimed; clock 00:15:00;
    lead2 created 00:15:00 (deadline 00:30:00) and claimed."""
    ctx = ctx_routing()  # default speed window 900s
    agent = ctx["agents"][0]
    lead1 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550070",
        contact_name="Lead One", contact_email="l1@x.com",
    )
    claim_as(lead1["id"], agent["id"])
    set_clock("2026-08-01T00:15:00Z")
    lead2 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550071",
        contact_name="Lead Two", contact_email="l2@x.com",
    )
    claim_as(lead2["id"], agent["id"])
    return ctx, agent, lead1, lead2


def test_response_at_exact_speed_deadline_within_sla(api):
    """PRD §3.4: "The lead's `first_response_at` is stamped exactly once (a second log-response is `ERR_INVALID_STATE`), `within_speed_sla` is computed as whether `first_response_at` fell at or before `speed_deadline_at`, the current assignment's `responded_at` is set, and the agent's `avg_first_response_seconds` is recomputed and `performance_tier` re-evaluated."
    PRD §3.4: "On the lead's first routing only, `speed_deadline_at` is snapshotted as the lead's `created_at` plus the effective speed window."

    Design: Difficulty/boundary_precision_check/speed_to_lead_exact_deadline_within_sla
    """
    _ctx, agent, lead1, _lead2 = _speed_boundary_setup(api)
    answered = log_response_at(api, lead1["id"], agent["id"])
    assert answered["within_speed_sla"] is True, "00:15:00 == created 00:00:00 + 900s (inclusive)"
    assert answered["status"] == "WORKING"


def test_response_one_second_past_deadline_outside_sla(api):
    """PRD §3.4: "The lead's `first_response_at` is stamped exactly once (a second log-response is `ERR_INVALID_STATE`), `within_speed_sla` is computed as whether `first_response_at` fell at or before `speed_deadline_at`, the current assignment's `responded_at` is set, and the agent's `avg_first_response_seconds` is recomputed and `performance_tier` re-evaluated."
    PRD §3.4: "On the lead's first routing only, `speed_deadline_at` is snapshotted as the lead's `created_at` plus the effective speed window."

    Design: Difficulty/boundary_precision_check/speed_to_lead_exact_deadline_within_sla
    """
    _ctx, agent, _lead1, lead2 = _speed_boundary_setup(api)
    set_clock("2026-08-01T00:30:01Z")
    answered = log_response_at(api, lead2["id"], agent["id"])
    assert answered["within_speed_sla"] is False, "One second past the 00:30:00 deadline"
    assert answered["status"] == "WORKING", "The flag is observational, not gating"


def log_response_at(api, lead_id, agent_id):
    return validate_success(api.log_response(lead_id, make_agent_headers(agent_id)), 200)


# ─── Release + re-route assignment cardinality (Difficulty) ──────────────────


def _release_setup(api):
    """Lead auto-routed to A (first-created) and claimed; released by admin."""
    ctx = ctx_routing(
        agents=(
            {"display_name": "Agent A", "license_number": "LIC-A", "max_active_leads": 10},
            {"display_name": "Agent B", "license_number": "LIC-B", "max_active_leads": 10},
        )
    )
    a, b = ctx["agents"]
    lead = intake_lead(ctx["team"]["id"], ctx["source"]["id"], "+15125550090")
    assert lead["assigned_agent_id"] == a["id"]
    first_assignment_id = lead["current_assignment_id"]
    claim_as(lead["id"], a["id"])
    released = validate_success(
        api.release_lead(lead["id"], {"reason": "agent reassigned by ops"}, ADMIN), 200
    )
    return ctx, a, b, lead, first_assignment_id, released


def test_release_clears_pointer_and_decrements_capacity(api):
    """PRD §3.4: "The assignment transitions to `RELEASED` with `outcome_reason` `RELEASED`, `assigned_agent_id` and `current_assignment_id` are cleared, and the agent's `active_lead_count` decrements. The lead then waits in `NEW` until explicitly re-routed."

    Design: Difficulty/compensating_invariant/release_and_reroute_preserves_single_active_assignment
    """
    _ctx, a, _b, lead, first_assignment_id, released = _release_setup(api)
    assert released["status"] == "NEW"
    assert released["assigned_agent_id"] is None
    assert released["current_assignment_id"] is None

    first = get_assignment(first_assignment_id)
    assert first["status"] == "RELEASED"
    assert first["outcome_reason"] == "RELEASED"
    assert get_agent(a["id"])["active_lead_count"] == 0


def test_reroute_after_release_starts_fresh_assignment(api):
    """PRD §3.2: "Every assignment the selector produces snapshots its routing context: the `policy_id` of the policy revision that produced it, a `policy_mode_snapshot` recording the effective mode after source overrides, a per-team monotonically increasing `rotation_seq`, and a `supersedes_assignment_id` pointing at the assignment it replaces on a re-route (null for a lead's first routing)."
    PRD §3.4: "Assignments list with `lead_id`, `agent_id`, `policy_id`, `supersedes_assignment_id`, and `status` filters, so a reassignment chain can be walked link by link."

    Design: Difficulty/compensating_invariant/release_and_reroute_preserves_single_active_assignment
    """
    _ctx, a, b, lead, _first_assignment_id, _released = _release_setup(api)
    asg2 = manual_route(lead["id"])
    assert asg2["agent_id"] == b["id"], "B never assigned (A is also retry-excluded)"
    assert asg2["supersedes_assignment_id"] is None, (
        "Release pooled the lead; the supersedes chain is only for direct reassignment"
    )

    rows = list_assignments({"lead_id": lead["id"]})
    assert len(rows) == 2
    assert sorted(r["status"] for r in rows) == ["OFFERED", "RELEASED"]
    assert get_agent(b["id"])["active_lead_count"] == 1
