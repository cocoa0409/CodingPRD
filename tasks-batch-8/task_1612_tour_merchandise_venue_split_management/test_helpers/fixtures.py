"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Seller is entity-backed, so every seller-scoped call is
made with make_seller_headers(<seller id>); opaque roles use the shared
TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_CASH_FLOAT_CENTS,
    DEFAULT_FLAT_COMMISSION_BPS,
    DEFAULT_SHOW_DATE,
)
from .factories import (
    count_out_payload,
    create_online_order_payload,
    create_product_payload,
    create_sale_record_payload,
    create_seller_payload,
    create_seller_session_payload,
    create_shipment_payload,
    create_show_payload,
    create_show_product_payload,
    create_tour_payload,
    dispute_payload,
    generate_allocations_payload,
    royalty_config_payload,
    verify_payload,
)
from .test_users import TEST_USERS, make_seller_headers

TM1 = TEST_USERS["tour_manager_headers"]
TM2 = TEST_USERS["tour_manager_2_headers"]
ACCT1 = TEST_USERS["accountant_headers"]
ACCT2 = TEST_USERS["accountant_2_headers"]
VENUE1 = TEST_USERS["venue_rep_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and single-step transitions
# ---------------------------------------------------------------------------

def create_tour(name="Test Tour", artist_name="Test Artist", **overrides):
    """Create a tour (born PLANNING). Returns the tour."""
    return get_success_data(
        api_client.create_tour(create_tour_payload(name=name, artist_name=artist_name,
                                                   **overrides), TM1))


def create_active_tour(name="Test Tour", **overrides):
    """Create a tour and activate it. Returns the ACTIVE tour."""
    tour = create_tour(name=name, **overrides)
    return get_success_data(api_client.activate_tour(tour["id"], TM1))


def create_show(tour_id, **overrides):
    """Create a show (born SCHEDULED). Returns the show."""
    return get_success_data(
        api_client.create_show(create_show_payload(tour_id, **overrides), TM1))


def open_show(show_id):
    return get_success_data(api_client.open_show(show_id, TM1))


def create_product(tour_id, **overrides):
    """Create a product. Returns the product (warehouse stock initialized)."""
    return get_success_data(
        api_client.create_product(create_product_payload(tour_id, **overrides), TM1))


def create_show_product(show_id, product_id, price_cents):
    return get_success_data(api_client.create_show_product(
        create_show_product_payload(show_id, product_id, price_cents), TM1))


def generate_allocations(show_id, product_id, total_units):
    """Generate allocations; returns the list of created Allocation rows."""
    return get_success_data(api_client.generate_allocations(
        show_id, generate_allocations_payload(product_id, total_units), TM1))


def create_seller(tour_id, display_name="Seller A", seller_code="SELLER-A"):
    return get_success_data(api_client.create_seller(
        create_seller_payload(tour_id, display_name=display_name,
                              seller_code=seller_code), TM1))


def create_seller_session(show_id, seller_id, cash_float_cents=DEFAULT_CASH_FLOAT_CENTS):
    return get_success_data(api_client.create_seller_session(
        create_seller_session_payload(show_id, seller_id, cash_float_cents), TM1))


def record_sale(session_id, allocation_id, quantity, tender, seller_id):
    """Record a sale as the owning seller. Returns the SaleRecord."""
    return get_success_data(api_client.create_sale_record(
        create_sale_record_payload(session_id, allocation_id, quantity, tender),
        make_seller_headers(seller_id)))


def count_out_session(session_id, counted_cash_cents, seller_id):
    """Count out as the owning seller. Returns the COUNTED_OUT session."""
    return get_success_data(api_client.count_out_session(
        session_id, count_out_payload(counted_cash_cents),
        make_seller_headers(seller_id)))


def verify_session(session_id, headers, decision="APPROVE", variance_override=None):
    return get_success_data(api_client.verify_session(
        session_id, verify_payload(decision, variance_override), headers))


def begin_reconciliation(show_id):
    """OPEN -> RECONCILING. Returns the updated show (carries settlement_id)."""
    return get_success_data(api_client.begin_reconciliation(show_id, TM1))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, TM1))


def reconcile_settlement(settlement_id, headers=ACCT1):
    return get_success_data(api_client.reconcile_settlement(settlement_id, headers))


def dispute_settlement(settlement_id, reason="Disputed", headers=VENUE1):
    return get_success_data(
        api_client.dispute_settlement(settlement_id, dispute_payload(reason), headers))


def resolve_settlement(settlement_id, headers=ACCT1):
    return get_success_data(api_client.resolve_settlement(settlement_id, headers))


def finalize_settlement(settlement_id, headers=ACCT2):
    return get_success_data(api_client.finalize_settlement(settlement_id, headers))


def rebase_royalty(settlement_id, headers=ACCT1):
    return get_success_data(api_client.rebase_royalty(settlement_id, headers))


def place_online_order(tour_id, product_id, quantity, size=None):
    return get_success_data(api_client.create_online_order(
        create_online_order_payload(tour_id, product_id, quantity, size=size), TM1))


def fulfill_online_order(order_id):
    return get_success_data(api_client.fulfill_online_order(order_id, TM1))


def cancel_online_order(order_id):
    return get_success_data(api_client.cancel_online_order(order_id, TM1))


def create_shipment(tour_id, destination_show_id, product_id, quantity=10,
                    size="OS", origin_type="WAREHOUSE", origin_show_id=None):
    payload = create_shipment_payload(
        tour_id, origin_type, destination_show_id,
        [{"product_id": product_id, "size": size, "quantity": quantity}],
        origin_show_id=origin_show_id)
    return get_success_data(api_client.create_shipment(payload, TM1))


def dispatch_shipment(shipment_id, headers=TM1):
    return get_success_data(api_client.dispatch_shipment(shipment_id, headers))


def receive_shipment(shipment_id, headers=TM2):
    return get_success_data(api_client.receive_shipment(shipment_id, headers))


def cancel_shipment(shipment_id, headers=TM1):
    return get_success_data(api_client.cancel_shipment(shipment_id, headers))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, TM1))


def get_shipment(shipment_id):
    return get_success_data(api_client.get_shipment(shipment_id, TM1))


def get_show(show_id):
    return get_success_data(api_client.get_show(show_id, TM1))


def get_tour(tour_id):
    return get_success_data(api_client.get_tour(tour_id, TM1))


def get_allocation(allocation_id):
    return get_success_data(api_client.get_allocation(allocation_id, TM1))


def get_session(session_id):
    return get_success_data(api_client.get_seller_session(session_id, TM1))


def list_allocations(params):
    data, _meta = validate_paginated(api_client.list_allocations(TM1, params=params))
    return data


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, TM1))


def patch_royalty_config(tour_id, expected_tour_version, **config):
    """Accepted royalty-config patch. Defaults to the current tour values for
    any field not overridden by the caller."""
    merged = {
        "standard_rate_bps": 1000,
        "tier_threshold_cents": 500000,
        "tier_bonus_bps": 500,
        "licensed_flat_per_unit_cents": 500,
        "licensed_rate_bps": 2000,
    }
    merged.update(config)
    return get_success_data(api_client.patch_royalty_config(
        tour_id,
        royalty_config_payload(expected_tour_version=expected_tour_version, **merged),
        TM1))


# ---------------------------------------------------------------------------
# Tier 2: the selling-show world (tour + show + product + price + allocations
# + rostered sellers), the common preamble for show-day scenarios
# ---------------------------------------------------------------------------

def setup_selling_show(*, tour_name="World Tour", tour_overrides=None,
                       activate=True, city="Springfield", venue_name="World Hall",
                       show_date=DEFAULT_SHOW_DATE, commission_mode="FLAT",
                       flat_commission_bps=DEFAULT_FLAT_COMMISSION_BPS,
                       commission_tiers=None, size_curve=None,
                       product_overrides=None, price_cents=4000,
                       total_units=300, num_sellers=2, open=True):
    """Tour (+ACTIVE) -> show (SCHEDULED) -> product -> price row ->
    allocations -> sellers -> show OPEN. Returns a world dict."""
    tour_overrides = tour_overrides or {}
    product_overrides = product_overrides or {}
    tour = create_tour(name=tour_name, **tour_overrides)
    if activate:
        tour = get_success_data(api_client.activate_tour(tour["id"], TM1))
    show = create_show(
        tour["id"], city=city, venue_name=venue_name, show_date=show_date,
        commission_mode=commission_mode, flat_commission_bps=flat_commission_bps,
        commission_tiers=commission_tiers, size_curve=size_curve)
    product = create_product(tour["id"], **product_overrides)
    show_product = create_show_product(show["id"], product["id"], price_cents)
    allocations = generate_allocations(show["id"], product["id"], total_units)
    sellers = [
        create_seller(tour["id"], display_name=f"Seller {chr(65 + i)}",
                      seller_code=f"S-{chr(65 + i)}")
        for i in range(num_sellers)
    ]
    if open:
        show = open_show(show["id"])
    return {
        "tour": tour,
        "show": show,
        "product": product,
        "show_product": show_product,
        "allocations": allocations,
        "allocation": allocations[0],
        "sellers": sellers,
        "sessions": [],
        "sale_records": [],
        "settlement": None,
    }


def staff_session(world, seller_index=0, cash_float_cents=DEFAULT_CASH_FLOAT_CENTS,
                  sales=(), count_out=True, counted_cash_cents=None,
                  verify=False, verify_by_index=1, verify_headers=None,
                  variance_override=None):
    """Staff one seller onto the world's OPEN show, optionally record sales,
    count out, and verify. sales: iterable of (quantity, tender). Returns the
    session in its final state."""
    seller = world["sellers"][seller_index]
    session = create_seller_session(world["show"]["id"], seller["id"], cash_float_cents)
    records = []
    for quantity, tender in sales:
        records.append(record_sale(session["id"], world["allocation"]["id"],
                                   quantity, tender, seller["id"]))
    if count_out:
        if counted_cash_cents is None:
            counted_cash_cents = cash_float_cents + sum(
                r["gross_cents"] for r in records if r["tender"] == "CASH")
        session = count_out_session(session["id"], counted_cash_cents, seller["id"])
    if verify:
        headers = verify_headers or make_seller_headers(
            world["sellers"][verify_by_index]["id"])
        session = verify_session(session["id"], headers,
                                 variance_override=variance_override)
    world["sessions"].append(session)
    world["sale_records"].extend(records)
    return session


def reach_settlement(world, stage="PROVISIONAL", reconcile_headers=ACCT1,
                     finalize_headers=ACCT2):
    """Drive the world's OPEN show into reconciliation and its settlement to
    the requested stage: PROVISIONAL, RECONCILED, or FINALIZED."""
    world["show"] = begin_reconciliation(world["show"]["id"])
    settlement = get_settlement(world["show"]["settlement_id"])
    if stage in ("RECONCILED", "FINALIZED"):
        settlement = reconcile_settlement(settlement["id"], reconcile_headers)
    if stage == "FINALIZED":
        settlement = finalize_settlement(settlement["id"], finalize_headers)
        world["show"] = get_show(world["show"]["id"])
    world["settlement"] = settlement
    return settlement
