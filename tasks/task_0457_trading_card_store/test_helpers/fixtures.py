"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific state that takes
several API calls to reach. These helpers encapsulate those preambles so tests can
focus on assertions. They use get_success_data() (lenient validator) so setup
failures produce clear "setup failed" errors rather than confusing assertions.

Identity threading: Customer is entity-backed, so any ownership-gated call uses
make_customer_headers(customer["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_inventory_item_payload,
    create_credit_adjustment_payload, create_buylist_submission_payload,
    create_buylist_line_payload, create_release_product_payload,
    create_pre_order_payload, create_event_payload, create_registration_payload,
    create_pairing_payload, create_grading_submission_payload,
    create_consignment_case_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_judge_headers

SM = TEST_USERS["store_manager_headers"]
JUDGE = TEST_USERS["judge_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the server logical clock (StoreManager-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, SM))


# ─── Tier 1: Primitive creators ────────────────────────────────────────────────
def create_customer(display_name="Test Customer", email="test@example.com",
                    credit_cents=0):
    """Create a customer and optionally seed store credit via a manual adjustment.
    Returns the customer dict (re-fetched after the adjustment so the balance is
    current)."""
    cust = get_success_data(api_client.create_customer(
        create_customer_payload(display_name=display_name, email=email), SM))
    if credit_cents:
        api_client.create_credit_adjustment(
            cust["id"], create_credit_adjustment_payload(delta_cents=credit_cents), SM)
        cust = get_success_data(api_client.get_customer(cust["id"], SM))
    return cust


def create_inventory_item(title="Test Card", product_kind="SINGLE",
                          market_price_cents=1000, **overrides):
    return get_success_data(api_client.create_inventory_item(
        create_inventory_item_payload(
            title=title, product_kind=product_kind,
            market_price_cents=market_price_cents, **overrides), SM))


def create_release_product(**overrides):
    return get_success_data(api_client.create_release_product(
        create_release_product_payload(**overrides), SM))


def create_event(**overrides):
    return get_success_data(api_client.create_event(
        create_event_payload(**overrides), SM))


# ─── Tier 2: Buylist lifecycle ──────────────────────────────────────────────────
def create_submitted_buylist(customer, lines, payout_method="STORE_CREDIT"):
    """customer: a customer dict. lines: list of (inventory_item, quantity).
    Creates a DRAFT submission owned by the customer, adds each line, and submits.
    Returns the SUBMITTED submission dict."""
    cust_h = make_customer_headers(customer["id"])
    sub = get_success_data(api_client.create_buylist_submission(
        create_buylist_submission_payload(customer["id"], payout_method), cust_h))
    for item, qty in lines:
        api_client.create_buylist_line(
            create_buylist_line_payload(sub["id"], item["id"], qty), cust_h)
    api_client.submit_buylist(sub["id"], cust_h)
    return get_success_data(api_client.get_buylist_submission(sub["id"], cust_h))


def create_accepted_buylist(customer, lines, payout_method="STORE_CREDIT"):
    """Create a submitted buylist then accept it (StoreManager). Returns the
    ACCEPTED submission dict."""
    sub = create_submitted_buylist(customer, lines, payout_method)
    return get_success_data(api_client.accept_buylist(sub["id"], SM))


# ─── Tier 3: Event / registration lifecycle ─────────────────────────────────────
def create_open_event(**overrides):
    """Create a SCHEDULED event and open it (StoreManager). Returns the OPEN event."""
    ev = create_event(**overrides)
    return get_success_data(api_client.open_event(ev["id"], SM))


def create_registration(event, customer):
    """Register the customer for the event (Customer-owned). Returns registration."""
    return get_success_data(api_client.create_registration(
        create_registration_payload(event["id"], customer["id"]),
        make_customer_headers(customer["id"])))


def create_paid_registration(event, customer):
    """Register + pay (Customer-owned). Customer must already hold enough credit.
    Returns the PAID registration dict."""
    reg = create_registration(event, customer)
    return get_success_data(api_client.pay_registration(
        reg["id"], make_customer_headers(customer["id"])))


def create_checked_in_registration(event, customer):
    """Register + pay + check in. Check-in is a StoreManager action. Returns the
    CHECKED_IN registration dict."""
    reg = create_paid_registration(event, customer)
    return get_success_data(api_client.check_in_registration(reg["id"], SM))


def setup_in_progress_event_with_two_players(
        entry_fee_cents=1000, starts_at="2026-07-01T00:00:00Z",
        ends_at="2026-07-01T05:00:00Z", event_format="MODERN"):
    """Full preamble to an IN_PROGRESS round-1 event with two CHECKED_IN players.

    clock → two credited customers → open event → both register, pay, check in →
    start (round 1). Returns (event, customer_a, customer_b, reg_a, reg_b).
    """
    set_clock("2026-06-01T00:00:00Z")
    ca = create_customer("P1", "p1_" + starts_at + "@x.com", credit_cents=5000)
    cb = create_customer("P2", "p2_" + starts_at + "@x.com", credit_cents=5000)
    ev = create_open_event(title="Floor Event", format=event_format,
                           starts_at=starts_at, ends_at=ends_at,
                           capacity=8, entry_fee_cents=entry_fee_cents)
    ra = create_checked_in_registration(ev, ca)
    rb = create_checked_in_registration(ev, cb)
    get_success_data(api_client.start_event(ev["id"], JUDGE))
    ev = get_success_data(api_client.get_event(ev["id"], SM))
    return ev, ca, cb, ra, rb


def create_pairing(event, reg_a, reg_b=None):
    """Create a pairing (JudgeStaff) for the event's current round."""
    return get_success_data(api_client.create_pairing(
        create_pairing_payload(event["id"], reg_a["id"],
                               reg_b["id"] if reg_b else None), JUDGE))


def report_pairing(pairing, result):
    """Report a pairing result (JudgeStaff)."""
    return get_success_data(api_client.report_pairing(
        pairing["id"], {"result": result}, JUDGE))


# ─── Tier 4: Release / pre-order lifecycle ───────────────────────────────────────
def create_requested_pre_order(customer, release_product, requested_quantity=1,
                               deposit_paid_cents=500):
    """Create a REQUESTED pre-order owned by the customer. Customer must hold
    enough credit to cover the deposit. Returns the pre-order dict."""
    return get_success_data(api_client.create_pre_order(
        create_pre_order_payload(customer["id"], release_product["id"],
                                 requested_quantity, deposit_paid_cents),
        make_customer_headers(customer["id"])))


def create_allocated_pre_order(customer, release_product, requested_quantity=1,
                               deposit_paid_cents=500):
    """Create a REQUESTED pre-order and allocate it, threading the release's current
    version into the OCC field. Returns (pre_order, release_product_after_allocate).
    """
    po = create_requested_pre_order(customer, release_product, requested_quantity,
                                    deposit_paid_cents)
    allocated = get_success_data(api_client.allocate_pre_order(
        po["id"], {"expected_release_product_version": release_product["version"]}, SM))
    rp_after = get_success_data(api_client.get_release_product(release_product["id"], SM))
    return allocated, rp_after


# ─── Tier 5: Grading lifecycle ───────────────────────────────────────────────────
def create_inventory_item_with_stock(market_price_cents=4000, quantity=1):
    """Create a SINGLE item and drive its quantity_on_hand to `quantity` via an
    accepted CASH buylist (CASH adds inventory but writes no ledger row). Returns
    (inventory_item_after, owner_customer)."""
    owner = create_customer("Stock Owner",
                            f"stock_{market_price_cents}_{quantity}@x.com")
    item = create_inventory_item(market_price_cents=market_price_cents)
    create_accepted_buylist(owner, [(item, quantity)], payout_method="CASH")
    item_after = get_success_data(api_client.get_inventory_item(item["id"], SM))
    return item_after, owner


def create_at_grader_submission(customer, inventory_item,
                                declared_value_cents=10000, service_tier="STANDARD"):
    """Create an INTAKE grading submission and send it to the grader (the item must
    already have quantity_on_hand >= 1). Returns the AT_GRADER submission dict."""
    gs = get_success_data(api_client.create_grading_submission(
        create_grading_submission_payload(
            customer["id"], inventory_item["id"], declared_value_cents, service_tier),
        SM))
    return get_success_data(api_client.send_grading_submission(gs["id"], SM))


# ─── Tier 6: Consignment lifecycle ───────────────────────────────────────────────
def create_listed_consignment(customer, inventory_item, quantity=1,
                              ask_price_cents=1000, commission_rate_bps=1500):
    """Create a LISTED consignment case owned by the customer."""
    return get_success_data(api_client.create_consignment_case(
        create_consignment_case_payload(
            customer["id"], inventory_item["id"], quantity, ask_price_cents,
            commission_rate_bps),
        make_customer_headers(customer["id"])))


def create_sold_consignment(customer, inventory_item, quantity=1,
                            ask_price_cents=1000, commission_rate_bps=1500):
    """Create a LISTED case then mark it SOLD (StoreManager). Returns the SOLD case."""
    cc = create_listed_consignment(customer, inventory_item, quantity,
                                   ask_price_cents, commission_rate_bps)
    return get_success_data(api_client.sell_consignment_case(cc["id"], SM))
