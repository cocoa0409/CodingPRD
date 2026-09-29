"""Payload factories - one per entity, request-supplied input fields only."""

import itertools

_seq = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic per-process suffix for values the PRD requires to be unique."""
    return f"{next(_seq):05d}"


def create_unit_payload(**overrides) -> dict:
    payload = {
        "unit_name": f"Test Birth Unit {unique_suffix()}",
        "licensed_ldr_beds": 4,
        "licensed_or_rooms": 1,
        "max_daily_induction_bed_minutes": 2880,
    }
    payload.update(overrides)
    return payload


def patch_unit_payload(**overrides) -> dict:
    payload = {"max_daily_induction_bed_minutes": 1440}
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": f"Test Clinician {unique_suffix()}",
        "staff_role": "RN_LABOR_DELIVERY",
        "fetal_monitoring_cert_level": "ADVANCED",
        "credential_expires_at": "2027-12-31T00:00:00Z",
        "or_circulating_qualified": False,
    }
    payload.update(overrides)
    return payload


def create_bed_payload(**overrides) -> dict:
    payload = {"bed_label": f"LDR-{unique_suffix()}", "bed_type": "LDR"}
    payload.update(overrides)
    return payload


def create_shift_payload(unit_id, staff_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "staff_id": staff_id,
        "role_slot": "BEDSIDE",
        "shift_start_utc": "2026-08-20T06:00:00Z",
        "shift_end_utc": "2026-08-20T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_encounter_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "patient_record_code": f"PRC-{unique_suffix()}",
        "parity": 1,
        "gestational_age_weeks": 39,
        "prior_cesarean": False,
        "fetus_count": 1,
        "presentation": "VERTEX",
    }
    payload.update(overrides)
    return payload


def create_care_assignment_payload(encounter_id, shift_assignment_id,
                                   expected_encounter_version, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "shift_assignment_id": shift_assignment_id,
        "coverage_mode": "RATIO_SHARED",
        "expected_encounter_version": expected_encounter_version,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "patient_record_code": f"PRC-IND-{unique_suffix()}",
        "gestational_age_weeks": 39,
        "indication_code": "GDM_CONTROLLED",
        "requested_start_utc": "2026-08-27T08:00:00Z",
        "expected_labor_minutes": 600,
    }
    payload.update(overrides)
    return payload


def create_hemorrhage_activation_payload(encounter_id, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "bundle_type": "OBSTETRIC_HEMORRHAGE",
        "activation_trigger": "QBL_THRESHOLD",
        "quantitative_blood_loss_ml": 1200,
    }
    payload.update(overrides)
    return payload


def create_hypertension_activation_payload(encounter_id, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "bundle_type": "SEVERE_HYPERTENSION",
        "activation_trigger": "BP_THRESHOLD",
        "systolic_mmhg": 168,
        "diastolic_mmhg": 114,
    }
    payload.update(overrides)
    return payload


def complete_checklist_item_payload(completed_at, performed_by_staff_id, **overrides) -> dict:
    payload = {
        "completed_at": completed_at,
        "performed_by_staff_id": performed_by_staff_id,
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(encounter_id, interpreted_by_staff_id, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "interpreted_by_staff_id": interpreted_by_staff_id,
        "category": "CATEGORY_II",
        "baseline_rate_bpm": 140,
        "variability": "MINIMAL",
        "recurrent_decelerations": True,
    }
    payload.update(overrides)
    return payload


def create_cesarean_payload(encounter_id, **overrides) -> dict:
    payload = {"encounter_id": encounter_id, "urgency_class": "CATEGORY_2_URGENT"}
    payload.update(overrides)
    return payload


def create_drill_payload(participant_staff_ids, scheduled_for_utc, **overrides) -> dict:
    payload = {
        "drill_type": "DECISION_TO_INCISION",
        "scheduled_for_utc": scheduled_for_utc,
        "participant_staff_ids": list(participant_staff_ids),
    }
    payload.update(overrides)
    return payload


def create_review_payload(encounter_id, facilitator_staff_id, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "complication_code": "APGAR5_UNDER_7",
        "facilitator_staff_id": facilitator_staff_id,
    }
    payload.update(overrides)
    return payload


def submit_findings_payload(**overrides) -> dict:
    payload = {
        "findings_summary": (
            "The debrief reviewed the monitoring record, the staffing ratio at the "
            "time of the event and the interval between decision and delivery."
        ),
        "contributing_factor_codes": ["STAFFING_RATIO"],
    }
    payload.update(overrides)
    return payload


def create_pass_payload(encounter_id, **overrides) -> dict:
    payload = {
        "encounter_id": encounter_id,
        "person_name": f"Support Person {unique_suffix()}",
        "credential_type": "PARTNER",
        "or_credentialed": False,
    }
    payload.update(overrides)
    return payload


def create_snapshot_payload(period_start_utc, period_end_utc, **overrides) -> dict:
    payload = {
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
    }
    payload.update(overrides)
    return payload
