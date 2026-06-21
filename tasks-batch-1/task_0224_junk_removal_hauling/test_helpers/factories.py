"""Payload factories — one per writable entity, input fields only."""
import itertools

from .constants import STD_POLICY, SHIFT_START_UTC, SHIFT_END_UTC

_email_counter = itertools.count(1)


def unique_email(prefix="cust"):
    """Generate a unique customer email (email is unique among customers, PRD §3.1)."""
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_pricing_policy_payload(**overrides) -> dict:
    """Required input fields for POST /pricing-policies (PRD §2.11 / §3.1).
    Defaults to the canonical std_policy rate set; optional knobs use policy defaults."""
    defaults = dict(STD_POLICY)
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Required input: email, full_name; optional credit_limit_cents (PRD §3.1)."""
    defaults = {
        "email": unique_email(),
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    """Required: name, shift_start_utc, shift_end_utc; optional buffer_minutes,
    hazmat_certified (PRD §3.1)."""
    defaults = {
        "name": "Test Crew",
        "shift_start_utc": SHIFT_START_UTC,
        "shift_end_utc": SHIFT_END_UTC,
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    """Required: name (PRD §3.1)."""
    defaults = {"name": "Test Truck"}
    defaults.update(overrides)
    return defaults


def create_haul_job_payload(customer_id, **overrides) -> dict:
    """Required: customer_id, service_type, address (PRD §3.2)."""
    defaults = {
        "customer_id": customer_id,
        "service_type": "SCHEDULED",
        "address": "1 Test St",
    }
    defaults.update(overrides)
    return defaults


def create_job_item_payload(category="STANDARD", **overrides) -> dict:
    """Required: category; optional quantity (default 1), description (PRD §3.2)."""
    defaults = {"category": category}
    defaults.update(overrides)
    return defaults


def create_photo_estimate_payload(raw_fraction=0.10, **overrides) -> dict:
    """Required: photo_url, raw_fraction; optional declared_items (PRD §3.2)."""
    defaults = {
        "photo_url": "http://photos.example/p.jpg",
        "raw_fraction": raw_fraction,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(haul_job_id, crew_id, truck_id, expected_crew_version,
                            window_start_utc="2026-06-10T09:00:00.000Z",
                            window_end_utc="2026-06-10T10:00:00.000Z", **overrides) -> dict:
    """Required: haul_job_id, crew_id, truck_id, window_start_utc, window_end_utc,
    expected_crew_version (PRD §3.4 / §2.10)."""
    defaults = {
        "haul_job_id": haul_job_id,
        "crew_id": crew_id,
        "truck_id": truck_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "expected_crew_version": expected_crew_version,
    }
    defaults.update(overrides)
    return defaults


def create_diversion_payload(destination="DONATION", tons=1.0, **overrides) -> dict:
    """Required: destination, tons (PRD §3.6)."""
    defaults = {"destination": destination, "tons": tons}
    defaults.update(overrides)
    return defaults


def create_dump_ticket_payload(fee_basis="WEIGHT_BASED", landfill_tons=0.8,
                               landfill_fraction=0.5, **overrides) -> dict:
    """Required: landfill_tons, landfill_fraction, fee_basis (PRD §3.6)."""
    defaults = {
        "landfill_tons": landfill_tons,
        "landfill_fraction": landfill_fraction,
        "fee_basis": fee_basis,
    }
    defaults.update(overrides)
    return defaults
