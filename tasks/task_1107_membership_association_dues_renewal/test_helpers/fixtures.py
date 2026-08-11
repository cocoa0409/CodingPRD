"""Composite setup helpers.

Each helper builds a precondition end-to-end via API calls and returns the
entity dicts the tests need. All helpers use `get_success_data` so setup
failures produce clear "Setup failed" AssertionErrors rather than confusing
assertion noise downstream.

Identity threading: any ownership-gated call uses
`make_member_headers(member["id"])` (Member is entity_backed).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_membership_category_payload,
    create_chapter_payload,
    create_renewal_cycle_policy_payload,
    create_dues_schedule_payload,
    create_member_payload,
    create_payment_payload,
    create_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
)

DUES_ADMIN = TEST_USERS["dues_admin_headers"]
MEMBERSHIP_ADMIN = TEST_USERS["membership_admin_headers"]


# ---------- Tier 1: reference data ----------

def create_category(**overrides):
    """Create a MembershipCategory. Returns category dict."""
    resp = api_client.create_membership_category(
        create_membership_category_payload(**overrides), DUES_ADMIN
    )
    return get_success_data(resp)


def create_chapter(**overrides):
    """Create a Chapter. Returns chapter dict."""
    resp = api_client.create_chapter(create_chapter_payload(**overrides), DUES_ADMIN)
    return get_success_data(resp)


def create_cycle_policy(**overrides):
    """Create a RenewalCyclePolicy. Returns policy dict."""
    resp = api_client.create_renewal_cycle_policy(
        create_renewal_cycle_policy_payload(**overrides), DUES_ADMIN
    )
    return get_success_data(resp)


def create_published_schedule(category_id, **overrides):
    """Create a DuesSchedule in DRAFT and publish it. Returns published schedule."""
    resp = api_client.create_dues_schedule(
        create_dues_schedule_payload(category_id=category_id, **overrides), DUES_ADMIN
    )
    schedule = get_success_data(resp)
    resp = api_client.publish_dues_schedule(schedule["id"], DUES_ADMIN)
    return get_success_data(resp)


def create_draft_schedule(category_id, **overrides):
    """Create a DuesSchedule in DRAFT (do not publish)."""
    resp = api_client.create_dues_schedule(
        create_dues_schedule_payload(category_id=category_id, **overrides), DUES_ADMIN
    )
    return get_success_data(resp)


# ---------- Tier 2: base scenario (reference data bundle) ----------

def setup_reference_data(category_overrides=None, chapter_overrides=None,
                          policy_overrides=None, schedule_overrides=None):
    """Returns (category, chapter, policy, published_schedule) tuple with
    sensible defaults for a basic ANNIVERSARY/NONE setup."""
    cat = create_category(**(category_overrides or {}))
    ch = create_chapter(**(chapter_overrides or {}))
    pol = create_cycle_policy(**(policy_overrides or {}))
    sched = create_published_schedule(cat["id"], **(schedule_overrides or {}))
    return cat, ch, pol, sched


# ---------- Tier 3: member setup ----------

def create_member(category_id, chapter_id, cycle_policy_id,
                  email="member@x.com", full_name="Member",
                  joined_at="2026-05-01T00:00:00Z", **extra):
    """Register a member. Returns the Member dict."""
    payload = create_member_payload(
        email=email,
        full_name=full_name,
        category_id=category_id,
        home_chapter_id=chapter_id,
        cycle_policy_id=cycle_policy_id,
        joined_at=joined_at,
        **extra,
    )
    resp = api_client.create_member(payload, make_member_headers("registrar"))
    return get_success_data(resp)


def get_initial_invoice(member_id, member_headers):
    """List the member's dues invoices and return the first (initial) one."""
    resp = api_client.list_member_dues_invoices(member_id, member_headers)
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1, (
        f"Setup failed: member {member_id} has no initial invoice; got {data}"
    )
    return data[0]


