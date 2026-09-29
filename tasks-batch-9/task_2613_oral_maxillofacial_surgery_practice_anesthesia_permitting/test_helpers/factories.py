"""Payload factories — one per resource, input fields only."""

DEFAULTS = {
    "PRACTICE_NAME": "Northside OMS",
    "STATE_CODE": "OH",
    "RECOVERY_BAY_COUNT": 2,
    "SURGEON_NAME": "Dr Alma Reyes",
    "MONITOR_NAME": "Nia Monitor",
    "PATIENT_NAME": "Pat Molar",
    "DATE_OF_BIRTH": "1980-03-15T00:00:00Z",
    "ACLS_EXPIRES_ON": "2027-06-30T00:00:00Z",
    "ROOM_CODE": "OR-1",
    "MANUFACTURER_CODE": "NBL",
    "CATALOG_REFERENCE": "NBL-4010",
    "NARRATIVE": "Desaturation during third molar extraction.",
}


def create_practice_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PRACTICE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "recovery_bay_count": DEFAULTS["RECOVERY_BAY_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_permit_payload(practice_id, permit_level="MODERATE_SEDATION",
                          applied_on="2026-08-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "permit_level": permit_level,
        "applied_on": applied_on,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(permit_id, scheduled_for, **overrides) -> dict:
    payload = {"permit_id": permit_id, "scheduled_for": scheduled_for}
    payload.update(overrides)
    return payload


def inspection_result_payload(minor_deficiency_count=0, major_deficiency_count=0,
                              critical_deficiency_count=0, **overrides) -> dict:
    payload = {
        "minor_deficiency_count": minor_deficiency_count,
        "major_deficiency_count": major_deficiency_count,
        "critical_deficiency_count": critical_deficiency_count,
    }
    payload.update(overrides)
    return payload


def create_drill_payload(practice_id, drill_type, conducted_at,
                         participant_staff_ids, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "drill_type": drill_type,
        "conducted_at": conducted_at,
        "participant_staff_ids": list(participant_staff_ids),
    }
    payload.update(overrides)
    return payload


def create_staff_payload(practice_id, full_name=None, role_type="SURGEON",
                         **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "full_name": full_name or DEFAULTS["SURGEON_NAME"],
        "role_type": role_type,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "asa_class": 2,
        "airway_class": 2,
        "weight_kg": 80,
    }
    payload.update(overrides)
    return payload


def create_block_payload(practice_id, surgeon_id, block_start, block_end,
                         **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "surgeon_id": surgeon_id,
        "room_code": DEFAULTS["ROOM_CODE"],
        "block_start": block_start,
        "block_end": block_end,
    }
    payload.update(overrides)
    return payload


def create_case_payload(practice_id, patient_id, primary_surgeon_id,
                        planned_start, planned_end,
                        planned_anesthesia_level="LOCAL_ONLY",
                        procedure_category="THIRD_MOLAR",
                        total_charge_cents=100_000, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "patient_id": patient_id,
        "primary_surgeon_id": primary_surgeon_id,
        "planned_anesthesia_level": planned_anesthesia_level,
        "procedure_category": procedure_category,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "total_charge_cents": total_charge_cents,
    }
    payload.update(overrides)
    return payload


def create_evaluation_payload(evaluator_staff_id, expected_case_version,
                              asa_class_recorded=2, airway_class_recorded=2,
                              **overrides) -> dict:
    payload = {
        "evaluator_staff_id": evaluator_staff_id,
        "expected_case_version": expected_case_version,
        "asa_class_recorded": asa_class_recorded,
        "airway_class_recorded": airway_class_recorded,
    }
    payload.update(overrides)
    return payload


def day_of_verification_payload(intent, fasting_solids_last_at, fasting_clears_last_at,
                                escort_confirmed=True, escort_name="Ada Escort",
                                **overrides) -> dict:
    payload = {
        "intent": intent,
        "fasting_solids_last_at": fasting_solids_last_at,
        "fasting_clears_last_at": fasting_clears_last_at,
        "escort_confirmed": escort_confirmed,
    }
    if escort_confirmed:
        payload["escort_name"] = escort_name
    payload.update(overrides)
    return payload


def service_line(code, charge_cents, benefit_class) -> dict:
    return {"code": code, "charge_cents": charge_cents, "benefit_class": benefit_class}


def create_determination_payload(case_id, service_lines, **overrides) -> dict:
    payload = {"case_id": case_id, "service_lines": list(service_lines)}
    payload.update(overrides)
    return payload


def create_lot_payload(practice_id, diameter_mm=4.0, length_mm=10.0,
                       unit_cost_cents=20_000, quantity_on_hand=5,
                       expiry_date="2027-12-31T00:00:00Z", **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "manufacturer_code": DEFAULTS["MANUFACTURER_CODE"],
        "catalog_reference": DEFAULTS["CATALOG_REFERENCE"],
        "diameter_mm": diameter_mm,
        "length_mm": length_mm,
        "unit_cost_cents": unit_cost_cents,
        "quantity_on_hand": quantity_on_hand,
        "expiry_date": expiry_date,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(case_id, lot_id, quantity, expected_lot_version,
                               **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "lot_id": lot_id,
        "quantity": quantity,
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def auto_size_payload(requested_diameter_mm, requested_length_mm, quantity,
                      **overrides) -> dict:
    payload = {
        "requested_diameter_mm": requested_diameter_mm,
        "requested_length_mm": requested_length_mm,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_adverse_event_payload(case_id, event_type="HYPOXEMIA", severity="MINOR",
                                 occurred_at="2026-08-01T00:00:00Z",
                                 narrative=None, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "event_type": event_type,
        "severity": severity,
        "occurred_at": occurred_at,
        "narrative": narrative or DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def create_imaging_study_payload(patient_id, modality="PANORAMIC",
                                 justification_code="THIRD_MOLAR_ASSESSMENT",
                                 acquired_at="2026-08-01T00:00:00Z",
                                 dose_mgy_cm2=50.0, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "modality": modality,
        "justification_code": justification_code,
        "acquired_at": acquired_at,
        "dose_mgy_cm2": dose_mgy_cm2,
    }
    payload.update(overrides)
    return payload
