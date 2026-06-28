"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors, not confusing assertion failures.

Identity threading: every entity_backed call uses make_<role>_headers(entity_id)
with the actual persisted id so ownership checks pass.

The test harness resets the database (and the logical clock to its startup
default 2026-05-01T00:00:00Z) before every test, so every fixture builds its
preconditions from scratch.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_practice_payload, create_provider_payload, create_employer_payload,
    register_member_payload, assign_pcp_payload, create_visit_slot_payload,
    create_visit_payload, complete_visit_payload, occupy_seat_payload,
    create_care_plan_payload, create_referral_payload, charge_payload,
    message_thread_payload,
)
from .test_users import (
    make_admin_headers, make_anonymous_headers, make_provider_headers,
    make_member_headers, make_employer_headers,
)

ADMIN = make_admin_headers()
ANON = make_anonymous_headers()


# ─── primitives ──────────────────────────────────────────────────────────

def _uniq_email(prefix="m"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@x.com"


def set_clock(iso: str):
    """Advance the server logical clock to the given ISO instant."""
    get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_practice(**overrides):
    """PlatformAdmin creates a Practice (config root)."""
    return get_success_data(api_client.create_practice(
        create_practice_payload(**overrides), ADMIN))


def create_provider(practice_id, **overrides):
    """PlatformAdmin registers a Provider under a practice."""
    return get_success_data(api_client.create_provider(
        create_provider_payload(practice_id, **overrides), ADMIN))


def create_employer(practice_id, **overrides):
    """PlatformAdmin registers an Employer sponsor under a practice."""
    return get_success_data(api_client.create_employer(
        create_employer_payload(practice_id, **overrides), ADMIN))


def register_member(practice_id, email=None, **overrides):
    """Anonymous self-registers a Member (+ its Membership) in one call."""
    if email is None:
        email = _uniq_email()
    return get_success_data(api_client.register_member(
        register_member_payload(practice_id, email, **overrides), ANON))


def get_membership_for(member_id):
    """Return the member's 1:1 Membership record."""
    data = get_success_data(api_client.list_member_memberships(
        member_id, make_member_headers(member_id)))
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]


def assign_pcp_manual(member_id, provider_id):
    """PlatformAdmin pins a specific PCP onto the member."""
    return get_success_data(api_client.assign_pcp(
        member_id, assign_pcp_payload("MANUAL", provider_id), ADMIN))


def assign_pcp_auto(member_id):
    """PlatformAdmin auto-assigns a PCP via the panel selector."""
    return get_success_data(api_client.assign_pcp(
        member_id, assign_pcp_payload("AUTO"), ADMIN))


def charge_membership(member_id, membership_id, amount_cents, outcome="SUCCEEDED", as_admin=False):
    """Charge the membership fee. Defaults to acting as the owning Member."""
    headers = ADMIN if as_admin else make_member_headers(member_id)
    return get_success_data(api_client.charge_membership(
        membership_id, charge_payload("MEMBERSHIP_FEE", amount_cents, outcome), headers))


def create_slot(provider_id, slot_type, starts_at, ends_at, **overrides):
    """Provider publishes an availability slot. Returns the VisitSlot."""
    return get_success_data(api_client.create_visit_slot(
        provider_id,
        create_visit_slot_payload(slot_type, starts_at, ends_at, **overrides),
        make_provider_headers(provider_id)))


def book_visit(member_id, slot_id, visit_type, expected_slot_version):
    """Member books a visit into a slot. Returns the Visit."""
    return get_success_data(api_client.create_visit(
        create_visit_payload(member_id, slot_id, visit_type, expected_slot_version),
        make_member_headers(member_id)))


# ─── Tier 1/2: member lifecycle setup helpers ────────────────────────────

def setup_practice_and_provider(clock="2026-06-01T00:00:00Z", practice_overrides=None,
                                provider_overrides=None):
    """Practice + one Provider, clock pinned. Returns (practice, provider)."""
    practice = create_practice(**(practice_overrides or {}))
    provider = create_provider(practice["id"], **(provider_overrides or {}))
    if clock is not None:
        set_clock(clock)
    return practice, provider


