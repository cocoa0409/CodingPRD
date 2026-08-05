"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import DEFAULT_POLICY


def create_permittee_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme",
        "contact_email": "a@x.com",
        "permittee_type": "CARRIER",
    }
    defaults.update(overrides)
    return defaults


def create_pricing_policy_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_POLICY)
    defaults.update(overrides)
    return defaults


def create_zone_payload(pricing_policy_id, **overrides) -> dict:
    defaults = {
        "name": "Z1",
        "block_face": "MAIN-100",
        "length_meters": 12,
        "designation": "LOADING",
        "capacity_slots": 5,
        "pricing_policy_id": pricing_policy_id,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(permittee_id, zone_ids, **overrides) -> dict:
    defaults = {
        "permittee_id": permittee_id,
        "requested_designation": "LOADING",
        "purpose": "deliveries",
        "zone_ids": zone_ids,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_window_payload(permit_id, zone_id, day_of_week, start_minute, end_minute, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "zone_id": zone_id,
        "day_of_week": day_of_week,
        "start_minute": start_minute,
        "end_minute": end_minute,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(permit_id, zone_id, start_utc, end_utc, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "zone_id": zone_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(zone_id, permittee_id, violation_type, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "permittee_id": permittee_id,
        "violation_type": violation_type,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(name, start_utc, end_utc, zone_ids, **overrides) -> dict:
    defaults = {
        "name": name,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "zone_ids": zone_ids,
    }
    defaults.update(overrides)
    return defaults
