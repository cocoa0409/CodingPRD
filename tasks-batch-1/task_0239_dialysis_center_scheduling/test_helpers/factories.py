"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD: only fields the PRD marks required are
included by default; optional fields are left to the caller via **overrides.
"""

DEFAULTS = {
    "CLINIC_NAME": "Test Clinic",
    "SHIFT_START": 360,       # 06:00
    "SHIFT_END": 600,         # 10:00
    "MACHINE_MODEL": "Test Model",
    "EFFECTIVE_FROM": "2026-06-01",
    "SERVICE_DATE": "2026-06-01",
    "SCHEDULED_DATE": "2026-06-15",
    "PERIOD_MONTH": "2026-06",
}


def create_clinic_payload(**overrides) -> dict:
    """Required: name. Optional: time_zone, dialyzer_reuse_limit."""
    defaults = {"name": DEFAULTS["CLINIC_NAME"]}
    defaults.update(overrides)
    return defaults


def create_shift_payload(clinic_id: str, **overrides) -> dict:
    """Required: clinic_id, code, day_pattern, start_minute, end_minute.
    Optional: turnover_buffer_minutes."""
    defaults = {
        "clinic_id": clinic_id,
        "code": "MON_AM",
        "day_pattern": "MWF",
        "start_minute": DEFAULTS["SHIFT_START"],
        "end_minute": DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(clinic_id: str, **overrides) -> dict:
    """Required: clinic_id, asset_tag, model. Optional: supports_hdf."""
    defaults = {
        "clinic_id": clinic_id,
        "asset_tag": "M1",
        "model": DEFAULTS["MACHINE_MODEL"],
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(clinic_id: str, machine_id: str, **overrides) -> dict:
    """Required: clinic_id, chair_label, machine_id. Optional: isolation_capable."""
    defaults = {
        "clinic_id": clinic_id,
        "chair_label": "C1",
        "machine_id": machine_id,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(clinic_id: str, **overrides) -> dict:
    """Required: clinic_id, mrn, full_name.
    Optional: patient_kind, payer_class, requires_isolation, coinsurance_pct."""
    defaults = {
        "clinic_id": clinic_id,
        "mrn": "P1",
        "full_name": "Test Patient",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(patient_id: str, **overrides) -> dict:
    """Required: patient_id, modality, effective_from_date.
    Optional: sessions_per_week, epo_units, iron_ordered."""
    defaults = {
        "patient_id": patient_id,
        "modality": "HEMODIALYSIS",
        "effective_from_date": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_standing_slot_payload(patient_id: str, shift_id: str, station_id: str,
                                  expected_patient_version: int, **overrides) -> dict:
    """Required: patient_id, shift_id, station_id, expected_patient_version."""
    defaults = {
        "patient_id": patient_id,
        "shift_id": shift_id,
        "station_id": station_id,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(patient_id: str, order_id: str, station_id: str, shift_id: str,
                           service_date: str, expected_patient_version: int, **overrides) -> dict:
    """Required: patient_id, order_id, station_id, shift_id, service_date,
    expected_patient_version. Optional: standing_slot_id, rescheduled_from_id."""
    defaults = {
        "patient_id": patient_id,
        "order_id": order_id,
        "station_id": station_id,
        "shift_id": shift_id,
        "service_date": service_date,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_transport_trip_payload(session_id: str, **overrides) -> dict:
    """Required: session_id, direction, miles.
    Optional: cross_county, wheelchair, shared_ride."""
    defaults = {
        "session_id": session_id,
        "direction": "INBOUND",
        "miles": 5,
    }
    defaults.update(overrides)
    return defaults


def create_lab_order_payload(patient_id: str, **overrides) -> dict:
    """Required: patient_id, panel, scheduled_date."""
    defaults = {
        "patient_id": patient_id,
        "panel": "MONTHLY_CHEM",
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(patient_id: str, **overrides) -> dict:
    """Required: patient_id, period_month."""
    defaults = {
        "patient_id": patient_id,
        "period_month": DEFAULTS["PERIOD_MONTH"],
    }
    defaults.update(overrides)
    return defaults
