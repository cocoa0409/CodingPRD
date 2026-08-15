"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All ownership-gated subscriber calls thread the real
account id through make_subscriber_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_NOW_UTC
from .factories import (
    cancel_subscription_payload,
    create_account_payload,
    create_billing_event_payload,
    create_partner_billing_record_payload,
    create_plan_payload,
    create_price_change_notice_payload,
    create_profile_payload,
    create_save_offer_payload,
    create_subscription_payload,
    create_winback_campaign_payload,
    pause_subscription_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]
PARTNER_OPS = TEST_USERS["partner_billing_ops_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 0 — clock control
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_NOW_UTC):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


def run_sweeps(advance_to_iso8601):
    resp = api_client.run_sweeps({"advance_to_iso8601": advance_to_iso8601}, ADMIN)
    return _ok("run_sweeps", resp)


# ---------------------------------------------------------------------------
# Tier 1 — single-entity stand-up
# ---------------------------------------------------------------------------

def create_plan(at=DEFAULT_NOW_UTC, **overrides):
    """Create a plan. Returns the plan dict."""
    set_clock(at)
    resp = api_client.create_plan(create_plan_payload(**overrides), ADMIN)
    return _ok("create_plan", resp)


def create_account(at=DEFAULT_NOW_UTC, **overrides):
    """Create an account. Returns the account dict."""
    set_clock(at)
    resp = api_client.create_account(create_account_payload(**overrides), ADMIN)
    return _ok("create_account", resp)


def create_profile(account_id, **overrides):
    resp = api_client.create_profile(create_profile_payload(account_id, **overrides),
                                     ADMIN)
    return _ok("create_profile", resp)


def create_subscription(account_id, plan_id, as_headers=None, **overrides):
    resp = api_client.create_subscription(
        create_subscription_payload(account_id, plan_id, **overrides),
        as_headers or ADMIN,
    )
    return _ok("create_subscription", resp)


def create_save_offer(subscription_id, as_headers=None, **overrides):
    resp = api_client.create_save_offer(
        create_save_offer_payload(subscription_id, **overrides),
        as_headers or ADMIN,
    )
    return _ok("create_save_offer", resp)


def cancel_subscription(subscription_id, as_headers=None, **overrides):
    resp = api_client.cancel_subscription(
        subscription_id, cancel_subscription_payload(**overrides),
        as_headers or ADMIN,
    )
    return _ok("cancel_subscription", resp)


def pause_subscription(subscription_id, as_headers=None, **overrides):
    resp = api_client.pause_subscription(
        subscription_id, pause_subscription_payload(**overrides),
        as_headers or ADMIN,
    )
    return _ok("pause_subscription", resp)


def resume_subscription(subscription_id, as_headers=None):
    resp = api_client.resume_subscription(subscription_id, as_headers or ADMIN)
    return _ok("resume_subscription", resp)


def get_subscription(subscription_id, as_headers=None):
    resp = api_client.get_subscription(subscription_id, as_headers or ADMIN)
    return _ok("get_subscription", resp)


def get_account(account_id, as_headers=None):
    resp = api_client.get_account(account_id, as_headers or ADMIN)
    return _ok("get_account", resp)


def get_profile(profile_id, as_headers=None):
    resp = api_client.get_profile(profile_id, as_headers or ADMIN)
    return _ok("get_profile", resp)


def get_save_offer(save_offer_id, as_headers=None):
    resp = api_client.get_save_offer(save_offer_id, as_headers or ADMIN)
    return _ok("get_save_offer", resp)


def get_plan(plan_id, as_headers=None):
    resp = api_client.get_plan(plan_id, as_headers or ADMIN)
    return _ok("get_plan", resp)


def get_signup_attribution(attribution_id, as_headers=None):
    resp = api_client.get_signup_attribution(attribution_id,
                                             as_headers or ADMIN)
    return _ok("get_signup_attribution", resp)


def get_partner_billing_record(record_id, as_headers=None):
    resp = api_client.get_partner_billing_record(record_id, as_headers or ADMIN)
    return _ok("get_partner_billing_record", resp)


