"""Business validations, listing/pagination, RBAC denials, and OCC swap concurrency.

Corner queue: validations, endpoints, rbac, cross_cutting_complexity_layers sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_customer_payload, create_order_payload, create_order_line_payload,
    create_sku_payload, swap_subscription_payload, create_winback_offer_payload,
    create_referral_payload,
    create_active_sku_with_lot, create_customer, create_corporate_buyer,
    create_active_subscription, setup_draft_bulk_quote,
    setup_customer_with_active_subscription,
    make_customer_headers, make_corporate_buyer_headers, TEST_USERS, ApiErrorId,
)

INV = TEST_USERS["inventory_manager_headers"]
COMP = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ───────────────────────── validations ─────────────────────────

def test_reserve_insufficient_points_rejected(api):
    """PRD §3.3: "If the buyer asked to redeem more points than they hold —
    requested_redeem_points greater than the customer's loyalty_points_balance — the
    reservation is rejected with ERR_INSUFFICIENT_POINTS before any capping is applied."

    Design: Corner/validations/reserve_insufficient_points_rejected
    """
    sku, _ = create_active_sku_with_lot(name="Pt Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1000,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")  # 0 loyalty points
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1",
                             requested_redeem_points=50), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    res = api.reserve_order(order["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


def test_self_referral_rejected(api):
    """PRD §3.1: "in that explicit form the referrer and the referred must be two distinct
    existing customers, and a referral whose referrer_id equals its referred_id is rejected
    with ERR_SELF_REFERRAL."

    Design: Corner/validations/self_referral_rejected
    """
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    res = api.create_referral(create_referral_payload(cid, cid), ADMIN)
    validate_error(res, ApiErrorId.ERR_SELF_REFERRAL.value)


def test_winback_offer_for_active_customer_rejected(api):
    """PRD §3.10: "A win-back offer targets exactly such customers: it may be created only for
    a customer whose status is DORMANT and whose churn_band is CHURN_IMMINENT, and an offer for
    any other customer is rejected with ERR_NOT_WINBACK_ELIGIBLE."

    Design: Corner/validations/winback_offer_for_active_customer_rejected
    """
    cust = create_customer(home_zone="Z1")  # ACTIVE, band OK
    res = api.create_winback_offer(
        create_winback_offer_payload(cust["id"], discount_pct=0.20,
                                     expires_iso="2026-12-31T00:00:00Z"), ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_WINBACK_ELIGIBLE.value)


def test_gift_order_missing_recipient_email_rejected(api):
    """PRD §3.3: "When order_kind is GIFT, a gift_recipient_email is required"
    PRD §2.9: "required body fields present and well-typed raises ERR_INVALID_REQUEST when
    violated (this includes a gift_recipient_email being present when order_kind is GIFT)"

    Design: Corner/validations/gift_order_missing_recipient_email_rejected
    """
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    res = api.create_order(create_order_payload(cid, order_kind="GIFT", ship_zone="Z1"),
                           make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ───────────────────────── endpoints / listing ─────────────────────────

def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response carries limit, offset, total_count, and has_more in the meta
    object of the envelope."

    Design: Corner/endpoints/list_customers_pagination_envelope
    """
    get_success_data(api.create_customer(create_customer_payload(email="p1@x.com",
                                         full_name="P1", home_zone="Z1"), ADMIN))
    get_success_data(api.create_customer(create_customer_payload(email="p2@x.com",
                                         full_name="P2", home_zone="Z1"), ADMIN))
    data, meta = validate_paginated(api.list_customers(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_accept_unquoted_bulk_quote_rejected(api):
    """PRD §3.11: "A CorporateBuyer accepts a quote, moving it QUOTED → ACCEPTED, but only
    while it is QUOTED and the SKU's available_units is at least the quote's quantity ...
    Illegal-state quote transitions are rejected with ERR_INVALID_STATE."

    Design: Corner/endpoints/bulk_quote_accept_requires_quoted_state
    """
    buyer, sku, bq = setup_draft_bulk_quote(quantity=10, unit_price_cents=1000, activate_sku=False)
    res = api.accept_bulk_quote(bq["id"], make_corporate_buyer_headers(buyer["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ───────────────────────── rbac ─────────────────────────

def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory headers: X-User-ID, identifying the
    acting user, and X-User-Role, declaring the capacity in which they act. A request missing
    either header — or carrying an unrecognized value — is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    res = api.list_customers({})  # no auth headers
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_customer_cannot_create_sku_forbidden(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/customer_cannot_create_sku_forbidden
    """
    cust = create_customer(home_zone="Z1")
    res = api.create_sku(create_sku_payload(name="Hack", category="HOT_SAUCE",
                                            storage_class="AMBIENT", unit_price_cents=1000),
                         make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customer_cannot_cancel_other_customers_subscription(api):
    """PRD §2.1: "ownership checks on any resource that references a Customer compare that
    resource's customer foreign key (for example an order's customer_id or a subscription's
    customer_id) to X-User-ID. ... A Customer or CorporateBuyer who acts on a customer,
    subscription, order, or bulk-quote resource they do not own is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_subscription
    """
    customer_a, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=14)
    customer_b = create_customer(home_zone="Z1")
    res = api.cancel_subscription(sub["id"], make_customer_headers(customer_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ───────────────────────── OCC swap concurrency ─────────────────────────

def test_swap_with_correct_version_succeeds(api):
    """PRD §2.8: "When a Customer stages a flavor swap on a subscription, the request must
    include expected_subscription_version carrying the version the client last observed for
    that subscription."
    PRD §2.4: "a version integer that starts at its initial value and increments by one on
    every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/occ_swap_correct_version_succeeds
    """
    sku_a, _ = create_active_sku_with_lot(name="SwA Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=2900, lot_code="LA")
    sku_b, _ = create_active_sku_with_lot(name="SwB Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=4900, lot_code="LB")
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    sub = create_active_subscription(cid, sku_a["id"], tier="STARTER", cadence_days=14)
    swapped = validate_success(api.swap_subscription(
        sub["id"], swap_subscription_payload(sku_b["id"], sub["version"]),
        make_customer_headers(cid)), 200)
    assert swapped["pending_swap_sku_id"] == sku_b["id"]
    assert swapped["version"] == sub["version"] + 1


def test_swap_with_stale_version_rejected(api):
    """PRD §2.8: "If expected_subscription_version does not equal the subscription's current
    version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_swap_stale_version_rejected
    """
    sku_a, _ = create_active_sku_with_lot(name="St Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=2900, lot_code="LA")
    sku_b, _ = create_active_sku_with_lot(name="St2 Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=4900, lot_code="LB")
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    sub = create_active_subscription(cid, sku_a["id"], tier="STARTER", cadence_days=14)
    stale_version = sub["version"]
    # First swap advances version; the captured stale_version is now out of date.
    validate_success(api.swap_subscription(
        sub["id"], swap_subscription_payload(sku_b["id"], stale_version),
        make_customer_headers(cid)), 200)
    res = api.swap_subscription(
        sub["id"], swap_subscription_payload(sku_a["id"], stale_version),
        make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
