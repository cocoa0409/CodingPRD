"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific state reached
through several API calls (plan -> subscriber -> subscription -> box -> wave ->
allocation -> lock -> ship, etc.). These helpers encapsulate those chains so
tests focus on assertions.

All helpers use get_success_data() (lenient 2xx validator) so a broken setup
step raises a clear "Setup step failed" error instead of a confusing assert.

Identity threading: a Subscriber is entity_backed, so every ownership-gated
call uses make_subscriber_headers(subscriber["id"]) with the real subscriber id.
CurationAdmin and BillingOperator are opaque, so their shared constants are used.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    unique_email, unique_sku,
    create_plan_payload, create_product_payload, restock_payload,
    create_subscriber_payload, create_wallet_entry_payload,
    create_subscription_payload, pause_payload, cancel_payload, prepay_payload,
    retry_charge_payload, create_box_selection_payload, swap_box_payload,
    create_wave_payload, create_allocation_payload,
    create_gift_grant_payload, redeem_gift_payload,
    set_clock_payload, renewal_run_payload,
)
from .test_users import (
    TEST_USERS, make_subscriber_headers,
)

ADMIN = TEST_USERS["curation_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the simulated current UTC instant (CurationAdmin-only)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def run_renewal(subscription_id=None, charge_outcome=None):
    """Run the renewal epoch at the current clock."""
    return api_client.run_renewal(
        renewal_run_payload(subscription_id=subscription_id, charge_outcome=charge_outcome),
        ADMIN,
    )


# ─── Tier 1: primitive creators ───────────────────────────────────────────

def create_plan(**overrides):
    """Create a plan (ACTIVE). Returns the plan resource."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def create_product(**overrides):
    """Create a SELLABLE product. Returns the product resource."""
    payload = create_product_payload(**overrides)
    if "sku" not in overrides:
        payload["sku"] = unique_sku()
    return get_success_data(api_client.create_product(payload, ADMIN))


def create_subscriber(**overrides):
    """Self-register a subscriber. Returns the subscriber resource."""
    payload = create_subscriber_payload(**overrides)
    if "email" not in overrides:
        payload["email"] = unique_email()
    return get_success_data(api_client.create_subscriber(payload, TEST_USERS["subscriber_headers"]))


def create_subscription(subscriber, plan, **overrides):
    """Create a pay-as-you-go subscription owned by `subscriber`.
    Bills period 1 immediately. Returns the subscription resource."""
    headers = make_subscriber_headers(subscriber["id"])
    return get_success_data(api_client.create_subscription(
        create_subscription_payload(subscriber["id"], plan["id"], **overrides), headers))


def create_wave(cutoff_at, ship_date, cadence="MONTHLY", capacity=10, **overrides):
    """Open a shipping wave (OPEN, reserved_count 0). Returns the wave resource."""
    return get_success_data(api_client.create_wave(
        create_wave_payload(cutoff_at, ship_date, cadence=cadence, capacity=capacity, **overrides),
        ADMIN))


# ─── Tier 2: subscription + box ───────────────────────────────────────────

def setup_subscription(plan_overrides=None, clock="2026-06-01T00:00:00Z"):
    """Clock + plan + subscriber + ACTIVE/CURRENT subscription.

    Returns dict: { plan, subscriber, subscription }.
    """
    if clock:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    subscriber = create_subscriber()
    subscription = create_subscription(subscriber, plan)
    return {"plan": plan, "subscriber": subscriber, "subscription": subscription}


def curate_box(subscription, subscriber, product_ids, period_index=2):
    """Curate the upcoming box with the given product_ids (decision CURATED).
    Returns the box selection resource."""
    headers = make_subscriber_headers(subscriber["id"])
    return get_success_data(api_client.create_box_selection(
        subscription["id"],
        create_box_selection_payload(period_index, product_ids=product_ids),
        headers))


# ─── Tier 3: allocation chain ─────────────────────────────────────────────

def reserve_box_into_wave(subscription, box, wave, expected_wave_version):
    """Reserve a curated box into an OPEN wave. Returns the allocation resource."""
    return get_success_data(api_client.create_allocation(
        create_allocation_payload(subscription["id"], wave["id"], box["id"],
                                  expected_wave_version),
        ADMIN))


def setup_reserved_allocation(product_on_hand=5, box_item_count=1,
                              wave_capacity=10, num_products_in_box=1,
                              cutoff_at="2026-06-15T00:00:00Z",
                              ship_date="2026-06-16T00:00:00Z",
                              clock="2026-06-01T00:00:00Z"):
    """End-to-end: clock + plan + subscriber + subscription + product + curated
    box + OPEN wave + one RESERVED allocation.

    The box repeats the single product `num_products_in_box` times (must equal
    box_item_count for a valid curation). Returns dict with all entities plus
    `wave_version_after` (the live wave.version after the allocation).
    """
    set_clock(clock)
    plan = create_plan(box_item_count=box_item_count)
    subscriber = create_subscriber()
    subscription = create_subscription(subscriber, plan)
    product = create_product(on_hand_qty=product_on_hand)
    box = curate_box(subscription, subscriber, [product["id"]] * num_products_in_box)
    wave = create_wave(cutoff_at, ship_date, capacity=wave_capacity)
    allocation = reserve_box_into_wave(subscription, box, wave, wave["version"])
    wave_after = get_success_data(api_client.get_wave(wave["id"], ADMIN))
    return {
        "plan": plan, "subscriber": subscriber, "subscription": subscription,
        "product": product, "box": box, "wave": wave, "allocation": allocation,
        "wave_version_after": wave_after["version"],
    }


def lock_wave(wave_id):
    """Lock an OPEN wave (clock must be at/after cutoff). Returns wave resource."""
    return get_success_data(api_client.lock_wave(wave_id, ADMIN))


def ship_wave(wave_id):
    """Ship a LOCKED wave. Returns wave resource."""
    return get_success_data(api_client.ship_wave(wave_id, ADMIN))


# ─── Tier 4: prepaid term targeting ───────────────────────────────────────

def setup_prepaid_subscription(period_price_cents=6000, term_periods=6,
                               prepaid_discount_pct=0.10,
                               clock="2026-06-01T00:00:00Z"):
    """Clock + plan offering the term + subscriber + subscription, then PREPAY.

    Returns dict: { plan, subscriber, subscription (post-prepay), term_periods }.
    The subscription is read back after prepay so its version/prepaid fields
    reflect the PREPAID state.
    """
    set_clock(clock)
    plan = create_plan(period_price_cents=period_price_cents,
                       prepaid_terms_offered=[term_periods],
                       prepaid_discount_pct=prepaid_discount_pct)
    subscriber = create_subscriber()
    subscription = create_subscription(subscriber, plan)
    headers = make_subscriber_headers(subscriber["id"])
    get_success_data(api_client.prepay_subscription(
        subscription["id"],
        prepay_payload(term_periods, subscription["version"]),
        headers))
    subscription = get_success_data(api_client.get_subscription(subscription["id"], ADMIN))
    return {"plan": plan, "subscriber": subscriber, "subscription": subscription,
            "term_periods": term_periods}


# ─── Tier 5: cancellation / win-back ──────────────────────────────────────

def cancel_immediate(subscription, subscriber):
    """Immediately cancel a subscription. Returns the subscription resource."""
    headers = make_subscriber_headers(subscriber["id"])
    return get_success_data(api_client.cancel_subscription(
        subscription["id"], cancel_payload("IMMEDIATE"), headers))


def setup_cancelled_subscription(plan_overrides=None,
                                 cancel_clock="2026-06-01T00:00:00Z"):
    """Clock + plan + subscriber + subscription, then IMMEDIATE cancel.

    Returns dict: { plan, subscriber, subscription (CANCELLED), cancelled_at }.
    No box ships, so this is the 'cold' win-back baseline.
    """
    ctx = setup_subscription(plan_overrides=plan_overrides, clock=cancel_clock)
    ctx["subscription"] = cancel_immediate(ctx["subscription"], ctx["subscriber"])
    return ctx


# ─── Tier 6: gifts ────────────────────────────────────────────────────────

def setup_issued_gift(term_periods=1, period_price_cents=6000,
                      prepaid_discount_pct=None, clock="2026-06-01T00:00:00Z"):
    """Clock + plan + gifter subscriber + ISSUED gift grant.

    Returns dict: { plan, gifter, gift } where gift carries redemption_code.
    """
    set_clock(clock)
    plan_kwargs = {"period_price_cents": period_price_cents}
    if prepaid_discount_pct is not None:
        plan_kwargs["prepaid_terms_offered"] = [term_periods] if term_periods >= 2 else []
        plan_kwargs["prepaid_discount_pct"] = prepaid_discount_pct
    plan = create_plan(**plan_kwargs)
    gifter = create_subscriber()
    gift = get_success_data(api_client.create_gift_grant(
        create_gift_grant_payload(plan["id"], gifter["id"], term_periods,
                                  unique_email("recipient")),
        make_subscriber_headers(gifter["id"])))
    return {"plan": plan, "gifter": gifter, "gift": gift}


def redeem_gift(gift, recipient):
    """Recipient redeems the gift code, creating a gift Subscription.
    Returns the new subscription resource."""
    return get_success_data(api_client.redeem_gift_grant(
        redeem_gift_payload(gift["redemption_code"], recipient["id"]),
        make_subscriber_headers(recipient["id"])))


def setup_redeemed_gift_subscription(term_periods=1, clock="2026-06-01T00:00:00Z"):
    """Full chain: issued gift + recipient subscriber + REDEEMED gift subscription.

    Returns dict: { plan, gifter, gift, recipient, subscription }.
    """
    ctx = setup_issued_gift(term_periods=term_periods, clock=clock)
    recipient = create_subscriber()
    subscription = redeem_gift(ctx["gift"], recipient)
    ctx["recipient"] = recipient
    ctx["subscription"] = subscription
    return ctx


# ─── Helpers for reads ────────────────────────────────────────────────────

def get_subscription(subscription_id):
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ADMIN))


def get_wave(wave_id):
    return get_success_data(api_client.get_wave(wave_id, ADMIN))


def get_allocation(allocation_id):
    return get_success_data(api_client.get_allocation(allocation_id, ADMIN))


def get_box_selection(box_id):
    return get_success_data(api_client.get_box_selection(box_id, ADMIN))


def get_subscriber(subscriber_id):
    return get_success_data(api_client.get_subscriber(subscriber_id, ADMIN))


def get_gift_grant(gift_id):
    return get_success_data(api_client.get_gift_grant(gift_id, ADMIN))


def list_wallet_entries(subscriber_id):
    """Return the subscriber's wallet entries (list)."""
    data, _meta = _list(api_client.list_wallet_entries(subscriber_id, ADMIN, params={"limit": 100}))
    return data


def list_invoices_for_subscription(subscription_id):
    data, _meta = _list(api_client.list_invoices(ADMIN, params={"subscription_id": subscription_id,
                                                                 "limit": 100}))
    return data


def list_billing_cycles_for_subscription(subscription_id):
    data, _meta = _list(api_client.list_billing_cycles(ADMIN, params={"subscription_id": subscription_id,
                                                                       "limit": 100}))
    return data


def list_shipments_for_allocation(allocation_id):
    data, _meta = _list(api_client.list_shipments(ADMIN, params={"allocation_id": allocation_id,
                                                                  "limit": 100}))
    return data


def _list(response):
    """Parse a 2xx list envelope into (data, meta) without status pinning."""
    body = get_success_data(response)
    # get_success_data returns the data list directly for array responses.
    # We re-read meta from the raw response for callers that need it.
    meta = response.json().get("meta", {})
    return body, meta
