"""Composite setup helpers for the Lawn Care DIY Subscription API tests.

Most testable claims require the system to be in a state that takes many API
calls to reach (customer -> lawn -> analyzed soil test -> reviewed plan ->
active subscription -> box -> invoice ...). These fixtures encapsulate those
chains so tests focus on assertions. All setup calls use the framework's
lenient get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error.

Identity threading: every ownership-gated Customer call uses
make_customer_headers(customer["id"]) built from the entity created in the
same chain — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_on_payload,
    catalog_product_payload,
    claim_payload,
    customer_payload,
    lab_result_analyzed_payload,
    lawn_payload,
    ledger_adjustment_payload,
    plan_line,
    plan_payload,
    shipment_payload,
    soil_test_payload,
    subscription_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]
OPS = TEST_USERS["fulfillment_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive builders (single calls, lenient validation)
# ---------------------------------------------------------------------------

def seed_catalog_products(*skus):
    """Create the named catalog fixture products. Returns {sku: product}."""
    created = {}
    for sku in skus:
        resp = api_client.create_catalog_product(catalog_product_payload(sku), ADMIN)
        created[sku] = get_success_data(resp)
    return created


def register_customer(email="user@x.com", full_name="Test User", climate_zone="COOL",
                      referred_by_code=None):
    resp = api_client.register_customer(
        customer_payload(email=email, full_name=full_name, climate_zone=climate_zone,
                         referred_by_code=referred_by_code)
    )
    return get_success_data(resp)


def add_credit(customer_id, amount_cents, note="promo"):
    resp = api_client.create_ledger_adjustment(
        ledger_adjustment_payload(customer_id, amount_cents, note=note), ADMIN
    )
    return get_success_data(resp)


def create_lawn(customer, label="Front", lawn_size_sqm=100, grass_type="COOL_SEASON",
                region="NE-OH"):
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_lawn(
        lawn_payload(customer["id"], label=label, lawn_size_sqm=lawn_size_sqm,
                     grass_type=grass_type, region=region),
        headers,
    )
    return get_success_data(resp)


def order_soil_test(customer, lawn):
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_soil_test(soil_test_payload(lawn["id"]), headers)
    return get_success_data(resp)


def analyze_soil_test(customer, kit):
    """Return the sample and post an ANALYZED lab result. Returns the kit."""
    headers = make_customer_headers(customer["id"])
    get_success_data(api_client.return_sample(kit["id"], headers))
    resp = api_client.post_lab_result(kit["id"], lab_result_analyzed_payload(), AGRONOMIST)
    return get_success_data(resp)


def create_draft_plan(lawn, soil_test, plan_lines=None, season_year=2026):
    resp = api_client.create_plan(
        plan_payload(lawn["id"], soil_test["id"], plan_lines=plan_lines,
                     season_year=season_year),
        AGRONOMIST,
    )
    return get_success_data(resp)


def submit_plan(plan):
    return get_success_data(api_client.submit_plan_review(plan["id"], AGRONOMIST))


def activate_plan(customer, lawn, plan, expected_lawn_version=None):
    """Activate a PENDING_REVIEW plan with the OCC guard on the lawn version."""
    if expected_lawn_version is None:
        expected_lawn_version = lawn["version"]
    headers = make_customer_headers(customer["id"])
    resp = api_client.activate_plan(
        plan["id"], {"expected_lawn_version": expected_lawn_version}, headers
    )
    return get_success_data(resp)


def create_subscription(customer, plan, billing_cycle="MONTHLY", auto_ship=False,
                        next_ship_date=None):
    headers = make_customer_headers(customer["id"])
    resp = api_client.create_subscription(
        subscription_payload(customer["id"], plan["id"], billing_cycle=billing_cycle,
                             auto_ship=auto_ship, next_ship_date=next_ship_date),
        headers,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression — the canonical onboarding chain
# ---------------------------------------------------------------------------

def setup_active_subscription(email="owner@x.com", lawn_size_sqm=100, region="NE-OH",
                              grass_type="COOL_SEASON", climate_zone="COOL",
                              plan_lines=None, season_year=2026,
                              billing_cycle="MONTHLY", auto_ship=False,
                              next_ship_date=None, seed_skus=("FERT-01",),
                              credit_adjust_cents=None):
    """Full onboarding chain ending in an ACTIVE subscription.

    Seeds catalog products, registers the customer, creates the lawn, runs the
    soil test to ANALYZED, drafts + submits + activates the plan, then starts
    the subscription. Returns a context dict with every created entity plus
    the customer's ownership headers.
    """
    seed_catalog_products(*seed_skus)
    customer = register_customer(email=email, climate_zone=climate_zone)
    if credit_adjust_cents is not None:
        add_credit(customer["id"], credit_adjust_cents)
    lawn = create_lawn(customer, lawn_size_sqm=lawn_size_sqm, grass_type=grass_type,
                       region=region)
    kit = analyze_soil_test(customer, order_soil_test(customer, lawn))
    plan = create_draft_plan(lawn, kit, plan_lines=plan_lines, season_year=season_year)
    submit_plan(plan)
    plan = activate_plan(customer, lawn, plan)
    subscription = create_subscription(customer, plan, billing_cycle=billing_cycle,
                                       auto_ship=auto_ship,
                                       next_ship_date=next_ship_date)
    return {
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "lawn": lawn,
        "soil_test": kit,
        "plan": plan,
        "subscription": subscription,
    }


# ---------------------------------------------------------------------------
# Tier 2: shipment boxes and invoices
# ---------------------------------------------------------------------------

def create_box(subscription_id, lines=None, ship_date="2026-06-03T00:00:00Z",
               box_kind="SEASONAL", window_days=7, delivery_window_start=None,
               delivery_window_end=None):
    resp = api_client.create_shipment(
        shipment_payload(subscription_id, lines=lines, ship_date=ship_date,
                         box_kind=box_kind, window_days=window_days,
                         delivery_window_start=delivery_window_start,
                         delivery_window_end=delivery_window_end),
        OPS,
    )
    return get_success_data(resp)


def get_box(box_id):
    return get_success_data(api_client.get_shipment(box_id, ADMIN))


def advance_box(box_id, to_status):
    resp = api_client.advance_fulfillment(box_id, {"to_status": to_status}, OPS)
    return get_success_data(resp)


def advance_box_to(box_id, target):
    """Walk the fulfillment pipeline SCHEDULED -> ... -> target."""
    order = ["SCHEDULED", "PICKING", "SHIPPED", "DELIVERED"]
    box = get_box(box_id)
    current = box["fulfillment_status"]
    assert current in order and target in order, f"cannot advance {current} -> {target}"
    for step in order[order.index(current) + 1: order.index(target) + 1]:
        box = advance_box(box_id, step)
    return box


def deliver_box(box_id, at_clock=None):
    """Advance a box to DELIVERED, optionally pinning the logical clock first
    so delivered_at (and the final charge) are taken from that instant."""
    if at_clock is not None:
        get_success_data(api_client.set_clock(at_clock, ADMIN))
    return advance_box_to(box_id, "DELIVERED")


def get_box_invoice(box_id):
    resp = api_client.list_invoices(ADMIN, params={"shipment_id": box_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one invoice for box {box_id}"
    )
    return data[0]


def record_payment(invoice_id, outcome):
    resp = api_client.record_payment(invoice_id, {"outcome": outcome}, ADMIN)
    return get_success_data(resp)


def setup_delivered_box(ctx, lines=None, ship_date="2026-06-03T00:00:00Z",
                        deliver_clock=None, window_days=7):
    """Create a box on the context's subscription and advance it to DELIVERED.
    Returns (box, invoice)."""
    box = create_box(ctx["subscription"]["id"], lines=lines, ship_date=ship_date,
                     window_days=window_days)
    advance_box_to(box["id"], "SHIPPED")
    invoice = get_box_invoice(box["id"])
    box = deliver_box(box["id"], at_clock=deliver_clock)
    return box, invoice


# ---------------------------------------------------------------------------
# Tier 3: add-ons, claims, referrals
# ---------------------------------------------------------------------------

def quote_add_on(ctx, add_on_sku="PEST-01", qty_units=1):
    resp = api_client.create_add_on(
        add_on_payload(ctx["subscription"]["id"], add_on_sku=add_on_sku,
                       qty_units=qty_units),
        ctx["customer_headers"],
    )
    return get_success_data(resp)


def confirm_add_on(ctx, add_on_id):
    resp = api_client.confirm_add_on(add_on_id, ctx["customer_headers"])
    return get_success_data(resp)


def file_claim(ctx, box, claim_reason="OTHER", evidence_url=None):
    resp = api_client.create_claim(
        claim_payload(ctx["subscription"]["id"], box["id"], claim_reason=claim_reason,
                      evidence_url=evidence_url),
        ctx["customer_headers"],
    )
    return get_success_data(resp)


def register_referral_pair(referrer_email="referrer@x.com", referee_email="referee@x.com"):
    """Register a referrer and a referee who used the referrer's code.
    Returns {'referrer', 'referee', 'referral'} with the referral PENDING."""
    referrer = register_customer(email=referrer_email)
    referee = register_customer(email=referee_email,
                                referred_by_code=referrer["referral_code"])
    resp = api_client.list_referrals(
        ADMIN, params={"referee_customer_id": referee["id"]}
    )
    referrals = get_success_data(resp)
    assert isinstance(referrals, list) and len(referrals) == 1, (
        "expected exactly one PENDING referral for the referee"
    )
    return {"referrer": referrer, "referee": referee, "referral": referrals[0]}


def setup_qualified_referral(box_qty=3, referrer_email="referrer@x.com",
                             referee_email="referee@x.com"):
    """Full chain: referral pair, then the referee's subscription and a box
    advanced to SHIPPED whose invoice is then paid — qualifying the referral.
    Returns {'referrer', 'referee', 'referral', 'ctx', 'box', 'invoice'}.
    """
    pair = register_referral_pair(referrer_email=referrer_email,
                                  referee_email=referee_email)
    referee = pair["referee"]
    seed_catalog_products("FERT-01")
    lawn = create_lawn(referee)
    kit = analyze_soil_test(referee, order_soil_test(referee, lawn))
    plan = create_draft_plan(
        lawn, kit, plan_lines=[plan_line("FERT-01", qty_units=box_qty, target_month=4)]
    )
    submit_plan(plan)
    plan = activate_plan(referee, lawn, plan)
    subscription = create_subscription(referee, plan, billing_cycle="MONTHLY",
                                       auto_ship=False)
    ctx = {
        "customer": referee,
        "customer_headers": make_customer_headers(referee["id"]),
        "lawn": lawn,
        "soil_test": kit,
        "plan": plan,
        "subscription": subscription,
    }
    box = create_box(
        subscription["id"],
        lines=[{"product_sku": "FERT-01", "qty_units": box_qty}],
        ship_date="2026-06-10T00:00:00Z",
    )
    advance_box_to(box["id"], "SHIPPED")
    invoice = get_box_invoice(box["id"])
    record_payment(invoice["id"], "SUCCEEDED")
    referral = get_success_data(api_client.get_referral(pair["referral"]["id"], ADMIN))
    return {**pair, "referral_pending": pair["referral"], "ctx": ctx, "box": box,
            "invoice": invoice, "referral": referral}


# ---------------------------------------------------------------------------
# Tier 4: read-side helpers
# ---------------------------------------------------------------------------

def get_customer_balance(customer_id):
    customer = get_success_data(api_client.get_customer(customer_id, ADMIN))
    return customer["credit_balance_cents"]


def list_ledger(customer_id=None, entry_type=None):
    resp = api_client.list_ledger_entries(
        ADMIN, params={"customer_id": customer_id, "entry_type": entry_type}
    )
    return get_success_data(resp)


def list_tasks(subscription_id=None, status=None, shipment_id=None, lawn_id=None):
    resp = api_client.list_applications(
        ADMIN,
        params={"subscription_id": subscription_id, "status": status,
                "shipment_id": shipment_id, "lawn_id": lawn_id},
    )
    return get_success_data(resp)


def list_boxes(subscription_id=None, source_claim_id=None, fulfillment_status=None,
               box_kind=None):
    resp = api_client.list_shipments(
        ADMIN,
        params={"subscription_id": subscription_id, "source_claim_id": source_claim_id,
                "fulfillment_status": fulfillment_status, "box_kind": box_kind},
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
