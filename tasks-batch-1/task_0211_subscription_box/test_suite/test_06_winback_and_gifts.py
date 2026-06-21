"""Win-back loyalty credit (cold vs standard tenure), the plan-retired cross-entity
guard, the win-back window boundary, and the gift lifecycle (purchase / redeem /
revoke).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    cancel_payload, create_gift_grant_payload, redeem_gift_payload,
    set_clock, get_subscription, get_subscriber, get_gift_grant,
    create_plan, create_product, create_subscriber, create_subscription,
    create_wave, curate_box, reserve_box_into_wave, lock_wave, ship_wave,
    setup_subscription, setup_cancelled_subscription, setup_issued_gift,
    setup_redeemed_gift_subscription, redeem_gift, cancel_immediate, get_wave,
    list_wallet_entries,
)

ADMIN = TEST_USERS["curation_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]
SUBSCRIBER = TEST_USERS["subscriber_headers"]


# ─── dual_variant_calc: winback credit cold vs standard (queue A, >=2 tests) ─

def test_winback_cold_subscriber_grant_value(api):
    """PRD §3.7: "For a subscriber with zero prior committed shipments (the **cold**
    path — for instance someone who cancelled before any box shipped), the tenure
    factor is 0, so the grant is simply the base multiplied by the base grant
    percentage 0.20, rounded half up."

    base 6000, no shipments: grant = round_half_up(6000 * 0.20) = 1200.

    Design: Difficulty/dual_variant_calc/winback_credit_standard_vs_cold_subscriber_tenure
    """
    ctx = setup_cancelled_subscription(plan_overrides={"period_price_cents": 6000},
                                       cancel_clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-20T00:00:00Z")  # inside the 60-day window
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.winback_subscription(ctx["subscription"]["id"], headers)
    won = validate_success(res, 200)
    assert won["lifecycle_status"] == "ACTIVE"

    grants = [e for e in list_wallet_entries(ctx["subscriber"]["id"]) if e["kind"] == "WINBACK_CREDIT"]
    assert len(grants) == 1
    assert grants[0]["amount_cents"] == 1200, (
        f"cold win-back grant must be 1200, got {grants[0]['amount_cents']}")


def test_winback_cold_grant_kind_and_source_ref(api):
    """PRD §3.3: "grants a one-time loyalty credit by creating a `WalletEntry` of
    kind `WINBACK_CREDIT` whose `amount_cents` is the win-back grant (§3.7) and
    whose `source_ref_id` is the subscription's own `id`."

    Design: Difficulty/dual_variant_calc/winback_credit_standard_vs_cold_subscriber_tenure
    """
    ctx = setup_cancelled_subscription(plan_overrides={"period_price_cents": 6000},
                                       cancel_clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-20T00:00:00Z")
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    validate_success(api.winback_subscription(ctx["subscription"]["id"], headers), 200)

    grants = [e for e in list_wallet_entries(ctx["subscriber"]["id"]) if e["kind"] == "WINBACK_CREDIT"]
    assert len(grants) == 1, "exactly one WINBACK_CREDIT entry"
    assert grants[0]["source_ref_id"] == ctx["subscription"]["id"], (
        "source_ref_id must be the subscription's own id")


def test_winback_standard_subscriber_with_one_committed_shipment(api):
    """PRD §3.7: "count every `Shipment` in `PACKED`, `DISPATCHED`, or `DELIVERED`
    status across all subscriptions owned by this subscriber — call this the
    committed-box count."
    PRD §3.7: "The tenure factor is the lesser of the committed-box count and 6 (the
    tenure cap), multiplied by 0.05 (the tenure weight)."
    PRD §3.7: "The grant before capping is the base multiplied by the sum of the
    base grant percentage 0.20 and the tenure factor, rounded half up to integer
    cents."

    One committed shipment: grant = round_half_up(6000 * (0.20 + 1*0.05)) =
    round_half_up(6000 * 0.25) = 1500.

    Design: Difficulty/dual_variant_calc/winback_credit_standard_vs_cold_subscriber_tenure
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="STD", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="STDP", name="STD P", on_hand_qty=5)
    subscriber = create_subscriber(email="std@x.com", full_name="STD S")
    headers = make_subscriber_headers(subscriber["id"])

    # First subscription: curate a box, reserve, lock, ship -> 1 committed shipment.
    sub1 = create_subscription(subscriber, plan)
    box = curate_box(sub1, subscriber, [product["id"]])
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    reserve_box_into_wave(sub1, box, wave, wave["version"])
    set_clock("2026-06-10T00:00:00Z")
    lock_wave(wave["id"])
    ship_wave(wave["id"])

    # Second subscription owned by the same subscriber: cancel then win back.
    set_clock("2026-06-11T00:00:00Z")
    sub2 = create_subscription(subscriber, plan)
    cancel_immediate(sub2, subscriber)
    set_clock("2026-06-20T00:00:00Z")
    res = api.winback_subscription(sub2["id"], headers)
    won = validate_success(res, 200)
    assert won["lifecycle_status"] == "ACTIVE"

    grants = [e for e in list_wallet_entries(subscriber["id"]) if e["kind"] == "WINBACK_CREDIT"]
    assert len(grants) == 1
    assert grants[0]["amount_cents"] == 1500, (
        f"standard win-back grant with one committed shipment must be 1500, "
        f"got {grants[0]['amount_cents']}")


# ─── cross_entity_state_dependency: winback needs plan ACTIVE (queue A, >=2) ─

def test_winback_rejected_when_plan_retired(api):
    """PRD §3.3: "when the plan's `status` is `ACTIVE`, otherwise `ERR_PLAN_RETIRED`."
    PRD §3.1: "A plan is born in `ACTIVE` `status` and can later be retired, moving
    its `status` to `RETIRED`; retirement is what later blocks win-back against that
    plan."

    Design: Difficulty/cross_entity_state_dependency/winback_requires_plan_active_not_retired
    """
    ctx = setup_cancelled_subscription(cancel_clock="2026-06-01T00:00:00Z")
    validate_success(api.retire_plan(ctx["plan"]["id"], ADMIN), 200)
    set_clock("2026-06-15T00:00:00Z")
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.winback_subscription(ctx["subscription"]["id"], headers)
    validate_error(res, ApiErrorId.ERR_PLAN_RETIRED.value, expected_status=422)


def test_winback_plan_retired_leaves_subscription_cancelled(api):
    """PRD §3.3: "Win-back is permitted only when the subscription's
    `lifecycle_status` is `CANCELLED`".
    PRD §3.3: "and when the plan's `status` is `ACTIVE`, otherwise `ERR_PLAN_RETIRED`."

    A rejected win-back must not transition the subscription; it stays CANCELLED.

    Design: Difficulty/cross_entity_state_dependency/winback_requires_plan_active_not_retired
    """
    ctx = setup_cancelled_subscription(cancel_clock="2026-06-01T00:00:00Z")
    validate_success(api.retire_plan(ctx["plan"]["id"], ADMIN), 200)
    set_clock("2026-06-15T00:00:00Z")
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    api.winback_subscription(ctx["subscription"]["id"], headers)
    assert get_subscription(ctx["subscription"]["id"])["lifecycle_status"] == "CANCELLED"


# ─── validations corner: winback window closed at +60d ──────────────────────

def test_winback_window_closed_at_exactly_60_days(api):
    """PRD §3.3: "the window is the half-open interval that starts at `cancelled_at`
    and ends exactly at `cancelled_at` plus 60 days, so a request at or after that
    60-day boundary is rejected with `ERR_WINBACK_WINDOW_CLOSED`".

    Cancelled at 2026-06-01, request at exactly 2026-07-31 (+60d) -> rejected.

    Design: Corner/validations/winback_window_closed_at_60_days_rejected
    """
    ctx = setup_cancelled_subscription(cancel_clock="2026-06-01T00:00:00Z")
    set_clock("2026-07-31T00:00:00Z")  # exactly cancelled_at + 60 days
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.winback_subscription(ctx["subscription"]["id"], headers)
    validate_error(res, ApiErrorId.ERR_WINBACK_WINDOW_CLOSED.value, expected_status=422)


# ─── calculations corner: gift charges + redemption ─────────────────────────

def test_gift_grant_charges_full_price_no_discount(api):
    """PRD §3.11: "charges the gifter `amount_paid_cents` equal to the plan's
    `period_price_cents` multiplied by `term_periods` (gifts take no prepaid
    discount)".

    6000 * 3 = 18000, even though the plan offers a 0.10 discount.

    Design: Corner/calculations/gift_grant_charges_full_price_no_discount
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="GG", period_price_cents=6000,
                       prepaid_terms_offered=[3], prepaid_discount_pct=0.10)
    gifter = create_subscriber(email="ggg@x.com", full_name="GG Gifter")
    res = api.create_gift_grant(
        create_gift_grant_payload(plan["id"], gifter["id"], 3, "ggr@x.com"),
        make_subscriber_headers(gifter["id"]))
    gift = validate_success(res, 201)
    assert gift["amount_paid_cents"] == 18000, (
        f"gift charge must be full price 18000, got {gift['amount_paid_cents']}")
    assert gift["status"] == "ISSUED"


def test_gift_redeem_creates_prepaid_gift_subscription(api):
    """PRD §3.11: "On redemption the grant moves `ISSUED` → `REDEEMED` and its
    `redeemed_subscription_id` is set; a new `Subscription` is created with
    `is_gift` true, `billing_status` `PREPAID`, `prepaid_periods_remaining` equal to
    the gift's `term_periods`, `lifecycle_status` `ACTIVE`".

    Design: Corner/calculations/gift_redeem_creates_prepaid_gift_subscription
    """
    ctx = setup_issued_gift(term_periods=3)
    recipient = create_subscriber(email="grr@x.com", full_name="GR Rec")
    res = api.redeem_gift_grant(
        redeem_gift_payload(ctx["gift"]["redemption_code"], recipient["id"]),
        make_subscriber_headers(recipient["id"]))
    sub = validate_success(res, 201)
    assert sub["is_gift"] is True
    assert sub["billing_status"] == "PREPAID"
    assert sub["prepaid_periods_remaining"] == 3
    assert sub["lifecycle_status"] == "ACTIVE"

    gift = get_gift_grant(ctx["gift"]["id"])
    assert gift["status"] == "REDEEMED"
    assert gift["redeemed_subscription_id"] == sub["id"]


def test_gift_redeem_already_redeemed_code_rejected(api):
    """PRD §3.11: "Redemption is allowed only when the code is in `ISSUED` status; a
    code already `REDEEMED` or `REVOKED` is rejected with `ERR_GIFT_NOT_REDEEMABLE`."

    Design: Corner/validations/gift_redeem_already_redeemed_code_rejected
    """
    ctx = setup_issued_gift(term_periods=1)
    r1 = create_subscriber(email="gr2r@x.com", full_name="GR2 R1")
    redeem_gift(ctx["gift"], r1)
    r2 = create_subscriber(email="gr2r2@x.com", full_name="GR2 R2")
    res = api.redeem_gift_grant(
        redeem_gift_payload(ctx["gift"]["redemption_code"], r2["id"]),
        make_subscriber_headers(r2["id"]))
    validate_error(res, ApiErrorId.ERR_GIFT_NOT_REDEEMABLE.value, expected_status=422)


def test_revoke_gift_refunds_gifter_wallet(api):
    """PRD §3.11: "A `BillingOperator` may **revoke** an unredeemed gift grant,
    moving it `ISSUED` → `REVOKED` and refunding the gifter: the system creates an
    `Invoice` of kind `CANCEL_REFUND` (negative) and a `WalletEntry` of kind
    `REFUND_CREDIT` for the grant's `amount_paid_cents`."

    1 period @ 6000 -> refund 6000.

    Design: Corner/endpoints/revoke_gift_refunds_gifter_wallet
    """
    ctx = setup_issued_gift(term_periods=1, period_price_cents=6000)
    res = api.revoke_gift_grant(ctx["gift"]["id"], BILLING)
    revoked = validate_success(res, 200)
    assert revoked["status"] == "REVOKED"
    gifter = get_subscriber(ctx["gifter"]["id"])
    assert gifter["wallet_balance_cents"] == 6000, (
        f"revoke must refund the gifter 6000, got {gifter['wallet_balance_cents']}")
