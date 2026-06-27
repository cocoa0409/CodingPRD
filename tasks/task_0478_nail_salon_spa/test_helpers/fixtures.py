"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so the DB always starts
empty). Fixtures use get_success_data() so a setup failure surfaces as a clear
"Setup failed" rather than a confusing downstream assertion error.

Identity threading: the Technician role is entity_backed, so any ownership-gated
call (start-service on the technician's own appointment, recording sanitation)
uses make_technician_headers(technician_id) with the real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_client_headers,
)
from . import factories as F

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=MANAGER):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def make_station(requires_autoclave=False, **overrides):
    """Create a station. Returns the Station dict."""
    payload = F.create_station_payload(requires_autoclave=requires_autoclave, **overrides)
    return get_success_data(api_client.create_station(payload, MANAGER))


def make_menu_item(base_price_cents=4500, duration_minutes=45,
                   loyalty_points_award=0, requires_sterile_station=False,
                   category="MANICURE", **overrides):
    """Create a service menu item. Returns the ServiceMenuItem dict."""
    payload = F.create_menu_item_payload(
        base_price_cents=base_price_cents, duration_minutes=duration_minutes,
        loyalty_points_award=loyalty_points_award,
        requires_sterile_station=requires_sterile_station, category=category, **overrides,
    )
    return get_success_data(api_client.create_menu_item(payload, MANAGER))


def make_add_on(price_cents=1500, extra_minutes=0, **overrides):
    """Create an add-on. Returns the AddOn dict."""
    payload = F.create_add_on_payload(
        price_cents=price_cents, extra_minutes=extra_minutes, **overrides
    )
    return get_success_data(api_client.create_add_on(payload, MANAGER))


def make_technician(home_station_id, pay_model="COMMISSION", commission_pct=0.40,
                    booth_rent_cents=None, license_expiry="2027-01-01T00:00:00Z",
                    **overrides):
    """Create a technician. Returns the Technician dict."""
    payload = F.create_technician_payload(
        home_station_id, pay_model=pay_model, commission_pct=commission_pct,
        license_expiry=license_expiry, **overrides,
    )
    if pay_model == "BOOTH_RENT" and booth_rent_cents is not None:
        payload["booth_rent_cents"] = booth_rent_cents
        payload.pop("commission_pct", None)
    return get_success_data(api_client.create_technician(payload, MANAGER))


def make_client(**overrides):
    """Register a client. Returns the Client dict."""
    payload = F.create_client_payload(**overrides)
    return get_success_data(api_client.create_client(payload, FRONT_DESK))


def make_gift_card(initial_balance_cents=5000, purchaser_client_id=None, **overrides):
    """Issue a gift card. Returns the GiftCard dict."""
    payload = F.create_gift_card_payload(
        initial_balance_cents=initial_balance_cents, **overrides
    )
    if purchaser_client_id is not None:
        payload["purchaser_client_id"] = purchaser_client_id
    return get_success_data(api_client.create_gift_card(payload, FRONT_DESK))


def record_pass_sanitation(station_id, technician_id, cycle_temp_c=134.0,
                           hold_minutes=30):
    """Record a PASS autoclave cycle (recomputes the station to CLEAN). The
    logging technician acts on their own behalf (entity_backed)."""
    payload = F.create_sanitation_log_payload(
        station_id, technician_id, cycle_result="PASS",
        cycle_temp_c=cycle_temp_c, hold_minutes=hold_minutes,
    )
    return get_success_data(
        api_client.create_sanitation_log(payload, make_technician_headers(technician_id))
    )


def inject_client_state(client_id, **overrides):
    """Set a client's strike/loyalty ledger to a baseline (PRD §3.17)."""
    payload = F.inject_client_state_payload(client_id, **overrides)
    return get_success_data(api_client.inject_client_state(payload, MANAGER))


