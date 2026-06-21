"""Payload factories — one per entity, input fields only.

Each factory returns a minimal valid create payload; tests pass **overrides to
control the values that the specific claim under test cares about.
"""
from .constants import (
    DEFAULT_MULTIPLIERS,
    DEFAULT_RESPONSE_TARGET,
    DEFAULT_RESOLVE_TARGET,
    DEFAULT_OLA_TARGET,
)

_UNIQUE = {"n": 0}


def _uniq(prefix: str) -> str:
    _UNIQUE["n"] += 1
    return f"{prefix}-{_UNIQUE['n']}"


def create_sla_policy_payload(**overrides) -> dict:
    payload = {
        "name": "Std",
        "response_target_minutes": DEFAULT_RESPONSE_TARGET,
        "resolve_target_minutes": DEFAULT_RESOLVE_TARGET,
        "ola_target_minutes": DEFAULT_OLA_TARGET,
        "priority_multipliers": dict(DEFAULT_MULTIPLIERS),
    }
    payload.update(overrides)
    return payload


def create_assignment_group_payload(**overrides) -> dict:
    payload = {"name": _uniq("Group")}
    payload.update(overrides)
    return payload


def create_category_payload(sla_policy_id: str, default_assignment_group_id: str, **overrides) -> dict:
    payload = {
        "name": _uniq("Category"),
        "default_priority": "P3",
        "sla_policy_id": sla_policy_id,
        "default_assignment_group_id": default_assignment_group_id,
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(category_id: str, **overrides) -> dict:
    payload = {
        "short_description": "Something is broken",
        "category_id": category_id,
    }
    payload.update(overrides)
    return payload


def create_problem_payload(owner_user_id: str = "owner-1", **overrides) -> dict:
    payload = {
        "title": "Recurring root cause",
        "owner_user_id": owner_user_id,
    }
    payload.update(overrides)
    return payload


def create_known_error_payload(**overrides) -> dict:
    payload = {
        "symptom": "Observable symptom",
        "workaround": "Documented workaround",
    }
    payload.update(overrides)
    return payload


def create_kb_article_payload(category_id: str, **overrides) -> dict:
    payload = {
        "title": "Self-service article",
        "category_id": category_id,
        "body": "Steps to resolve.",
    }
    payload.update(overrides)
    return payload


def create_change_request_payload(ticket_id: str, **overrides) -> dict:
    payload = {
        "title": "Controlled change",
        "ticket_id": ticket_id,
        "risk": "MEDIUM",
    }
    payload.update(overrides)
    return payload


def cast_vote_payload(decision: str, expected_change_request_version: int, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_change_request_version": expected_change_request_version,
    }
    payload.update(overrides)
    return payload


def create_csat_survey_payload(ticket_id: str, score: int = 5, **overrides) -> dict:
    payload = {
        "ticket_id": ticket_id,
        "score": score,
    }
    payload.update(overrides)
    return payload


def create_asset_payload(**overrides) -> dict:
    payload = {
        "asset_tag": _uniq("ASSET"),
        "kind": "SERVER",
    }
    payload.update(overrides)
    return payload


def route_payload(assignment_group_id: str, expected_ticket_version: int, **overrides) -> dict:
    payload = {
        "assignment_group_id": assignment_group_id,
        "expected_ticket_version": expected_ticket_version,
    }
    payload.update(overrides)
    return payload
