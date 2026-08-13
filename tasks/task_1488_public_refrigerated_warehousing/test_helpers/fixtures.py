"""Composite setup helpers.

Every test starts against an empty database, so these helpers build complete
precondition chains (customer onboarding -> rate card -> zone -> receipt ->
arrival -> putaway -> orders/claims/billing) out of PRD-declared endpoints
only. Setup failures raise a clear "Setup step failed" error via
get_success_data.

Identity threading: CustomerAdmin is entity-backed by Customer, so every
ownership-gated call (receipt create, order create/submit/amend/cancel, claim
file/reopen/withdraw, invoice dispute) uses
make_customer_admin_headers(customer_id).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK, DEFAULT_CREDIT_LIMIT
from .factories import (
    create_booking_payload,
    create_cell_payload,
    create_claim_payload,
    create_customer_payload,
    create_excursion_payload,
    create_order_payload,
    create_rate_card_payload,
    create_recall_payload,
    create_receipt_payload,
    create_zone_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_admin_headers,
    make_quality_manager_headers,
    make_warehouse_operator_headers,
)

BILLING = TEST_USERS["billing_admin_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Tier 0: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Set the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, BILLING))


# ---------------------------------------------------------------------------
# Tier 1: customers, rate cards, zones
# ---------------------------------------------------------------------------

def create_customer(name="Test Co", credit_limit_cents=DEFAULT_CREDIT_LIMIT):
    return get_success_data(
        api_client.create_customer(create_customer_payload(name, credit_limit_cents),
                                   BILLING))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, BILLING))


def patch_customer(customer_id, **fields):
    return get_success_data(api_client.patch_customer(customer_id, fields, BILLING))


def create_rate_card_for(customer, **overrides):
    """Create the customer's ACTIVE rate card; OCC-guarded on the live version."""
    fresh = get_customer(customer["id"])
    payload = create_rate_card_payload(customer["id"], fresh["version"], **overrides)
    return get_success_data(api_client.create_rate_card(payload, BILLING))


def create_customer_with_card(name="Test Co", credit_limit_cents=DEFAULT_CREDIT_LIMIT,
                              **card_overrides):
    """Onboard a customer and install their ACTIVE rate card."""
    customer = create_customer(name, credit_limit_cents)
    card = create_rate_card_for(customer, **card_overrides)
    return customer, card


def create_zone(zone_code="FZ-1", temp_class="FROZEN", capacity_pallets=10,
                dock_doors=2):
    return get_success_data(
        api_client.create_zone(
            create_zone_payload(zone_code, temp_class, capacity_pallets, dock_doors),
            OPERATOR))


def get_zone(zone_id):
    return get_success_data(api_client.get_zone(zone_id, OPERATOR))


# ---------------------------------------------------------------------------
# Tier 2: inbound receiving (schedule -> arrive -> complete)
# ---------------------------------------------------------------------------

def schedule_receipt(customer_id, zone_id, product_code="PEAS", lot_code="L1",
                     production_date="2026-01-15", temp_class="FROZEN",
                     expected_pallets=1, window_start="2026-08-02T08:00:00Z",
                     window_end="2026-08-02T10:00:00Z"):
    payload = create_receipt_payload(
        customer_id, zone_id, product_code, lot_code, production_date, temp_class,
        expected_pallets, window_start, window_end)
    return get_success_data(
        api_client.create_inbound_receipt(
            payload, make_customer_admin_headers(customer_id)))


def get_receipt(receipt_id):
    return get_success_data(api_client.get_inbound_receipt(receipt_id, OPERATOR))


def arrive_receipt(receipt_id):
    return get_success_data(api_client.arrive_inbound_receipt(receipt_id, OPERATOR))


def complete_receipt(receipt_id, actual_pallets):
    return get_success_data(
        api_client.complete_inbound_receipt(
            receipt_id, {"actual_pallets": actual_pallets}, OPERATOR))


def receive_stock(customer_id, zone_id, expected_pallets, actual_pallets=None,
                  **receipt_kwargs):
    """Full inbound chain: schedule -> arrive -> complete. Returns the COMPLETED
    receipt (whose lot_id names the upserted lot)."""
    receipt = schedule_receipt(customer_id, zone_id,
                               expected_pallets=expected_pallets, **receipt_kwargs)
    arrive_receipt(receipt["id"])
    return complete_receipt(receipt["id"],
                            actual_pallets if actual_pallets is not None
                            else expected_pallets)


