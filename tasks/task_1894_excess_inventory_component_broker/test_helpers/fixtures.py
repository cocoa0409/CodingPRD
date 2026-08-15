"""Composite setup helpers for multi-step test prerequisites.

Every helper builds state from scratch via PRD-declared endpoints (the runner
restarts the server before every test, so nothing persists between tests).
Setup calls use get_success_data() so failures surface as clear setup errors.

Identity threading: entity-backed roles (Seller, Customer) always act through
make_seller_headers(entity_id) / make_customer_headers(entity_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_seller_payload,
    create_customer_payload,
    create_storage_bin_payload,
    create_buy_offer_payload,
    accept_buy_offer_payload,
    convert_to_lot_payload,
    create_consignment_agreement_payload,
    create_listing_payload,
    create_market_price_snapshot_payload,
    create_sales_order_payload,
    create_return_case_payload,
)
from .test_users import TEST_USERS, make_seller_headers, make_customer_headers

BROKER = TEST_USERS["broker_ops_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]

_clock_counter = {"n": 0}


# ---------------------------------------------------------------------------
# Tier 2: basic counterparties
# ---------------------------------------------------------------------------

def create_seller(name="Test Seller", **overrides):
    """Register a seller. Returns the Seller resource."""
    res = api_client.create_seller(
        create_seller_payload(name=name, **overrides), BROKER
    )
    return get_success_data(res)


def create_customer(name="Test Customer", credit_limit_cents=1_000_000,
                    urgency_tier=None, **overrides):
    """Register a customer. Returns the Customer resource."""
    payload = create_customer_payload(
        name=name, credit_limit_cents=credit_limit_cents, **overrides
    )
    if urgency_tier is not None:
        payload["urgency_tier"] = urgency_tier
    res = api_client.create_customer(payload, BROKER)
    return get_success_data(res)


_bin_seq = {"n": 0}


def create_bin(capacity_units=100, bin_code=None):
    """Create a storage bin. Returns the StorageBin resource."""
    if bin_code is None:
        _bin_seq["n"] += 1
        bin_code = f"BIN-AUT{_bin_seq['n']:04d}"
    res = api_client.create_storage_bin(
        create_storage_bin_payload(bin_code=bin_code, capacity_units=capacity_units),
        BROKER,
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1/3: buy-offer pipeline state progression
# ---------------------------------------------------------------------------

def create_pending_offer(seller, mpn="LM317T", quantity=10,
                         ask_price_per_unit_cents=8000,
                         provenance_doc_url="https://docs.example.com/p.pdf"):
    """Seller submits a buy offer. Returns the PENDING_REVIEW offer."""
    payload = create_buy_offer_payload(
        seller["id"],
        mpn=mpn,
        quantity=quantity,
        ask_price_per_unit_cents=ask_price_per_unit_cents,
    )
    if provenance_doc_url is None:
        payload.pop("provenance_doc_url", None)
    else:
        payload["provenance_doc_url"] = provenance_doc_url
    res = api_client.create_buy_offer(payload, make_seller_headers(seller["id"]))
    return get_success_data(res)


def create_accepted_offer(seller, mpn="LM317T", quantity=10,
                          ask_price_per_unit_cents=8000,
                          agreed_unit_price_cents=5000,
                          acquisition_mode="BROKER_OWNED",
                          provenance_doc_url="https://docs.example.com/p.pdf"):
    """Offer walked to ACCEPTED."""
    offer = create_pending_offer(
        seller, mpn=mpn, quantity=quantity,
        ask_price_per_unit_cents=ask_price_per_unit_cents,
        provenance_doc_url=provenance_doc_url,
    )
    res = api_client.accept_buy_offer(
        offer["id"],
        accept_buy_offer_payload(
            agreed_unit_price_cents=agreed_unit_price_cents,
            acquisition_mode=acquisition_mode,
        ),
        BROKER,
    )
    return get_success_data(res)


def create_received_offer(seller, **kwargs):
    """Offer walked to UNDER_INSPECTION."""
    offer = create_accepted_offer(seller, **kwargs)
    res = api_client.receive_buy_offer(offer["id"], BROKER)
    return get_success_data(res)


def create_inspection_passed_offer(seller, **kwargs):
    """Offer walked to INSPECTION_PASSED (PASS outcome, provenance present)."""
    offer = create_received_offer(seller, **kwargs)
    res = api_client.inspect_buy_offer(offer["id"], {"outcome": "PASS"}, INSPECTOR)
    return get_success_data(res)


def create_lot(seller, storage_bin, mpn="LM317T", quantity=10,
               ask_price_per_unit_cents=8000, agreed_unit_price_cents=5000,
               acquisition_mode="BROKER_OWNED",
               provenance_doc_url="https://docs.example.com/p.pdf"):
    """Full intake pipeline: offer -> accept -> receive -> inspect PASS ->
    convert. Returns (lot, offer)."""
    offer = create_inspection_passed_offer(
        seller,
        mpn=mpn,
        quantity=quantity,
        ask_price_per_unit_cents=ask_price_per_unit_cents,
        agreed_unit_price_cents=agreed_unit_price_cents,
        acquisition_mode=acquisition_mode,
        provenance_doc_url=provenance_doc_url,
    )
    res = api_client.convert_buy_offer_to_lot(
        offer["id"], convert_to_lot_payload(storage_bin["id"]), BROKER
    )
    lot = get_success_data(res)
    return lot, offer


# ---------------------------------------------------------------------------
# Tier 3: listing and order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_active_listing(lot, asking_price_per_unit_cents=8000):
    """Create a listing on the lot and activate it. Returns (listing, activate_body)."""
    listing = get_success_data(
        api_client.create_listing(
            create_listing_payload(
                lot["id"], asking_price_per_unit_cents=asking_price_per_unit_cents
            ),
            BROKER,
        )
    )
    active = get_success_data(api_client.activate_listing(listing["id"], BROKER))
    return listing, active


def create_consignment_agreement(seller, lot, broker_fee_bps=1000,
                                 effective_from="2026-08-01T00:00:00Z",
                                 effective_to="2027-08-01T00:00:00Z"):
    """Create an ACTIVE consignment agreement window."""
    res = api_client.create_consignment_agreement(
        create_consignment_agreement_payload(
            seller["id"], lot["id"],
            broker_fee_bps=broker_fee_bps,
            effective_from=effective_from,
            effective_to=effective_to,
        ),
        BROKER,
    )
    return get_success_data(res)


def place_order(customer, listing, quantity=1):
    """Customer places an order against the listing. Returns the SalesOrder."""
    res = api_client.create_sales_order(
        create_sales_order_payload(customer["id"], listing["id"], quantity=quantity),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def fund_order_fully(customer, order):
    """Deposit exactly the required escrow in one shot. Returns updated order."""
    res = api_client.deposit_escrow(
        order["id"],
        {"amount_cents": order["required_escrow_cents"]},
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def advance_order_to_delivered(customer, order):
    """Fund escrow, then walk ESCROW_FUNDED -> FULFILLING -> SHIPPED -> DELIVERED."""
    funded = fund_order_fully(customer, order)
    get_success_data(api_client.fulfill_sales_order(funded["id"], BROKER))
    get_success_data(api_client.ship_sales_order(funded["id"], BROKER))
    delivered = get_success_data(api_client.deliver_sales_order(funded["id"], BROKER))
    return delivered


def set_clock(to_iso8601):
    """Advance the logical clock. Returns the clock response body."""
    return get_success_data(api_client.set_clock(to_iso8601, BROKER))


def post_snapshot(mpn, spot_price_cents, source="TRADE_DESK"):
    """Record a market price snapshot at the current logical time."""
    return get_success_data(
        api_client.create_market_price_snapshot(
            create_market_price_snapshot_payload(
                mpn=mpn, spot_price_cents=spot_price_cents, source=source
            ),
            BROKER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: full-scenario composites
# ---------------------------------------------------------------------------

def setup_listed_broker_owned_scenario(mpn="LM317T", quantity=10,
                                       agreed_unit_price_cents=5000,
                                       asking_price_per_unit_cents=8000,
                                       credit_limit_cents=1_000_000,
                                       urgency_tier="STANDARD",
                                       bin_capacity=100):
    """Seller + bin + converted BROKER_OWNED lot + ACTIVE listing + customer.

    Returns dict with keys: seller, customer, bin, lot, offer, listing.
    """
    seller = create_seller()
    customer = create_customer(
        credit_limit_cents=credit_limit_cents, urgency_tier=urgency_tier
    )
    storage_bin = create_bin(capacity_units=bin_capacity)
    lot, offer = create_lot(
        seller, storage_bin,
        mpn=mpn, quantity=quantity,
        agreed_unit_price_cents=agreed_unit_price_cents,
        acquisition_mode="BROKER_OWNED",
    )
    listing, _ = create_active_listing(
        lot, asking_price_per_unit_cents=asking_price_per_unit_cents
    )
    return {
        "seller": seller,
        "customer": customer,
        "bin": storage_bin,
        "lot": lot,
        "offer": offer,
        "listing": listing,
    }


def setup_listed_consignment_scenario(mpn="STM32F103", quantity=10,
                                      agreed_unit_price_cents=8000,
                                      asking_price_per_unit_cents=10000,
                                      broker_fee_bps=1500,
                                      effective_from="2026-08-01T00:00:00Z",
                                      effective_to="2027-08-01T00:00:00Z",
                                      credit_limit_cents=1_000_000,
                                      urgency_tier="STANDARD",
                                      bin_capacity=100):
    """Seller + bin + converted CONSIGNMENT lot + ACTIVE agreement + ACTIVE
    listing + customer.

    Returns dict with keys: seller, customer, bin, lot, offer, agreement, listing.
    """
    seller = create_seller()
    customer = create_customer(
        credit_limit_cents=credit_limit_cents, urgency_tier=urgency_tier
    )
    storage_bin = create_bin(capacity_units=bin_capacity)
    lot, offer = create_lot(
        seller, storage_bin,
        mpn=mpn, quantity=quantity,
        agreed_unit_price_cents=agreed_unit_price_cents,
        acquisition_mode="CONSIGNMENT",
    )
    agreement = create_consignment_agreement(
        seller, lot,
        broker_fee_bps=broker_fee_bps,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    listing, _ = create_active_listing(
        lot, asking_price_per_unit_cents=asking_price_per_unit_cents
    )
    return {
        "seller": seller,
        "customer": customer,
        "bin": storage_bin,
        "lot": lot,
        "offer": offer,
        "agreement": agreement,
        "listing": listing,
    }


def setup_delivered_order(listing_scenario, quantity=1):
    """From a listed scenario dict, place + fund + deliver an order.

    Returns the DELIVERED order (fresh body after the deliver call).
    """
    order = place_order(
        listing_scenario["customer"], listing_scenario["listing"], quantity=quantity
    )
    return advance_order_to_delivered(listing_scenario["customer"], order)
