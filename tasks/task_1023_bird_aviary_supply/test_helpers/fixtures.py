"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors rather than confusing assertion failures.

The test harness resets the database before every individual test, so each helper
builds its preconditions from scratch using only PRD-declared endpoints.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_species_payload, create_permit_payload,
    create_bird_payload, create_cage_payload, create_reservation_payload,
    create_station_payload, create_appointment_payload, create_subscription_payload,
    create_inventory_item_payload, create_special_order_payload,
)
from .test_users import TEST_USERS, make_customer_headers

SM = TEST_USERS["store_manager_headers"]
STAFF = TEST_USERS["aviary_staff_headers"]
CO = TEST_USERS["compliance_officer_headers"]

_counter = itertools.count(1)


def _uid() -> int:
    return next(_counter)


# ─── Atomic entity builders ───────────────────────────────────────────────

def new_customer(wallet_cents: int = 0, club_tier: str = None, suspended: bool = False) -> dict:
    """Create a customer, optionally topping up the wallet, setting a club tier,
    and/or suspending. Returns the freshest customer view."""
    n = _uid()
    cust = get_success_data(api_client.create_customer(
        create_customer_payload(full_name=f"Cust {n}", email=f"cust{n}@x.com"), SM))
    cid = cust["id"]
    if club_tier:
        cust = get_success_data(api_client.set_club_membership(cid, {"club_tier": club_tier}, SM))
    if wallet_cents:
        cust = get_success_data(api_client.adjust_wallet(cid, {"amount_cents": wallet_cents}, SM))
    if suspended:
        cust = get_success_data(api_client.suspend_customer(cid, SM))
    return cust


def new_inventory(feed_kind: str = "DRY", on_hand: int = 10) -> dict:
    n = _uid()
    return get_success_data(api_client.create_inventory_item(
        create_inventory_item_payload(sku=f"SKU-{n}", feed_kind=feed_kind, quantity_on_hand=on_hand), SM))


def new_housing_cage(capacity: int = 1) -> dict:
    n = _uid()
    return get_success_data(api_client.create_cage(
        create_cage_payload(label=f"H{n}", cage_class="HOUSING", capacity=capacity), SM))


def new_boarding_cage(capacity: int = 1, nightly_rate_cents: int = 3000) -> dict:
    n = _uid()
    return get_success_data(api_client.create_cage(
        create_cage_payload(label=f"B{n}", cage_class="BOARDING", capacity=capacity,
                            nightly_rate_cents=nightly_rate_cents), SM))


def new_species(cites_appendix: str = "NONE") -> dict:
    n = _uid()
    return get_success_data(api_client.create_species(
        create_species_payload(common_name=f"Species {n}",
                               scientific_name=f"Testus specus{n}",
                               cites_appendix=cites_appendix), SM_CO()))


def SM_CO():
    # species/permits are ComplianceOfficer-owned
    return CO


def new_bird(species_id: str, imported: bool = False, list_price_cents: int = 50000) -> dict:
    n = _uid()
    payload = create_bird_payload(species_id, band_code=f"BAND-{n}", list_price_cents=list_price_cents)
    if imported:
        payload["imported"] = True
    return get_success_data(api_client.create_bird(payload, STAFF))


def new_station(service_types=None) -> dict:
    n = _uid()
    return get_success_data(api_client.create_station(
        create_station_payload(label=f"G{n}", service_types=service_types or ["WING_TRIM", "NAIL_TRIM"]), SM))


def set_clock(iso: str) -> None:
    get_success_data(api_client.set_clock(iso, SM))


# ─── Permit lifecycle ─────────────────────────────────────────────────────

def approved_permit_for_species(species_id: str, valid_until: str = "2027-01-01T00:00:00Z") -> dict:
    """Create a permit, submit, and approve it. Approval also sets Species.status ACTIVE.
    Returns the APPROVED permit."""
    n = _uid()
    permit = get_success_data(api_client.create_permit(
        create_permit_payload(species_id, permit_number=f"CITES-{n}", valid_until=valid_until), CO))
    api_client.submit_permit(permit["id"], CO)
    return get_success_data(api_client.approve_permit(permit["id"], CO))


