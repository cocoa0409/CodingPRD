"""Payload factories — one per entity, input fields only.

Each factory provides sensible required-field defaults and merges any overrides.
Optional fields (those the PRD declares optional or defaulted) are omitted unless
explicitly supplied via overrides, so tests can exercise default behavior.
"""

DEFAULTS = {
    "DEPARTMENT_NAME": "Streets & Sanitation",
    "BACKLOG_THRESHOLD": 5,
    "CATEGORY_NAME": "Pothole Repair",
    "CATEGORY_CODE": "POTHOLE",
    "JURISDICTION_NAME": "District 4",
    "CITIZEN_FULL_NAME": "Test Citizen",
    "AGENT_FULL_NAME": "Test Agent",
    "DESCRIPTION": "Reported issue",
    "RESOLUTION_SLA_HOURS": 24,
    "ESCALATION_TIER1_HOURS": 2,
    "ESCALATION_TIER2_HOURS": 6,
}


def create_department_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DEPARTMENT_NAME"],
        "backlog_threshold": DEFAULTS["BACKLOG_THRESHOLD"],
    }
    payload.update(overrides)
    return payload


def create_category_payload(default_department_id, **overrides) -> dict:
    payload = {
        "name": DEFAULTS["CATEGORY_NAME"],
        "code": DEFAULTS["CATEGORY_CODE"],
        "default_department_id": default_department_id,
    }
    payload.update(overrides)
    return payload


def create_jurisdiction_payload(
    min_lat, max_lat, min_lng, max_lng, **overrides
) -> dict:
    payload = {
        "name": DEFAULTS["JURISDICTION_NAME"],
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lng": min_lng,
        "max_lng": max_lng,
    }
    payload.update(overrides)
    return payload


def create_sla_policy_payload(category_id, priority, **overrides) -> dict:
    payload = {
        "category_id": category_id,
        "priority": priority,
        "resolution_sla_hours": DEFAULTS["RESOLUTION_SLA_HOURS"],
        "escalation_tier1_hours": DEFAULTS["ESCALATION_TIER1_HOURS"],
        "escalation_tier2_hours": DEFAULTS["ESCALATION_TIER2_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_citizen_payload(email, **overrides) -> dict:
    payload = {
        "email": email,
        "full_name": DEFAULTS["CITIZEN_FULL_NAME"],
    }
    payload.update(overrides)
    return payload


def create_agent_payload(department_id, **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "full_name": DEFAULTS["AGENT_FULL_NAME"],
    }
    payload.update(overrides)
    return payload


def create_service_request_payload(citizen_id, category_id, **overrides) -> dict:
    payload = {
        "citizen_id": citizen_id,
        "category_id": category_id,
        "description": DEFAULTS["DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_duplicate_cluster_payload(
    category_id, canonical_request_id, expected_canonical_version, **overrides
) -> dict:
    payload = {
        "category_id": category_id,
        "canonical_request_id": canonical_request_id,
        "expected_canonical_version": expected_canonical_version,
    }
    payload.update(overrides)
    return payload


def assign_work_order_payload(assigned_agent_id, expected_work_order_version, **overrides) -> dict:
    payload = {
        "assigned_agent_id": assigned_agent_id,
        "expected_work_order_version": expected_work_order_version,
    }
    payload.update(overrides)
    return payload


def complete_work_order_payload(completion_note="fixed", **overrides) -> dict:
    payload = {"completion_note": completion_note}
    payload.update(overrides)
    return payload


def create_escalation_payload(request_id, **overrides) -> dict:
    payload = {"request_id": request_id}
    payload.update(overrides)
    return payload


def respond_survey_payload(score, **overrides) -> dict:
    payload = {"score": score}
    payload.update(overrides)
    return payload


def create_service_window_payload(window_type, starts_at, ends_at, **overrides) -> dict:
    payload = {
        "window_type": window_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload
