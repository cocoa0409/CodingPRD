"""Payload factories — one per entity, input fields only."""

# Default temporal anchors used across setups (ISO 8601 UTC).
DEFAULT_SHOOT_START = "2026-06-01T08:00:00Z"
DEFAULT_SHOOT_END = "2026-06-01T18:00:00Z"


def production_company_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Acme Films",
        "contact_email": "ops@acme.test",
        "primary_contact": "Pat Lee",
    }
    payload.update(overrides)
    return payload


def department_payload(**overrides) -> dict:
    payload = {
        "code": "POLICE",
        "name": "Police",
        "trigger_condition": "ALL_APPLICATIONS",
    }
    payload.update(overrides)
    return payload


def officer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ofc Diaz",
        "badge_number": "B-1",
        "rank": "OFFICER",
        "hourly_rate_cents": 8000,
    }
    payload.update(overrides)
    return payload


def street_segment_payload(**overrides) -> dict:
    payload = {
        "segment_code": "MAIN-100",
        "name": "Main St 100",
        "length_m": 120,
    }
    payload.update(overrides)
    return payload


def application_payload(production_company_id, **overrides) -> dict:
    payload = {
        "production_company_id": production_company_id,
        "title": "Night Shoot",
        "synopsis": "City scene",
        "shoot_start_at": DEFAULT_SHOOT_START,
        "shoot_end_at": DEFAULT_SHOOT_END,
        "crew_size": 5,
    }
    payload.update(overrides)
    return payload


def location_detail_payload(**overrides) -> dict:
    payload = {
        "address": "100 Main St",
        "geo_zone": "Z1",
        "activity_type": "FILMING",
        "requested_start_at": DEFAULT_SHOOT_START,
        "requested_end_at": DEFAULT_SHOOT_END,
    }
    payload.update(overrides)
    return payload


def insurance_certificate_payload(expected_application_version, **overrides) -> dict:
    payload = {
        "policy_number": "POL-1",
        "coverage_amount_cents": 5000000,
        "effective_date": "2026-01-01T00:00:00Z",
        "expiration_date": "2026-12-31T00:00:00Z",
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def rider_payload(rider_type, **overrides) -> dict:
    payload = {"rider_type": rider_type}
    payload.update(overrides)
    return payload


def road_closure_booking_payload(application_id, street_segment_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "street_segment_id": street_segment_id,
        "closure_start_at": "2026-06-01T08:00:00Z",
        "closure_end_at": "2026-06-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def officer_assignment_payload(application_id, officer_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "officer_id": officer_id,
        "shift_start_at": "2026-06-01T08:00:00Z",
        "shift_end_at": "2026-06-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def notification_payload(**overrides) -> dict:
    payload = {
        "geo_zone": "Z1",
        "notice_method": "MAILED",
    }
    payload.update(overrides)
    return payload


def payment_payload(entry_type, amount_cents) -> dict:
    return {"entry_type": entry_type, "amount_cents": amount_cents}