# ─── Quarantine setup ─────────────────────────────────────────────────────

def qr_id_for_bird(bird_id: str) -> str:
    recs = get_success_data(api_client.list_bird_quarantine_records(bird_id, STAFF))
    return recs[0]["id"]


def open_quarantine(cites_appendix: str = "NONE", imported: bool = False,
                    housing_capacity: int = 1, opened_clock: str = "2026-07-01T00:00:00Z") -> dict:
    """Create species + HOUSING cage + bird, advance the clock to `opened_clock`, and
    start quarantine (opening an OPEN QuarantineRecord). Returns dict with keys:
    species, cage, bird (post-start-quarantine, carries provisional_risk_score), qr_id."""
    species = new_species(cites_appendix)
    cage = new_housing_cage(capacity=housing_capacity)
    bird = new_bird(species["id"], imported=imported)
    set_clock(opened_clock)
    bird = get_success_data(api_client.start_quarantine(bird["id"], {"cage_id": cage["id"]}, STAFF))
    return {"species": species, "cage": cage, "bird": bird, "qr_id": qr_id_for_bird(bird["id"])}


def setup_listed_bird(cites_appendix: str = "II",
                      opened_clock: str = "2026-07-01T00:00:00Z",
                      clear_clock: str = "2026-07-16T00:00:00Z") -> dict:
    """Full path to a LISTED bird of a permit-required species with an APPROVED permit.
    Returns dict: species, permit, cage, bird (LISTED), qr_id."""
    set_clock(opened_clock)
    species = new_species(cites_appendix)
    permit = approved_permit_for_species(species["id"])
    cage = new_housing_cage(capacity=1)
    bird = new_bird(species["id"])
    get_success_data(api_client.start_quarantine(bird["id"], {"cage_id": cage["id"]}, STAFF))
    qr_id = qr_id_for_bird(bird["id"])
    set_clock(clear_clock)
    get_success_data(api_client.clear_quarantine(qr_id, STAFF))
    bird = get_success_data(api_client.list_bird_for_sale(bird["id"], STAFF))
    return {"species": species, "permit": permit, "cage": cage, "bird": bird, "qr_id": qr_id}


# ─── Boarding setup ───────────────────────────────────────────────────────

def new_reservation(customer_id: str, cage_id: str,
                    planned_check_in: str, planned_check_out: str) -> dict:
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(customer_id, cage_id,
                                   planned_check_in=planned_check_in,
                                   planned_check_out=planned_check_out),
        make_customer_headers(customer_id)))


# ─── Special order setup ──────────────────────────────────────────────────

def new_special_order(customer_id: str, cage_item_id: str,
                      build_qty: int = 1, line_items=None) -> dict:
    payload = create_special_order_payload(customer_id, cage_item_id, build_qty=build_qty)
    if line_items is not None:
        payload["line_items"] = line_items
    return get_success_data(api_client.create_special_order(payload, make_customer_headers(customer_id)))


def setup_paid_cancelled_order(wallet_cents: int = 5000, invoice_line=None) -> dict:
    """Customer with wallet; DRY inventory; order created, PAID, then build CANCELLED.
    Returns dict: customer, inventory, order."""
    cust = new_customer(wallet_cents=wallet_cents)
    inv = new_inventory("DRY", on_hand=5)
    line = invoice_line or [{"unit_price_cents": 1000, "quantity": 1, "tax_rate": 0.0}]
    order = new_special_order(cust["id"], inv["id"], build_qty=1, line_items=line)
    api_client.pay_order(order["id"], make_customer_headers(cust["id"]))
    order = get_success_data(api_client.cancel_build(order["id"], SM))
    return {"customer": cust, "inventory": inv, "order": order}


# ─── Grooming setup ───────────────────────────────────────────────────────

def new_appointment(customer_id: str, station_id: str, service_type: str,
                    slot_start: str, slot_end: str, fee_cents: int = 1500) -> dict:
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(customer_id, station_id, service_type=service_type,
                                   slot_start=slot_start, slot_end=slot_end, fee_cents=fee_cents),
        make_customer_headers(customer_id)))
