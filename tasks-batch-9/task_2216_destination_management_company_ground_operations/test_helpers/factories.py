"""Payload factories — one per entity, request-input fields only.

Every factory accepts `**overrides` so tests can pin the exact literal inputs a
scenario needs.
"""

from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    payload = {
        "client_name": "Meridian Pharma",
        "group_name": "Global Sales Kickoff",
        "arrival_date": TEST_DEFAULTS["ARRIVAL_DATE"],
        "departure_date": TEST_DEFAULTS["DEPARTURE_DATE"],
        "guaranteed_count": 100,
        "markup_pct": 0.18,
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": "Harbor Pavilion",
        "capacity_seated": 200,
        "capacity_reception": 400,
        "turnover_buffer_minutes": 90,
        "requires_special_venue_permit": False,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Bayside Ground Services LLC",
        "supplier_type": "ACTIVITY",
        "insurance_expires_on": TEST_DEFAULTS["INSURANCE_EXPIRES_ON"],
        "insurance_liability_limit_cents": TEST_DEFAULTS[
            "INSURANCE_LIABILITY_LIMIT_CENTS"
        ],
        "coi_verified": True,
        "status": "APPROVED",
    }
    payload.update(overrides)
    return payload


def create_supplier_contract_payload(program_id, supplier_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "supplier_id": supplier_id,
        "contract_value_cents": 200_000,
        "required_liability_limit_cents": TEST_DEFAULTS[
            "REQUIRED_LIABILITY_LIMIT_CENTS"
        ],
        "deposit_pct": 0.3,
        "cancellation_tier": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_program_element_payload(
    program_id, supplier_id, expected_program_version, **overrides
) -> dict:
    payload = {
        "program_id": program_id,
        "supplier_id": supplier_id,
        "element_type": "ACTIVITY",
        "title": "Harbor Sail Regatta",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
        "planned_headcount": 40,
        "guaranteed_headcount": 40,
        "per_person_cost_cents": 5_000,
        "is_weather_dependent": False,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(element_id, **overrides) -> dict:
    payload = {
        "element_id": element_id,
        "permit_type": "SPECIAL_VENUE",
        "authority_name": "City Licensing Board",
        "lead_time_days_required": 30,
    }
    payload.update(overrides)
    return payload


def create_transport_segment_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "segment_type": "SHUTTLE_LOOP",
        "vehicle_code": "SHUT-01",
        "origin": "Host Hotel",
        "destination": "Convention Center",
        "depart_at": "2026-09-11T09:00:00Z",
        "arrive_at": "2026-09-11T17:30:00Z",
        "seat_capacity": 40,
        "wheelchair_accessible": True,
    }
    payload.update(overrides)
    return payload


def create_manifest_entry_payload(segment_id, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "guest_ref": "G-001",
        "guest_name": "Ingrid Halvorsen",
        "seat_count": 1,
        "mobility_assist": False,
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Okafor",
        "role_type": "COORDINATOR",
        "badge_expires_on": TEST_DEFAULTS["BADGE_EXPIRES_ON"],
        "first_aid_expires_on": TEST_DEFAULTS["FIRST_AID_EXPIRES_ON"],
        "pay_rate_cents_per_hour": 4_500,
        "min_rest_minutes": 600,
        "max_daily_minutes": 720,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_staff_assignment_payload(staff_id, program_id, **overrides) -> dict:
    payload = {
        "staff_id": staff_id,
        "program_id": program_id,
        "target_type": "ELEMENT",
        "role_type": "COORDINATOR",
        "starts_at": "2026-09-11T09:00:00Z",
        "ends_at": "2026-09-11T13:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_settlement_payment_payload(
    program_id, supplier_id, contract_id, expected_contract_version, **overrides
) -> dict:
    payload = {
        "program_id": program_id,
        "supplier_id": supplier_id,
        "contract_id": contract_id,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload
