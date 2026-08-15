"""Payload factories — one per entity, input fields only (PRD §3).

Identifiers that must be unique (nhsn_org_id, mrn, employee_code,
nhsn_location_code) are suffixed with a per-process counter so that multiple
creations inside one test never collide.
"""
import itertools

from .constants import (
    DEFAULT_CAUTI_BASELINE_PER_1000,
    DEFAULT_CLABSI_BASELINE_PER_1000,
    DEFAULT_SSI_BASELINE_PER_PROCEDURE,
)

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_facility_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Facility-{n}",
        "nhsn_org_id": f"ORG-{n}",
        "clabsi_baseline_per_1000": DEFAULT_CLABSI_BASELINE_PER_1000,
        "cauti_baseline_per_1000": DEFAULT_CAUTI_BASELINE_PER_1000,
        "ssi_baseline_per_procedure": DEFAULT_SSI_BASELINE_PER_PROCEDURE,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(facility_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "facility_id": facility_id,
        "name": f"Unit-{n}",
        "unit_type": "ICU",
        "nhsn_location_code": f"LOC-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(unit_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "mrn": f"MRN-{n}",
        "admitted_at": "2026-08-01T08:00:00Z",
        "unit_id": unit_id,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(home_unit_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "employee_code": f"EMP-{n}",
        "role_title": "Registered Nurse",
        "home_unit_id": home_unit_id,
    }
    defaults.update(overrides)
    return defaults


def create_device_episode_payload(patient_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "device_type": "CENTRAL_LINE",
        "placed_at": "2026-08-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_surgical_procedure_payload(patient_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "patient_id": patient_id,
        "procedure_code": f"PROC-{n}",
        "performed_at": "2026-08-02T09:00:00Z",
        "duration_minutes": 60,
        "asa_score": 2,
        "wound_class": "CLEAN",
    }
    defaults.update(overrides)
    return defaults


def create_infection_case_payload(patient_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "patient_id": patient_id,
        "case_type": "CLABSI",
        "suspected_organism": f"Organism-{n}",
        "first_positive_specimen_at": "2026-08-04T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def adjudicate_hai_payload(date_of_event: str, **overrides) -> dict:
    defaults = {
        "outcome": "ADJUDICATED_HAI",
        "date_of_event": date_of_event,
        "rationale": "meets the surveillance definition",
    }
    defaults.update(overrides)
    return defaults


def adjudicate_ruled_out_payload(**overrides) -> dict:
    defaults = {
        "outcome": "RULED_OUT",
        "rationale": "does not meet the definition",
    }
    defaults.update(overrides)
    return defaults


def reopen_payload(**overrides) -> dict:
    defaults = {"reason": "new laboratory evidence arrived"}
    defaults.update(overrides)
    return defaults


def create_device_day_count_payload(unit_id: str, count_date: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "count_date": count_date,
        "central_line_days": 20,
        "urinary_catheter_days": 10,
        "ventilator_days": 5,
        "patient_days": 40,
    }
    defaults.update(overrides)
    return defaults


def correct_device_day_count_payload(expected_version: int, **overrides) -> dict:
    defaults = {
        "central_line_days": 20,
        "urinary_catheter_days": 10,
        "ventilator_days": 5,
        "patient_days": 40,
        "expected_device_day_count_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def create_monthly_summary_payload(unit_id: str, month: str = "2026-08", **overrides) -> dict:
    defaults = {"unit_id": unit_id, "month": month}
    defaults.update(overrides)
    return defaults


def create_outbreak_investigation_payload(unit_id: str, organism: str, **overrides) -> dict:
    defaults = {"unit_id": unit_id, "organism": organism}
    defaults.update(overrides)
    return defaults


def create_isolation_order_payload(patient_id: str, **overrides) -> dict:
    defaults = {"patient_id": patient_id, "precaution_type": "CONTACT"}
    defaults.update(overrides)
    return defaults


def create_audit_payload(isolation_order_id: str, **overrides) -> dict:
    defaults = {
        "isolation_order_id": isolation_order_id,
        "observed_at": "2026-08-02T09:00:00Z",
        "elements_checked": 10,
        "elements_passed": 10,
    }
    defaults.update(overrides)
    return defaults


def create_observation_payload(unit_id: str, observed_at: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "observed_at": observed_at,
        "opportunity_type": "BEFORE_PATIENT_CONTACT",
        "action": "COMPLIANT",
    }
    defaults.update(overrides)
    return defaults


def create_exposure_payload(employee_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "exposure_type": "PERCUTANEOUS",
        "occurred_at": "2026-08-01T10:00:00Z",
        "source_hbv_status": "UNKNOWN",
        "source_hcv_status": "UNKNOWN",
        "source_hiv_status": "UNKNOWN",
    }
    defaults.update(overrides)
    return defaults


def record_draw_payload(stage: str, drawn_at: str, result: str = "NEGATIVE", **overrides) -> dict:
    defaults = {"stage": stage, "drawn_at": drawn_at, "result": result}
    defaults.update(overrides)
    return defaults


def record_serologies_payload(
    hbv: str = "NEGATIVE", hcv: str = "NEGATIVE", hiv: str = "NEGATIVE", **overrides
) -> dict:
    defaults = {
        "source_hbv_status": hbv,
        "source_hcv_status": hcv,
        "source_hiv_status": hiv,
    }
    defaults.update(overrides)
    return defaults


def create_cap_payload(unit_id: str, source_type: str, source_ref_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "source_type": source_type,
        "source_ref_id": source_ref_id,
        "description": "corrective plan narrative",
        "due_date": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def submit_for_verification_payload(**overrides) -> dict:
    defaults = {"evidence_notes": "documented completion evidence"}
    defaults.update(overrides)
    return defaults
