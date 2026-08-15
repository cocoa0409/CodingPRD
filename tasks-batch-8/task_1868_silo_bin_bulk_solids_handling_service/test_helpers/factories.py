"""Payload factories — one per entity, input fields only (PRD §3.1–§3.9)."""

DEFAULTS = {
    "SITE_NAME": "Test Site",
    "STATE_CODE": "IA",
    "TECH_NAME": "Test Tech",
    "WEEKLY_CAPACITY_HOURS": 40,
    "VESSEL_NAME": "SILO-1",
    "VESSEL_KIND": "SILO",
    "CAPACITY_TONS": 100,
    "MATERIAL_NAME": "cement",
    "REORDER_POINT_PCT": 30,
    "JOB_TYPE": "INSPECTION",
    "EST_HOURS": 2,
    "CREW_SIZE": 1,
    "MEASURED_AT": "2026-08-02T00:00:00Z",
    "LEVEL_PCT": 50.0,
    "SAMPLED_AT": "2026-08-02T00:00:00Z",
    "MOISTURE_PCT": 10.0,
    "CAKING_INDEX": 1,
    "TESTED_AT": "2026-08-02T00:00:00Z",
    "TEST_WEIGHT_TONS": 20.0,
    "INDICATED_TONS": 20.0,
    "PERMIT_WINDOW_START": "2026-08-10T08:00:00Z",
    "PERMIT_WINDOW_END": "2026-08-10T10:00:00Z",
}


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TECH_NAME"],
        "weekly_capacity_hours": DEFAULTS["WEEKLY_CAPACITY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "name": DEFAULTS["VESSEL_NAME"],
        "vessel_kind": DEFAULTS["VESSEL_KIND"],
        "capacity_tons": DEFAULTS["CAPACITY_TONS"],
        "material_name": DEFAULTS["MATERIAL_NAME"],
        "reorder_point_pct": DEFAULTS["REORDER_POINT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_level_reading_payload(vessel_id: str, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "measured_at": DEFAULTS["MEASURED_AT"],
        "level_pct": DEFAULTS["LEVEL_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_quality_report_payload(vessel_id: str, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "sampled_at": DEFAULTS["SAMPLED_AT"],
        "moisture_pct": DEFAULTS["MOISTURE_PCT"],
        "caking_index": DEFAULTS["CAKING_INDEX"],
    }
    defaults.update(overrides)
    return defaults


def create_scale_calibration_payload(vessel_id: str, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "tested_at": DEFAULTS["TESTED_AT"],
        "test_weight_tons": DEFAULTS["TEST_WEIGHT_TONS"],
        "indicated_tons": DEFAULTS["INDICATED_TONS"],
    }
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(site_id: str, vessel_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "vessel_id": vessel_id,
        "job_type": DEFAULTS["JOB_TYPE"],
        "requires_entry": False,
        "est_hours": DEFAULTS["EST_HOURS"],
        "crew_size": DEFAULTS["CREW_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_entry_permit_payload(
    vessel_id: str, ticket_id: str, entrant_technician_id: str, **overrides
) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "ticket_id": ticket_id,
        "entrant_technician_id": entrant_technician_id,
        "window_start": DEFAULTS["PERMIT_WINDOW_START"],
        "window_end": DEFAULTS["PERMIT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults
