"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through the public API
(each test runs against a fresh server/database) and validates setup calls
with get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: entity-backed roles always use make_*_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import BIG_BUDGET_CENTS, DEFAULT_EXPECTED_CLOSE_PRICE_CENTS
from .factories import (
    agent_payload,
    deal_payload,
    engagement_event_payload,
    import_stats_payload,
    lead_payload,
    lead_source_payload,
    nurture_campaign_payload,
    nurture_enrollment_payload,
    referral_partner_payload,
    routing_policy_payload,
    split_agreement_payload,
    team_payload,
    time_off_payload,
)
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_referral_partner_headers,
    make_team_leader_headers,
)

ADMIN = TEST_USERS["team_admin_headers"]


# ─── Primitive steps (validated) ─────────────────────────────────────────────


def create_team(**overrides):
    """Create a team. Returns the team resource (version starts at 1)."""
    return get_success_data(api_client.create_team(team_payload(**overrides), ADMIN))


def get_team(team_id):
    return get_success_data(api_client.get_team(team_id, ADMIN))


def create_draft_policy(team_id, mode="ROUND_ROBIN", **overrides):
    return get_success_data(
        api_client.create_routing_policy(routing_policy_payload(team_id, mode, **overrides), ADMIN)
    )


def activate_policy(policy_id, expected_team_version):
    return get_success_data(
        api_client.activate_routing_policy(
            policy_id, {"expected_team_version": expected_team_version}, ADMIN
        )
    )


def create_active_policy(team, mode="ROUND_ROBIN", **overrides):
    """Create a DRAFT policy and activate it under OCC with the team's current version."""
    policy = create_draft_policy(team["id"], mode, **overrides)
    return activate_policy(policy["id"], team["version"])


def create_lead_source(team_id, **overrides):
    return get_success_data(
        api_client.create_lead_source(lead_source_payload(team_id, **overrides), ADMIN)
    )


def create_agent(
    team_id,
    license_number,
    display_name="Agent",
    max_active_leads=5,
    role_on_team=None,
    activate=True,
    import_stats=None,
):
    """Create an agent; optionally backfill production stats (PRD §3.1 allows
    the import on an onboarding agent, so it runs before activation), then
    optionally activate. Returns the latest agent representation."""
    payload = agent_payload(
        team_id,
        license_number,
        display_name=display_name,
        max_active_leads=max_active_leads,
    )
    if role_on_team is not None:
        payload["role_on_team"] = role_on_team
    agent = get_success_data(api_client.create_agent(payload, ADMIN))
    if import_stats:
        agent = get_success_data(
            api_client.import_production_stats(agent["id"], import_stats_payload(**import_stats), ADMIN)
        )
    if activate:
        agent = get_success_data(api_client.activate_agent(agent["id"], ADMIN))
    return agent


def create_leader_agent(team_id, display_name="Leader L", license_number="LIC-L"):
    """An ONBOARDING agent with role_on_team LEADER — identity backing for the
    TeamLeader request role (PRD §2.1 requires the LEADER role_on_team only)."""
    return create_agent(
        team_id,
        license_number,
        display_name=display_name,
        max_active_leads=5,
        role_on_team="LEADER",
        activate=False,
    )


def leader_headers(leader):
    return make_team_leader_headers(leader["id"])


def create_partner(team_id, name="Pat", fee_bps=2500):
    return get_success_data(
        api_client.create_referral_partner(
            referral_partner_payload(team_id, name=name, fee_bps=fee_bps), ADMIN
        )
    )


def intake_lead(team_id, source_id, phone, headers=None, **overrides):
    """Successful lead intake (201). Defaults to a TeamAdmin caller."""
    return get_success_data(
        api_client.create_lead(
            lead_payload(team_id, source_id, phone, **overrides), headers or ADMIN
        )
    )


def get_lead(lead_id):
    return get_success_data(api_client.get_lead(lead_id, ADMIN))


def get_agent(agent_id):
    return get_success_data(api_client.get_agent(agent_id, ADMIN))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN))


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_nurture_enrollment(enrollment_id, ADMIN))


def get_deal(deal_id):
    return get_success_data(api_client.get_deal(deal_id, ADMIN))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_split_agreement(agreement_id, ADMIN))


def list_assignments(params=None):
    data, _meta = validate_paginated(api_client.list_assignments(ADMIN, params=params))
    return data