def inject_appointment_deposit(appointment_id, deposit_due_cents):
    """Force a specific deposit_due_cents on a REQUESTED appointment (PRD §3.17)."""
    payload = F.inject_appointment_deposit_payload(appointment_id, deposit_due_cents)
    return get_success_data(api_client.inject_appointment_deposit(payload, MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: Base configuration — station + menu + technician + client
# ---------------------------------------------------------------------------
def setup_base(base_price_cents=4500, duration_minutes=45, loyalty_points_award=0,
               requires_autoclave=False, requires_sterile_station=False,
               pay_model="COMMISSION", commission_pct=0.40, booth_rent_cents=None,
               license_expiry="2027-01-01T00:00:00Z", category="MANICURE"):
    """Create one station, one menu item, one technician, one client.
    Returns dict with keys: station, menu, technician, client."""
    station = make_station(requires_autoclave=requires_autoclave)
    menu = make_menu_item(
        base_price_cents=base_price_cents, duration_minutes=duration_minutes,
        loyalty_points_award=loyalty_points_award,
        requires_sterile_station=requires_sterile_station, category=category,
    )
    tech = make_technician(
        station["id"], pay_model=pay_model, commission_pct=commission_pct,
        booth_rent_cents=booth_rent_cents, license_expiry=license_expiry,
    )
    client = make_client()
    return {"station": station, "menu": menu, "technician": tech, "client": client}


# ---------------------------------------------------------------------------
# Tier 1/3: Appointment lifecycle progression
# ---------------------------------------------------------------------------
def book_appointment(client_id, technician_id, station_id, service_item_id,
                     origin="APPOINTMENT", start_at=None):
    """Book a REQUESTED appointment. Returns the Appointment dict."""
    payload = F.create_appointment_payload(
        client_id, technician_id, station_id, service_item_id,
        origin=origin, start_at=start_at,
    )
    return get_success_data(api_client.create_appointment(payload, FRONT_DESK))


def attach_add_on(appointment_id, add_on_id, expected_version):
    """Attach an add-on to a REQUESTED appointment (bumps appointment version)."""
    payload = F.attach_add_on_payload(add_on_id, expected_version)
    return get_success_data(api_client.attach_add_on(appointment_id, payload, FRONT_DESK))


def confirm(appointment_id):
    return get_success_data(api_client.confirm_appointment(appointment_id, FRONT_DESK))


def check_in(appointment_id):
    return get_success_data(api_client.check_in_appointment(appointment_id, FRONT_DESK))


def start_service(appointment_id, technician_id):
    """Begin service. The technician acts on their own appointment (entity_backed)."""
    return get_success_data(
        api_client.start_service(appointment_id, make_technician_headers(technician_id))
    )


def drive_to_in_service(client_id, technician_id, station_id, service_item_id,
                        origin="APPOINTMENT", start_at=None, add_on_ids=None):
    """Book -> (attach add-ons) -> confirm -> check-in -> start-service.
    Returns the IN_SERVICE Appointment dict (carries the live version).
    Requires the station to already be CLEAN if sterilization is required."""
    appt = book_appointment(client_id, technician_id, station_id, service_item_id,
                            origin=origin, start_at=start_at)
    version = appt["version"]
    for add_on_id in (add_on_ids or []):
        attached = attach_add_on(appt["id"], add_on_id, version)
        # Re-read the appointment to capture the bumped version.
        appt = get_success_data(api_client.get_appointment(appt["id"], FRONT_DESK))
        version = appt["version"]
    confirm(appt["id"])
    check_in(appt["id"])
    started = start_service(appt["id"], technician_id)
    return started


def checkout(appointment_id, expected_version, loyalty_points_redeemed=None,
             gift_card_id=None):
    """Checkout an IN_SERVICE appointment. Returns the COMPLETED Appointment dict."""
    payload = F.checkout_payload(
        expected_version, loyalty_points_redeemed=loyalty_points_redeemed,
        gift_card_id=gift_card_id,
    )
    return get_success_data(
        api_client.checkout_appointment(appointment_id, payload, FRONT_DESK)
    )


def drive_to_completed(client_id, technician_id, station_id, service_item_id,
                       origin="WALK_IN", start_at=None, loyalty_points_redeemed=None,
                       gift_card_id=None):
    """Full happy path: book -> confirm -> check-in -> start-service -> checkout.
    Returns the COMPLETED Appointment dict. Station must not require sterilization
    (or be CLEAN) for this convenience helper."""
    started = drive_to_in_service(client_id, technician_id, station_id,
                                  service_item_id, origin=origin, start_at=start_at)
    return checkout(started["id"], started["version"],
                    loyalty_points_redeemed=loyalty_points_redeemed,
                    gift_card_id=gift_card_id)


# ---------------------------------------------------------------------------
# Tier 5: Commission statement creation
# ---------------------------------------------------------------------------
def make_draft_statement(technician_id, period_start, period_end):
    """Create a DRAFT commission statement. Returns the CommissionStatement dict."""
    payload = F.create_commission_statement_payload(technician_id, period_start, period_end)
    return get_success_data(api_client.create_commission_statement(payload, MANAGER))
