"""Payload factories — one per entity, request-input fields only."""

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "ROOFER_NAME": "Ridgeline Roofing",
    "SOLAR_OWNER_NAME": "Nguyen Household",
    "SYSTEM_OWNER_NAME": "Helio Lease Holdings",
    "CREW_NAME": "SunSystem Crew A",
    "SITE_ADDRESS": "418 Mesquite Way, Tempe AZ",
    "JURISDICTION_NAME": "City of Tempe Building Safety",
}


def create_party_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROOFER_NAME"],
        "party_type": "ROOFER",
        "contact_email": "ops@ridgeline.example",
    }
    payload.update(overrides)
    return payload


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["JURISDICTION_NAME"],
        "code": "TEMPE1",
        "repermit_required_for_reinstall": False,
        "reinspection_required": False,
        "inspection_slots_per_day": 2,
        "backlog_days": 0,
        "permit_review_days": 5,
    }
    payload.update(overrides)
    return payload


def create_project_payload(
    roofer_party_id: str,
    solar_owner_party_id: str,
    solar_contractor_party_id: str,
    **overrides,
) -> dict:
    payload = {
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "ownership_model": "LEASE",
        "system_dc_kw": TEST_DEFAULTS["SYSTEM_DC_KW"],
        "roofer_party_id": roofer_party_id,
        "solar_owner_party_id": solar_owner_party_id,
        "solar_contractor_party_id": solar_contractor_party_id,
        "baseline_daily_kwh": TEST_DEFAULTS["BASELINE_DAILY_KWH"],
        "downtime_days_estimated": TEST_DEFAULTS["DOWNTIME_DAYS_ESTIMATED"],
        "upgrade_budget_cents": TEST_DEFAULTS["UPGRADE_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_array_circuit_payload(**overrides) -> dict:
    payload = {"circuit_label": "S1", "module_count": 1, "dc_kw": 0.41}
    payload.update(overrides)
    return payload


def create_storage_bin_payload(**overrides) -> dict:
    payload = {"bin_label": "BIN-A", "capacity_slots": 4}
    payload.update(overrides)
    return payload


def create_hardware_unit_payload(array_circuit_id: str, **overrides) -> dict:
    payload = {
        "array_circuit_id": array_circuit_id,
        "unit_type": "PANEL",
        "manufacturer": TEST_DEFAULTS["MANUFACTURER"],
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "serial_number": "SN-0001",
        "rated_watts": TEST_DEFAULTS["RATED_WATTS"],
    }
    payload.update(overrides)
    return payload


def create_deck_finding_payload(**overrides) -> dict:
    payload = {
        "finding_type": "FASTENER_PULLOUT",
        "severity": "LOW",
        "affected_area_sqft": 20,
        "attachment_count_affected": 2,
    }
    payload.update(overrides)
    return payload


def create_permit_application_payload(
    project_id: str, jurisdiction_id: str, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "jurisdiction_id": jurisdiction_id,
        "scope": "REINSTALL_ONLY",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_type": "ROOF_DECK",
        "slot_date": "2026-08-10",
        "window_start_utc": "2026-08-10T13:00:00Z",
        "window_end_utc": "2026-08-10T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_work_window_payload(project_id: str, party_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "party_id": party_id,
        "trade": "ROOFING",
        "start_utc": "2026-08-05T13:00:00Z",
        "end_utc": "2026-08-05T21:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sourcing_order_payload(
    project_id: str, hardware_unit_id: str, expected_project_version: int, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "hardware_unit_id": hardware_unit_id,
        "requested_model_code": TEST_DEFAULTS["MODEL_CODE"],
        "offered_manufacturer": TEST_DEFAULTS["MANUFACTURER"],
        "offered_model_code": TEST_DEFAULTS["MODEL_CODE"],
        "offered_rated_watts": TEST_DEFAULTS["RATED_WATTS"],
        "unit_cost_cents": 32_000,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def warranty_notice_payload(expected_project_version: int, **overrides) -> dict:
    payload = {
        "manufacturer": TEST_DEFAULTS["MANUFACTURER"],
        "notice_reference": "MN-2026-0417",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload
