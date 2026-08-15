"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BUILDING_NAME": "Test Hall",
    "FALL_OPENING_DATE": "2026-08-20",
    "KEY_POOL_SIZE": 10,
    "ROOM_NUMBER": "R1",
    "BED_COUNT": 1,
    "CLIENT_NAME": "Test Client",
    "CONTACT_EMAIL": "client@example.com",
    "ARRIVAL_DATE": "2026-06-15",
    "DEPARTURE_DATE": "2026-06-17",
    "CONTRACTED_BED_COUNT": 1,
    "FULL_NAME": "Test Person",
    "ADULT_DOB": "1990-01-01",
    "MINOR_DOB": "2012-04-04",
    "ROLE_IN_GROUP": "ATTENDEE",
    "CHECKIN_AT": "2026-06-15T15:00:00Z",
    "CHECKOUT_AT": "2026-06-17T11:00:00Z",
    "CONSENT_REFERENCE": "CONS-TEST",
}


def create_building_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BUILDING_NAME"],
        "fall_opening_date": DEFAULTS["FALL_OPENING_DATE"],
        "key_pool_size": DEFAULTS["KEY_POOL_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "room_number": DEFAULTS["ROOM_NUMBER"],
        "bed_count": DEFAULTS["BED_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_conference_group_payload(building_id, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "client_name": DEFAULTS["CLIENT_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "arrival_date": DEFAULTS["ARRIVAL_DATE"],
        "departure_date": DEFAULTS["DEPARTURE_DATE"],
        "contracted_bed_count": DEFAULTS["CONTRACTED_BED_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["ADULT_DOB"],
        "role_in_group": DEFAULTS["ROLE_IN_GROUP"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_entry(participant_id, room_id, **overrides) -> dict:
    entry = {
        "participant_id": participant_id,
        "room_id": room_id,
        "checkin_at": DEFAULTS["CHECKIN_AT"],
        "checkout_at": DEFAULTS["CHECKOUT_AT"],
    }
    entry.update(overrides)
    return entry


def create_revision_payload(expected_conference_group_version, assignments) -> dict:
    return {
        "expected_conference_group_version": expected_conference_group_version,
        "assignments": assignments,
    }


def create_screening_payload(**overrides) -> dict:
    defaults = {"consent_reference": DEFAULTS["CONSENT_REFERENCE"]}
    defaults.update(overrides)
    return defaults


def create_damage_line_item(description="Fixture", quantity=1,
                            unit_replacement_cost_cents=10000,
                            fixture_age_months=0) -> dict:
    return {
        "description": description,
        "quantity": quantity,
        "unit_replacement_cost_cents": unit_replacement_cost_cents,
        "fixture_age_months": fixture_age_months,
    }


def create_damage_assessment_payload(group_id, line_items=None) -> dict:
    return {
        "group_id": group_id,
        "line_items": line_items if line_items is not None else [create_damage_line_item()],
    }


def create_maintenance_window_payload(expected_building_version, **overrides) -> dict:
    defaults = {
        "start_date": "2026-08-10",
        "end_date": "2026-08-12",
        "expected_building_version": expected_building_version,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_run_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-06-01",
        "period_end": "2026-07-01",
    }
    defaults.update(overrides)
    return defaults
