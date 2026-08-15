"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from . import constants as C

DEFAULTS = {
    "CIRCUIT_REF": "CKT-1",
    "VOLTAGE_CLASS": "KV_15",
    "LENGTH_M": 1000,
    "INSTALLATION_YEAR": 2015,
    "WINDOW_KIND": "PLANNED_DIAGNOSTIC",
    "BUDGET_CENTS": 800000,
    "METHODS": ["VLF_TAN_DELTA"],
    "TEST_VOLTAGE_KV": C.KV15_TEST_VOLTAGE,
    "UNIT_CODE": "VAN-1",
    "UNIT_CAPABILITIES": ["VLF", "PD", "TDR"],
    "UNIT_MAX_KV": 30.0,
    "GROUND_COUNT": 2,
    "EXCAVATION_COST_CENTS": 100040,
    "SPLICE_COST_CENTS": 200040,
    "SPLICE_TYPE": "HEAT_SHRINK",
    "PERMIT_REF": "MX-100",
    "TARGET_LOCATION_M": 1560.0,
}


def create_circuit_payload(**overrides) -> dict:
    defaults = {
        "circuit_ref": DEFAULTS["CIRCUIT_REF"],
        "voltage_class": DEFAULTS["VOLTAGE_CLASS"],
        "length_m": DEFAULTS["LENGTH_M"],
        "installation_year": DEFAULTS["INSTALLATION_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(circuit_id, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "kind": DEFAULTS["WINDOW_KIND"],
        "window_start": C.WINDOW_START,
        "window_end": C.WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(circuit_id, window_id, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "outage_window_id": window_id,
        "requested_methods": list(DEFAULTS["METHODS"]),
        "approved_budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(job_id, **overrides) -> dict:
    defaults = {
        "test_job_id": job_id,
        "isolation_points": ["SW-N", "SW-F"],
        "ground_count": DEFAULTS["GROUND_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(job_id, **overrides) -> dict:
    defaults = {
        "test_job_id": job_id,
        "method": "VLF_TAN_DELTA",
        "test_voltage_kv": DEFAULTS["TEST_VOLTAGE_KV"],
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(step_index, **overrides) -> dict:
    defaults = {
        "step_index": step_index,
        "applied_voltage_kv": 8.7,
        "ambient_temp_c": 20.0,
    }
    defaults.update(overrides)
    return defaults


def create_fault_payload(series_id, **overrides) -> dict:
    defaults = {"test_series_id": series_id}
    defaults.update(overrides)
    return defaults


def pinpoint_fault_payload(**overrides) -> dict:
    defaults = {
        "trace_time_us": 20.0,
        "pinpoint_method": "PULSE_ECHO",
    }
    defaults.update(overrides)
    return defaults


def create_excavation_payload(fault_id, **overrides) -> dict:
    defaults = {
        "fault_record_id": fault_id,
        "target_location_m": DEFAULTS["TARGET_LOCATION_M"],
        "dig_start": C.DIG_START,
        "dig_end": C.DIG_END,
        "permit_ref": DEFAULTS["PERMIT_REF"],
        "cost_cents": DEFAULTS["EXCAVATION_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_splice_payload(fault_id, excavation_id, **overrides) -> dict:
    defaults = {
        "fault_record_id": fault_id,
        "excavation_order_id": excavation_id,
        "splice_type": DEFAULTS["SPLICE_TYPE"],
        "cost_cents": DEFAULTS["SPLICE_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": DEFAULTS["UNIT_CODE"],
        "capabilities": list(DEFAULTS["UNIT_CAPABILITIES"]),
        "max_test_voltage_kv": DEFAULTS["UNIT_MAX_KV"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(unit_id, job_id, **overrides) -> dict:
    defaults = {
        "mobile_unit_id": unit_id,
        "test_job_id": job_id,
        "mobilize_at": C.MOBILIZE_AT,
        "demobilize_at": C.DEMOBILIZE_AT,
    }
    defaults.update(overrides)
    return defaults


def create_health_assessment_payload(circuit_id, expected_circuit_version, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "basis": "FORMAL",
        "expected_circuit_version": expected_circuit_version,
    }
    defaults.update(overrides)
    return defaults
