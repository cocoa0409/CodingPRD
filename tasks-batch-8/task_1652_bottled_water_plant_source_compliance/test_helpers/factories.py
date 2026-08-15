"""Payload factories — one per entity, input fields only (PRD §3)."""
from . import constants as C


def create_plant_payload(**overrides) -> dict:
    defaults = {"name": "Test Plant"}
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": "SP-1",
        "source_classification": "SPRING",
        "daily_cap_gallons": C.DEFAULTS["DAILY_CAP_GALLONS"],
        "monthly_cap_gallons": C.DEFAULTS["MONTHLY_CAP_GALLONS"],
        "valid_from": C.DEFAULTS["VALID_FROM"],
        "valid_to": C.DEFAULTS["VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_event_payload(**overrides) -> dict:
    defaults = {
        "withdrawal_date": C.STARTUP_DATE,
        "gallons": 100,
        "meter_reading_start_gallons": 0,
        "meter_reading_end_gallons": 100,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_run_payload(**overrides) -> dict:
    defaults = {
        "source_permit_id": None,
        "scheduled_start": "2026-08-03T06:00:00Z",
        "scheduled_end": "2026-08-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def passing_parameters_payload(**overrides) -> dict:
    """Disinfection parameters exactly at the passing thresholds (§3.3)."""
    defaults = {
        "uv_dose_mj_cm2": C.UV_DOSE_MIN,
        "ozone_ct_mg_min_l": C.OZONE_CT_MIN,
        "turbidity_ntu": C.TURBIDITY_MAX,
        "micro_pore_micron": C.MICRO_PORE_MAX_SPRING,
    }
    defaults.update(overrides)
    return defaults


def create_lab_test_payload(**overrides) -> dict:
    defaults = {
        "test_type": "SOURCE_RAW",
        "subject_permit_id": None,
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(**overrides) -> dict:
    defaults = {
        "result": "PASS",
        "collected_at": "2026-08-04T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bottling_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "LINE-1",
        "daily_capacity_units": C.DEFAULTS["LINE_DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_preform_delivery_payload(**overrides) -> dict:
    defaults = {
        "supplier": "ACME",
        "delivered_units": 5000,
    }
    defaults.update(overrides)
    return defaults


def qc_verdict_payload(**overrides) -> dict:
    defaults = {
        "verdict": "ACCEPTED",
        "accepted_units": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_production_lot_payload(**overrides) -> dict:
    defaults = {
        "treatment_run_id": None,
        "label_classification": "SPRING",
        "planned_units": 100,
        "scheduled_start": "2026-08-04T08:00:00Z",
        "scheduled_end": "2026-08-04T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(**overrides) -> dict:
    defaults = {
        "reason": "quality defect",
        "lot_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_wash_batch_payload(**overrides) -> dict:
    defaults = {
        "washer_unit": "WASHER_A",
        "scheduled_start": "2026-08-05T09:00:00Z",
        "scheduled_end": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_wash_batch_payload(**overrides) -> dict:
    defaults = {
        "rinse_temp_c": C.RINSE_TEMP_MIN_C,
        "sanitizer_ppm": C.SANITIZER_MIN_PPM,
    }
    defaults.update(overrides)
    return defaults


def create_bottle_payload(**overrides) -> dict:
    defaults = {
        "bottle_code": "B-001",
    }
    defaults.update(overrides)
    return defaults


def create_community_report_payload(**overrides) -> dict:
    defaults = {
        "period_year": 2026,
        "period_month": 8,
    }
    defaults.update(overrides)
    return defaults