def list_billing_events(subscription_id=None, account_id=None, event_type=None,
                        as_headers=None):
    params = {}
    if subscription_id is not None:
        params["subscription_id"] = subscription_id
    if account_id is not None:
        params["account_id"] = account_id
    if event_type is not None:
        params["event_type"] = event_type
    resp = api_client.list_billing_events(as_headers or ADMIN, params=params)
    return _ok("list_billing_events", resp)


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy: plan + account + subscription
# ---------------------------------------------------------------------------

def setup_account_with_subscription(
    at=DEFAULT_NOW_UTC,
    plan_overrides=None,
    account_overrides=None,
    subscription_overrides=None,
):
    """Plan + account + subscription. Returns (plan, account, subscription).

    With the default trial_days=0 the subscription opens ACTIVE; pass
    plan_overrides={"trial_days": N} for a TRIALING entry state.
    """
    plan = create_plan(at=at, **(plan_overrides or {}))
    account = create_account(at=at, **(account_overrides or {}))
    subscription = create_subscription(
        account["account_id"], plan["plan_id"], **(subscription_overrides or {})
    )
    return plan, account, subscription


def setup_account_with_profiles(num_profiles=2, at=DEFAULT_NOW_UTC, **kwargs):
    """Plan + account + subscription + N ACTIVE profiles. Returns
    (plan, account, subscription, [profiles])."""
    plan, account, subscription = setup_account_with_subscription(at=at, **kwargs)
    profiles = [
        create_profile(account["account_id"], display_name=f"P{i+1}")
        for i in range(num_profiles)
    ]
    return plan, account, subscription, profiles


def setup_cancelled_subscription(at=DEFAULT_NOW_UTC, **kwargs):
    """Plan + account + subscription, then cancel. Returns
    (plan, account, subscription_after_cancel)."""
    plan, account, subscription = setup_account_with_subscription(at=at, **kwargs)
    cancelled = cancel_subscription(subscription["subscription_id"])
    return plan, account, cancelled


def setup_subscription_with_presented_offer(
    offer_type="PAUSE_1M", at=DEFAULT_NOW_UTC, offer_overrides=None, **kwargs
):
    """Plan + account + ACTIVE subscription + one PRESENTED save offer.
    Returns (plan, account, subscription, save_offer)."""
    plan, account, subscription = setup_account_with_subscription(at=at, **kwargs)
    offer = create_save_offer(
        subscription["subscription_id"],
        offer_type=offer_type,
        **(offer_overrides or {}),
    )
    return plan, account, subscription, offer


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_paused_subscription(at=DEFAULT_NOW_UTC, duration_months=1, **kwargs):
    """Plan + account + ACTIVE subscription, then direct-pause it.
    Returns (plan, account, paused_subscription)."""
    plan, account, subscription = setup_account_with_subscription(at=at, **kwargs)
    paused = pause_subscription(
        subscription["subscription_id"], duration_months=duration_months
    )
    return plan, account, paused


def setup_deactivated_profile(at=DEFAULT_NOW_UTC, **kwargs):
    """Plan + account + subscription + one profile, deactivated.
    Returns (plan, account, subscription, profile)."""
    plan, account, subscription, profiles = setup_account_with_profiles(
        num_profiles=1, at=at, **kwargs
    )
    profile = profiles[0]
    resp = api_client.deactivate_profile(profile["profile_id"], ADMIN)
    deactivated = _ok("deactivate_profile", resp)
    return plan, account, subscription, deactivated


def setup_archived_plan(at=DEFAULT_NOW_UTC, **overrides):
    """Create a plan then archive it. Returns the archived plan."""
    plan = create_plan(at=at, **overrides)
    resp = api_client.archive_plan(plan["plan_id"], ADMIN)
    return _ok("archive_plan", resp)


# ---------------------------------------------------------------------------
# Tier 4 — dunning accumulation
# ---------------------------------------------------------------------------

