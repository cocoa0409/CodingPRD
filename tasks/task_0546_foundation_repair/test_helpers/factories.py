"""Payload factories — one per create endpoint, input fields only (PRD §3).

Only source: input fields appear here. Computed and system fields (subtotal_cents,
financing_balance_cents, status, version, ...) are never sent by the client.
"""

DEFAULT_INSPECTION_AT = "2026-05-02T09:00:00Z"


def create_lead_payload(**overrides) -> dict:
    payload = {
        "customer_name": "Test Owner",
        "property_address": "1 Test St",
        "contact_email": "owner@example.com",
        "region_code": "NORTH",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(lead_id: str, **overrides) -> dict:
    payload = {
        "lead_id": lead_id,
        "scheduled_at": DEFAULT_INSPECTION_AT,
    }
    payload.update(overrides)
    return payload


def complete_inspection_payload(**overrides) -> dict:
    payload = {
        "soil_class": "STABLE",
        "crack_severity": 1,
        "max_crack_width_mm": 2.0,
        "settlement_inches": 0.5,
    }
    payload.update(overrides)
    return payload


def create_scope_payload(lead_id: str, inspection_id: str, expected_lead_version: int,
                         **overrides) -> dict:
    payload = {
        "lead_id": lead_id,
        "inspection_id": inspection_id,
        "pier_count": 8,
        "anchor_count": 0,
        "avg_pier_depth_ft": 18,
        "access_difficulty": "EASY",
        "supplemental_engineering": False,
        "expected_lead_version": expected_lead_version,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(lead_id: str, scope_id: str, financing_plan: str = "CASH",
                         **overrides) -> dict:
    payload = {
        "lead_id": lead_id,
        "scope_id": scope_id,
        "financing_plan": financing_plan,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "crew_name": "Test Crew",
        "region_code": "NORTH",
    }
    payload.update(overrides)
    return payload


def create_permit_payload(job_id: str, permit_type: str = "STANDARD", **overrides) -> dict:
    payload = {
        "job_id": job_id,
        "permit_type": permit_type,
    }
    payload.update(overrides)
    return payload


def schedule_job_payload(crew_id: str,
                         scheduled_start: str = "2026-06-01T08:00:00Z",
                         scheduled_end: str = "2026-06-01T12:00:00Z",
                         **overrides) -> dict:
    payload = {
        "crew_id": crew_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def complete_job_payload(piers_installed: int = 8, adjustment_inches: float = 1.0,
                         **overrides) -> dict:
    payload = {
        "piers_installed": piers_installed,
        "adjustment_inches": adjustment_inches,
    }
    payload.update(overrides)
    return payload


def create_maintenance_visit_payload(warranty_id: str, scheduled_date: str,
                                     **overrides) -> dict:
    payload = {
        "warranty_id": warranty_id,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(warranty_id: str, reported_settlement_inches: float = 1.0,
                         **overrides) -> dict:
    payload = {
        "warranty_id": warranty_id,
        "description": "Homeowner callback",
        "reported_settlement_inches": reported_settlement_inches,
    }
    payload.update(overrides)
    return payload
