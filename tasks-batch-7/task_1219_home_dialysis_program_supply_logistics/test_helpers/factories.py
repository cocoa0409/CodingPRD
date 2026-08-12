"""Payload factories — one per entity, input fields only (PRD section 4)."""
import itertools

from .constants import TEST_DEFAULTS, DEFAULT_CATALOG

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# -------------------------------------------------------------- program
def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": f"{TEST_DEFAULTS['PROGRAM_NAME']} {_seq()}",
        "review_cadence_treatments": TEST_DEFAULTS["REVIEW_CADENCE_TREATMENTS"],
        "max_missed_log_streak": TEST_DEFAULTS["MAX_MISSED_LOG_STREAK"],
        "waste_ratio_alert_threshold": TEST_DEFAULTS["WASTE_RATIO_ALERT_THRESHOLD"],
        "supply_catalog": list(DEFAULT_CATALOG),
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- patient
def create_patient_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "full_name": f"{TEST_DEFAULTS['PATIENT_FULL_NAME']} {_seq()}",
        "prescription_treatments_per_week":
            TEST_DEFAULTS["PRESCRIPTION_TREATMENTS_PER_WEEK"],
        "prescription_units_per_treatment":
            TEST_DEFAULTS["PRESCRIPTION_UNITS_PER_TREATMENT"],
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- training
def create_training_attempt_payload(patient_id, module_code, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "module_code": module_code,
        "score_pct": 90,
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- assessment
def create_home_assessment_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "assessment_kind": "INITIAL",
        "water_chloramine_ppm": TEST_DEFAULTS["CHLORAMINE_OK_PPM"],
        "electrical_dedicated_circuit": True,
        "electrical_voltage_verified": True,
        "storage_area_sqft": TEST_DEFAULTS["STORAGE_AREA_SQFT"],
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- work order
def create_work_order_payload(patient_id, assessment_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "assessment_id": assessment_id,
        "work_type": "PLUMBING",
        "cost_estimate_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- machine
def create_machine_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "serial_number": f"SN-{_seq()}",
        "model": TEST_DEFAULTS["MACHINE_MODEL"],
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- maintenance
def create_maintenance_event_payload(machine_id, **overrides) -> dict:
    defaults = {
        "machine_id": machine_id,
        "event_type": "PREVENTIVE",
        "window_start": "2026-05-10T09:00:00Z",
        "window_end": "2026-05-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- backup plan
def create_backup_plan_payload(patient_id, expected_patient_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "plan_mode": "IN_CENTER_CHAIR",
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- supply order
def create_supply_order_payload(patient_id, order_month, lines,
                                expected_patient_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "order_month": order_month,
        "lines": lines,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def order_line(sku, quantity) -> dict:
    return {"sku": sku, "quantity": quantity}


# -------------------------------------------------------------- appointment
def create_delivery_appointment_payload(supply_order_id, **overrides) -> dict:
    defaults = {
        "supply_order_id": supply_order_id,
        "window_start": "2026-05-04T08:00:00Z",
        "window_end": "2026-05-04T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- treatment log
def create_treatment_log_payload(patient_id, machine_id, treatment_date,
                                 **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "machine_id": machine_id,
        "treatment_date": treatment_date,
        "duration_minutes": 240,
        "consumption": [],
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- chair
def create_chair_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "chair_code": f"CH-{_seq()}",
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- slot
def create_slot_reservation_payload(patient_id, chair_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "chair_id": chair_id,
        "slot_start": "2026-05-10T10:00:00Z",
        "slot_end": "2026-05-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# -------------------------------------------------------------- waste/return
def create_waste_return_payload(patient_id, record_type, activity_month, lines,
                                **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "record_type": record_type,
        "activity_month": activity_month,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def waste_line(sku, units, expired=False) -> dict:
    return {"sku": sku, "units": units, "expired": expired}


# -------------------------------------------------------------- transition
def create_transition_payload(patient_id, direction, reason_code, effective_from,
                              **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "direction": direction,
        "reason_code": reason_code,
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return defaults
