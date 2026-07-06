"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server (empty DB) before every test, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient validator) internally so a setup misstep
surfaces as a clear "setup failed" rather than a confusing assertion error.

Identity threading: after creating a Client or VirtualAssistant, every
ownership-gated call uses make_client_headers(client_id) / make_va_headers(va_id)
with the real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_skill_tag_payload, create_sla_policy_payload,
    create_virtual_assistant_payload, create_client_payload, scope_client_payload,
    create_engagement_payload, activate_engagement_payload, create_addon_payload,
    create_task_payload, create_time_entry_payload, create_escalation_payload,
    close_cycle_payload, unique_email,
)
from .test_users import (
    TEST_USERS, make_staffing_manager_headers, make_client_headers, make_va_headers,
)

SM = TEST_USERS["staffing_manager_headers"]


# ─── Primitives ─────────────────────────────────────────────────────────────
def set_clock(iso=CLOCK_DEFAULT):
    """Set the logical clock; defaults to the platform startup value."""
    return get_success_data(api_client.set_clock(iso, SM))


def create_skill_tag(code, name=None, is_specialized=False):
    res = api_client.create_skill_tag(
        create_skill_tag_payload(code=code, name=name or code.title(),
                                 is_specialized=is_specialized), SM)
    return get_success_data(res)


def create_sla_policy(tier="STANDARD", response_minutes=60, resolution_hours=24,
                      breach_penalty_pct=0.0):
    res = api_client.create_sla_policy(
        create_sla_policy_payload(tier=tier, response_minutes=response_minutes,
                                  resolution_hours=resolution_hours,
                                  breach_penalty_pct=breach_penalty_pct), SM)
    return get_success_data(res)


def create_va(skill_tag_ids, email=None, full_name="Test VA",
              weekly_capacity_hours=40, rating=4.0):
    res = api_client.create_virtual_assistant(
        create_virtual_assistant_payload(
            full_name=full_name, email=email or unique_email("va"),
            skill_tag_ids=skill_tag_ids, weekly_capacity_hours=weekly_capacity_hours,
            rating=rating), SM)
    return get_success_data(res)


def create_client(company_name="Test Co", contact_email=None):
    res = api_client.create_client(
        create_client_payload(company_name=company_name,
                              contact_email=contact_email or unique_email("client")), SM)
    return get_success_data(res)


def scope_client(client_id, required_skill_tag_ids, monthly_retainer_hours=10,
                 base_rate_cents=5000, overage_rate_cents=8000, rollover_cap_hours=0):
    res = api_client.scope_client(
        client_id,
        scope_client_payload(required_skill_tag_ids=required_skill_tag_ids,
                             monthly_retainer_hours=monthly_retainer_hours,
                             base_rate_cents=base_rate_cents,
                             overage_rate_cents=overage_rate_cents,
                             rollover_cap_hours=rollover_cap_hours),
        make_client_headers(client_id))
    return get_success_data(res)


def open_cycle_for_client(client_id):
    """Return the single OPEN RetainerCycle for a client."""
    res = api_client.list_cycles(SM, params={"client_id": client_id, "status": "OPEN"})
    data, _ = _paginated(res)
    assert data, f"expected an OPEN cycle for client {client_id}"
    return data[0]


def _paginated(res):
    body = res.json()
    return body["data"], body.get("meta", {})


# ─── Tier 1/2: Scoped + active client on an ACTIVE engagement ───────────────
def setup_active_client_engagement(
        skill_code="GENERAL", is_specialized=False, with_sla=True,
        monthly_retainer_hours=10, base_rate_cents=5000, overage_rate_cents=8000,
        rollover_cap_hours=0, breach_penalty_pct=0.0, set_clock_first=True):
    """Walk: clock -> skill -> (sla) -> VA -> client -> scope -> engagement
    propose+accept+activate. Activation drives the SCOPED client to ACTIVE,
    which opens RetainerCycle #1.

    Returns a dict with: skill, va, client, engagement, cycle, plus header
    helpers (client_headers, va_headers) bound to the real entity ids.
    """
    if set_clock_first:
        set_clock()
    skill = create_skill_tag(skill_code, is_specialized=is_specialized)
    if with_sla:
        create_sla_policy(breach_penalty_pct=breach_penalty_pct)
    va = create_va([skill["id"]])
    client = create_client()
    scope_client(client["id"], [skill["id"]],
                 monthly_retainer_hours=monthly_retainer_hours,
                 base_rate_cents=base_rate_cents, overage_rate_cents=overage_rate_cents,
                 rollover_cap_hours=rollover_cap_hours)
    eng = get_success_data(api_client.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM))
    get_success_data(api_client.accept_engagement(
        eng["id"], make_client_headers(client["id"])))
    get_success_data(api_client.activate_engagement(
        eng["id"], activate_engagement_payload(True), SM))
    cycle = open_cycle_for_client(client["id"])
    return {
        "skill": skill,
        "va": va,
        "client": client,
        "engagement": eng,
        "cycle": cycle,
        "client_headers": make_client_headers(client["id"]),
        "va_headers": make_va_headers(va["id"]),
        "sm_headers": SM,
    }


