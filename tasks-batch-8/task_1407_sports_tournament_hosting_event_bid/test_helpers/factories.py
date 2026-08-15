"""Payload factories — one per creatable entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "River City Cup",
        "sanctioning_body": "NFSA",
        "host_city": "River City",
        "starts_on": TEST_DEFAULTS["EVENT_STARTS_ON"],
        "ends_on": TEST_DEFAULTS["EVENT_ENDS_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(expected_event_version, **overrides) -> dict:
    defaults = {"expected_event_version": expected_event_version}
    defaults.update(overrides)
    return defaults


def create_requirement_payload(**overrides) -> dict:
    defaults = {
        "kind": "INSURANCE_CERT",
        "is_mandatory": True,
        "weight_points": 100,
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "River Park",
        "address": "1 Park Way",
        "rental_fee_cents": TEST_DEFAULTS["VENUE_RENTAL_FEE_CENTS"],
        "revenue_share_pct": TEST_DEFAULTS["VENUE_REVENUE_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_field_payload(**overrides) -> dict:
    defaults = {
        "name": "Field 1",
        "surface_type": "TURF",
        "has_lights": True,
        "slot_minutes": TEST_DEFAULTS["FIELD_SLOT_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_hotel_block_payload(**overrides) -> dict:
    defaults = {
        "hotel_name": "Riverside Inn",
        "contracted_rooms_per_night": TEST_DEFAULTS["BLOCK_ROOMS_PER_NIGHT"],
        "room_rate_cents": TEST_DEFAULTS["BLOCK_RATE_CENTS"],
        "block_start_date": TEST_DEFAULTS["BLOCK_START_DATE"],
        "block_end_date": TEST_DEFAULTS["BLOCK_END_DATE"],
        "cutoff_date": TEST_DEFAULTS["BLOCK_CUTOFF_DATE"],
        "attrition_allowance_pct": TEST_DEFAULTS["BLOCK_ATTRITION_ALLOWANCE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "booker_type": "COMMISSION",
        "guest_name": "Block A",
        "rooms_count": 2,
        "check_in_date": TEST_DEFAULTS["BLOCK_START_DATE"],
        "check_out_date": TEST_DEFAULTS["BLOCK_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_division_payload(**overrides) -> dict:
    defaults = {
        "name": "U16",
        "team_cap": TEST_DEFAULTS["DIVISION_TEAM_CAP"],
        "min_teams": TEST_DEFAULTS["DIVISION_MIN_TEAMS"],
        "registration_fee_cents": TEST_DEFAULTS["DIVISION_REGISTRATION_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    defaults = {
        "name": "Tigers",
        "contact_email": "t@x.com",
        "strength_rating": 90,
    }
    defaults.update(overrides)
    return defaults


def create_official_payload(**overrides) -> dict:
    defaults = {
        "name": "Nat Ref",
        "certification_level": "NATIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(official_id, **overrides) -> dict:
    defaults = {"official_id": official_id, "slot_role": "CREW_CHIEF"}
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {"name": "Vic One", "email": "v1@x.com"}
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "role_needed": "FIELD_MARSHAL",
        "starts_at": "2026-10-10T08:00:00Z",
        "ends_at": "2026-10-10T10:30:00Z",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_weather_alert_payload(**overrides) -> dict:
    defaults = {
        "severity": "WARNING",
        "window_start": "2026-10-10T12:00:00Z",
        "window_end": "2026-10-10T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_impact_report_payload(**overrides) -> dict:
    defaults = {"projected_attendance": 400}
    defaults.update(overrides)
    return defaults


def create_settlement_payload(**overrides) -> dict:
    defaults = {"sponsor_contributions_cents": 0}
    defaults.update(overrides)
    return defaults
