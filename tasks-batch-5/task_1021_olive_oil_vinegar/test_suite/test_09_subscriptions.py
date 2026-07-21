"""Subscriptions: pause/resume cycle, terminal lockdown, renewal cascade, and the
optimistic-concurrency guards on subscription-create and order-pay."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_member, create_bottle, create_order, create_subscription, transition_subscription,
    make_customer_headers, TEST_USERS,
)

STAFF = TEST_USERS["shop_staff_headers"]


def _member_with_subscription(api, cadence_days=30):
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=2000)
    sub = create_subscription(api, member, product["id"], cadence_days=cadence_days)
    return member, product, sub


# ── Corner: state_machines / subscription_pause_then_resume_cycles_active ──

def test_pause_then_resume_returns_subscription_to_active(api):
    """PRD §3.8: "The owner may pause an `ACTIVE` subscription (`ACTIVE → PAUSED`), resume a
    paused one (`PAUSED → ACTIVE`), or cancel from either `ACTIVE` or `PAUSED` to the terminal
    `CANCELLED`".

    Design: Corner/state_machines/subscription_pause_then_resume_cycles_active
    """
    member, product, sub = _member_with_subscription(api)
    transition_subscription(api, sub["id"], "PAUSE", member=member)
    resumed = transition_subscription(api, sub["id"], "RESUME", member=member)
    assert resumed["status"] == "ACTIVE", resumed["status"]


# ── Corner: state_machines / cancelled_subscription_cannot_resume ──

def test_resume_cancelled_subscription_rejected(api):
    """PRD §3.8: "The owner may pause an `ACTIVE` subscription (`ACTIVE → PAUSED`), resume a
    paused one (`PAUSED → ACTIVE`), or cancel from either `ACTIVE` or `PAUSED` to the terminal
    `CANCELLED`; each increments the subscription's `version`, and an undefined transition is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_subscription_cannot_resume
    """
    member, product, sub = _member_with_subscription(api)
    transition_subscription(api, sub["id"], "CANCEL", member=member)
    resp = api.transition_subscription(sub["id"], {"action": "RESUME"},
                                       make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ── Corner: state_machines / subscription_renew_creates_order_and_advances_counter ──

def test_renew_creates_order_and_increments_counter(api):
    """PRD §3.8: "Renewal is a `ShopStaff` action and an `ACTIVE` self-loop, permitted only when
    the logical now has reached or passed the `next_renewal_date`: it creates a new `Order` for
    the subscription's member with a single line derived from the subscription's product,
    quantity, and volume — the order opening `UNPAID` and `PENDING` — records that order's id as
    `last_order_id`, advances `next_renewal_date` by another cadence interval, increases
    `renewals_count` by one, and increments the subscription's `version`."

    Design: Corner/state_machines/subscription_renew_creates_order_and_advances_counter
    """
    member, product, sub = _member_with_subscription(api, cadence_days=30)
    # created at default clock 2026-07-01 -> next_renewal 2026-07-31; advance past it.
    validate_success(api.set_clock("2026-08-01T00:00:00Z", TEST_USERS["platform_admin_headers"]))
    renewed = transition_subscription(api, sub["id"], "RENEW", as_staff=True)
    assert renewed["renewals_count"] == 1, renewed["renewals_count"]
    assert renewed["status"] == "ACTIVE", renewed["status"]
    assert renewed["last_order_id"], "last_order_id must be set to the created order's id"


# ── Corner: cross_cutting_complexity_layers / occ_stale_member_supersede_subscription_create ──

def test_second_subscription_with_stale_member_version_rejected(api):
    """PRD §2.6: "a create request must carry `expected_member_version` matching the member's
    current `version`. If another writer has advanced the member's `version` since the client
    last read the member, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_supersede_subscription_create
    """
    member = create_member(api)  # version 1
    product = create_bottle(api, unit_price_cents=2000)
    create_subscription(api, member, product["id"], cadence_days=30,
                        expected_member_version=member["version"])  # bumps member -> 2
    resp = api.create_subscription(
        {"product_id": product["id"], "quantity": 1, "cadence_days": 30,
         "expected_member_version": member["version"]},  # still 1 -> stale
        make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ── Corner: cross_cutting_complexity_layers / occ_stale_order_version_on_pay ──

def test_pay_with_stale_order_version_rejected(api):
    """PRD §2.6: "When paying, fulfilling, or cancelling an order, the request must include
    `expected_order_version` carrying the order's last-observed `version`; ... if the supplied
    value does not equal the target resource's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_pay
    """
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=2000)
    order = create_order(api, member, [{"line_type": "UNIT", "product_id": product["id"], "quantity": 1}])
    resp = api.pay_order(order["id"], {"expected_order_version": order["version"] - 1},
                         make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ── Corner: errors / subscription_not_found_on_transition ──

def test_transition_missing_subscription_returns_not_found(api):
    """PRD §2.8: "When a path contains a resource identifier, the server validates existence left
    to right and rejects the first missing identifier with the matching not-found error (for
    example ... `ERR_SUBSCRIPTION_NOT_FOUND` ...), each carrying HTTP 404."

    Design: Corner/errors/subscription_not_found_on_transition
    """
    member = create_member(api)
    resp = api.transition_subscription("00000000-0000-0000-0000-000000000000",
                                       {"action": "PAUSE"}, make_customer_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value)