# ─── Tier 3: Task lifecycle shortcuts ───────────────────────────────────────
def create_task(client_id, skill_id=None, priority="STANDARD", estimated_hours=1,
                title="Test Task", as_headers=None):
    res = api_client.create_task(
        create_task_payload(client_id, title=title, priority=priority,
                            required_skill_tag_id=skill_id, estimated_hours=estimated_hours),
        as_headers or make_client_headers(client_id))
    return get_success_data(res)


def create_assigned_task(ctx, priority="STANDARD", estimated_hours=1, title="Test Task"):
    """Create a QUEUED task on the active client and assign it. Returns the task."""
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"],
                       priority=priority, estimated_hours=estimated_hours, title=title,
                       as_headers=ctx["client_headers"])
    return get_success_data(api_client.assign_task(task["id"], SM))


def create_in_progress_task(ctx, **task_kwargs):
    """Create, assign, and start a task (ASSIGNED -> IN_PROGRESS). Returns the task."""
    task = create_assigned_task(ctx, **task_kwargs)
    return get_success_data(api_client.start_task(task["id"], ctx["va_headers"]))


def log_time(ctx, task_id, raw_minutes):
    res = api_client.create_time_entry(
        create_time_entry_payload(task_id, raw_minutes=raw_minutes), ctx["va_headers"])
    return get_success_data(res)


def log_and_approve_time(ctx, task_id, raw_minutes):
    entry = log_time(ctx, task_id, raw_minutes)
    return get_success_data(api_client.approve_time_entry(entry["id"], ctx["client_headers"]))


def close_open_cycle(client_id):
    """Close the client's current OPEN cycle using its fresh version."""
    cyc = open_cycle_for_client(client_id)
    res = api_client.close_cycle(cyc["id"], close_cycle_payload(cyc["version"]), SM)
    return get_success_data(res), cyc


# ─── Tier 4: AddOn ──────────────────────────────────────────────────────────
def setup_active_addon(ctx, surcharge_rate_cents=3000):
    """Request and activate a specialized AddOn for ctx's specialized skill on the
    engagement. Must be called against a context built with is_specialized=True
    BEFORE the engagement is activated, or against a still-onboarding engagement.
    Returns the activated AddOn."""
    addon = get_success_data(api_client.create_addon(
        create_addon_payload(ctx["engagement"]["id"], ctx["skill"]["id"],
                            surcharge_rate_cents=surcharge_rate_cents),
        ctx["client_headers"]))
    return get_success_data(api_client.activate_addon(addon["id"], SM))


def setup_active_client_with_active_addon(
        skill_code="SPECIALIZED", surcharge_rate_cents=3000, breach_penalty_pct=0.0,
        monthly_retainer_hours=10, base_rate_cents=5000, overage_rate_cents=8000):
    """Walk to an ACTIVE engagement whose specialized AddOn is already ACTIVE,
    mirroring the PRD ordering: propose -> accept -> (request+activate addon during
    ONBOARDING) -> activate engagement (which opens cycle #1).

    Returns the same ctx dict as setup_active_client_engagement, plus 'addon'.
    """
    set_clock()
    skill = create_skill_tag(skill_code, is_specialized=True)
    create_sla_policy(breach_penalty_pct=breach_penalty_pct)
    va = create_va([skill["id"]])
    client = create_client()
    scope_client(client["id"], [skill["id"]],
                 monthly_retainer_hours=monthly_retainer_hours,
                 base_rate_cents=base_rate_cents, overage_rate_cents=overage_rate_cents)
    eng = get_success_data(api_client.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM))
    get_success_data(api_client.accept_engagement(
        eng["id"], make_client_headers(client["id"])))
    addon = get_success_data(api_client.create_addon(
        create_addon_payload(eng["id"], skill["id"],
                            surcharge_rate_cents=surcharge_rate_cents),
        make_client_headers(client["id"])))
    addon = get_success_data(api_client.activate_addon(addon["id"], SM))
    get_success_data(api_client.activate_engagement(
        eng["id"], activate_engagement_payload(True), SM))
    cycle = open_cycle_for_client(client["id"])
    return {
        "skill": skill,
        "va": va,
        "client": client,
        "engagement": eng,
        "addon": addon,
        "cycle": cycle,
        "client_headers": make_client_headers(client["id"]),
        "va_headers": make_va_headers(va["id"]),
        "sm_headers": SM,
    }


# ─── Tier 5: Escalation ─────────────────────────────────────────────────────
def open_escalation(ctx, reason="QUALITY"):
    res = api_client.create_escalation(
        create_escalation_payload(ctx["client"]["id"], reason=reason), SM)
    return get_success_data(res)
