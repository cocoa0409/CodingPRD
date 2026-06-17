"""Payload factories — one per entity, input fields only (PRD §3).

Each factory returns a fresh dict so overrides do not bleed across tests. The
test server is restarted before every pytest test, so the email counter resets
to 0 each process load — no cross-test bleed.
"""
import itertools

_email_counter = itertools.count(10000)


def fresh_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ---- Marina (PRD §3.1) ----
def create_marina_payload(**overrides) -> dict:
    defaults = {"name": "Test Marina", "slot_count": 2}
    defaults.update(overrides)
    return defaults


# ---- DockSlot (PRD §3.1) ----
def create_dock_slot_payload(marina_id: str, **overrides) -> dict:
    defaults = {"marina_id": marina_id, "slot_label": "A1", "max_boat_length_ft": 40}
    defaults.update(overrides)
    return defaults


# ---- Boat (PRD §3.1) ----
def create_boat_payload(marina_id: str, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "name": "Test Boat",
        "length_ft": 30,
        "passenger_capacity": 6,
    }
    defaults.update(overrides)
    return defaults


# ---- Captain (PRD §3.1) ----
def create_captain_payload(marina_id: str, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "full_name": "Test Captain",
        "uscg_license_grade": "MASTER_50",
        "license_expires_on": "2030-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---- Mate (PRD §3.1) ----
def create_mate_payload(marina_id: str, **overrides) -> dict:
    defaults = {"marina_id": marina_id, "full_name": "Test Mate"}
    defaults.update(overrides)
    return defaults


# ---- Permit (PRD §3.1) ----
def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_kind": "FEDERAL_OFFSHORE",
        "permit_number": "F-TEST",
        "valid_through": "2030-01-01T00:00:00Z",
        "daily_bag_limit": 20,
    }
    defaults.update(overrides)
    return defaults


# ---- Customer (PRD §3.1) ----
def create_customer_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Customer", "email": fresh_email("cust")}
    defaults.update(overrides)
    return defaults


# ---- Charter (PRD §3.2) ----
def create_charter_payload(marina_id: str, boat_id: str, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "boat_id": boat_id,
        "trip_type": "INSHORE",
        "depart_at": "2027-06-10T12:00:00Z",
        "return_at": "2027-06-10T16:00:00Z",
        "base_seat_price_cents": 10000,
        "seats_total": 6,
    }
    defaults.update(overrides)
    return defaults


# ---- CrewAssignment (PRD §3.2) ----
def create_crew_assignment_payload(charter_id: str, role_slot: str, **overrides) -> dict:
    defaults = {"charter_id": charter_id, "role_slot": role_slot}
    defaults.update(overrides)
    return defaults


# ---- SlotReservation (PRD §3.3) ----
def create_slot_reservation_payload(dock_slot_id: str, charter_id: str,
                                     expected_charter_version: int, **overrides) -> dict:
    defaults = {
        "dock_slot_id": dock_slot_id,
        "charter_id": charter_id,
        "expected_charter_version": expected_charter_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Booking (PRD §3.4) ----
def create_booking_payload(charter_id: str, customer_id: str,
                           expected_charter_version: int, **overrides) -> dict:
    defaults = {
        "charter_id": charter_id,
        "customer_id": customer_id,
        "party_size": 2,
        "expected_charter_version": expected_charter_version,
    }
    defaults.update(overrides)
    return defaults


# ---- AddOnLine (PRD §3.5) ----
def create_add_on_line_payload(booking_id: str, addon_kind: str, quantity: int, **overrides) -> dict:
    defaults = {"booking_id": booking_id, "addon_kind": addon_kind, "quantity": quantity}
    defaults.update(overrides)
    return defaults


# ---- CatchReport (PRD §3.6) ----
def create_catch_report_payload(charter_id: str, species: str, fish_count: int, **overrides) -> dict:
    defaults = {"charter_id": charter_id, "species": species, "fish_count": fish_count}
    defaults.update(overrides)
    return defaults