def manual_route(lead_id, headers=None):
    """Manual route of a pooled NEW lead (201 Assignment)."""
    return get_success_data(api_client.route_lead(lead_id, headers or ADMIN))


def claim_as(lead_id, agent_id):
    """The offered agent claims the lead (200 Lead)."""
    return get_success_data(api_client.claim_lead(lead_id, make_agent_headers(agent_id)))


def log_response_as(lead_id, agent_id):
    """The assigned agent logs the first response (200 Lead -> WORKING)."""
    return get_success_data(api_client.log_response(lead_id, make_agent_headers(agent_id)))


def work_lead(lead_id, agent_id):
    """Claim then log the first response; returns the WORKING lead."""
    claim_as(lead_id, agent_id)
    return log_response_as(lead_id, agent_id)


def create_deal_as_agent(lead_id, agent_id, gross_commission_cents):
    return get_success_data(
        api_client.create_deal(
            deal_payload(lead_id, gross_commission_cents), make_agent_headers(agent_id)
        )
    )


def approve_deal_as_leader(deal_id, leader_id, payload=None):
    return get_success_data(
        api_client.approve_deal(deal_id, payload or {}, make_team_leader_headers(leader_id))
    )


def create_campaign(team_id, activate=True, **overrides):
    campaign = get_success_data(
        api_client.create_nurture_campaign(nurture_campaign_payload(team_id, **overrides), ADMIN)
    )
    if activate:
        campaign = get_success_data(api_client.activate_nurture_campaign(campaign["id"], ADMIN))
    return campaign


def enroll_as_leader(campaign_id, lead_id, leader_id):
    return get_success_data(
        api_client.create_nurture_enrollment(
            nurture_enrollment_payload(campaign_id, lead_id), make_team_leader_headers(leader_id)
        )
    )


def create_split_agreement(team_id, agent_a_id, agent_b_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_split_agreement(
            split_agreement_payload(team_id, agent_a_id, agent_b_id, **overrides),
            headers or ADMIN,
        )
    )


def create_time_off(agent_id, starts_at, ends_at, reason="time off", headers=None):
    return get_success_data(
        api_client.create_time_off(
            agent_id, time_off_payload(starts_at, ends_at, reason), headers or ADMIN
        )
    )


def post_event(lead_id, event_type, occurred_at, headers=None):
    return get_success_data(
        api_client.create_engagement_event(
            lead_id, engagement_event_payload(event_type, occurred_at), headers or ADMIN
        )
    )


