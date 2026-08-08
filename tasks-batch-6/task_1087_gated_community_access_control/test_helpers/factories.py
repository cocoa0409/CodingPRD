"""Payload factories — one per entity, PRD input fields only (Section 3, 4).

Required fields carry sensible defaults so a test overrides only what it cares
about; optional fields are omitted unless supplied via ``**overrides``.
"""


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_community_payload(**overrides) -> dict:
    payload = {"name": "Oakcrest"}
    payload.update(overrides)
    return payload


def create_resident_payload(community_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "full_name": "Rita Resident",
        "email": "rita@example.com",
        "resident_type": "OWNER",
    }
    payload.update(overrides)
    return payload


def create_vehicle_payload(resident_id: str, **overrides) -> dict:
    payload = {
        "resident_id": resident_id,
        "plate": "CAR001",
        "plate_state": "CA",
    }
    payload.update(overrides)
    return payload


def create_decal_payload(vehicle_id: str, expected_vehicle_version: int, **overrides) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "tier": "RESIDENT",
        "valid_from": "2026-05-01T00:00:00Z",
        "valid_until": "2027-05-01T00:00:00Z",
        "expected_vehicle_version": expected_vehicle_version,
    }
    payload.update(overrides)
    return payload


def create_pass_payload(sponsor_resident_id: str, **overrides) -> dict:
    payload = {
        "sponsor_resident_id": sponsor_resident_id,
        "pass_type": "GUEST",
        "visitor_name": "Vera Visitor",
        "visitor_plate": "GUEST1",
        "valid_from": "2026-06-01T09:00:00Z",
        "valid_until": "2026-06-01T18:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_gate_event_payload(community_id: str, plate_read: str, direction: str = "ENTRY", **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "gate_id": "G1",
        "direction": direction,
        "plate_read": plate_read,
    }
    payload.update(overrides)
    return payload


def create_amenity_payload(community_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "name": "Main Pool",
        "amenity_type": "POOL",
        "capacity": 10,
        "hourly_fee_cents": 1000,
        "deposit_cents": 0,
        "open_hour": 6,
        "close_hour": 22,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(amenity_id: str, resident_id: str, **overrides) -> dict:
    payload = {
        "amenity_id": amenity_id,
        "resident_id": resident_id,
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T12:00:00Z",
        "party_size": 1,
    }
    payload.update(overrides)
    return payload


def create_patrol_payload(community_id: str, officer_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "officer_id": officer_id,
        "start_at": "2026-06-01T08:00:00Z",
        "end_at": "2026-06-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_incident_payload(community_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "incident_type": "NOISE",
        "severity": "LOW",
        "description": "Loud party at the pool",
    }
    payload.update(overrides)
    return payload


def create_violation_payload(community_id: str, resident_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "resident_id": resident_id,
        "violation_type": "PARKING",
        "base_fine_cents": 5000,
    }
    payload.update(overrides)
    return payload
