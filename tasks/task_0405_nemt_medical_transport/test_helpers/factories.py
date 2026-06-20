"""Payload factories — one per entity, input fields only.

Field names match the PRD exactly. Optional input fields (those the PRD gives a
default for) are omitted from the defaults unless an override supplies them.
"""


def create_member_payload(**overrides) -> dict:
    """POST /members input: medicaid_id, full_name, mobility_level, home_county."""
    defaults = {
        "medicaid_id": "M-TEST-1",
        "full_name": "Test Member",
        "mobility_level": "AMBULATORY",
        "home_county": "C1",
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_span_payload(member_id, **overrides) -> dict:
    """POST /eligibility-spans input: member_id, level_of_service, coverage_start, coverage_end."""
    defaults = {
        "member_id": member_id,
        "level_of_service": "ROUTINE",
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    """POST /brokers input: name, covered_counties, max_modality, free_deadhead_miles, deadhead_rate_cents_per_mile."""
    defaults = {
        "name": "Test Broker",
        "covered_counties": ["C1"],
        "max_modality": "AMBULATORY",
        "free_deadhead_miles": 5,
        "deadhead_rate_cents_per_mile": 80,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(broker_id, **overrides) -> dict:
    """POST /drivers input: broker_id, full_name, vehicle_modality, base_county."""
    defaults = {
        "broker_id": broker_id,
        "full_name": "Test Driver",
        "vehicle_modality": "AMBULATORY",
        "base_county": "C2",
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    """POST /rate-schedules input: modality, base_fare_cents, loaded_rate_cents_per_mile,
    dwell_free_minutes, dwell_cents_per_minute."""
    defaults = {
        "modality": "AMBULATORY",
        "base_fare_cents": 1500,
        "loaded_rate_cents_per_mile": 120,
        "dwell_free_minutes": 15,
        "dwell_cents_per_minute": 40,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(member_id, **overrides) -> dict:
    """POST /trips input: member_id, modality, requested_level_of_service, appointment_at,
    scheduled_loaded_miles (required); is_round_trip / return_is_will_call optional with defaults."""
    defaults = {
        "member_id": member_id,
        "modality": "AMBULATORY",
        "requested_level_of_service": "ROUTINE",
        "appointment_at": "2026-03-02T09:00:00Z",
        "scheduled_loaded_miles": 8,
    }
    defaults.update(overrides)
    return defaults


def create_standing_order_payload(member_id, **overrides) -> dict:
    """POST /standing-orders input: member_id, modality, level_of_service, weekday_mask,
    appointment_time_utc, scheduled_loaded_miles."""
    defaults = {
        "member_id": member_id,
        "modality": "WHEELCHAIR",
        "level_of_service": "ROUTINE",
        "weekday_mask": 21,
        "appointment_time_utc": "09:00:00",
        "scheduled_loaded_miles": 7,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(trip_id, **overrides) -> dict:
    """POST /claims input: trip_id."""
    defaults = {"trip_id": trip_id}
    defaults.update(overrides)
    return defaults


def create_encounter_payload(trip_id, **overrides) -> dict:
    """POST /encounters input: trip_id."""
    defaults = {"trip_id": trip_id}
    defaults.update(overrides)
    return defaults
