"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import COURSE_DEFAULTS, DEFAULT_CLOCK


def create_course_payload(**overrides) -> dict:
    payload = dict(COURSE_DEFAULTS)
    payload.update(overrides)
    return payload


def create_time_slot_payload(course_id, start_at, capacity=None, **overrides) -> dict:
    payload = {"course_id": course_id, "start_at": start_at}
    if capacity is not None:
        payload["capacity"] = capacity
    payload.update(overrides)
    return payload


def create_guide_payload(name="G1", certification_level=3, **overrides) -> dict:
    payload = {"name": name, "certification_level": certification_level}
    payload.update(overrides)
    return payload


def create_guide_assignment_payload(guide_id, time_slot_id, **overrides) -> dict:
    payload = {"guide_id": guide_id, "time_slot_id": time_slot_id}
    payload.update(overrides)
    return payload


def create_participant_payload(full_name="P A", weight_kg=70,
                               birthdate="2000-01-01T00:00:00Z", **overrides) -> dict:
    payload = {"full_name": full_name, "weight_kg": weight_kg, "birthdate": birthdate}
    payload.update(overrides)
    return payload


def create_waiver_payload(signature_name="P A", **overrides) -> dict:
    payload = {"signature_name": signature_name}
    payload.update(overrides)
    return payload


def create_season_pass_payload(expected_participant_version, tier="STANDARD",
                               valid_from=DEFAULT_CLOCK,
                               valid_until="2026-12-31T23:59:59Z",
                               total_uses=5, **overrides) -> dict:
    payload = {
        "tier": tier,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "total_uses": total_uses,
        "expected_participant_version": expected_participant_version,
    }
    payload.update(overrides)
    return payload


def create_group_payload(time_slot_id, expected_size=2, name="Team",
                         organizer_name="Org", **overrides) -> dict:
    payload = {
        "name": name,
        "time_slot_id": time_slot_id,
        "expected_size": expected_size,
        "organizer_name": organizer_name,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(time_slot_id, participant_id, group_id=None,
                           use_season_pass=None, **overrides) -> dict:
    payload = {"time_slot_id": time_slot_id, "participant_id": participant_id}
    if group_id is not None:
        payload["group_id"] = group_id
    if use_season_pass is not None:
        payload["use_season_pass"] = use_season_pass
    payload.update(overrides)
    return payload


def create_gear_item_payload(gear_type="HARNESS", size="M", **overrides) -> dict:
    payload = {"gear_type": gear_type, "size": size}
    payload.update(overrides)
    return payload


def create_gear_checkout_payload(gear_item_id, booking_id, **overrides) -> dict:
    payload = {"gear_item_id": gear_item_id, "booking_id": booking_id}
    payload.update(overrides)
    return payload


def create_incident_report_payload(booking_id, reported_by_guide_id,
                                   severity="SEVERE",
                                   description="fall arrested by harness",
                                   **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "severity": severity,
        "description": description,
        "reported_by_guide_id": reported_by_guide_id,
    }
    payload.update(overrides)
    return payload
