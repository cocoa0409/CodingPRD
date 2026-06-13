"""Subscription lifecycle: pause/resume, cancel, the parallel lifecycle x billing
state dimensions, pause-limit and resume-date preconditions, renewal-driven
PAST_DUE / retry-charge, gift expiry, and subscription-create first-period billing.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    pause_payload, cancel_payload, prepay_payload, retry_charge_payload,
    set_clock, run_renewal, get_subscription,
    setup_subscription, setup_prepaid_subscription, setup_redeemed_gift_subscription,
    create_plan, create_subscriber, create_subscription,
    list_billing_cycles_for_subscription, list_invoices_for_subscription,
)

ADMIN = TEST_USERS["curation_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]


# ─── non_linear_state_machine: parallel dimensions (queue A, >=2 tests) ─────

def test_prepay_then_pause_parallel_dimensions_evolve_independently(api):
    """PRD §3.3: "A successful pause moves `lifecycle_status` to `PAUSED`, sets
    `paused_until` to the supplied instant, increments `pause_count_in_term` by 1,
    and freezes `next_renewal_at` so renewal does not fire while paused; the
    billing posture is left untouched."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_dimensions
    """
    ctx = setup_prepaid_subscription(period_price_cents=6000, term_periods=6,
                                     prepaid_discount_pct=0.10)
    sub = ctx["subscription"]
    assert sub["billing_status"] == "PREPAID"
    assert sub["lifecycle_status"] == "ACTIVE"

    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.pause_subscription(sub["id"], pause_payload("2026-08-01T00:00:00Z"), headers)
    paused = validate_success(res, 200)
    assert paused["lifecycle_status"] == "PAUSED"
    assert paused["billing_status"] == "PREPAID", "billing dimension unchanged by pause"
    assert paused["prepaid_periods_remaining"] == 6


def test_prepay_leaves_lifecycle_active_while_changing_billing(api):
    """PRD §3.4: "On success the system charges that total, creates an `Invoice`
    of kind `PREPAID_CHARGE`, sets `billing_status` to `PREPAID`".
    PRD §3.4: "The purchase is allowed only when `billing_status` is `CURRENT`
    and `lifecycle_status` is `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_dimensions
    """
    ctx = setup_subscription(plan_overrides={
        "period_price_cents": 6000, "prepaid_terms_offered": [6], "prepaid_discount_pct": 0.10})
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.prepay_subscription(sub["id"], prepay_payload(6, sub["version"]), headers)
    updated = validate_success(res, 200)
    assert updated["billing_status"] == "PREPAID"
    assert updated["lifecycle_status"] == "ACTIVE", "lifecycle dimension unchanged by prepay"


# ─── state_machines corner ──────────────────────────────────────────────────

def test_pause_then_resume_valid_transition(api):
    """PRD §3.3: "A `PAUSED` subscription returns to `ACTIVE` either when the
    subscriber **resumes** it manually or when the renewal run observes the clock
    has reached `paused_until`."
    PRD §3.3: "On resume, `next_renewal_at` is advanced by the elapsed pause
    duration, rounded to whole cadence periods forward so that renewal lands on a
    future cadence boundary, and `paused_until` is cleared."

    Design: Corner/state_machines/pause_then_resume_valid_transition
    """
    ctx = setup_subscription(plan_overrides={"name": "RP"})
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    validate_success(api.pause_subscription(sub["id"], pause_payload("2026-08-01T00:00:00Z"), headers), 200)
    res = api.resume_subscription(sub["id"], headers)
    resumed = validate_success(res, 200)
    assert resumed["lifecycle_status"] == "ACTIVE"
    assert resumed["paused_until"] is None, "paused_until must be cleared on resume"


def test_cancel_already_cancelled_returns_invalid_state(api):
    """PRD §3.3: "An immediate cancellation may be issued from either `ACTIVE` or
    `PAUSED` and takes the subscription to `CANCELLED`."
    PRD §2.8: "the target resource is in a state from which the requested
    transition is defined; for a reservation, the referenced `ShippingWave` must be
    `OPEN`. A violation yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_already_cancelled_returns_invalid_state
    """
    ctx = setup_subscription(plan_overrides={"name": "CC"})
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    validate_success(api.cancel_subscription(sub["id"], cancel_payload("IMMEDIATE"), headers), 200)
    res = api.cancel_subscription(sub["id"], cancel_payload("IMMEDIATE"), headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_pause_limit_reached_after_three_pauses(api):
    """PRD §3.3: "`pause_count_in_term` is below 3, so the third existing pause is
    the last permitted and a further pause request once the count has reached 3 is
    rejected with `ERR_PAUSE_LIMIT_REACHED`".

    Design: Corner/state_machines/pause_limit_reached_after_three_pauses
    """
    ctx = setup_subscription(plan_overrides={"name": "PL"})
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    for d in ("2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", "2026-07-03T00:00:00Z"):
        validate_success(api.pause_subscription(sub["id"], pause_payload(d), headers), 200)
        validate_success(api.resume_subscription(sub["id"], headers), 200)
    res = api.pause_subscription(sub["id"], pause_payload("2026-07-04T00:00:00Z"), headers)
    validate_error(res, ApiErrorId.ERR_PAUSE_LIMIT_REACHED.value, expected_status=422)


def test_pause_invalid_resume_date_in_past_rejected(api):
    """PRD §3.3: "when the supplied `paused_until` is strictly after the current
    clock, otherwise `ERR_INVALID_RESUME_DATE`".

    Design: Corner/state_machines/pause_invalid_resume_date_in_past_rejected
    """
    ctx = setup_subscription(plan_overrides={"name": "IR"})
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.pause_subscription(sub["id"], pause_payload("2026-05-01T00:00:00Z"), headers)
    validate_error(res, ApiErrorId.ERR_INVALID_RESUME_DATE.value, expected_status=422)


def test_gift_subscription_expires_on_last_prepaid_draw(api):
    """PRD §3.12: "A gift subscription whose last prepaid period is drawn at a
    renewal run — that is, its `prepaid_periods_remaining` was 1 before that draw
    and `is_gift` is true — moves its lifecycle to `EXPIRED`, with `next_renewal_at`
    cleared and no further charge or auto-renew."

    Design: Corner/state_machines/gift_subscription_expires_on_last_prepaid_draw
    """
    ctx = setup_redeemed_gift_subscription(term_periods=1)
    sub = ctx["subscription"]
    assert sub["prepaid_periods_remaining"] == 1
    set_clock("2026-07-01T00:00:00Z")
    run_renewal(subscription_id=sub["id"])
    expired = get_subscription(sub["id"])
    assert expired["lifecycle_status"] == "EXPIRED"
    assert expired["prepaid_periods_remaining"] == 0


def test_renewal_charge_failed_moves_billing_to_past_due(api):
    """PRD §3.12: "When a `CHARGE`-funded renewal cycle settles `FAILED`, the
    subscription's `billing_status` moves `CURRENT` → `PAST_DUE`".

    Design: Corner/state_machines/renewal_charge_failed_moves_billing_to_past_due
    """
    ctx = setup_subscription(plan_overrides={"name": "PD"})
    sub = ctx["subscription"]
    set_clock("2026-07-01T00:00:00Z")
    run_renewal(subscription_id=sub["id"], charge_outcome="FAILED")
    updated = get_subscription(sub["id"])
    assert updated["billing_status"] == "PAST_DUE"


def test_retry_charge_recovers_past_due_to_current(api):
    """PRD §3.12: "an `outcome` of `PAID` settles the replacement cycle `PAID` and
    moves `billing_status` `PAST_DUE` → `CURRENT`".

    Design: Corner/state_machines/retry_charge_recovers_past_due_to_current
    """
    ctx = setup_subscription(plan_overrides={"name": "RT"})
    sub = ctx["subscription"]
    set_clock("2026-07-01T00:00:00Z")
    run_renewal(subscription_id=sub["id"], charge_outcome="FAILED")
    res = api.retry_charge(sub["id"], retry_charge_payload("PAID"), BILLING)
    updated = validate_success(res, 200)
    assert updated["billing_status"] == "CURRENT"


# ─── calculations corner: first-period billing ─────────────────────────────

def test_subscription_create_charges_first_period_invoice(api):
    """PRD §3.2: "The first period is billed immediately: the system creates a
    `BillingCycle` for `period_index` 1 with `funding_source` `CHARGE`, settles it
    `PAID`, and creates an `Invoice` of kind `PERIOD_CHARGE`."

    Design: Corner/calculations/subscription_create_charges_first_period_invoice
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="FP", period_price_cents=6000)
    subscriber = create_subscriber(email="fp@x.com", full_name="FP S")
    sub = create_subscription(subscriber, plan)
    assert sub["current_period_index"] == 1

    invoices = [i for i in list_invoices_for_subscription(sub["id"]) if i["kind"] == "PERIOD_CHARGE"]
    assert len(invoices) == 1, f"expected exactly one PERIOD_CHARGE invoice, got {len(invoices)}"
    assert invoices[0]["gross_amount_cents"] == 6000

    cycles = list_billing_cycles_for_subscription(sub["id"])
    charge_cycles = [c for c in cycles if c["funding_source"] == "CHARGE"]
    assert len(charge_cycles) == 1
    assert charge_cycles[0]["status"] == "PAID"
    assert charge_cycles[0]["period_index"] == 1