def setup_active_member(clock="2026-06-01T00:00:00Z", practice_overrides=None,
                        provider_overrides=None, member_overrides=None,
                        practice=None, provider=None):
    """Active member on a fresh provider/practice. The membership-fee charge
    that drives PENDING_PAYMENT->ACTIVE pays exactly member_share_cents.

    Returns dict: practice, provider, member, membership.
    """
    if practice is None or provider is None:
        practice, provider = setup_practice_and_provider(
            clock=clock, practice_overrides=practice_overrides,
            provider_overrides=provider_overrides)
    elif clock is not None:
        set_clock(clock)
    member = register_member(practice["id"], **(member_overrides or {}))
    assign_pcp_manual(member["id"], provider["id"])
    membership = get_membership_for(member["id"])
    charge_membership(member["id"], membership["id"], membership["member_share_cents"], "SUCCEEDED")
    membership = get_membership_for(member["id"])
    member = get_success_data(api_client.get_member(member["id"], ADMIN))
    return {"practice": practice, "provider": provider, "member": member, "membership": membership}


def setup_pending_member_no_pcp(clock="2026-06-01T00:00:00Z", member_overrides=None):
    """Registered member in PENDING_PAYMENT with NO PCP assigned.
    Returns dict: practice, member, membership."""
    practice = create_practice()
    if clock is not None:
        set_clock(clock)
    member = register_member(practice["id"], **(member_overrides or {}))
    membership = get_membership_for(member["id"])
    return {"practice": practice, "member": member, "membership": membership}


# ─── Tier 3: clinical-lifecycle shortcuts ─────────────────────────────────

def book_in_person_visit(ctx, starts_at, ends_at, visit_type="SAME_DAY"):
    """Given an active-member ctx, publish an IN_PERSON slot and book it.
    Returns dict: slot, visit."""
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON", starts_at, ends_at)
    visit = book_visit(ctx["member"]["id"], slot["id"], visit_type, slot["version"])
    return {"slot": slot, "visit": visit}


def setup_completed_visit(service_lines, visit_type="SAME_DAY",
                          starts_at="2026-06-02T09:00:00Z", ends_at="2026-06-02T09:30:00Z",
                          clock="2026-06-01T00:00:00Z", member_overrides=None,
                          practice_overrides=None):
    """Active member with a COMPLETED visit carrying `service_lines`.
    Returns dict: practice, provider, member, membership, slot, visit."""
    ctx = setup_active_member(clock=clock, member_overrides=member_overrides,
                              practice_overrides=practice_overrides)
    booked = book_in_person_visit(ctx, starts_at, ends_at, visit_type)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    get_success_data(api_client.check_in_visit(booked["visit"]["id"], prov_h))
    visit = get_success_data(api_client.complete_visit(
        booked["visit"]["id"], complete_visit_payload(service_lines), prov_h))
    ctx["slot"] = booked["slot"]
    ctx["visit"] = visit
    return ctx


def setup_invoiced_visit(service_lines, visit_type="SAME_DAY",
                         clock="2026-06-01T00:00:00Z", member_overrides=None,
                         practice_overrides=None):
    """Active member with a COMPLETED visit that has been INVOICED (Invoice ISSUED).
    Returns dict: ... plus invoice."""
    ctx = setup_completed_visit(service_lines, visit_type=visit_type, clock=clock,
                                member_overrides=member_overrides,
                                practice_overrides=practice_overrides)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    invoice = get_success_data(api_client.invoice_visit(ctx["visit"]["id"], prov_h))
    ctx["invoice"] = invoice
    return ctx


def setup_completed_annual_physical(goal_count=1, clock="2026-06-01T00:00:00Z"):
    """Active member with a COMPLETED ANNUAL_PHYSICAL visit and a DRAFT CarePlan
    (goal_count default 1). Returns dict: ... plus visit, care_plan."""
    ctx = setup_active_member(clock=clock)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    visit = book_visit(ctx["member"]["id"], slot["id"], "ANNUAL_PHYSICAL", slot["version"])
    get_success_data(api_client.check_in_visit(visit["id"], prov_h))
    visit = get_success_data(api_client.complete_visit(
        visit["id"], complete_visit_payload([]), prov_h))
    care_plan = get_success_data(api_client.create_care_plan(
        create_care_plan_payload(ctx["member"]["id"], visit["id"], goal_count=goal_count),
        prov_h))
    ctx["slot"] = slot
    ctx["visit"] = visit
    ctx["care_plan"] = care_plan
    return ctx


