"""Payload factories — one per entity, input fields only.

Each factory builds a minimal-valid create/transition payload and accepts
**overrides for the values individual tests need to control. Unique fields
(email, sku) are randomized per call so independent tests never collide.
"""
import uuid


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": f"customer-{_unique_suffix()}@example.com",
        "service_address": "100 Test St",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Test Tech",
        "skill_level": "CERTIFIED",
        "certified_for_install": True,
    }
    defaults.update(overrides)
    return defaults


def create_door_model_payload(**overrides) -> dict:
    defaults = {
        "sku": f"DR-{_unique_suffix()}",
        "name": "Test Door",
        "width_in": 96,
        "height_in": 84,
        "list_price_cents": 120000,
        "install_labor_minutes": 180,
        "requires_lift": False,
    }
    defaults.update(overrides)
    return defaults


def create_opener_model_payload(**overrides) -> dict:
    defaults = {
        "sku": f"OP-{_unique_suffix()}",
        "name": "Test Opener",
        "horsepower": 0.75,
        "list_price_cents": 30000,
        "install_labor_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": f"PRT-{_unique_suffix()}",
        "category": "SPRING",
        "unit_price_cents": 10000,
        "markup_pct": 0.35,
        "on_hand_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    defaults = {
        "name": f"Lift-{_unique_suffix()}",
        "concurrent_capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "quote_type": "SERVICE_CALL",
        "service_call_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(item_kind, **overrides) -> dict:
    defaults = {
        "item_kind": item_kind,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def schedule_job_payload(technician_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_part_reservation_payload(job_id, part_id, qty, expected_job_version, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "part_id": part_id,
        "qty": qty,
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_plan_payload(job_id, customer_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "customer_id": customer_id,
        "tune_ups_included": 2,
    }
    defaults.update(overrides)
    return defaults


def create_financing_application_payload(customer_id, quote_id, principal_cents, term_months, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "quote_id": quote_id,
        "principal_cents": principal_cents,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults


def create_callback_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "reason": "Test callback reason",
    }
    defaults.update(overrides)
    return defaults


def resolve_callback_payload(fault_confirmed, **overrides) -> dict:
    defaults = {
        "fault_confirmed": fault_confirmed,
    }
    defaults.update(overrides)
    return defaults
