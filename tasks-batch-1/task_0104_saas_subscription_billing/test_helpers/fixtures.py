"""Composite setup helpers for multi-step test prerequisites.

Each helper drives an empty database to a target state using only PRD endpoints.
Helpers use get_success_data() (lenient 2xx validator) so setup failures surface
as clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: AccountOwner is entity_backed on Account, so every
ownership-gated call uses make_account_owner_headers(account_id) with the real
account id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_addon_payload,
    create_coupon_payload,
    create_tax_jurisdiction_payload,
    create_account_payload,
    create_subscription_payload,
    create_pause_window_payload,
    set_clock_payload,
    set_card_state_payload,
)
from .test_users import TEST_USERS, make_account_owner_headers

ADMIN = TEST_USERS["billing_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Low-level building blocks ────────────────────────
def set_clock(iso8601: str):
    """Set the server clock. Returns the response data ({now: ...})."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), ADMIN))


def create_jurisdiction(region_code="US-CA", tax_rate_bps=875):
    res = api_client.create_tax_jurisdiction(
        create_tax_jurisdiction_payload(region_code=region_code, tax_rate_bps=tax_rate_bps), ADMIN
    )
    return get_success_data(res)


def create_plan(**kwargs):
    return get_success_data(api_client.create_plan(create_plan_payload(**kwargs), ADMIN))


def create_addon(code="SEATS", monthly_fee_cents=2000):
    return get_success_data(
        api_client.create_addon(create_addon_payload(code=code, monthly_fee_cents=monthly_fee_cents), ADMIN)
    )


def create_coupon(**kwargs):
    return get_success_data(api_client.create_coupon(create_coupon_payload(**kwargs), ADMIN))


def archive_plan(plan_id):
    return get_success_data(api_client.archive_plan(plan_id, ADMIN))


def create_account(email, region_code="US-CA", company_name="Acme", payment_method_ok=True):
    res = api_client.create_account(
        create_account_payload(
            email=email,
            company_name=company_name,
            region_code=region_code,
            payment_method_ok=payment_method_ok,
        ),
        ANON,
    )
    return get_success_data(res)


def set_card_state(account_id, payment_method_ok):
    return get_success_data(
        api_client.set_card_state(set_card_state_payload(account_id, payment_method_ok), ADMIN)
    )


def get_subscription(subscription_id, account_id):
    return get_success_data(
        api_client.get_subscription(subscription_id, make_account_owner_headers(account_id))
    )


def get_account(account_id):
    return get_success_data(
        api_client.get_account(account_id, make_account_owner_headers(account_id))
    )


def list_account_invoices(account_id, params=None):
    res = api_client.list_invoices(account_id, make_account_owner_headers(account_id), params=params)
    body = res.json()
    # Reuse lenient validation for status, then return the array payload.
    get_success_data(res)
    return body["data"]


# ─── Catalogue setup ──────────────────────────────────
def setup_jurisdiction_and_clock(clock="2026-06-01T00:00:00Z", region_code="US-CA", tax_rate_bps=875):
    """Set the clock and create one tax jurisdiction. Returns the jurisdiction."""
    set_clock(clock)
    return create_jurisdiction(region_code=region_code, tax_rate_bps=tax_rate_bps)


# ─── Tier 1/2: Account + subscription setup ───────────
def setup_active_subscription(
    plan_fee_cents=3000,
    plan_tier="BASIC",
    overage_tiers=None,
    included_usage_units=1000,
    coupon_id=None,
    email="acct@x.com",
    clock="2026-06-01T00:00:00Z",
    region_code="US-CA",
    tax_rate_bps=875,
    payment_method_ok=True,
):
    """Clock + jurisdiction + trial_days=0 plan + account + subscription that
    opens directly ACTIVE (PRD §3.2). Returns (plan, account, subscription)."""
    setup_jurisdiction_and_clock(clock=clock, region_code=region_code, tax_rate_bps=tax_rate_bps)
    plan = create_plan(
        tier=plan_tier,
        monthly_fee_cents=plan_fee_cents,
        included_usage_units=included_usage_units,
        overage_tiers=overage_tiers,
        trial_days=0,
    )
    account = create_account(email=email, region_code=region_code, payment_method_ok=payment_method_ok)
    sub_res = api_client.create_subscription(
        account["id"],
        create_subscription_payload(plan["id"], coupon_id=coupon_id),
        make_account_owner_headers(account["id"]),
    )
    subscription = get_success_data(sub_res)
    return plan, account, subscription


def setup_converted_subscription(
    plan_fee_cents=9000,
    plan_tier="PRO",
    overage_tiers=None,
    included_usage_units=1000,
    trial_days=14,
    coupon_id=None,
    email="acct@x.com",
    clock="2026-06-01T00:00:00Z",
    region_code="US-CA",
    tax_rate_bps=875,
    payment_method_ok=True,
):
    """Clock + jurisdiction + trial plan + account + subscription created
    TRIALING then converted ACTIVE early (PRD §3.3). Returns (plan, account,
    subscription-after-convert)."""
    setup_jurisdiction_and_clock(clock=clock, region_code=region_code, tax_rate_bps=tax_rate_bps)
    plan = create_plan(
        tier=plan_tier,
        monthly_fee_cents=plan_fee_cents,
        included_usage_units=included_usage_units,
        overage_tiers=overage_tiers,
        trial_days=trial_days,
    )
    account = create_account(email=email, region_code=region_code, payment_method_ok=payment_method_ok)
    sub = get_success_data(
        api_client.create_subscription(
            account["id"],
            create_subscription_payload(plan["id"], coupon_id=coupon_id),
            make_account_owner_headers(account["id"]),
        )
    )
    converted = get_success_data(
        api_client.convert_subscription(account["id"], sub["id"], make_account_owner_headers(account["id"]))
    )
    return plan, account, converted


