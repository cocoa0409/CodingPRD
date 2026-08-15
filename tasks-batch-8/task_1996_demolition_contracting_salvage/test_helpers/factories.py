"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "address": "1 Demo St",
        "lot_area_sqft": TEST_DEFAULTS["LOT_AREA_SQFT"],
    }
    defaults.update(overrides)
    return defaults


def create_structure_survey_payload(**overrides) -> dict:
    defaults = {"structure_label": "Main"}
    defaults.update(overrides)
    return defaults


def complete_survey_payload(**overrides) -> dict:
    defaults = {"action": "COMPLETE", "hazmat_found": False, "findings_summary": "clean"}
    defaults.update(overrides)
    return defaults


def create_abatement_payload(**overrides) -> dict:
    defaults = {
        "material_type": "ASBESTOS",
        "description": "pipe wrap",
        "containment_method": "wet removal",
    }
    defaults.update(overrides)
    return defaults


def create_utility_disconnect_payload(**overrides) -> dict:
    defaults = {
        "utility_type": "ELECTRIC",
        "provider_name": "City Power",
        "disconnect_window_start": TEST_DEFAULTS["WINDOW_START"],
        "disconnect_window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": "P-1",
        "gross_floor_area_sqft": TEST_DEFAULTS["PERMIT_AREA_SQFT"],
    }
    defaults.update(overrides)
    return defaults


def create_engineering_survey_payload(**overrides) -> dict:
    defaults = {
        "demolition_method": "MECHANICAL",
        "structural_stability_rating": "STABLE",
        "max_structure_height_ft": 30,
        "adjacent_structure_distance_ft": 40,
    }
    defaults.update(overrides)
    return defaults


def create_salvage_manifest_payload(**overrides) -> dict:
    defaults = {"valuation_policy": "CONSERVATIVE", "processing_fee_cents": 50000}
    defaults.update(overrides)
    return defaults


def create_salvage_item_payload(**overrides) -> dict:
    defaults = {
        "material": "STEEL",
        "description": "beams",
        "quantity": 1,
        "unit": "TON",
        "low_unit_value_cents": 20000,
        "high_unit_value_cents": 32000,
    }
    defaults.update(overrides)
    return defaults


def create_neighbor_notification_payload(**overrides) -> dict:
    defaults = {
        "address": "1 Neighbor Ave",
        "notice_method": "CERTIFIED_MAIL",
        "scheduled_delivery_date": "2026-08-02",
    }
    defaults.update(overrides)
    return defaults


def create_dust_noise_log_payload(**overrides) -> dict:
    defaults = {
        "reading_type": "PM25",
        "measured_value": 100,
        "wind_speed_mph": 10,
        "duration_hours": 5,
    }
    defaults.update(overrides)
    return defaults


def create_debris_ticket_payload(**overrides) -> dict:
    defaults = {
        "ticket_number": "T-1",
        "facility_type": "LANDFILL",
        "material_class": "MIXED_CD",
        "gross_tons": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_backfill_plan_payload(**overrides) -> dict:
    defaults = {
        "design_disturbed_area_sqft": 10000,
        "planned_protected_area_sqft": 9500,
        "fill_volume_cu_yd": 500,
        "required_compaction_pct": 95.0,
    }
    defaults.update(overrides)
    return defaults


def create_final_inspection_payload(**overrides) -> dict:
    defaults = {"inspection_type": "FINAL_LOT", "scheduled_date": "2026-08-20"}
    defaults.update(overrides)
    return defaults
