"""Payload factories — one per entity, input fields only."""


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Incident",
        "incident_type": "WILDERNESS_SEARCH",
        "ics_incident_number": "OR-2026-9000",
    }
    defaults.update(overrides)
    return defaults


def create_task_payload(incident_id, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "task_number": "T-1",
        "task_type": "GRID_SEARCH",
        "segment_area_sqkm": 5.0,
        "planned_searcher_hours": 4,
        "planned_start": "2026-05-02T08:00:00Z",
        "planned_end": "2026-05-02T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Team",
        "team_type": "GROUND",
        "base_location": "Bend",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(team_id, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "full_name": "Test Volunteer",
        "email": "vol@x.org",
        "member_role": "SEARCHER",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "cert_type": "WFR",
        "issued_date": "2024-01-01T00:00:00Z",
        "expires_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_callout_payload(task_id, member_id, **overrides) -> dict:
    defaults = {
        "task_id": task_id,
        "member_id": member_id,
    }
    defaults.update(overrides)
    return defaults


def create_resource_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Asset",
        "resource_type": "HELICOPTER",
    }
    defaults.update(overrides)
    return defaults


def create_resource_assignment_payload(resource_id, task_id, expected_resource_version, **overrides) -> dict:
    defaults = {
        "resource_id": resource_id,
        "task_id": task_id,
        "window_start": "2026-05-02T09:00:00Z",
        "window_end": "2026-05-02T11:00:00Z",
        "expected_resource_version": expected_resource_version,
    }
    defaults.update(overrides)
    return defaults


def create_ground_track_payload(task_id, member_id, **overrides) -> dict:
    defaults = {
        "task_id": task_id,
        "member_id": member_id,
        "recorded_at": "2026-05-02T10:00:00Z",
        "distance_km": 10.0,
        "duration_min": 60,
        "coverage_area_sqkm": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_clue_payload(incident_id, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "clue_number": "C-1",
        "description": "footprint",
        "found_at": "2026-05-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(member_id, incident_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "incident_id": incident_id,
        "declared_mileage_miles": 20,
    }
    defaults.update(overrides)
    return defaults


def create_aar_payload(incident_id, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "summary": "prelim",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
