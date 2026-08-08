"""Payload factories — one per entity, input fields only."""


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": "Metro",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_exclusion_zone_payload(**overrides) -> dict:
    payload = {
        "name": "Lincoln Elementary",
        "zone_type": "SCHOOL",
        "center_x": 0,
        "center_y": 0,
        "radius_meters": 500,
    }
    payload.update(overrides)
    return payload


def create_registrant_payload(jurisdiction_id, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "full_name": "Test Subject",
        "date_of_birth": "1980-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_offense_payload(**overrides) -> dict:
    payload = {
        "statute_code": "P290",
        "offense_class": "CLASS_B",
        "conviction_date": "2020-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_address_payload(expected_registrant_version, **overrides) -> dict:
    payload = {
        "address_type": "RESIDENCE",
        "line1": "1 A St",
        "city": "Metro",
        "state_code": "CA",
        "postal_code": "90001",
        "grid_x": 4000,
        "grid_y": 4000,
        "expected_registrant_version": expected_registrant_version,
    }
    payload.update(overrides)
    return payload


def create_verification_payload(**overrides) -> dict:
    payload = {
        "verification_type": "PERIODIC",
        "officer_ref": "off-1",
    }
    payload.update(overrides)
    return payload


def create_flag_payload(**overrides) -> dict:
    payload = {
        "flag_type": "UNREPORTED_MOVE",
    }
    payload.update(overrides)
    return payload


def create_travel_notice_payload(destination_jurisdiction_id, **overrides) -> dict:
    payload = {
        "destination_jurisdiction_id": destination_jurisdiction_id,
        "travel_type": "TEMPORARY",
        "departure_date": "2026-06-01T00:00:00Z",
        "return_date": "2026-06-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_notification_payload(**overrides) -> dict:
    payload = {
        "audience_scope": "PUBLIC",
    }
    payload.update(overrides)
    return payload


def create_petition_payload(**overrides) -> dict:
    payload = {
        "petition_type": "DEREGISTER",
    }
    payload.update(overrides)
    return payload
