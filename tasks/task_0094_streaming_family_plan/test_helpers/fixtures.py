"""Composite setup helpers.

These encapsulate the multi-step API sequences that the test suite repeats, so
each test can focus on its trigger + assertions. Every helper builds its
preconditions from scratch using only PRD-declared endpoints (the harness wipes
the database before every test). Setup calls go through get_success_data() so a
broken precondition surfaces as a clear "Setup step failed" rather than a
confusing downstream assertion error.

Identity threading: after creating an Account we use make_owner_headers(acct_id)
for owner-gated calls, and after creating a Profile we use
make_profile_headers(profile_id) for profile-gated calls — never the shared
fallback constants, which intentionally do not equal any real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_admin_headers,
    make_anonymous_headers,
    make_owner_headers,
    make_profile_headers,
)
from . import factories as f


# ---------------------------------------------------------------------------
# Tier 0: clock control + catalog primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, run_sweeps=False):
    """Set/advance the logical clock (PlatformAdmin seam)."""
    resp = api_client.advance_clock(
        f.clock_advance_payload(to_iso8601, run_sweeps), make_admin_headers()
    )
    # /_clock/advance returns 200 with an (empty) data object.
    assert 200 <= resp.status_code < 300, f"clock advance failed: {resp.status_code} {resp.text}"
    return resp


def create_plan(**overrides):
    """Create a plan. Default preset is PREMIUM (ad-free, HD allowed)."""
    resp = api_client.create_subscription_plan(f.create_plan_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_ad_supported_plan(**overrides):
    resp = api_client.create_subscription_plan(f.ad_supported_plan_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_ad_free_plan(**overrides):
    resp = api_client.create_subscription_plan(f.ad_free_plan_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


def create_title(**overrides):
    resp = api_client.create_title(f.create_title_payload(**overrides), make_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: account + child primitives
# ---------------------------------------------------------------------------

def create_account(plan_id, **overrides):
    """Create an ACTIVE account on a plan. Returns the account dict."""
    resp = api_client.create_account(f.create_account_payload(plan_id, **overrides), make_owner_headers("bootstrap"))
    # account creation is not ownership-gated (no account exists yet); the
    # server mints the id, so any well-formed AccountOwner header is accepted.
    return get_success_data(resp)


def create_profile(account_id, **overrides):
    resp = api_client.create_profile(
        f.create_profile_payload(account_id, **overrides), make_owner_headers(account_id)
    )
    return get_success_data(resp)


def create_device(account_id, **overrides):
    resp = api_client.create_device(
        f.create_device_payload(account_id, **overrides), make_owner_headers(account_id)
    )
    return get_success_data(resp)


def set_parental_control(account_id, profile_id, **overrides):
    resp = api_client.set_parental_control(
        profile_id, f.create_parental_control_payload(**overrides), make_owner_headers(account_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: composite scenarios for streaming / downloads
# ---------------------------------------------------------------------------

def setup_account_profile_device(plan_overrides=None, account_overrides=None,
                                 profile_overrides=None, device_overrides=None):
    """Active account on a PREMIUM plan + one ADULT profile + one device.

    Returns dict with plan, account, profile, device. The most common
    streaming/download base scenario.
    """
    plan = create_plan(**(plan_overrides or {}))
    account = create_account(plan["id"], **(account_overrides or {}))
    profile = create_profile(account["id"], **(profile_overrides or {}))
    device = create_device(account["id"], **(device_overrides or {}))
    return {"plan": plan, "account": account, "profile": profile, "device": device}


def start_stream(profile_id, device_id, title_id):
    """Start a stream session as the owning ProfileUser. Returns the session."""
    resp = api_client.create_stream_session(
        f.create_stream_session_payload(profile_id, device_id, title_id),
        make_profile_headers(profile_id),
    )
    return get_success_data(resp)


def stop_stream(profile_id, session_id):
    """Stop a stream session as the owning ProfileUser. Returns the session."""
    resp = api_client.stop_stream_session(session_id, make_profile_headers(profile_id))
    return get_success_data(resp)


def create_download(profile_id, device_id, title_id, quality="SD"):
    resp = api_client.create_download(
        f.create_download_payload(profile_id, device_id, title_id, quality=quality),
        make_profile_headers(profile_id),
    )
    return get_success_data(resp)


def create_ready_download(profile_id, device_id, title_id, quality="SD"):
    """Create a download and complete it to READY. Returns the download dict."""
    dl = create_download(profile_id, device_id, title_id, quality=quality)
    resp = api_client.complete_download(dl["id"], make_profile_headers(profile_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: account lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_suspended_account(plan_overrides=None, account_overrides=None):
    """Create an account and drive it to SUSPENDED. Returns the suspended account dict."""
    plan = create_plan(**(plan_overrides or {}))
    account = create_account(plan["id"], **(account_overrides or {}))
    resp = api_client.suspend_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    suspended = get_success_data(resp)
    return {"plan": plan, "account": suspended}


def create_closed_account(plan_overrides=None, account_overrides=None):
    """Create an account and close it. Returns the closed account dict."""
    plan = create_plan(**(plan_overrides or {}))
    account = create_account(plan["id"], **(account_overrides or {}))
    resp = api_client.close_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    closed = get_success_data(resp)
    return {"plan": plan, "account": closed}


# ---------------------------------------------------------------------------
# Tier 4: billing / proration targeting
# ---------------------------------------------------------------------------

def setup_two_plans_with_midperiod_upgrade(period_open_iso, day1_iso,
                                           ad_fee=500, prem_fee=1000,
                                           initial_credit_cents=100000,
                                           billing_anchor_day=1):
    """Open an account on an AD_SUPPORTED plan at period open, then apply one
    PlanChange to PREMIUM after exactly one whole day.

    Period is 1 day @ ad_fee + 29 days @ prem_fee. Returns dict with both plans,
    the account (post-change), and the plan_change record.
    """
    plan_ad = create_ad_supported_plan(monthly_fee_cents=ad_fee)
    plan_prem = create_plan(monthly_fee_cents=prem_fee)
    set_clock(period_open_iso, run_sweeps=False)
    account = create_account(
        plan_ad["id"], owner_email=f"prorate-{period_open_iso}@x.com",
        billing_anchor_day=billing_anchor_day, initial_credit_cents=initial_credit_cents,
    )
    set_clock(day1_iso, run_sweeps=False)
    resp = api_client.create_plan_change(
        account["id"],
        {"to_plan_id": plan_prem["id"], "expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    plan_change = get_success_data(resp)
    return {
        "plan_ad": plan_ad,
        "plan_prem": plan_prem,
        "account": account,
        "plan_change": plan_change,
    }


def setup_account_for_plan_change(ad_fee=500, prem_fee=1000, initial_credit_cents=50000):
    """An account on an AD_SUPPORTED plan with a known starting version, plus a
    PREMIUM destination plan. Returns (plan_ad, plan_prem, account). Used for
    OCC plan-change tests.
    """
    plan_ad = create_ad_supported_plan(monthly_fee_cents=ad_fee)
    plan_prem = create_plan(monthly_fee_cents=prem_fee)
    account = create_account(
        plan_ad["id"], owner_email="occ@x.com", billing_anchor_day=1,
        initial_credit_cents=initial_credit_cents,
    )
    return plan_ad, plan_prem, account


# ---------------------------------------------------------------------------
# Tier 5: invites
# ---------------------------------------------------------------------------

def create_account_with_pending_invite(invitee_email="invitee@x.com",
                                       initial_credit_cents=10000,
                                       plan_overrides=None, account_overrides=None):
    """Active account + one PENDING invite (seat hold debited). Returns dict with
    plan, account, invite (the invite dict includes token + hold_amount_cents).
    """
    plan = create_plan(**(plan_overrides or {}))
    acct_kwargs = {"initial_credit_cents": initial_credit_cents}
    acct_kwargs.update(account_overrides or {})
    account = create_account(plan["id"], **acct_kwargs)
    resp = api_client.create_invite(
        f.create_invite_payload(account["id"], invitee_email=invitee_email),
        make_owner_headers(account["id"]),
    )
    invite = get_success_data(resp)
    return {"plan": plan, "account": account, "invite": invite}


def accept_invite(invite_id, token):
    resp = api_client.accept_invite(invite_id, {"token": token}, make_anonymous_headers())
    return get_success_data(resp)


def decline_invite(invite_id, token):
    resp = api_client.decline_invite(invite_id, {"token": token}, make_anonymous_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Read-back helpers (owner-scoped)
# ---------------------------------------------------------------------------

def fetch_account(account_id):
    resp = api_client.get_account(account_id, make_owner_headers(account_id))
    return get_success_data(resp)


def fetch_profile(account_id, profile_id):
    resp = api_client.get_profile(profile_id, make_owner_headers(account_id))
    return get_success_data(resp)


def fetch_download(account_id, download_id):
    resp = api_client.get_download(download_id, make_owner_headers(account_id))
    return get_success_data(resp)
