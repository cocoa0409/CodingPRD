"""Payload factories — one per entity, input fields only."""
import itertools

_email_seq = itertools.count(1)


def unique_email(prefix: str = "dig") -> str:
    return f"{prefix}{next(_email_seq)}@example.com"


def create_excavator_payload(**overrides) -> dict:
    defaults = {
        "company_name": "DigCo",
        "contact_email": unique_email("exc"),
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_member_utility_payload(**overrides) -> dict:
    defaults = {
        "name": "Gas Co",
        "facility_type": "GAS",
        "service_polygon": {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 100},
    }
    defaults.update(overrides)
    return defaults


def create_locate_tech_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Tina Tech",
        "certified_facility_types": ["GAS"],
    }
    # member_utility_id is required and has no sensible default; caller supplies it.
    defaults.update(overrides)
    return defaults


def create_locate_ticket_payload(**overrides) -> dict:
    defaults = {
        "ticket_type": "EMERGENCY",
        "dig_polygon": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
        "work_description": "job",
    }
    # excavator_id supplied by caller.
    defaults.update(overrides)
    return defaults


def create_positive_response_payload(**overrides) -> dict:
    defaults = {
        "outcome": "CLEAR",
    }
    # notification_id supplied by caller.
    defaults.update(overrides)
    return defaults


def create_locate_assignment_payload(**overrides) -> dict:
    defaults = {}
    # ticket_id, notification_id, locate_tech_id all supplied by caller.
    defaults.update(overrides)
    return defaults


def create_mark_out_payload(**overrides) -> dict:
    defaults = {
        "marks_count": 2,
    }
    # assignment_id, ticket_id supplied by caller.
    defaults.update(overrides)
    return defaults


def create_meet_request_payload(**overrides) -> dict:
    defaults = {
        "proposed_start_min": 100,
        "proposed_end_min": 200,
    }
    # ticket_id, member_utility_id supplied by caller.
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(**overrides) -> dict:
    defaults = {
        "repair_cost_cents": 10000,
        "dug_within_marks": False,
    }
    # ticket_id, member_utility_id supplied by caller.
    defaults.update(overrides)
    return defaults
