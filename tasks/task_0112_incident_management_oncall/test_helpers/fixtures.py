"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a freshly restarted server (empty database), so every
fixture builds its preconditions from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient validator) internally so setup failures
surface as clear "Setup step failed" errors rather than confusing assertions.

Identity threading: ResponderUser is entity_backed:Responder. Any ownership-gated
call (acknowledge, resolve-by-responder, action-item start/complete) uses
make_responder_headers(responder["id"]), never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_service_payload,
    create_responder_payload,
    create_on_call_schedule_payload,
    create_schedule_shift_payload,
    create_escalation_policy_payload,
    create_escalation_tier_payload,
    create_maintenance_window_payload,
    create_incident_payload,
    create_postmortem_payload,
    create_action_item_payload,
)
from .test_users import TEST_USERS, make_responder_headers

ADMIN = TEST_USERS["platform_admin_headers"]
COMMANDER = TEST_USERS["incident_commander_headers"]

# A wide shift interval covering essentially any test clock used below.
WIDE_SHIFT_START = "2026-05-01T00:00:00Z"
WIDE_SHIFT_END = "2026-07-01T00:00:00Z"
DEFAULT_CLOCK = "2026-06-01T12:00:00Z"


# ─── Tier 0: Clock ─────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the server logical clock. Returns the echoed payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: Single-entity creation shortcuts ──────────────────────
def create_service(tier="TIER_2", error_budget_minutes=1000, name="S", **overrides):
    """Create a service. Returns the created Service."""
    res = api_client.create_service(
        create_service_payload(name=name, tier=tier, error_budget_minutes=error_budget_minutes, **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_responder(**overrides):
    """Create a responder. Returns the created Responder."""
    res = api_client.create_responder(create_responder_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_schedule(service_id, name="Sch", **overrides):
    res = api_client.create_on_call_schedule(
        create_on_call_schedule_payload(service_id, name=name, **overrides), ADMIN
    )
    return get_success_data(res)


def create_shift(schedule_id, responder_id, starts_at=WIDE_SHIFT_START, ends_at=WIDE_SHIFT_END, **overrides):
    res = api_client.create_schedule_shift(
        create_schedule_shift_payload(schedule_id, responder_id, starts_at, ends_at, **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_policy(service_id, name="P", **overrides):
    res = api_client.create_escalation_policy(
        create_escalation_policy_payload(service_id, name=name, **overrides), ADMIN
    )
    return get_success_data(res)


def create_tier(policy_id, schedule_id, tier_level, delay_minutes=0, **overrides):
    res = api_client.create_escalation_tier(
        create_escalation_tier_payload(policy_id, schedule_id, tier_level, delay_minutes, **overrides),
        ADMIN,
    )
    return get_success_data(res)


# ─── Tier 2: On-call foundation (service + responder + schedule + shift + policy + tier) ──
def setup_pageable_service(
    tier="TIER_2",
    error_budget_minutes=1000,
    shift_starts_at=WIDE_SHIFT_START,
    shift_ends_at=WIDE_SHIFT_END,
    responder_overrides=None,
):
    """Build a complete on-call topology where a tier-1 page can fire:
    service + responder + schedule + one covering shift + policy + tier-1.

    Returns dict with keys: service, responder, schedule, shift, policy, tier.
    The shift defaults to a wide interval covering the standard test clock.
    """
    service = create_service(tier=tier, error_budget_minutes=error_budget_minutes)
    responder = create_responder(**(responder_overrides or {}))
    schedule = create_schedule(service["id"])
    shift = create_shift(schedule["id"], responder["id"], shift_starts_at, shift_ends_at)
    policy = create_policy(service["id"])
    tier_obj = create_tier(policy["id"], schedule["id"], tier_level=1, delay_minutes=0)
    return {
        "service": service,
        "responder": responder,
        "schedule": schedule,
        "shift": shift,
        "policy": policy,
        "tier": tier_obj,
    }


# ─── Tier 3: Incident lifecycle shortcuts ──────────────────────────
def trigger_incident(service_id, policy_id, severity="SEV2", **overrides):
    """Trigger an incident (auto first page). Returns the created Incident."""
    res = api_client.create_incident(
        create_incident_payload(service_id, policy_id, severity=severity, **overrides),
        COMMANDER,
    )
    return get_success_data(res)


def setup_triggered_incident(tier="TIER_2", error_budget_minutes=1000, severity="SEV2"):
    """Foundation + one TRIGGERED incident with tier-1 paged.

    Returns (env, incident) where env is the dict from setup_pageable_service.
    """
    env = setup_pageable_service(tier=tier, error_budget_minutes=error_budget_minutes)
    incident = trigger_incident(env["service"]["id"], env["policy"]["id"], severity=severity)
    return env, incident


def acknowledge(incident_id, responder_id):
    """Acknowledge an incident as the paged responder. Returns the Incident."""
    res = api_client.acknowledge_incident(incident_id, make_responder_headers(responder_id))
    return get_success_data(res)


def resolve(incident_id, responder_id):
    """Resolve an acknowledged incident as the responder. Returns the Incident."""
    res = api_client.resolve_incident(incident_id, make_responder_headers(responder_id))
    return get_success_data(res)


def setup_acknowledged_incident(tier="TIER_2", error_budget_minutes=1000, severity="SEV2"):
    """Foundation + incident triggered then ACKNOWLEDGED by its paged responder.

    Returns (env, incident_after_ack).
    """
    env, incident = setup_triggered_incident(tier, error_budget_minutes, severity)
    incident = acknowledge(incident["id"], env["responder"]["id"])
    return env, incident


def setup_resolved_incident(
    tier="TIER_2",
    error_budget_minutes=1000,
    severity="SEV2",
    open_clock=None,
    resolve_clock=None,
):
    """Foundation + incident triggered, acknowledged, then RESOLVED.

    If open_clock is given, the clock is set there before trigger; if resolve_clock
    is given, the clock is advanced there before resolve (to control downtime).
    Returns (env, incident_after_resolve).
    """
    if open_clock:
        set_clock(open_clock)
    env, incident = setup_triggered_incident(tier, error_budget_minutes, severity)
    incident = acknowledge(incident["id"], env["responder"]["id"])
    if resolve_clock:
        set_clock(resolve_clock)
    incident = resolve(incident["id"], env["responder"]["id"])
    return env, incident


# ─── Tier 4: Postmortem / action-item shortcuts ────────────────────
def create_postmortem(incident_id, summary="rca"):
    res = api_client.create_postmortem(create_postmortem_payload(incident_id, summary), COMMANDER)
    return get_success_data(res)


def create_action_item(postmortem_id, owner_responder_id, description="fix"):
    res = api_client.create_action_item(
        create_action_item_payload(postmortem_id, owner_responder_id, description), COMMANDER
    )
    return get_success_data(res)


def setup_draft_postmortem(severity="SEV2"):
    """Resolved incident + a DRAFT postmortem.

    Returns (env, incident, postmortem).
    """
    env, incident = setup_resolved_incident(severity=severity)
    pm = create_postmortem(incident["id"])
    return env, incident, pm


def setup_in_review_postmortem(severity="SEV2"):
    """Resolved incident + a postmortem submitted to IN_REVIEW (no action items).

    Returns (env, incident, postmortem_in_review).
    """
    env, incident, pm = setup_draft_postmortem(severity=severity)
    pm = get_success_data(api_client.submit_postmortem(pm["id"], COMMANDER))
    return env, incident, pm


def setup_postmortem_with_action_item(severity="SEV2"):
    """DRAFT postmortem with one OPEN action item owned by env['responder'].

    Returns (env, incident, postmortem, action_item).
    """
    env, incident, pm = setup_draft_postmortem(severity=severity)
    ai = create_action_item(pm["id"], env["responder"]["id"])
    return env, incident, pm, ai


# ─── Tier 5: Maintenance window shortcuts ──────────────────────────
def create_window(service_id, starts_at, ends_at, **overrides):
    res = api_client.create_maintenance_window(
        create_maintenance_window_payload(service_id, starts_at, ends_at, **overrides), ADMIN
    )
    return get_success_data(res)


def setup_active_window_service(clock="2026-06-01T12:00:00Z"):
    """Service with an ACTIVE maintenance window covering `clock`, plus a policy.

    Returns dict: service, policy, window (ACTIVE).
    """
    set_clock(clock)
    service = create_service()
    policy = create_policy(service["id"])
    window = create_window(service["id"], "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z", reason="deploy")
    window = get_success_data(api_client.activate_maintenance_window(window["id"], ADMIN))
    return {"service": service, "policy": policy, "window": window}


# ─── Tier 6: Multi-tier escalation foundation (for OCC tests) ──────
def setup_multi_tier_incident(num_tiers=2, repeat_rounds=0, clock="2026-06-01T12:00:00Z"):
    """Service + N schedules/responders/shifts + policy with N tiers + triggered incident.

    Each tier i (1-based) pages schedule i covered by responder i. Returns
    (env, incident) where env contains 'service', 'policy', 'responders' (list),
    'schedules' (list).
    """
    set_clock(clock)
    service = create_service()
    responders = []
    schedules = []
    policy = create_policy(service["id"], repeat_rounds=repeat_rounds)
    for level in range(1, num_tiers + 1):
        r = create_responder()
        sch = create_schedule(service["id"], name=f"Sch{level}")
        create_shift(sch["id"], r["id"], WIDE_SHIFT_START, WIDE_SHIFT_END)
        create_tier(policy["id"], sch["id"], tier_level=level, delay_minutes=(0 if level == 1 else 5))
        responders.append(r)
        schedules.append(sch)
    incident = trigger_incident(service["id"], policy["id"], severity="SEV2")
    env = {"service": service, "policy": policy, "responders": responders, "schedules": schedules}
    return env, incident
