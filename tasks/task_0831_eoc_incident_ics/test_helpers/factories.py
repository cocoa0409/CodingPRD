"""Payload factories — one per entity, input fields only (PRD §3).

Each factory supplies sensible defaults for the entity's own scalar input
fields; foreign-key fields that must reference real created resources are
passed explicitly. Optional fields (those with a PRD default) are omitted
unless overridden, so the server exercises its own defaulting.
"""

DEFAULTS = {
    "OP_START": "2026-03-01T06:00:00Z",
    "OP_END": "2026-03-02T06:00:00Z",
    "DEPLOY_START": "2026-03-01T08:00:00Z",
    "DEPLOY_END": "2026-03-01T18:00:00Z",
}


def create_incident_payload(**overrides) -> dict:
    """PRD §3.1: name + hazard_type required; declaration_category and
    cost_ceiling optional (server defaults EMERGENCY / 100,000,000)."""
    payload = {"name": "Test Incident", "hazard_type": "FLOOD"}
    payload.update(overrides)
    return payload


def create_jurisdiction_payload(**overrides) -> dict:
    """PRD §3.6: name required; contact_email optional."""
    payload = {"name": "Test Jurisdiction"}
    payload.update(overrides)
    return payload


def create_resource_pool_payload(jurisdiction_id, **overrides) -> dict:
    """PRD §3.2: jurisdiction_id + resource_type + total_units required;
    surge_cap and turnaround_hours optional."""
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "resource_type": "VEHICLE",
        "total_units": 10,
    }
    payload.update(overrides)
    return payload


def create_resource_request_payload(incident_id, **overrides) -> dict:
    """PRD §3.2: incident_id + resource_type + requested_quantity required;
    priority optional (defaults MEDIUM)."""
    payload = {
        "incident_id": incident_id,
        "resource_type": "VEHICLE",
        "requested_quantity": 2,
    }
    payload.update(overrides)
    return payload


def create_iap_payload(incident_id, expected_incident_version, **overrides) -> dict:
    """PRD §3.4: incident_id, operational period, and expected_incident_version required."""
    payload = {
        "incident_id": incident_id,
        "operational_period_start": DEFAULTS["OP_START"],
        "operational_period_end": DEFAULTS["OP_END"],
        "expected_incident_version": expected_incident_version,
    }
    payload.update(overrides)
    return payload


def create_task_payload(iap_id, **overrides) -> dict:
    """PRD §3.4: iap_id + title required; parent_task_id and
    resource_request_id optional."""
    payload = {"iap_id": iap_id, "title": "Test Task"}
    payload.update(overrides)
    return payload


def create_shelter_payload(incident_id, **overrides) -> dict:
    """PRD §3.5: incident_id + name + capacity required."""
    payload = {"incident_id": incident_id, "name": "Test Shelter", "capacity": 100}
    payload.update(overrides)
    return payload


def create_mutual_aid_request_payload(incident_id, to_jurisdiction_id, **overrides) -> dict:
    """PRD §3.6: incident_id + to_jurisdiction_id + resource_type + requested_units required."""
    payload = {
        "incident_id": incident_id,
        "to_jurisdiction_id": to_jurisdiction_id,
        "resource_type": "PERSONNEL",
        "requested_units": 5,
    }
    payload.update(overrides)
    return payload


def create_damage_assessment_payload(incident_id, **overrides) -> dict:
    """PRD §3.7: incident_id + site_name + estimated_loss + infrastructure_category required."""
    payload = {
        "incident_id": incident_id,
        "site_name": "Test Site",
        "estimated_loss": 1000.00,
        "infrastructure_category": "CAT_C_ROADS",
    }
    payload.update(overrides)
    return payload


def create_cost_record_payload(incident_id, expected_incident_version, **overrides) -> dict:
    """PRD §3.8: incident_id + category + estimated_cost + expected_incident_version
    required; resource_request_id and eligible optional (eligible defaults true)."""
    payload = {
        "incident_id": incident_id,
        "category": "LABOR",
        "estimated_cost": 100.00,
        "expected_incident_version": expected_incident_version,
    }
    payload.update(overrides)
    return payload
