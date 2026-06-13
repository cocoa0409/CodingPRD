"""Payload factories — one per entity, input (client-supplied) fields only.

Each factory returns sensible defaults and accepts **overrides so tests control
only the values relevant to them. Email factories include a uniqueness counter
because Customer.email is unique across customers (PRD §3.1).
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "cust") -> str:
    """Generate a per-call unique email (Customer.email is unique)."""
    return f"{prefix}.{next(_email_counter)}@tailor-test.example.com"


# ─── Customer ───────────────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email("cust"),
    }
    defaults.update(overrides)
    return defaults


# ─── MeasurementProfile ─────────────────────────────────────────────────
def create_measurement_profile_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "chest_cm": 100,
        "waist_cm": 84,
        "hip_cm": 100,
        "inseam_cm": 80,
        "source": "MANUAL",
    }
    defaults.update(overrides)
    return defaults


# ─── Fabric ─────────────────────────────────────────────────────────────
def create_fabric_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Wool",
        "price_per_meter_cents": 8000,
        "bolt_meters_initial": 50,
    }
    defaults.update(overrides)
    return defaults


# ─── Tailor ─────────────────────────────────────────────────────────────
def create_tailor_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Test Tailor",
    }
    defaults.update(overrides)
    return defaults


# ─── FittingRoom ────────────────────────────────────────────────────────
def create_fitting_room_payload(**overrides) -> dict:
    defaults = {
        "room_name": "Test Room",
        "cleanup_buffer_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


# ─── GroupOrder ─────────────────────────────────────────────────────────
def create_group_order_payload(**overrides) -> dict:
    defaults = {
        "event_name": "Test Wedding",
        "event_date": "2026-09-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# ─── GarmentOrder ───────────────────────────────────────────────────────
def create_order_payload(customer_id: str, measurement_profile_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "measurement_profile_id": measurement_profile_id,
        "garment_type": "SUIT",
        "base_labor_cents": 40000,
        "fabric_meters_required": 7.0,
        "promised_date": "2026-08-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# ─── GarmentOptionLine ──────────────────────────────────────────────────
def create_option_line_payload(fabric_id: str, option_code: str = "MONOGRAM", **overrides) -> dict:
    defaults = {
        "fabric_id": fabric_id,
        "option_code": option_code,
    }
    defaults.update(overrides)
    return defaults


# ─── Fitting ────────────────────────────────────────────────────────────
def create_fitting_payload(tailor_id: str, room_id: str, milestone: str,
                           start_at: str, end_at: str, expected_order_version: int,
                           **overrides) -> dict:
    defaults = {
        "tailor_id": tailor_id,
        "room_id": room_id,
        "milestone": milestone,
        "start_at": start_at,
        "end_at": end_at,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


# ─── AlterationTicket ───────────────────────────────────────────────────
def create_alteration_payload(description: str = "Take in waist", **overrides) -> dict:
    defaults = {
        "description": description,
    }
    defaults.update(overrides)
    return defaults


# ─── Payment ────────────────────────────────────────────────────────────
def create_payment_payload(kind: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "kind": kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults
