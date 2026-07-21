"""Composite setup helpers for multi-step test prerequisites.

The test harness restarts the server (empty database) before every test, so
every helper builds its preconditions from scratch using only PRD-declared
endpoints. All setup calls use get_success_data() (lenient) so a broken
precondition surfaces as a clear "Setup step failed" error.

Identity threading: Customer and Practitioner are entity-backed. After creating
one, every ownership-gated call uses make_<role>_headers(entity["id"]) — never
the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_product_payload, create_lot_payload, create_customer_payload,
    create_practitioner_payload, create_recommendation_payload,
    create_bundle_payload, create_subscription_payload, create_order_payload,
    create_order_line_payload, create_return_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_practitioner_headers,
)

OPERATOR = TEST_USERS["store_operator_headers"]


# ─── Clock control ────────────────────────────────────────────────────────

def set_clock(iso8601: str):
    """Advance the server logical clock to a supplied instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, OPERATOR))


def run_expiry_sweep():
    """Materialize lot / recommendation expiry against the logical clock."""
    return get_success_data(api_client.run_expiry_sweep(OPERATOR))


# ─── Tier 1: single-entity creators ───────────────────────────────────────

def new_customer(email="cust@x.com", full_name="Test Customer"):
    """Create an ACTIVE customer. Returns the customer dict."""
    return get_success_data(api_client.create_customer(
        create_customer_payload(email=email, full_name=full_name), OPERATOR))


def new_customer_with_points(lifetime_points_earned, points_balance=0,
                             email="cust@x.com", full_name="Test Customer"):
    """Create a customer then seed its loyalty accumulators (operator-only
    injection). Returns the recomputed customer dict."""
    cust = new_customer(email=email, full_name=full_name)
    payload = {"customer_id": cust["id"],
               "lifetime_points_earned": lifetime_points_earned,
               "points_balance": points_balance}
    return get_success_data(api_client.inject_loyalty_state(payload, OPERATOR))


def new_gold_customer(email="gold@x.com", full_name="Gold Customer", points_balance=0):
    """Customer seeded to GOLD tier (1000 lifetime points)."""
    return new_customer_with_points(1000, points_balance, email, full_name)


def new_product(unit_price_cents=1000, is_practitioner_line=False,
                dshea_claim_type="NONE", name="Test SKU", form="CAPSULE",
                regimen_goals=None, **overrides):
    """Create a Product/SKU. Returns the product dict."""
    payload = create_product_payload(
        name=name, form=form,
        regimen_goals=regimen_goals or ["IMMUNITY"],
        dshea_claim_type=dshea_claim_type,
        unit_price_cents=unit_price_cents, **overrides)
    if is_practitioner_line:
        payload["is_practitioner_line"] = True
    return get_success_data(api_client.create_product(payload, OPERATOR))


def new_lot(product_id, quantity_received=10, expiration_date="2027-01-01T00:00:00Z",
            lot_number="LOT-1"):
    """Receive a lot against a product. Returns the lot dict."""
    return get_success_data(api_client.create_lot(
        product_id,
        create_lot_payload(lot_number=lot_number, expiration_date=expiration_date,
                           quantity_received=quantity_received),
        OPERATOR))


def new_practitioner(full_name="Dr Test", license_number="LIC-1"):
    return get_success_data(api_client.create_practitioner(
        create_practitioner_payload(full_name=full_name, license_number=license_number),
        OPERATOR))


def new_recommendation(practitioner_id, customer_id, product_id,
                       expires_at="2026-12-31T00:00:00Z", max_units=5):
    """Issue a recommendation as the given practitioner (ownership-threaded)."""
    return get_success_data(api_client.create_recommendation(
        create_recommendation_payload(customer_id, product_id,
                                      expires_at=expires_at, max_units=max_units),
        make_practitioner_headers(practitioner_id)))


def new_bundle(component_product_ids, discount_pct=0.15, name="Test Stack"):
    return get_success_data(api_client.create_bundle(
        create_bundle_payload(component_product_ids, discount_pct=discount_pct, name=name),
        OPERATOR))


def new_subscription(customer_id, product_id, quantity_per_cycle=1, cadence_days=30,
                     first_ship_date="2026-08-01T00:00:00Z"):
    """Create an auto-ship subscription owned by the customer (ownership-threaded)."""
    return get_success_data(api_client.create_subscription(
        create_subscription_payload(product_id, quantity_per_cycle=quantity_per_cycle,
                                    cadence_days=cadence_days, first_ship_date=first_ship_date),
        make_customer_headers(customer_id)))


# ─── Tier 2: order building blocks ─────────────────────────────────────────

def new_order(customer_id, **payload_overrides):
    """Open a one-off DRAFT order owned by the customer. Returns the order dict."""
    return get_success_data(api_client.create_order(
        create_order_payload(**payload_overrides), make_customer_headers(customer_id)))


def add_line(order_id, customer_id, product_id, quantity, bundle_id=None):
    """Add a line to a DRAFT order. Returns the order-line dict."""
    payload = create_order_line_payload(product_id, quantity)
    if bundle_id is not None:
        payload["bundle_id"] = bundle_id
    return get_success_data(api_client.create_order_line(
        order_id, payload, make_customer_headers(customer_id)))


