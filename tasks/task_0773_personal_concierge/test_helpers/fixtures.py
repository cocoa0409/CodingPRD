"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures raise
clear "Setup step failed" errors rather than confusing assertion failures.

Because the server DB is reset before every test, every helper builds its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    unique_email,
    create_member_payload,
    create_retainer_plan_payload,
    create_membership_payload,
    create_vendor_payload,
    create_service_request_payload,
    accept_payload,
    create_engagement_payload,
    create_time_entry_payload,
    create_rating_payload,
    DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
)

AM = TEST_USERS["account_manager_headers"]
AGENT = TEST_USERS["concierge_agent_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


# ─── Tier 1: primitive creation / state progression ───────────────────────
def create_member(full_name="Test Member", email=None):
    """Create a Member (PENDING). Returns the member dict."""
    res = api_client.create_member(
        create_member_payload(full_name=full_name, email=email or unique_email()), AM)
    return get_success_data(res)


def create_active_member(full_name="Test Member", email=None):
    """Create + activate a Member. Returns (member_after_activate, version)."""
    member = create_member(full_name=full_name, email=email)
    activated = get_success_data(api_client.activate_member(member["id"], AM))
    return activated, activated["version"]


def create_plan(plan_kind="STD", **overrides):
    """Create a RetainerPlan. plan_kind selects the STD or GOLD defaults."""
    base = dict(DEFAULTS["GOLD_PLAN"] if plan_kind == "GOLD" else DEFAULTS["STD_PLAN"])
    base.update(overrides)
    return get_success_data(api_client.create_retainer_plan(create_retainer_plan_payload(**base), AM))


def create_vendor(name="Test Vendor", category="BOOKING"):
    """Create an ACTIVE Vendor. Returns the vendor dict."""
    return get_success_data(api_client.create_vendor(create_vendor_payload(name=name, category=category), AM))


# ─── Tier 2: active membership scenario ────────────────────────────────────
def setup_membership(vip_tier="STANDARD", plan_kind="STD", plan_overrides=None):
    """Active member + ACTIVE membership on a fresh plan. Returns a context dict:

    {member, member_id, member_headers, plan, plan_id,
     membership, ms_id, member_version}

    member_headers is make_member_headers(member_id) so member-owned, ownership-gated
    calls (intake, generate, ratings, cancel) pass the ownership check.
    """
    member, version = create_active_member()
    plan = create_plan(plan_kind=plan_kind, **(plan_overrides or {}))
    membership = get_success_data(api_client.create_membership(
        member["id"],
        create_membership_payload(plan["id"], expected_member_version=version, vip_tier=vip_tier),
        AM,
    ))
    return {
        "member": member,
        "member_id": member["id"],
        "member_headers": make_member_headers(member["id"]),
        "plan": plan,
        "plan_id": plan["id"],
        "membership": membership,
        "ms_id": membership["id"],
        "member_version": version,
    }


def get_open_cycle(ms_id):
    """Return the OPEN BillingCycle dict of a membership."""
    cycles = get_success_data(api_client.list_billing_cycles(
        AM, params={"membership_id": ms_id, "status": "OPEN"}))
    assert cycles, f"Setup step failed: no OPEN cycle for membership {ms_id}"
    return cycles[0]


def intake_request(ctx, category="ERRAND", title="Test request", **overrides):
    """Intake a ServiceRequest on ctx's membership as the owning member."""
    payload = create_service_request_payload(ctx["ms_id"], category=category, title=title, **overrides)
    return get_success_data(api_client.create_service_request(payload, ctx["member_headers"]))


# ─── Tier 3: request lifecycle shortcuts ───────────────────────────────────
def accept_request(sr_id, scheduled_start, scheduled_end):
    """Advance a SUBMITTED request to IN_PROGRESS with a service window."""
    return get_success_data(api_client.accept_service_request(
        sr_id, accept_payload(scheduled_start, scheduled_end), AGENT))


def fulfill_request(sr_id):
    """Advance an IN_PROGRESS request to FULFILLED."""
    return get_success_data(api_client.fulfill_service_request(sr_id, AGENT))


def setup_fulfilled_request(ctx, category="ERRAND", title="Test request",
                            scheduled_start="2026-03-02T09:00:00Z",
                            scheduled_end="2026-03-02T10:00:00Z"):
    """Intake → accept → fulfill. Returns the fulfilled request."""
    sr = intake_request(ctx, category=category, title=title)
    accept_request(sr["id"], scheduled_start, scheduled_end)
    return fulfill_request(sr["id"])


def rate_request(ctx, sr_id, score):
    """Create a SatisfactionRating for a fulfilled request as the owning member."""
    return get_success_data(api_client.create_rating(
        sr_id, create_rating_payload(score=score), ctx["member_headers"]))


def fulfill_and_rate(ctx, score,
                     scheduled_start="2026-03-02T09:00:00Z",
                     scheduled_end="2026-03-02T10:00:00Z"):
    """Intake an ERRAND, accept, fulfill, then rate it with `score`. Returns the rating."""
    sr = setup_fulfilled_request(ctx, category="ERRAND", title="rate-me",
                                 scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    return rate_request(ctx, sr["id"], score)


# ─── Tier 4: hour-bank accumulation / time logging ─────────────────────────
def log_time(sr_id, minutes, note=None):
    """Log FINALIZED time against a request's hour-bank. Returns the time entry."""
    payload = create_time_entry_payload(minutes=minutes)
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.create_time_entry(sr_id, payload, AGENT))


def setup_time_logged(vip_tier="GOLD", plan_kind="GOLD", minutes=700, category="ERRAND"):
    """Active membership + OPEN cycle 0 + one request + `minutes` logged.

    Returns {ctx, cycle_id, sr, time_entry}.
    """
    ctx = setup_membership(vip_tier=vip_tier, plan_kind=plan_kind)
    cycle = get_open_cycle(ctx["ms_id"])
    sr = intake_request(ctx, category=category, title="time task")
    te = log_time(sr["id"], minutes)
    return {"ctx": ctx, "cycle_id": cycle["id"], "sr": sr, "time_entry": te}


# ─── Tier 5: vendor engagement lifecycle ───────────────────────────────────
def propose_engagement(sr_id, vendor_id, billing_mode, estimated_cost_lines,
                       service_start, service_end, markup_pct=None):
    """Create a PROPOSED VendorEngagement. Returns the engagement dict."""
    extra = {} if markup_pct is None else {"markup_pct": markup_pct}
    payload = create_engagement_payload(
        vendor_id, billing_mode, estimated_cost_lines, service_start, service_end, **extra)
    return get_success_data(api_client.create_engagement(sr_id, payload, AGENT))


def confirm_engagement(engagement_id):
    """Confirm a PROPOSED engagement (provisional charge). Returns the engagement."""
    return get_success_data(api_client.confirm_engagement(engagement_id, AGENT))


def reconcile_engagement(engagement_id, actual_cost_lines):
    """Reconcile a CONFIRMED engagement with actuals. Returns the engagement."""
    return get_success_data(api_client.reconcile_engagement(
        engagement_id, {"actual_cost_lines": actual_cost_lines}, FINANCE))


def setup_confirmed_engagement(vip_tier="STANDARD", plan_kind="STD",
                               billing_mode="MARKUP", markup_pct=0.10,
                               estimated_cost_lines=(1000,),
                               service_start="2026-03-06T10:00:00Z",
                               service_end="2026-03-06T11:00:00Z"):
    """Active membership + BOOKING request + ACTIVE BOOKING vendor +
    engagement CONFIRMED. Returns {ctx, vendor, sr, engagement}.
    """
    ctx = setup_membership(vip_tier=vip_tier, plan_kind=plan_kind)
    vendor = create_vendor(name="Bk", category="BOOKING")
    sr = intake_request(ctx, category="BOOKING", title="reserve")
    eng = propose_engagement(sr["id"], vendor["id"], billing_mode,
                             list(estimated_cost_lines), service_start, service_end,
                             markup_pct=markup_pct if billing_mode == "MARKUP" else None)
    eng = confirm_engagement(eng["id"])
    return {"ctx": ctx, "vendor": vendor, "sr": sr, "engagement": eng}


def setup_reconciled_expense(vip_tier="STANDARD", plan_kind="STD",
                             estimated_cost_lines=(1000,), actual_cost_lines=(1000,),
                             markup_pct=0.10):
    """Engagement CONFIRMED then RECONCILED, producing a RECONCILED Expense.
    Returns {ctx, vendor, sr, engagement, expense}.
    """
    s = setup_confirmed_engagement(vip_tier=vip_tier, plan_kind=plan_kind,
                                   billing_mode="MARKUP", markup_pct=markup_pct,
                                   estimated_cost_lines=estimated_cost_lines)
    eng = reconcile_engagement(s["engagement"]["id"], list(actual_cost_lines))
    expenses = get_success_data(api_client.list_expenses(
        FINANCE, params={"vendor_engagement_id": eng["id"]}))
    assert expenses, "Setup step failed: no Expense produced by reconcile"
    s["engagement"] = eng
    s["expense"] = expenses[0]
    return s