def setup_stocked_account(customer_name="Stock Co",
                          credit_limit_cents=DEFAULT_CREDIT_LIMIT,
                          zone_code="FZ-1", temp_class="FROZEN", capacity_pallets=10,
                          dock_doors=2, pallets=2, product_code="PEAS", lot_code="L1",
                          production_date="2026-01-15", card_overrides=None,
                          clock=None, window_start="2026-08-02T08:00:00Z",
                          window_end="2026-08-02T10:00:00Z"):
    """Customer + ACTIVE card + zone + one COMPLETED receipt of `pallets` pallets.

    Returns a scenario dict: customer, card, zone, receipt, lot_id.
    """
    if clock is not None:
        set_clock(clock)
    customer, card = create_customer_with_card(customer_name, credit_limit_cents,
                                               **(card_overrides or {}))
    zone = create_zone(zone_code, temp_class, capacity_pallets, dock_doors)
    receipt = receive_stock(customer["id"], zone["id"], pallets,
                            product_code=product_code, lot_code=lot_code,
                            production_date=production_date, temp_class=temp_class,
                            window_start=window_start, window_end=window_end)
    return {
        "customer": customer,
        "card": card,
        "zone": zone,
        "receipt": receipt,
        "lot_id": receipt["lot_id"],
    }


# ---------------------------------------------------------------------------
# Tier 2: lots and pallets
# ---------------------------------------------------------------------------

def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, OPERATOR))


def list_lot_pallets(lot_id, limit=100):
    data, _meta = validate_paginated(
        api_client.list_pallets(OPERATOR, params={"lot_id": lot_id, "limit": limit}))
    return data


def get_pallet(pallet_id):
    return get_success_data(api_client.get_pallet(pallet_id, OPERATOR))


def release_quarantine(pallet_id, user_id="qm-1"):
    return get_success_data(
        api_client.release_pallet_quarantine(
            pallet_id, make_quality_manager_headers(user_id)))


def dispose_pallet(pallet_id, user_id="qm-1"):
    return get_success_data(
        api_client.dispose_pallet(pallet_id, make_quality_manager_headers(user_id)))


# ---------------------------------------------------------------------------
# Tier 3: outbound order lifecycle
# ---------------------------------------------------------------------------

def create_order(customer_id, product_code="PEAS", requested_pallets=1, lot_code=None):
    payload = create_order_payload(customer_id, product_code, requested_pallets,
                                   lot_code)
    return get_success_data(
        api_client.create_outbound_order(
            payload, make_customer_admin_headers(customer_id)))


def get_order(order_id):
    return get_success_data(api_client.get_outbound_order(order_id, OPERATOR))


def submit_order(order_id, customer_id):
    return get_success_data(
        api_client.submit_outbound_order(
            order_id, make_customer_admin_headers(customer_id)))


def allocate_order(order_id):
    return get_success_data(api_client.allocate_outbound_order(order_id, OPERATOR))


def ship_order(order_id):
    return get_success_data(api_client.ship_outbound_order(order_id, OPERATOR))


def cancel_order(order_id, customer_id):
    return get_success_data(
        api_client.cancel_outbound_order(
            order_id, make_customer_admin_headers(customer_id)))


def create_submitted_order(customer_id, requested_pallets, product_code="PEAS",
                           lot_code=None):
    order = create_order(customer_id, product_code, requested_pallets, lot_code)
    return submit_order(order["id"], customer_id)


def create_allocated_order(customer_id, requested_pallets, product_code="PEAS",
                           lot_code=None):
    order = create_submitted_order(customer_id, requested_pallets, product_code,
                                   lot_code)
    return allocate_order(order["id"])


def list_order_allocations(order_id):
    data, _meta = validate_paginated(
        api_client.list_allocations(OPERATOR, params={"order_id": order_id}))
    return data


def release_allocation(allocation_id):
    return get_success_data(api_client.release_allocation(allocation_id, OPERATOR))


# ---------------------------------------------------------------------------
# Tier 3: blast freezing
# ---------------------------------------------------------------------------

def create_cell(cell_code="BC-1", capacity_pallets=5, turnaround_minutes=30):
    return get_success_data(
        api_client.create_blast_freeze_cell(
            create_cell_payload(cell_code, capacity_pallets, turnaround_minutes),
            OPERATOR))


def create_booking(cell_id, lot_id, pallet_count=1,
                   window_start="2026-08-05T10:00:00Z",
                   window_end="2026-08-05T12:00:00Z"):
    return get_success_data(
        api_client.create_blast_freeze_booking(
            create_booking_payload(cell_id, lot_id, pallet_count, window_start,
                                   window_end),
            OPERATOR))


def get_booking(booking_id):
    return get_success_data(api_client.get_blast_freeze_booking(booking_id, OPERATOR))