def place(order_id, customer_id):
    """Place a DRAFT order. Returns the placed order dict."""
    return get_success_data(api_client.place_order(order_id, make_customer_headers(customer_id)))


def fulfill(order_id):
    """Fulfill a PLACED order (operator). Returns the fulfilled order dict."""
    return get_success_data(api_client.fulfill_order(order_id, OPERATOR))


def generate_autoship_order(subscription_id, customer_id, expected_version):
    """Generate the current-cycle auto-ship order. Returns the DRAFT order dict."""
    return get_success_data(api_client.generate_order(
        subscription_id, {"expected_subscription_version": expected_version},
        make_customer_headers(customer_id)))


# ─── Tier 3: composite lifecycle shortcuts ─────────────────────────────────

def setup_placed_one_off_order(unit_price_cents=5000, quantity=2, lot_quantity=10,
                               tier=None, points_redeemed=0):
    """Customer + product + lot + one-off order with one line, PLACED.

    `tier` (None/"GOLD"/"SILVER") seeds the buyer's loyalty tier so pricing
    discounts apply. Returns a dict of the created resources.
    """
    if tier == "GOLD":
        cust = new_gold_customer()
    elif tier == "SILVER":
        cust = new_customer_with_points(500)
    else:
        cust = new_customer()
    prod = new_product(unit_price_cents=unit_price_cents)
    lot = new_lot(prod["id"], quantity_received=lot_quantity)
    order = new_order(cust["id"], points_redeemed=points_redeemed) if points_redeemed \
        else new_order(cust["id"])
    line = add_line(order["id"], cust["id"], prod["id"], quantity)
    placed = place(order["id"], cust["id"])
    return {"customer": cust, "product": prod, "lot": lot,
            "order": placed, "line": line}


def setup_fulfilled_one_off_order(unit_price_cents=5000, quantity=2, lot_quantity=10,
                                  tier=None):
    """Customer + product + lot + one-off order, PLACED then FULFILLED."""
    ctx = setup_placed_one_off_order(unit_price_cents=unit_price_cents, quantity=quantity,
                                     lot_quantity=lot_quantity, tier=tier)
    ctx["order"] = fulfill(ctx["order"]["id"])
    return ctx


def setup_active_subscription(cadence_days=30, quantity_per_cycle=1,
                              unit_price_cents=2000, first_ship_date="2026-08-01T00:00:00Z",
                              lot_quantity=None, tier=None):
    """Customer + product (+ optional lot) + one ACTIVE subscription.

    Returns a dict with customer, product, (lot,) subscription.
    """
    if tier == "GOLD":
        cust = new_gold_customer()
    else:
        cust = new_customer()
    prod = new_product(unit_price_cents=unit_price_cents)
    ctx = {"customer": cust, "product": prod}
    if lot_quantity is not None:
        ctx["lot"] = new_lot(prod["id"], quantity_received=lot_quantity)
    ctx["subscription"] = new_subscription(
        cust["id"], prod["id"], quantity_per_cycle=quantity_per_cycle,
        cadence_days=cadence_days, first_ship_date=first_ship_date)
    return ctx


def setup_autoship_draft_order(cadence_days=30, quantity_per_cycle=1,
                               unit_price_cents=5000, lot_quantity=100, tier=None):
    """ACTIVE subscription + one generate-order run (a DRAFT auto-ship order).

    Returns a dict with customer, product, lot, subscription, order.
    """
    ctx = setup_active_subscription(
        cadence_days=cadence_days, quantity_per_cycle=quantity_per_cycle,
        unit_price_cents=unit_price_cents, lot_quantity=lot_quantity, tier=tier)
    sub = ctx["subscription"]
    ctx["order"] = generate_autoship_order(sub["id"], ctx["customer"]["id"], sub["version"])
    return ctx


def setup_return_ready(reason="DEFECT", unit_price_cents=5000, quantity=2,
                       return_quantity=None, lot_quantity=10, approve=True):
    """Fulfilled one-off order (BRONZE) + a Return request in REQUESTED (or
    APPROVED) status against its single line.

    Returns a dict with customer, product, lot, order, line, return_.
    """
    ctx = setup_fulfilled_one_off_order(unit_price_cents=unit_price_cents,
                                        quantity=quantity, lot_quantity=lot_quantity)
    rq = return_quantity if return_quantity is not None else quantity
    ret = get_success_data(api_client.create_return(
        create_return_payload(ctx["order"]["id"], ctx["line"]["id"], rq, reason),
        make_customer_headers(ctx["customer"]["id"])))
    if approve:
        ret = get_success_data(api_client.set_return_state(
            ret["id"], {"to_status": "APPROVED"}, OPERATOR))
    ctx["return_"] = ret
    return ctx


def refund_return(return_id):
    """Drive an APPROVED return to REFUNDED (operator). Returns the return dict."""
    return get_success_data(api_client.set_return_state(
        return_id, {"to_status": "REFUNDED"}, OPERATOR))


def recall_lot(lot_id, reason="contamination", severity="CLASS_I"):
    """Recall an AVAILABLE/QUARANTINED lot (runs the recall cascade)."""
    return get_success_data(api_client.set_lot_state(
        lot_id, {"to_status": "RECALLED", "reason": reason, "severity": severity}, OPERATOR))
