"""Payload factories — one per entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "CLIENT_NAME": "Test Client",
    "BILLING_MODEL": "PER_STORE",
    "PER_STORE_RATE_CENTS": 3500,
    "HOURLY_RATE_CENTS": 4200,
    "STORE_NAME": "Test Store",
    "STORE_ADDRESS": "1 Main St",
    "STORE_TIMEZONE": "America/Chicago",
    "REP_FULL_NAME": "Test Rep",
    "EMPLOYMENT_TYPE": "W2",
    "HOME_BASE_COMMUTE_MILES": 5,
    "MILEAGE_RATE_CENTS": 67,
    "TRAVEL_MINUTE_RATE_CENTS": 40,
    "MILEAGE_POLICY": "HOME_BASED",
    "PROJECT_TITLE": "Test Project",
    "SCOPE_TYPE": "AUDIT",
    "DUE_DATE": "2026-08-20",
    "SCHEDULED_START": "2026-08-05T09:00:00Z",
    "SCHEDULED_END": "2026-08-05T11:00:00Z",
    "IMAGE_URL": "https://img/evidence.jpg",
    "CARRIER": "UPS",
    "TRACKING_NUMBER": "1Z999",
    "PROMISED_DATE": "2026-08-15",
    "ROUND_TRIP_MILES": 100,
    "HOME_TO_FIRST_STOP_MILES": 10,
    "DRIVE_MINUTES": 60,
    "REWORK_REASON": "photo evidence insufficient",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLIENT_NAME"],
        "billing_model": DEFAULTS["BILLING_MODEL"],
        "per_store_rate_cents": DEFAULTS["PER_STORE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(store_number="S1", **overrides) -> dict:
    defaults = {
        "store_number": store_number,
        "name": DEFAULTS["STORE_NAME"],
        "address": DEFAULTS["STORE_ADDRESS"],
        "timezone": DEFAULTS["STORE_TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_rep_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["REP_FULL_NAME"],
        "employment_type": DEFAULTS["EMPLOYMENT_TYPE"],
        "home_base_commute_miles": DEFAULTS["HOME_BASE_COMMUTE_MILES"],
        "mileage_rate_cents": DEFAULTS["MILEAGE_RATE_CENTS"],
        "travel_minute_rate_cents": DEFAULTS["TRAVEL_MINUTE_RATE_CENTS"],
        "mileage_policy": DEFAULTS["MILEAGE_POLICY"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "title": DEFAULTS["PROJECT_TITLE"],
        "scope_type": DEFAULTS["SCOPE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_project_store_payload(project_id, store_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "store_id": store_id,
        "due_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(project_id, project_store_id, rep_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "project_store_id": project_store_id,
        "rep_id": rep_id,
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(photo_type, captured_at, **overrides) -> dict:
    defaults = {
        "photo_type": photo_type,
        "image_url": DEFAULTS["IMAGE_URL"],
        "captured_at": captured_at,
    }
    defaults.update(overrides)
    return defaults


def create_exception_payload(**overrides) -> dict:
    defaults = {
        "exception_type": "OUT_OF_STOCK",
        "sku_count": 1,
        "severity": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_rework_authorization_payload(project_id, project_store_id,
                                        rejected_store_visit_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "project_store_id": project_store_id,
        "rejected_store_visit_id": rejected_store_visit_id,
        "reason": DEFAULTS["REWORK_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_fixture_shipment_payload(project_id, project_store_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "project_store_id": project_store_id,
        "carrier": DEFAULTS["CARRIER"],
        "tracking_number": DEFAULTS["TRACKING_NUMBER"],
        "promised_date": DEFAULTS["PROMISED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_mileage_log_payload(rep_id, assignment_id, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "assignment_id": assignment_id,
        "round_trip_miles": DEFAULTS["ROUND_TRIP_MILES"],
        "home_to_first_stop_miles": DEFAULTS["HOME_TO_FIRST_STOP_MILES"],
        "drive_minutes": DEFAULTS["DRIVE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(client_id, project_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "project_id": project_id,
    }
    defaults.update(overrides)
    return defaults
