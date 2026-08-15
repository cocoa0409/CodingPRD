"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

# Canonical policy defaults per equipment class (PRD §3.1 policy book fields).
POLICY_DEFAULTS = {
    "POWER_TRANSFORMER": {
        "interval_months": 12,
        "condition_escalation_threshold": 60,
        "condition_critical_threshold": 40,
        "oil_warn_ppm": 20,
        "oil_critical_ppm": 35,
        "ir_min_mohm": 1000,
        "relay_timing_warn_pct": 5,
        "relay_timing_fail_pct": 10,
        "w_insulation": 0.4,
        "w_oil": 0.35,
        "w_relay": 0.25,
    },
    "CIRCUIT_BREAKER": {
        "interval_months": 12,
        "condition_escalation_threshold": 60,
        "condition_critical_threshold": 40,
        "oil_warn_ppm": 20,
        "oil_critical_ppm": 35,
        "ir_min_mohm": 500,
        "relay_timing_warn_pct": 5,
        "relay_timing_fail_pct": 10,
        "w_insulation": 0.5,
        "w_oil": 0.2,
        "w_relay": 0.3,
    },
    "RELAY": {
        "interval_months": 6,
        "condition_escalation_threshold": 60,
        "condition_critical_threshold": 40,
        "oil_warn_ppm": 20,
        "oil_critical_ppm": 35,
        "ir_min_mohm": 100,
        "relay_timing_warn_pct": 5,
        "relay_timing_fail_pct": 10,
        "w_insulation": 0.3,
        "w_oil": 0.1,
        "w_relay": 0.6,
    },
}


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def create_substation_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Sub"), "code": _uniq("SUB"), "region": "North"}
    defaults.update(overrides)
    return defaults


def create_policy_payload(asset_class="POWER_TRANSFORMER", **overrides) -> dict:
    defaults = {"asset_class": asset_class}
    defaults.update(POLICY_DEFAULTS[asset_class])
    defaults.update(overrides)
    return defaults


def create_asset_payload(substation_id, asset_class="POWER_TRANSFORMER", **overrides) -> dict:
    defaults = {
        "substation_id": substation_id,
        "asset_class": asset_class,
        "voltage_kv": 115,
        "install_date": "2020-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"full_name": _uniq("Tech"), "employee_code": _uniq("EMP")}
    defaults.update(overrides)
    return defaults


def create_certification_payload(cert_type="NETA_LEVEL_2", **overrides) -> dict:
    defaults = {
        "cert_type": cert_type,
        "issued_at": "2025-01-01T00:00:00Z",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_outage_window_payload(substation_id, asset_id, start_ts, end_ts, **overrides) -> dict:
    defaults = {
        "substation_id": substation_id,
        "asset_id": asset_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "purpose": "Planned maintenance",
    }
    defaults.update(overrides)
    return defaults


def create_switching_step_payload(sequence_no=1, **overrides) -> dict:
    defaults = {"sequence_no": sequence_no, "description": f"Step {sequence_no}"}
    defaults.update(overrides)
    return defaults


def create_test_event_payload(asset_id, test_type="OIL_MOISTURE", **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "test_type": test_type,
        "value_primary": 10,
        "measured_at": "2026-07-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_defect_payload(asset_id, severity="C2", **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "title": _uniq("Defect"),
        "description": "Finding detail",
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(defect_id, assigned_technician_id, **overrides) -> dict:
    defaults = {
        "defect_id": defect_id,
        "assigned_technician_id": assigned_technician_id,
        "title": _uniq("WO"),
        "estimated_hours": 4,
    }
    defaults.update(overrides)
    return defaults


def create_spare_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_type": "SPARE_TRANSFORMER",
        "rating_mva": 25,
        "voltage_class_kv": 115,
        "impedance_pct": 6.5,
        "home_location": _uniq("Yard"),
    }
    defaults.update(overrides)
    return defaults


def create_spare_reservation_payload(start_ts, end_ts, **overrides) -> dict:
    defaults = {
        "unit_type": "SPARE_TRANSFORMER",
        "required_mva": 20,
        "required_voltage_kv": 115,
        "start_ts": start_ts,
        "end_ts": end_ts,
    }
    defaults.update(overrides)
    return defaults


def create_relay_setting_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "setting_group": "G1",
        "pickup_a": 80,
        "time_dial": 2.0,
        "curve": "IEC_SI",
    }
    defaults.update(overrides)
    return defaults


def create_environmental_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_date": "2026-07-15T00:00:00Z",
        "largest_vessel_gal": 1000,
        "containment_capacity_gal": 1050,
        "rainfall_freeboard_gal": 40,
        "method": "SPCC_SIMPLE",
    }
    defaults.update(overrides)
    return defaults