def settle_invoice(invoice_id, member_headers, token="tok_v"):
    """Settle an invoice via a SUCCEEDED payment."""
    resp = api_client.submit_payment(
        invoice_id, create_payment_payload(payment_method_token=token,
                                           simulated_outcome="SUCCEEDED"),
        member_headers,
    )
    return get_success_data(resp)


def fail_invoice(invoice_id, member_headers, outcome="DECLINED_TRANSIENT", token="tok_v"):
    """Submit a failing payment attempt."""
    resp = api_client.submit_payment(
        invoice_id, create_payment_payload(payment_method_token=token,
                                           simulated_outcome=outcome),
        member_headers,
    )
    return resp  # may be 201 or 4xx depending on state


def verify_member(member_id):
    """Verify a member (transitions PENDING_VERIFICATION -> ACTIVE). Returns updated Member."""
    resp = api_client.verify_member(member_id, make_member_headers(member_id))
    return get_success_data(resp)


def get_member(member_id, headers=None):
    """Get member via admin (no ownership constraint)."""
    resp = api_client.get_member(member_id, headers or MEMBERSHIP_ADMIN)
    return get_success_data(resp)


def create_active_member(category_id, chapter_id, cycle_policy_id,
                         email="member@x.com", joined_at="2026-05-01T00:00:00Z"):
    """Register a member, settle the initial invoice, verify -> ACTIVE.
    Returns (member, initial_invoice)."""
    member = create_member(category_id, chapter_id, cycle_policy_id,
                           email=email, joined_at=joined_at)
    mh = make_member_headers(member["id"])
    inv = get_initial_invoice(member["id"], mh)
    settle_invoice(inv["id"], mh)
    member = verify_member(member["id"])
    inv = get_success_data(api_client.get_dues_invoice(inv["id"], mh))
    return member, inv


# ---------- Tier 4: scheduler / clock ----------

def set_clock(to_iso8601: str):
    """Advance the logical clock. Triggers the scheduler sweep."""
    resp = api_client.set_current_utc(create_clock_payload(to_iso8601), DUES_ADMIN)
    return resp


def run_renewal_cycle():
    """Fire the scheduler sweep explicitly."""
    resp = api_client.run_renewal_cycle(DUES_ADMIN)
    return resp


def advance_clock_and_run(to_iso8601: str):
    """Advance the clock and fire the renewal cycle sweep."""
    set_clock(to_iso8601)
    return run_renewal_cycle()


# ---------- Tier 5: composite workflows ----------

def setup_active_member_with_schedule(category_overrides=None,
                                       schedule_overrides=None,
                                       policy_overrides=None,
                                       member_email="m@x.com",
                                       joined_at="2026-05-01T00:00:00Z"):
    """Standard fixture: reference data + an ACTIVE member with the initial
    invoice settled. Returns (cat, ch, pol, sched, member, initial_invoice)."""
    cat, ch, pol, sched = setup_reference_data(
        category_overrides=category_overrides,
        policy_overrides=policy_overrides,
        schedule_overrides=schedule_overrides,
    )
    member, inv = create_active_member(
        cat["id"], ch["id"], pol["id"], email=member_email, joined_at=joined_at
    )
    return cat, ch, pol, sched, member, inv


def get_pending_renewal_invoice(member_id):
    """List PENDING dues invoices for the member and return the first one.
    Used after the scheduler issues a renewal invoice."""
    mh = make_member_headers(member_id)
    resp = api_client.list_member_dues_invoices(member_id, mh, params={"payment_status": "PENDING"})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1, (
        f"Setup failed: expected a PENDING renewal invoice for member {member_id}; got {data}"
    )
    return data[0]


def list_benefits(member_id, headers=None):
    resp = api_client.list_benefit_entitlements(member_id, headers or MEMBERSHIP_ADMIN)
    return get_success_data(resp)


def get_directory_listing(member_id, headers=None):
    resp = api_client.get_directory_listing(member_id, headers or MEMBERSHIP_ADMIN)
    return get_success_data(resp)


def get_auto_renew_auth(member_id, headers=None):
    resp = api_client.get_auto_renew(member_id, headers or MEMBERSHIP_ADMIN)
    return get_success_data(resp)