def start_booking(booking_id):
    return get_success_data(api_client.start_blast_freeze_booking(booking_id, OPERATOR))


def complete_booking(booking_id):
    return get_success_data(
        api_client.complete_blast_freeze_booking(booking_id, OPERATOR))


def cancel_booking(booking_id):
    return get_success_data(api_client.cancel_blast_freeze_booking(booking_id, OPERATOR))


def list_cell_bookings(cell_id):
    data, _meta = validate_paginated(
        api_client.list_blast_freeze_bookings(OPERATOR, params={"cell_id": cell_id}))
    return data


# ---------------------------------------------------------------------------
# Tier 3: temperature excursions
# ---------------------------------------------------------------------------

def report_excursion(zone_id, observed_temp_c=-2.0,
                     window_start="2026-08-03T00:00:00Z",
                     window_end="2026-08-04T00:00:00Z", reporter_user_id="op-1"):
    payload = create_excursion_payload(zone_id, observed_temp_c, window_start,
                                       window_end)
    return get_success_data(
        api_client.create_temperature_excursion(
            payload, make_warehouse_operator_headers(reporter_user_id)))


def confirm_excursion(excursion_id, confirmer_user_id="qm-1"):
    return get_success_data(
        api_client.confirm_temperature_excursion(
            excursion_id, make_quality_manager_headers(confirmer_user_id)))


def get_excursion(excursion_id):
    return get_success_data(api_client.get_temperature_excursion(excursion_id, QUALITY))


def setup_confirmed_excursion(sc, observed_temp_c=-2.0,
                              window_start="2026-08-03T00:00:00Z",
                              window_end="2026-08-04T00:00:00Z", reporter="op-1",
                              confirmer="qm-1"):
    """Report and confirm an excursion on the scenario's zone. Mutates and
    returns the scenario dict with an added `excursion` key."""
    excursion = report_excursion(sc["zone"]["id"], observed_temp_c, window_start,
                                 window_end, reporter_user_id=reporter)
    confirm_excursion(excursion["id"], confirmer_user_id=confirmer)
    sc["excursion"] = get_excursion(excursion["id"])
    return sc


# ---------------------------------------------------------------------------
# Tier 3: recalls
# ---------------------------------------------------------------------------

def declare_recall(customer_id, product_code="PEAS", lot_code="L1",
                   reason="quality hold"):
    return get_success_data(
        api_client.create_recall(
            create_recall_payload(customer_id, product_code, lot_code, reason),
            QUALITY))


def activate_recall(recall_id):
    return get_success_data(api_client.activate_recall(recall_id, QUALITY))


def get_recall(recall_id):
    return get_success_data(api_client.get_recall(recall_id, QUALITY))


# ---------------------------------------------------------------------------
# Tier 3: claims
# ---------------------------------------------------------------------------

def file_claim(customer_id, excursion_id, affected_pallet_count=1,
               declared_value_cents=10_000):
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(customer_id, excursion_id, affected_pallet_count,
                                 declared_value_cents),
            make_customer_admin_headers(customer_id)))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, BILLING))


def review_claim(claim_id):
    return get_success_data(api_client.review_claim(claim_id, ADJUSTER))


def decide_claim(claim_id, decision):
    return get_success_data(
        api_client.decide_claim(claim_id, {"decision": decision}, ADJUSTER))


def settle_claim(claim_id):
    return get_success_data(api_client.settle_claim(claim_id, BILLING))


# ---------------------------------------------------------------------------
# Tier 4: invoices and the billing checkpoint
# ---------------------------------------------------------------------------

def list_invoices(customer_id=None, status=None):
    params = {}
    if customer_id is not None:
        params["customer_id"] = customer_id
    if status is not None:
        params["status"] = status
    data, _meta = validate_paginated(api_client.list_invoices(BILLING, params=params))
    return data


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, BILLING))


def get_open_invoice(customer_id):
    """The customer's single OPEN invoice (PRD §2.10)."""
    invoices = list_invoices(customer_id, status="OPEN")
    assert len(invoices) == 1, (
        f"Expected exactly one OPEN invoice, got {len(invoices)}")
    return invoices[0]


def get_finalized_invoices(customer_id):
    """FINALIZED invoices sorted created_at ASC (PRD §3.9 listing order)."""
    return list_invoices(customer_id, status="FINALIZED")


def run_billing():
    return get_success_data(api_client.run_billing(BILLING))


def finalize_due_invoices(at="2026-09-01T00:00:00Z"):
    """Advance the clock and run the billing checkpoint."""
    set_clock(at)
    return run_billing()
