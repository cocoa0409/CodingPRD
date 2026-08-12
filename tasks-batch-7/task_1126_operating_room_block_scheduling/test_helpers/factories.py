"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "LINE_NAME": "GS",
    "TARGET_UTILIZATION_PCT": 75,
    "ROOM_NAME": "OR1",
    "SURGEON_NAME": "Dr. G",
    "PROVIDER_REF": "AN1",
    "BLOCK_DATE": "2026-05-04",
    "BLOCK_START": 420,
    "BLOCK_END": 720,
    "PROCEDURE_CLASS": "STANDARD",
    "PRIORITY": "ELECTIVE",
}


def create_service_line_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LINE_NAME"],
        "target_utilization_pct": DEFAULTS["TARGET_UTILIZATION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_surgeon_payload(service_line_id: str, **overrides) -> dict:
    defaults = {
        "service_line_id": service_line_id,
        "full_name": DEFAULTS["SURGEON_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_operating_room_payload(**overrides) -> dict:
    defaults = {"room_name": DEFAULTS["ROOM_NAME"]}
    defaults.update(overrides)
    return defaults


def create_block_payload(service_line_id: str, or_id: str, **overrides) -> dict:
    defaults = {
        "service_line_id": service_line_id,
        "or_id": or_id,
        "date": DEFAULTS["BLOCK_DATE"],
        "start_minute": DEFAULTS["BLOCK_START"],
        "end_minute": DEFAULTS["BLOCK_END"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(surgeon_id: str, **overrides) -> dict:
    defaults = {
        "surgeon_id": surgeon_id,
        "procedure_class": DEFAULTS["PROCEDURE_CLASS"],
        "priority": DEFAULTS["PRIORITY"],
    }
    defaults.update(overrides)
    return defaults


def create_anesthesia_coverage_payload(or_id: str, **overrides) -> dict:
    defaults = {
        "or_id": or_id,
        "date": DEFAULTS["BLOCK_DATE"],
        "start_minute": 420,
        "end_minute": 1200,
        "provider_ref": DEFAULTS["PROVIDER_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_reallocation_request_payload(slot_id: str, case_id: str, **overrides) -> dict:
    defaults = {"slot_id": slot_id, "case_id": case_id}
    defaults.update(overrides)
    return defaults


def create_vote_payload(vote: str, expected_review_version: int, **overrides) -> dict:
    defaults = {"vote": vote, "expected_review_version": expected_review_version}
    defaults.update(overrides)
    return defaults


def schedule_block_payload(block_id: str, **overrides) -> dict:
    defaults = {"block_id": block_id}
    defaults.update(overrides)
    return defaults


def schedule_emergent_payload(or_id: str, date: str, desired_start_minute: int, **overrides) -> dict:
    defaults = {
        "or_id": or_id,
        "date": date,
        "desired_start_minute": desired_start_minute,
    }
    defaults.update(overrides)
    return defaults