def post_charge_failed(account_id, subscription_id, tag, amount_cents=3000):
    """Post one manual CHARGE_FAILED billing event (the test-driving path for
    a failed renewal; PRD section 2.7)."""
    resp = api_client.create_billing_event(
        create_billing_event_payload(
            account_id,
            subscription_id,
            event_type="CHARGE_FAILED",
            amount_cents=amount_cents,
            external_reference=f"fail-{tag}",
            notes=f"simulated failure {tag}",
        ),
        ADMIN,
    )
    return _ok("post_charge_failed", resp)


def setup_subscription_in_dunning(failures=1, at=DEFAULT_NOW_UTC,
                                  failure_time="2026-09-01T00:00:00Z", **kwargs):
    """Plan + account + ACTIVE subscription, then `failures` CHARGE_FAILED
    events posted at `failure_time`. Returns (plan, account, subscription)."""
    plan, account, subscription = setup_account_with_subscription(at=at, **kwargs)
    set_clock(failure_time)
    for i in range(failures):
        post_charge_failed(account["account_id"], subscription["subscription_id"],
                           f"f{i+1}")
    return plan, account, subscription


def setup_dunning_exhausted(at=DEFAULT_NOW_UTC, num_profiles=0,
                            failure_time="2026-09-01T00:00:00Z",
                            sweep_time="2026-09-02T00:00:00Z", **kwargs):
    """Plan + account + subscription (+ optional profiles), five CHARGE_FAILED
    events, then a sweep to fire dunning exhaustion. Returns
    (plan, account, subscription, [profiles])."""
    if num_profiles:
        plan, account, subscription, profiles = setup_account_with_profiles(
            num_profiles=num_profiles, at=at, **kwargs
        )
    else:
        plan, account, subscription = setup_account_with_subscription(at=at, **kwargs)
        profiles = []
    set_clock(failure_time)
    for i in range(5):
        post_charge_failed(account["account_id"], subscription["subscription_id"],
                           f"f{i+1}")
    run_sweeps(sweep_time)
    return plan, account, subscription, profiles


# ---------------------------------------------------------------------------
# Tier 4b — partner billing
# ---------------------------------------------------------------------------

def setup_partner_billing_record(expected_amount_cents=10000, at=DEFAULT_NOW_UTC,
                                 **overrides):
    """Account + EXPECTED partner billing record. Returns (account, record)."""
    account = create_account(at=at)
    resp = api_client.create_partner_billing_record(
        create_partner_billing_record_payload(
            account["account_id"],
            expected_amount_cents=expected_amount_cents,
            **overrides,
        ),
        PARTNER_OPS,
    )
    record = _ok("create_partner_billing_record", resp)
    return account, record


def setup_received_partner_record(received_amount_cents,
                                  expected_amount_cents=10000, at=DEFAULT_NOW_UTC,
                                  **overrides):
    """Account + partner record moved EXPECTED → RECEIVED.
    Returns (account, record_after_receipt)."""
    account, record = setup_partner_billing_record(
        expected_amount_cents=expected_amount_cents, at=at, **overrides
    )
    resp = api_client.report_partner_receipt(
        record["partner_billing_record_id"],
        {"received_amount_cents": received_amount_cents},
        PARTNER_OPS,
    )
    received = _ok("report_partner_receipt", resp)
    return account, received


# ---------------------------------------------------------------------------
# Tier 5 — price change notices and campaigns
# ---------------------------------------------------------------------------

def create_price_change_notice(plan_id, as_headers=None, **overrides):
    resp = api_client.create_price_change_notice(
        create_price_change_notice_payload(plan_id, **overrides),
        as_headers or ADMIN,
    )
    return _ok("create_price_change_notice", resp)


def create_active_campaign(at=DEFAULT_NOW_UTC, **overrides):
    """Create a win-back campaign and activate it. Returns campaign dict."""
    set_clock(at)
    resp = api_client.create_winback_campaign(
        create_winback_campaign_payload(**overrides), ADMIN
    )
    campaign = _ok("create_winback_campaign", resp)
    resp = api_client.activate_winback_campaign(
        campaign["winback_campaign_id"], ADMIN
    )
    return _ok("activate_winback_campaign", resp)
