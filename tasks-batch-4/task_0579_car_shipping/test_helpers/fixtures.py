"""Composite setup helpers for multi-step test prerequisites.

The test harness restarts the API server (empty database) before every test, so
every fixture builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so a broken
precondition surfaces as a clear "Setup step failed" error.

Identity threading (PRD §2.1): after creating an entity-backed Shipper or Carrier,
ownership-gated calls MUST use make_shipper_headers(shipper["id"]) /
make_carrier_headers(carrier["id"]) — never the shared TEST_USERS constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_carrier_payload,
    create_claim_payload,
    create_inspection_payload,
    create_ledger_entry_payload,
    create_listing_payload,
    create_offer_payload,
    create_order_payload,
    create_quote_payload,
    create_shipper_payload,
    create_terminal_payload,
    create_vehicle_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_headers,
    make_shipper_headers,
)

# Default pickup window / eta shared across most orders (clock default 2026-05-01).
DEFAULT_PICKUP_WINDOW_START = "2026-06-01T08:00:00Z"
DEFAULT_PICKUP_WINDOW_END = "2026-06-05T18:00:00Z"
DEFAULT_PICKUP_ETA = "2026-06-02T09:00:00Z"
DEFAULT_INSURANCE_EXPIRY = "2027-01-01T00:00:00Z"

# Monotonic counter for unique emails / mc_numbers (the DB resets per test, but
# uniqueness within a test's DB is guaranteed by never repeating a value).
_uniq = itertools.count(1)


# ─── Tier 0: Singletons ────────────────────────────────────────────────────

def set_clock(iso8601: str) -> None:
    """Set the server logical clock (Admin-only, PRD §2.6)."""
    get_success_data(api_client.set_clock(iso8601, TEST_USERS["admin_headers"]))


# ─── Tier 1: Single-entity creation ────────────────────────────────────────

def register_shipper(email=None, full_name="Test Shipper") -> dict:
    """Register a shipper (via Admin)."""
    if email is None:
        email = f"shipper{next(_uniq)}@x.com"
    payload = create_shipper_payload(email=email, full_name=full_name)
    return get_success_data(api_client.create_shipper(payload, TEST_USERS["admin_headers"]))


def register_carrier(
    equipment_type="OPEN",
    cargo_insurance_limit_cents=3_000_000,
    insurance_expiry_date=DEFAULT_INSURANCE_EXPIRY,
    legal_name="Test Carrier",
    mc_number=None,
    rating=None,
) -> dict:
    """Register a carrier onto the load board (via Broker)."""
    if mc_number is None:
        mc_number = f"MC-{next(_uniq):06d}"
    payload = create_carrier_payload(
        legal_name=legal_name,
        mc_number=mc_number,
        cargo_insurance_limit_cents=cargo_insurance_limit_cents,
        insurance_expiry_date=insurance_expiry_date,
        equipment_type=equipment_type,
        rating=rating,
    )
    return get_success_data(api_client.create_carrier(payload, TEST_USERS["broker_headers"]))


def register_terminal(dock_count=1, buffer_minutes=60, name="Test Terminal", dock_zip="90001") -> dict:
    """Register a terminal facility (via Broker)."""
    payload = create_terminal_payload(
        name=name, dock_zip=dock_zip, dock_count=dock_count, buffer_minutes=buffer_minutes
    )
    return get_success_data(api_client.create_terminal(payload, TEST_USERS["broker_headers"]))


def create_order(
    shipper_id,
    route_miles=1200,
    transport_type="OPEN",
    service_level=None,
    delivery_mode=None,
    pickup_window_start=DEFAULT_PICKUP_WINDOW_START,
    pickup_window_end=DEFAULT_PICKUP_WINDOW_END,
    terminal_id=None,
    terminal_slot_start=None,
    terminal_slot_end=None,
) -> dict:
    """Create a DRAFT order owned by shipper_id (ownership-gated: shipper headers)."""
    payload = create_order_payload(
        route_miles=route_miles,
        transport_type=transport_type,
        service_level=service_level,
        delivery_mode=delivery_mode,
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end,
        terminal_id=terminal_id,
        terminal_slot_start=terminal_slot_start,
        terminal_slot_end=terminal_slot_end,
    )
    return get_success_data(api_client.create_order(payload, make_shipper_headers(shipper_id)))


def attach_vehicle(order_id, shipper_id, declared_value_cents=1_000_000, is_inoperable=None,
                   make="Honda", model="Civic", year=2020) -> dict:
    """Attach a vehicle to a DRAFT order (bumps order.version by 1)."""
    payload = create_vehicle_payload(
        make=make, model=model, year=year,
        declared_value_cents=declared_value_cents, is_inoperable=is_inoperable,
    )
    return get_success_data(api_client.create_vehicle(order_id, payload, make_shipper_headers(shipper_id)))


def read_order(order_id, shipper_id=None) -> dict:
    """Read an order (uses shipper headers when given, else Admin)."""
    headers = make_shipper_headers(shipper_id) if shipper_id else TEST_USERS["admin_headers"]
    return get_success_data(api_client.get_order(order_id, headers))


def get_carrier(carrier_id) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, TEST_USERS["admin_headers"]))


def get_offer(offer_id) -> dict:
    return get_success_data(api_client.get_offer(offer_id, TEST_USERS["admin_headers"]))


def get_listing(listing_id) -> dict:
    return get_success_data(api_client.get_listing(listing_id, TEST_USERS["admin_headers"]))


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, TEST_USERS["admin_headers"]))


def get_claim(claim_id) -> dict:
    return get_success_data(api_client.get_claim(claim_id, TEST_USERS["admin_headers"]))


def list_order_ledger(order_id) -> list:
    """Return all POSTED/VOIDED ledger entries for an order (Admin read)."""
    return get_success_data(
        api_client.list_ledger_entries(TEST_USERS["admin_headers"], params={"order_id": order_id, "limit": 100})
    )


def generate_quote(order_id, shipper_id, expected_order_version=None) -> dict:
    """Generate an OFFERED quote. Reads the current order.version when the caller
    does not pin expected_order_version explicitly (OCC, PRD §2.7)."""
    if expected_order_version is None:
        expected_order_version = read_order(order_id, shipper_id)["version"]
    payload = create_quote_payload(expected_order_version)
    return get_success_data(api_client.create_quote(order_id, payload, make_shipper_headers(shipper_id)))


def accept_quote(order_id, quote_id, shipper_id) -> dict:
    """Accept an OFFERED quote (DRAFT->QUOTED). Returns the updated order."""
    return get_success_data(api_client.accept_quote(order_id, quote_id, make_shipper_headers(shipper_id)))


def post_ledger(order_id, kind, amount_cents, headers=None) -> dict:
    """Post a ledger entry (Broker/Admin)."""
    headers = headers or TEST_USERS["broker_headers"]
    payload = create_ledger_entry_payload(kind, amount_cents)
    return get_success_data(api_client.create_ledger_entry(order_id, payload, headers))


def create_listing(order_id, offered_carrier_pay_cents=50000) -> dict:
    """Post a QUOTED order to the load board (QUOTED->LISTED)."""
    payload = create_listing_payload(offered_carrier_pay_cents=offered_carrier_pay_cents)
    return get_success_data(api_client.create_listing(order_id, payload, TEST_USERS["broker_headers"]))


def post_offer(listing_id, carrier_id, ask_pay_cents=50000, pickup_eta=DEFAULT_PICKUP_ETA) -> dict:
    """Carrier bids on an OPEN listing (ownership-gated: carrier headers)."""
    payload = create_offer_payload(ask_pay_cents=ask_pay_cents, pickup_eta=pickup_eta)
    return get_success_data(api_client.create_offer(listing_id, payload, make_carrier_headers(carrier_id)))


def accept_offer(listing_id, offer_id) -> dict:
    """Broker awards the load (LISTED->DISPATCHED). Returns the Assignment."""
    return get_success_data(api_client.accept_offer(listing_id, offer_id, TEST_USERS["broker_headers"]))


def suspend_carrier(carrier_id) -> dict:
    """Admin suspends a carrier."""
    return get_success_data(api_client.suspend_carrier(carrier_id, TEST_USERS["admin_headers"]))


def record_inspection(order_id, carrier_id, phase, odometer=10000, damage_count=None,
                      observed_inoperable_count=None) -> dict:
    """Record a BOL inspection (ownership-gated: assigned carrier's headers)."""
    payload = create_inspection_payload(
        phase, odometer=odometer, damage_count=damage_count,
        observed_inoperable_count=observed_inoperable_count,
    )
    return get_success_data(api_client.create_inspection(order_id, payload, make_carrier_headers(carrier_id)))


def file_claim(order_id, shipper_id, claimed_cents) -> dict:
    """Shipper files a damage claim (ownership-gated: shipper headers)."""
    payload = create_claim_payload(claimed_cents)
    return get_success_data(api_client.create_claim(order_id, payload, make_shipper_headers(shipper_id)))


# ─── Tier 2: Order lifecycle composites ────────────────────────────────────

def _attach_vehicles(order_id, shipper_id, vehicles, num_vehicles, declared_value_cents):
    if vehicles is None:
        vehicles = [{"declared_value_cents": declared_value_cents} for _ in range(num_vehicles)]
    for spec in vehicles:
        attach_vehicle(order_id, shipper_id, **spec)


def setup_order_with_offered_quote(
    route_miles=1200, transport_type="OPEN", service_level=None,
    vehicles=None, num_vehicles=1, declared_value_cents=1_000_000, attach=True,
) -> dict:
    """DRAFT order + (optional vehicles) + one generated OFFERED quote (not accepted).

    Returns {shipper, order, quote}. The order remains in DRAFT."""
    shipper = register_shipper()
    order = create_order(shipper["id"], route_miles=route_miles,
                         transport_type=transport_type, service_level=service_level)
    if attach:
        _attach_vehicles(order["id"], shipper["id"], vehicles, num_vehicles, declared_value_cents)
    quote = generate_quote(order["id"], shipper["id"])
    return {"shipper": shipper, "order": order, "quote": quote}


def setup_quoted_order(
    route_miles=1200, transport_type="OPEN", service_level=None,
    vehicles=None, num_vehicles=1, declared_value_cents=1_000_000,
) -> dict:
    """Order advanced to QUOTED via an accepted quote (no deposit yet).

    Returns {shipper, order (QUOTED), quote}."""
    ctx = setup_order_with_offered_quote(
        route_miles=route_miles, transport_type=transport_type, service_level=service_level,
        vehicles=vehicles, num_vehicles=num_vehicles, declared_value_cents=declared_value_cents,
    )
    order = accept_quote(ctx["order"]["id"], ctx["quote"]["id"], ctx["shipper"]["id"])
    ctx["order"] = order
    return ctx


def setup_listed_order(
    route_miles=1200, transport_type="OPEN", service_level=None,
    vehicles=None, num_vehicles=1, declared_value_cents=1_000_000,
    deposit_cents=20000, offered_carrier_pay_cents=50000,
) -> dict:
    """Order advanced to LISTED: quoted, deposit paid, posted to the load board.

    Returns {shipper, order (LISTED), quote, deposit, listing}."""
    ctx = setup_quoted_order(
        route_miles=route_miles, transport_type=transport_type, service_level=service_level,
        vehicles=vehicles, num_vehicles=num_vehicles, declared_value_cents=declared_value_cents,
    )
    deposit = post_ledger(ctx["order"]["id"], "DEPOSIT", deposit_cents)
    listing = create_listing(ctx["order"]["id"], offered_carrier_pay_cents=offered_carrier_pay_cents)
    ctx["deposit"] = deposit
    ctx["listing"] = listing
    ctx["order"] = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    return ctx


def setup_pending_offer(
    carrier_equipment_type="OPEN", carrier_insurance_limit_cents=3_000_000,
    carrier_insurance_expiry=DEFAULT_INSURANCE_EXPIRY,
    ask_pay_cents=50000, pickup_eta=DEFAULT_PICKUP_ETA, **listed_kwargs,
) -> dict:
    """LISTED order with a registered carrier and one PENDING offer on the listing.

    Returns setup_listed_order() context plus {carrier, offer}."""
    ctx = setup_listed_order(**listed_kwargs)
    carrier = register_carrier(
        equipment_type=carrier_equipment_type,
        cargo_insurance_limit_cents=carrier_insurance_limit_cents,
        insurance_expiry_date=carrier_insurance_expiry,
    )
    offer = post_offer(ctx["listing"]["id"], carrier["id"], ask_pay_cents=ask_pay_cents, pickup_eta=pickup_eta)
    ctx["carrier"] = carrier
    ctx["offer"] = offer
    return ctx


def setup_dispatched_order(**kwargs) -> dict:
    """Order awarded to the carrier (DISPATCHED) with an Assignment.

    Returns setup_pending_offer() context plus {assignment}."""
    ctx = setup_pending_offer(**kwargs)
    assignment = accept_offer(ctx["listing"]["id"], ctx["offer"]["id"])
    ctx["assignment"] = assignment
    ctx["order"] = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    return ctx


def setup_delivered_order(
    pickup_observed_inoperable=0, delivery_damage_count=0, **kwargs,
) -> dict:
    """Order carried through PICKUP + DELIVERY inspections to DELIVERED.

    The PICKUP inspection records pickup_observed_inoperable (feeds settlement);
    the DELIVERY inspection records delivery_damage_count (enables claim approval).
    Returns setup_dispatched_order() context plus {pickup_inspection, delivery_inspection}."""
    ctx = setup_dispatched_order(**kwargs)
    ctx["pickup_inspection"] = record_inspection(
        ctx["order"]["id"], ctx["carrier"]["id"], "PICKUP",
        odometer=10000, observed_inoperable_count=pickup_observed_inoperable,
    )
    ctx["delivery_inspection"] = record_inspection(
        ctx["order"]["id"], ctx["carrier"]["id"], "DELIVERY",
        odometer=10120, damage_count=delivery_damage_count,
    )
    ctx["order"] = read_order(ctx["order"]["id"], ctx["shipper"]["id"])
    return ctx


# ─── Tier 3: Cross-order helpers (shared carrier across two orders) ─────────

def dispatch_order_for_carrier(
    shipper_id, carrier_id, route_miles=1200, declared_value_cents=1_000_000,
    pickup_window_start=DEFAULT_PICKUP_WINDOW_START, pickup_window_end=DEFAULT_PICKUP_WINDOW_END,
    pickup_eta=DEFAULT_PICKUP_ETA, deposit_cents=20000, offered_carrier_pay_cents=50000,
    ask_pay_cents=50000,
) -> dict:
    """Build a fresh order and DISPATCH it to an existing carrier.

    Returns {order, quote, listing, offer, assignment}."""
    order = create_order(shipper_id, route_miles=route_miles, transport_type="OPEN",
                         pickup_window_start=pickup_window_start, pickup_window_end=pickup_window_end)
    attach_vehicle(order["id"], shipper_id, declared_value_cents=declared_value_cents)
    quote = generate_quote(order["id"], shipper_id)
    accept_quote(order["id"], quote["id"], shipper_id)
    post_ledger(order["id"], "DEPOSIT", deposit_cents)
    listing = create_listing(order["id"], offered_carrier_pay_cents=offered_carrier_pay_cents)
    offer = post_offer(listing["id"], carrier_id, ask_pay_cents=ask_pay_cents, pickup_eta=pickup_eta)
    assignment = accept_offer(listing["id"], offer["id"])
    return {
        "order": read_order(order["id"], shipper_id),
        "quote": quote, "listing": listing, "offer": offer, "assignment": assignment,
    }


def list_pending_offer_for_carrier(
    shipper_id, carrier_id, route_miles=1200, declared_value_cents=1_000_000,
    pickup_window_start=DEFAULT_PICKUP_WINDOW_START, pickup_window_end=DEFAULT_PICKUP_WINDOW_END,
    pickup_eta=DEFAULT_PICKUP_ETA, deposit_cents=20000, offered_carrier_pay_cents=50000,
    ask_pay_cents=50000,
) -> dict:
    """Build a fresh order to LISTED with a PENDING offer from an existing carrier
    (no award). Returns {order, quote, listing, offer}."""
    order = create_order(shipper_id, route_miles=route_miles, transport_type="OPEN",
                         pickup_window_start=pickup_window_start, pickup_window_end=pickup_window_end)
    attach_vehicle(order["id"], shipper_id, declared_value_cents=declared_value_cents)
    quote = generate_quote(order["id"], shipper_id)
    accept_quote(order["id"], quote["id"], shipper_id)
    post_ledger(order["id"], "DEPOSIT", deposit_cents)
    listing = create_listing(order["id"], offered_carrier_pay_cents=offered_carrier_pay_cents)
    offer = post_offer(listing["id"], carrier_id, ask_pay_cents=ask_pay_cents, pickup_eta=pickup_eta)
    return {
        "order": read_order(order["id"], shipper_id),
        "quote": quote, "listing": listing, "offer": offer,
    }
