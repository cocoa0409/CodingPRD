"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "FARM_NAME": "Test Farm",
    "CONTACT_EMAIL": "farm@example.org",
    "COUNTY_CODE": "AAA",
    "DONOR_TIN": "12-3456789",
    "CROP_CODE": "ROOT_VEG",
    "ESTIMATED_LBS": 100.0,
    "WINDOW_START": "2026-08-05T00:00:00Z",
    "WINDOW_END": "2026-08-20T00:00:00Z",
    "PERISHABILITY": "LOW",
    "VOLUNTEER_NAME": "Test Volunteer",
    "VEHICLE_PAYLOAD_LBS": 5000.0,
    "AGENCY_CAPACITY_LBS": 10000.0,
    "CONTAINER_TARE_LBS": 10.0,
    "CONTAINER_CAPACITY_LBS": 500.0,
    "EVENT_START": "2026-08-10T08:00:00Z",
    "EVENT_END": "2026-08-10T12:00:00Z",
    "CREW_CAPACITY": 1,
    "GROSS_LBS": 110.0,
    "CULL_LBS": 0.0,
    "PLANNED_LBS": 50.0,
    "DELIVERY_DATE": "2026-08-12T10:00:00Z",
    "TEMP_RECORDED_AT": "2026-08-10T13:00:00Z",
    "TEMP_F": 38.0,
    "CONDEMNED_LBS": 5.0,
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-09-01T00:00:00Z",
}


def create_farm_payload(**overrides) -> dict:
    defaults = {
        "farm_name": DEFAULTS["FARM_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "county_code": DEFAULTS["COUNTY_CODE"],
        "donor_tin": DEFAULTS["DONOR_TIN"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(farm_id, **overrides) -> dict:
    defaults = {
        "farm_id": farm_id,
        "crop_code": DEFAULTS["CROP_CODE"],
        "estimated_lbs": DEFAULTS["ESTIMATED_LBS"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "perishability_class": DEFAULTS["PERISHABILITY"],
        "requires_refrigeration": False,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["VOLUNTEER_NAME"],
        "email": "volunteer@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(volunteer_id, glean_event_id, witness_volunteer_id, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "glean_event_id": glean_event_id,
        "signature_payload": "sig",
        "witness_volunteer_id": witness_volunteer_id,
    }
    defaults.update(overrides)
    return defaults


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_name": "Test Agency",
        "county_code": DEFAULTS["COUNTY_CODE"],
        "weekly_capacity_lbs": DEFAULTS["AGENCY_CAPACITY_LBS"],
        "refrigeration_capable": False,
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(**overrides) -> dict:
    defaults = {
        "label": "BIN-1",
        "tare_lbs": DEFAULTS["CONTAINER_TARE_LBS"],
        "capacity_lbs": DEFAULTS["CONTAINER_CAPACITY_LBS"],
        "refrigerated": False,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "plate": "PLATE-1",
        "payload_capacity_lbs": DEFAULTS["VEHICLE_PAYLOAD_LBS"],
        "refrigerated": False,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(surplus_offer_id, crew_leader_volunteer_id, assigned_vehicle_id, **overrides) -> dict:
    defaults = {
        "surplus_offer_id": surplus_offer_id,
        "scheduled_start": DEFAULTS["EVENT_START"],
        "scheduled_end": DEFAULTS["EVENT_END"],
        "crew_leader_volunteer_id": crew_leader_volunteer_id,
        "assigned_vehicle_id": assigned_vehicle_id,
        "crew_capacity": DEFAULTS["CREW_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(glean_event_id, volunteer_id, **overrides) -> dict:
    defaults = {"glean_event_id": glean_event_id, "volunteer_id": volunteer_id}
    defaults.update(overrides)
    return defaults


def create_lot_payload(glean_event_id, container_id, recorded_by_volunteer_id, **overrides) -> dict:
    defaults = {
        "glean_event_id": glean_event_id,
        "container_id": container_id,
        "gross_lbs": DEFAULTS["GROSS_LBS"],
        "cull_lbs": DEFAULTS["CULL_LBS"],
        "recorded_by_volunteer_id": recorded_by_volunteer_id,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(glean_event_id, agency_id, expected_event_version, **overrides) -> dict:
    defaults = {
        "glean_event_id": glean_event_id,
        "agency_id": agency_id,
        "planned_lbs": DEFAULTS["PLANNED_LBS"],
        "delivery_date": DEFAULTS["DELIVERY_DATE"],
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_templog_payload(glean_event_id, **overrides) -> dict:
    defaults = {
        "glean_event_id": glean_event_id,
        "recorded_at": DEFAULTS["TEMP_RECORDED_AT"],
        "temp_f": DEFAULTS["TEMP_F"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(glean_event_id, reported_by_volunteer_id, **overrides) -> dict:
    defaults = {
        "glean_event_id": glean_event_id,
        "severity": "MINOR",
        "condemned_lbs": DEFAULTS["CONDEMNED_LBS"],
        "reported_by_volunteer_id": reported_by_volunteer_id,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "county_code": DEFAULTS["COUNTY_CODE"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults
