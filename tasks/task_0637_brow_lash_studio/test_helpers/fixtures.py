"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures. Every helper builds its
preconditions from scratch — the harness restarts the server (empty DB) before every test.

Identity threading: after creating a LashTech, ownership-gated calls (e.g. completing an
appointment assigned to that tech) use make_lash_tech_headers(tech["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as F
from .test_users import TEST_USERS, make_lash_tech_headers, make_member_headers

SM = TEST_USERS["studio_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─── Clock control ────────────────────────────────────
def set_clock(to_iso8601):
    """Move the server logical clock; returns the response data (current_utc)."""
    return get_success_data(api_client.set_clock(to_iso8601, SM))


# ─── Tier 0: Primitive creators ──────────────────────
def create_studio(**overrides):
    """Create a Studio. Returns the studio object."""
    return get_success_data(api_client.create_studio(F.create_studio_payload(**overrides), SM))


def create_service_type(studio_id, **overrides):
    """Create a ServiceType under a studio. Returns the service type object."""
    return get_success_data(
        api_client.create_service_type(F.create_service_type_payload(studio_id, **overrides), SM))


def create_plan(studio_id, **overrides):
    """Create a MembershipPlan. Returns the plan object."""
    return get_success_data(
        api_client.create_membership_plan(F.create_membership_plan_payload(studio_id, **overrides), SM))


def create_tech(studio_id, **overrides):
    """Create a LashTech. Returns the tech object."""
    return get_success_data(
        api_client.create_lash_tech(F.create_lash_tech_payload(studio_id, **overrides), SM))


def create_member(studio_id, **overrides):
    """Create a Member. Returns the member object."""
    return get_success_data(
        api_client.create_member(F.create_member_payload(studio_id, **overrides), FD))


def create_membership(member_id, plan_id, **overrides):
    """Enroll a member in a plan. Returns the membership object."""
    return get_success_data(
        api_client.create_membership(F.create_membership_payload(member_id, plan_id, **overrides), FD))


def sanitize_tech(tech_id, sanitized_at_utc):
    """Record a COMPLETED SanitationLog for a tech. Returns the log object."""
    return get_success_data(
        api_client.create_sanitation_log(F.create_sanitation_log_payload(tech_id, sanitized_at_utc), SM))


# ─── Tier 1: Sanitized-tech studio scaffolding ───────
def setup_studio_with_sanitized_tech(studio_overrides=None, service_overrides=None,
                                     tech_overrides=None, sanitized_at_utc="2026-06-10T09:00:00Z",
                                     clock=None):
    """Studio + one ServiceType + one sanitized AVAILABLE LashTech + one Member.

    Returns (studio, service_type, tech, member). Sets the clock last if `clock` given.
    """
    studio = create_studio(**(studio_overrides or {}))
    st = create_service_type(studio["id"], **(service_overrides or {}))
    tech = create_tech(studio["id"], **(tech_overrides or {}))
    sanitize_tech(tech["id"], sanitized_at_utc)
    member = create_member(studio["id"])
    if clock is not None:
        set_clock(clock)
    return studio, st, tech, member


# ─── Tier 2: Premium anchor (last_premium_completed_utc) ──
def setup_member_with_premium_anchor(anchor_start_utc="2026-06-01T10:00:00Z",
                                     studio_overrides=None,
                                     full_set_overrides=None,
                                     sanitized_at_utc="2026-06-01T09:00:00Z",
                                     post_complete_clock=None):
    """Create a studio/member, book + COMPLETE a PREMIUM FULL_SET so the member's
    last_premium_completed_utc anchors to `anchor_start_utc`.

    Returns (studio, full_st, tech, member). Leaves the clock just past the anchor's
    completion (or at `post_complete_clock` if given).
    """
    studio = create_studio(**(studio_overrides or {}))
    fso = {"code": "FULL_SET", "name": "Full Set", "duration_minutes": 120,
           "base_price_cents": 12000, "credit_cost": 4, "category": "PREMIUM",
           "requires_patch_test": False}
    fso.update(full_set_overrides or {})
    full_st = create_service_type(studio["id"], **fso)
    tech = create_tech(studio["id"], skill_level=3, station_number=1)
    sanitize_tech(tech["id"], sanitized_at_utc)
    member = create_member(studio["id"])
    # Clock to just before the anchor start so the booking is in the future, then book.
    set_clock("2026-06-01T09:00:00Z")
    appt = get_success_data(api_client.create_appointment(
        F.create_appointment_payload(member["id"], full_st["id"], anchor_start_utc,
                                     pay_with_credits=False), FD))
    # Advance clock past start and complete (assigned tech completes it).
    set_clock("2026-06-01T12:30:00Z")
    tech_id = appt["lash_tech_id"]
    get_success_data(api_client.complete_appointment(appt["id"], make_lash_tech_headers(tech_id)))
    if post_complete_clock is not None:
        set_clock(post_complete_clock)
    return studio, full_st, tech, member


# ─── Tier 3: Suspension via three in-window no-shows ──
def setup_suspended_membership(noshow_threshold=3, advance_clock_for_third=True):
    """Drive a membership to SUSPENDED via three in-window NO_SHOW strikes.

    Builds: studio (threshold=3, window=90) + ESSENTIAL plan + STANDARD TINT (no patch
    test) + sanitized tech + member + ACTIVE membership. Books three cash TINT
    appointments and marks each NO_SHOW. The third strike auto-suspends the membership.

    Returns (studio, plan, tint_st, tech, member, membership). Clock left at
    2026-06-10T09:00:00Z (strikes still within the 90-day window).
    """
    studio = create_studio(noshow_strike_threshold=noshow_threshold, noshow_strike_window_days=90)
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    tint_st = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                                  base_price_cents=4000, credit_cost=2, category="STANDARD",
                                  requires_patch_test=False)
    tech = create_tech(studio["id"], skill_level=1, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T00:00:00Z")
    member = create_member(studio["id"])
    membership = create_membership(member["id"], plan["id"])
    set_clock("2026-06-10T09:00:00Z")
    starts = ["2026-06-10T07:00:00Z", "2026-06-10T07:30:00Z", "2026-06-10T08:00:00Z"]
    for s in starts:
        appt = get_success_data(api_client.create_appointment(
            F.create_appointment_payload(member["id"], tint_st["id"], s, pay_with_credits=False), FD))
        get_success_data(api_client.mark_no_show(appt["id"], FD))
    return studio, plan, tint_st, tech, member, membership


# ─── Tier 4: Member with ACTIVE membership and credit balance ──
def setup_member_with_active_membership(initial_credits=8, plan_overrides=None,
                                        studio_overrides=None):
    """Studio + PREMIER plan + member + ACTIVE membership with a known initial credit balance.

    Returns (studio, plan, member, membership).
    """
    studio = create_studio(**(studio_overrides or {}))
    po = {"tier": "PREMIER", "monthly_credit_allotment": 8, "monthly_fee_cents": 9900}
    po.update(plan_overrides or {})
    plan = create_plan(studio["id"], **po)
    member = create_member(studio["id"])
    membership = create_membership(member["id"], plan["id"], initial_credits=initial_credits)
    return studio, plan, member, membership


def credit_ledger(membership_id):
    """Return the membership's CreditLedgerEntry list in creation order."""
    resp = api_client.list_credit_ledger(membership_id, SM)
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)


def get_membership(membership_id):
    return get_success_data(api_client.get_membership(membership_id, SM))


def get_appointment(appointment_id):
    return get_success_data(api_client.get_appointment(appointment_id, SM))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, SM))