def setup_active_care_plan(clock="2026-06-01T00:00:00Z"):
    """Active member with a CarePlan walked DRAFT->ACTIVE (goal_count=2).
    Returns dict: ... plus visit, care_plan (ACTIVE)."""
    ctx = setup_completed_annual_physical(goal_count=2, clock=clock)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    cp = get_success_data(api_client.activate_care_plan(ctx["care_plan"]["id"], prov_h))
    ctx["care_plan"] = cp
    return ctx


def setup_referral(status="REQUESTED", clock="2026-06-01T00:00:00Z"):
    """Active member with a Referral in the requested `status`
    (REQUESTED / AUTHORIZED / DENIED). Returns dict: ... plus visit, referral."""
    ctx = setup_active_member(clock=clock)
    prov_h = make_provider_headers(ctx["provider"]["id"])
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-02T09:00:00Z", "2026-06-02T09:30:00Z")
    visit = book_visit(ctx["member"]["id"], slot["id"], "SAME_DAY", slot["version"])
    referral = get_success_data(api_client.create_referral(
        create_referral_payload(ctx["member"]["id"], visit["id"], "CARDIOLOGY"), prov_h))
    if status == "AUTHORIZED":
        referral = get_success_data(api_client.authorize_referral(referral["id"], prov_h))
    elif status == "DENIED":
        referral = get_success_data(api_client.deny_referral(referral["id"], prov_h))
    ctx["visit"] = visit
    ctx["referral"] = referral
    return ctx


# ─── Tier 2: employer sponsorship setup helpers ───────────────────────────

def allocate_seat(employer_id):
    """Employer allocates a new OPEN seat. Returns the EmployerSeat."""
    return get_success_data(api_client.create_seat(
        employer_id, {}, make_employer_headers(employer_id)))


def employer_version(employer_id):
    emp = get_success_data(api_client.get_employer(
        employer_id, make_employer_headers(employer_id)))
    return emp["version"]


def occupy_seat(employer_id, seat_id, member_id, expected_employer_version=None):
    """Employer occupies an OPEN seat with a member. Returns the EmployerSeat."""
    if expected_employer_version is None:
        expected_employer_version = employer_version(employer_id)
    return get_success_data(api_client.occupy_seat(
        employer_id, seat_id,
        occupy_seat_payload(member_id, expected_employer_version),
        make_employer_headers(employer_id)))


def setup_sponsored_active_member(sponsorship_pct=1.0, plan_type="MONTHLY",
                                  clock="2026-06-01T00:00:00Z"):
    """Member occupying an employer seat, then activated. The activating charge
    pays exactly member_share_cents (0 when sponsorship_pct=1.0 on MONTHLY).
    Returns dict: practice, provider, employer, member, membership, seat."""
    practice = create_practice()
    provider = create_provider(practice["id"])
    employer = create_employer(practice["id"], sponsorship_pct=sponsorship_pct)
    if clock is not None:
        set_clock(clock)
    member = register_member(practice["id"], plan_type=plan_type)
    assign_pcp_manual(member["id"], provider["id"])
    seat = allocate_seat(employer["id"])
    seat = occupy_seat(employer["id"], seat["id"], member["id"])
    membership = get_membership_for(member["id"])
    charge_membership(member["id"], membership["id"], membership["member_share_cents"], "SUCCEEDED")
    membership = get_membership_for(member["id"])
    member = get_success_data(api_client.get_member(member["id"], ADMIN))
    employer = get_success_data(api_client.get_employer(
        employer["id"], make_employer_headers(employer["id"])))
    return {"practice": practice, "provider": provider, "employer": employer,
            "member": member, "membership": membership, "seat": seat}


# ─── Tier 4: PAST_DUE / period-rollover targeting ─────────────────────────

def drive_member_past_due(ctx, rollover_clock, fail_clock=None):
    """Take an ACTIVE member ctx to PAST_DUE: advance the clock to/past
    current_period_end, then submit a FAILED membership-fee charge at rollover.
    Returns the refreshed member dict."""
    set_clock(rollover_clock)
    membership = get_membership_for(ctx["member"]["id"])
    charge_membership(ctx["member"]["id"], membership["id"],
                      membership["member_share_cents"], "FAILED", as_admin=True)
    if fail_clock is not None:
        set_clock(fail_clock)
    member = get_success_data(api_client.get_member(ctx["member"]["id"], ADMIN))
    ctx["member"] = member
    ctx["membership"] = get_membership_for(ctx["member"]["id"])
    return member
