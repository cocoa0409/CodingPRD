"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_cemetery_payload(**overrides) -> dict:
    defaults = {
        "name": "Restful Pines",
        "allowed_materials": ["GRANITE"],
        "max_height_cm": 90,
        "max_width_cm": 75,
        "max_base_width_cm": 80,
        "requires_permit": True,
        "permit_fee_cents": 12000,
        "requires_foundation": True,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"full_name": "Jane Doe", "email": "jane@example.com"}
    defaults.update(overrides)
    return defaults


def create_workshop_payload(**overrides) -> dict:
    defaults = {"name": "Shop A"}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {"name": "Crew 1"}
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, cemetery_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "cemetery_id": cemetery_id,
        "subject_type": "HUMAN",
        "material": "GRANITE",
        "height_cm": 60,
        "width_cm": 40,
        "base_width_cm": 50,
        "estimated_line_char_counts": [20, 20],
    }
    defaults.update(overrides)
    return defaults


def create_design_proof_payload(order_id, expected_order_version, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "expected_order_version": expected_order_version,
        "engraving_text": "In Loving Memory",
        "line_char_counts": [21, 31],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(order_id, payment_type, amount_cents, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "payment_type": payment_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_fabrication_job_payload(order_id, workshop_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "workshop_id": workshop_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(order_id, cemetery_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "cemetery_id": cemetery_id,
        "permit_number": "P-100",
        "placement_date": "2026-03-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_installation_payload(order_id, crew_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "crew_id": crew_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_restoration_payload(order_id, service_type, reported_area_cm2, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "service_type": service_type,
        "is_warranty": False,
        "reported_area_cm2": reported_area_cm2,
    }
    defaults.update(overrides)
    return defaults


def assess_restoration_payload(workshop_id, measured_area_cm2, condition, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "workshop_id": workshop_id,
        "measured_area_cm2": measured_area_cm2,
        "condition": condition,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults
