"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Generate a process-unique suffix for unique-constrained fields."""
    return f"{prefix}-{next(_counter)}"


# ---------------------------------------------------------------------------
# Technician (PRD §3.1)
#   Required: full_name, license_number, license_expiry, pay_model, home_station_id
#   Optional (have PRD defaults): commission_pct (0.40), booth_rent_cents (0)
# ---------------------------------------------------------------------------
def create_technician_payload(home_station_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Technician",
        "license_number": _uniq("LIC"),
        "license_expiry": "2027-01-01T00:00:00Z",
        "pay_model": "COMMISSION",
        "commission_pct": 0.40,
        "home_station_id": home_station_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Station (PRD §3.2)
#   Required: name
#   Optional: requires_autoclave (default true)
# ---------------------------------------------------------------------------
def create_station_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Station")}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# SanitationLog (PRD §3.2)
#   Required: station_id, logged_by_technician_id, cycle_result, cycle_temp_c, hold_minutes
# ---------------------------------------------------------------------------
def create_sanitation_log_payload(station_id: str, logged_by_technician_id: str,
                                   cycle_result: str = "PASS",
                                   cycle_temp_c: float = 134.0,
                                   hold_minutes: int = 30,
                                   **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "logged_by_technician_id": logged_by_technician_id,
        "cycle_result": cycle_result,
        "cycle_temp_c": cycle_temp_c,
        "hold_minutes": hold_minutes,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ServiceMenuItem (PRD §3.3)
#   Required: name, category, duration_minutes, base_price_cents
#   Optional: loyalty_points_award (0), requires_sterile_station (true)
# ---------------------------------------------------------------------------
def create_menu_item_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Gel Manicure"),
        "category": "MANICURE",
        "duration_minutes": 45,
        "base_price_cents": 4500,
        "loyalty_points_award": 0,
        "requires_sterile_station": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AddOn (PRD §3.3)
#   Required: name, price_cents
#   Optional: extra_minutes (0)
# ---------------------------------------------------------------------------
def create_add_on_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Paraffin Dip"),
        "price_cents": 1500,
        "extra_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Client (PRD §3.4)
#   Required: full_name, email
# ---------------------------------------------------------------------------
def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Client",
        "email": _uniq("client") + "@x.com",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Appointment (PRD §3.5)
#   Required: client_id, technician_id, station_id, service_item_id, origin
#   Optional: start_at (defaults to clock for WALK_IN)
# ---------------------------------------------------------------------------
def create_appointment_payload(client_id: str, technician_id: str, station_id: str,
                               service_item_id: str, origin: str = "APPOINTMENT",
                               start_at: str = None, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "technician_id": technician_id,
        "station_id": station_id,
        "service_item_id": service_item_id,
        "origin": origin,
    }
    if start_at is not None:
        defaults["start_at"] = start_at
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Add-on attach (PRD §3.5)
#   Required: add_on_id, expected_appointment_version
# ---------------------------------------------------------------------------
def attach_add_on_payload(add_on_id: str, expected_appointment_version: int,
                          **overrides) -> dict:
    defaults = {
        "add_on_id": add_on_id,
        "expected_appointment_version": expected_appointment_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Checkout (PRD §3.10)
#   Required: expected_appointment_version
#   Optional: loyalty_points_redeemed (0), gift_card_id (null)
# ---------------------------------------------------------------------------
def checkout_payload(expected_appointment_version: int,
                     loyalty_points_redeemed: int = None,
                     gift_card_id: str = None, **overrides) -> dict:
    defaults = {"expected_appointment_version": expected_appointment_version}
    if loyalty_points_redeemed is not None:
        defaults["loyalty_points_redeemed"] = loyalty_points_redeemed
    if gift_card_id is not None:
        defaults["gift_card_id"] = gift_card_id
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# GiftCard (PRD §3.15)
#   Required: code, initial_balance_cents
#   Optional: purchaser_client_id (null)
# ---------------------------------------------------------------------------
def create_gift_card_payload(initial_balance_cents: int = 5000, **overrides) -> dict:
    defaults = {
        "code": _uniq("GC"),
        "initial_balance_cents": initial_balance_cents,
    }
    defaults.update(overrides)
    return defaults


def redeem_gift_card_payload(amount_cents: int, expected_gift_card_version: int,
                             **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_gift_card_version": expected_gift_card_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CommissionStatement (PRD §3.16)
#   Required: technician_id, period_start, period_end
# ---------------------------------------------------------------------------
def create_commission_statement_payload(technician_id: str, period_start: str,
                                         period_end: str, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Test-driving injection payloads (PRD §3.17)
# ---------------------------------------------------------------------------
def inject_client_state_payload(client_id: str, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults


def inject_appointment_deposit_payload(appointment_id: str, deposit_due_cents: int) -> dict:
    return {"appointment_id": appointment_id, "deposit_due_cents": deposit_due_cents}