def set_clock(to_iso8601):
    """Advance the logical clock and run the sweep (200 with sweep counters)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 2/3: composite scenarios ───────────────────────────────────────────


def ctx_routing(
    mode="ROUND_ROBIN",
    source_type="PORTAL",
    auto_route=True,
    cost_per_lead_cents=0,
    monthly_budget_cents=BIG_BUDGET_CENTS,
    agents=({"display_name": "Agent C", "license_number": "LIC-C", "max_active_leads": 5},),
    with_leader=False,
    policy_overrides=None,
    source_overrides=None,
):
    """Team + ACTIVE policy + lead source + activated agents (+ optional leader).

    Returns a context dict: team, policy, source, agents (list), leader (or None).
    """
    team = create_team()
    policy = create_active_policy(team, mode, **(policy_overrides or {}))
    source_kwargs = {
        "type": source_type,
        "cost_per_lead_cents": cost_per_lead_cents,
        "monthly_budget_cents": monthly_budget_cents,
        "auto_route": auto_route,
    }
    source_kwargs.update(source_overrides or {})
    source = create_lead_source(team["id"], **source_kwargs)
    created = []
    for spec in agents:
        created.append(
            create_agent(
                team["id"],
                spec["license_number"],
                display_name=spec.get("display_name", "Agent"),
                max_active_leads=spec.get("max_active_leads", 5),
                role_on_team=spec.get("role_on_team"),
                activate=spec.get("activate", True),
                import_stats=spec.get("import_stats"),
            )
        )
    leader = create_leader_agent(team["id"]) if with_leader else None
    return {
        "team": team,
        "policy": policy,
        "source": source,
        "agents": created,
        "leader": leader,
    }


def ctx_working_lead(
    source_type="PORTAL",
    auto_route=True,
    with_leader=True,
    partner=None,
    phone="+15125550001",
    agent_spec=None,
    lead_overrides=None,
):
    """Single-agent scenario with one lead driven to WORKING.

    Returns ctx with team, policy, source, agent (agents[0]), leader, lead.
    """
    spec = agent_spec or {"display_name": "Closer C", "license_number": "LIC-C", "max_active_leads": 10}
    ctx = ctx_routing(
        source_type=source_type,
        auto_route=auto_route,
        agents=(spec,),
        with_leader=with_leader,
    )
    agent = ctx["agents"][0]
    intake_kwargs = dict(lead_overrides or {})
    if partner is not None:
        intake_kwargs["referral_partner_id"] = partner["id"]
    lead = intake_lead(ctx["team"]["id"], ctx["source"]["id"], phone, **intake_kwargs)
    if lead["status"] == "NEW":
        manual_route(lead["id"])
    work_lead(lead["id"], agent["id"])
    ctx["lead"] = get_lead(lead["id"])
    return ctx


def ctx_pending_deal(
    gross_commission_cents,
    with_partner=False,
    partner_fee_bps=2500,
    split=None,
    phone="+15125550001",
):
    """Full chain to a PENDING deal: team + ACTIVE ROUND_ROBIN policy + source
    + ACTIVE closer C + ONBOARDING leader L (+ optional referral partner and
    split agreement) + lead WORKING + deal created by the closer.

    `split` may be {"agent_b": spec, "a_share_bps": int, "b_share_bps": int,
    "effective_from": iso, "effective_until": iso|None}.
    """
    partner = None
    source_type = "PORTAL"
    ctx_team = create_team()
    policy = create_active_policy(ctx_team, "ROUND_ROBIN")
    if with_partner:
        partner = create_partner(ctx_team["id"], fee_bps=partner_fee_bps)
        source_type = "REFERRAL_PARTNER"
    source = create_lead_source(ctx_team["id"], type=source_type)
    closer = create_agent(ctx_team["id"], "LIC-C", display_name="Closer C", max_active_leads=10)
    leader = create_leader_agent(ctx_team["id"])
    agreement = None
    if split is not None:
        agent_b = create_agent(
            ctx_team["id"],
            split["agent_b"].get("license_number", "LIC-B2"),
            display_name=split["agent_b"].get("display_name", "Partner B2"),
            max_active_leads=split["agent_b"].get("max_active_leads", 10),
        )
        split_kwargs = {
            "a_share_bps": split["a_share_bps"],
            "b_share_bps": split["b_share_bps"],
            "effective_from": split.get("effective_from", "2026-08-01T00:00:00Z"),
        }
        if split.get("effective_until") is not None:
            split_kwargs["effective_until"] = split["effective_until"]
        agreement = create_split_agreement(ctx_team["id"], closer["id"], agent_b["id"], **split_kwargs)
    else:
        agent_b = None
    intake_kwargs = {}
    if partner is not None:
        intake_kwargs["referral_partner_id"] = partner["id"]
    lead = intake_lead(ctx_team["id"], source["id"], phone, **intake_kwargs)
    if lead["status"] == "NEW":
        manual_route(lead["id"])
    work_lead(lead["id"], closer["id"])
    deal = create_deal_as_agent(lead["id"], closer["id"], gross_commission_cents)
    return {
        "team": ctx_team,
        "policy": policy,
        "source": source,
        "partner": partner,
        "closer": closer,
        "leader": leader,
        "agent_b": agent_b,
        "agreement": agreement,
        "lead": get_lead(lead["id"]),
        "deal": deal,
    }


def ctx_claimed_lead_with_campaign(
    campaign_target="COLD",
    campaign_activate=True,
    campaign_steps=None,
    phone="+15125550001",
):
    """Team + ACTIVE policy + auto-route source + ACTIVE agent C + ONBOARDING
    leader L + nurture campaign + one lead CLAIMED by C. The lead is COLD at
    this point (no engagement events)."""
    ctx = ctx_routing(source_type="PORTAL", auto_route=True, with_leader=True)
    agent = ctx["agents"][0]
    campaign_kwargs = {"temperature_target": campaign_target}
    if campaign_steps is not None:
        campaign_kwargs["steps"] = campaign_steps
    campaign = create_campaign(ctx["team"]["id"], activate=campaign_activate, **campaign_kwargs)
    lead = intake_lead(ctx["team"]["id"], ctx["source"]["id"], phone)
    claim_as(lead["id"], agent["id"])
    ctx.update(
        {
            "agent": agent,
            "campaign": campaign,
            "lead": get_lead(lead["id"]),
        }
    )
    return ctx