def setup_trialing_subscription(
    plan_fee_cents=9000,
    plan_tier="PRO",
    trial_days=14,
    email="acct@x.com",
    clock="2026-06-01T00:00:00Z",
):
    """Clock + jurisdiction + trial plan + account + subscription created
    TRIALING (not converted). Returns (plan, account, subscription)."""
    setup_jurisdiction_and_clock(clock=clock)
    plan = create_plan(tier=plan_tier, monthly_fee_cents=plan_fee_cents, trial_days=trial_days)
    account = create_account(email=email)
    sub = get_success_data(
        api_client.create_subscription(
            account["id"],
            create_subscription_payload(plan["id"]),
            make_account_owner_headers(account["id"]),
        )
    )
    return plan, account, sub


# ─── Tier 3: Usage + renewal ──────────────────────────
def record_usage(account_id, subscription_id, units, recorded_at):
    from .factories import record_usage_payload

    res = api_client.record_usage(
        account_id,
        subscription_id,
        record_usage_payload(units, recorded_at),
        make_account_owner_headers(account_id),
    )
    return get_success_data(res)


def run_renewals():
    return get_success_data(api_client.run_renewals(ADMIN))


def run_dunning():
    return get_success_data(api_client.run_dunning(ADMIN))


def setup_converted_with_usage_then_renew(
    plan_fee_cents=9000,
    overage_tiers=None,
    included_usage_units=1000,
    units=5001,
    usage_recorded_at="2026-06-15T00:00:00Z",
    coupon_id=None,
    addon_id_to_attach=None,
    email="use@x.com",
    period_end_clock="2026-07-01T00:00:00Z",
):
    """ACTIVE PRO subscription (via convert) with metered usage recorded
    in-period, then the clock advanced to period end and run-renewals invoked.
    Returns (plan, account, subscription, renewal_result)."""
    plan, account, sub = setup_converted_subscription(
        plan_fee_cents=plan_fee_cents,
        overage_tiers=overage_tiers,
        included_usage_units=included_usage_units,
        coupon_id=coupon_id,
        email=email,
    )
    if addon_id_to_attach is not None:
        from .factories import add_addon_payload

        get_success_data(
            api_client.add_subscription_addon(
                account["id"],
                sub["id"],
                add_addon_payload(addon_id_to_attach),
                make_account_owner_headers(account["id"]),
            )
        )
    if units and units > 0:
        record_usage(account["id"], sub["id"], units, usage_recorded_at)
    set_clock(period_end_clock)
    renewal = run_renewals()
    return plan, account, sub, renewal


# ─── Tier 4: Dunning progression ──────────────────────
def setup_renewal_with_failing_card(
    plan_fee_cents=9000,
    email="dun@x.com",
    period_end_clock="2026-07-01T00:00:00Z",
):
    """ACTIVE PRO subscription (via convert), card flipped to fail, clock at
    period end, run-renewals invoked so a renewal invoice exists and is OPEN.
    Returns (plan, account, subscription)."""
    plan, account, sub = setup_converted_subscription(plan_fee_cents=plan_fee_cents, email=email)
    set_card_state(account["id"], False)
    set_clock(period_end_clock)
    run_renewals()
    return plan, account, sub


def find_renewal_invoice(account_id, period_start="2026-07-01T00:00:00Z"):
    """Return the invoice whose period_start matches the renewal cycle start."""
    invoices = list_account_invoices(account_id)
    for inv in invoices:
        if inv.get("period_start", "").startswith(period_start[:10]):
            return inv
    return None


# ─── Tier 5: Pause window setup ───────────────────────
def setup_subscription_with_pause_window(
    pause_from="2026-06-01T00:00:00Z",
    pause_to="2026-06-10T00:00:00Z",
    email="pw@x.com",
):
    """ACTIVE BASIC subscription with one SCHEDULED pause window.
    Returns (account, subscription, pause_window)."""
    plan, account, sub = setup_active_subscription(email=email)
    pw = get_success_data(
        api_client.create_pause_window(
            account["id"],
            sub["id"],
            create_pause_window_payload(pause_from, pause_to),
            make_account_owner_headers(account["id"]),
        )
    )
    return account, sub, pw


# ─── Plan + price-schedule setup ──────────────────────
def setup_plan_with_price_schedule(
    effective_from="2026-01-01T00:00:00Z",
    effective_to="2026-04-01T00:00:00Z",
    monthly_fee_cents=3000,
):
    """A BASIC plan carrying one price schedule window. Returns (plan, schedule)."""
    plan = create_plan(tier="BASIC", monthly_fee_cents=3000, trial_days=0)
    from .factories import create_price_schedule_payload

    schedule = get_success_data(
        api_client.create_price_schedule(
            plan["id"],
            create_price_schedule_payload(monthly_fee_cents, effective_from, effective_to),
            ADMIN,
        )
    )
    return plan, schedule
