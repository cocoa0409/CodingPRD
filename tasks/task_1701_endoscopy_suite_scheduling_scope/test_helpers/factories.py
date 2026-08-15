"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PATIENT_MRN": "MRN-0001",
    "PATIENT_NAME": "Pat Test",
    "PATIENT_DOB": "1990-05-05",
    "PROVIDER_NAME": "Dr Test",
    "PROVIDER_SPECIALTY": "GASTROENTEROLOGY",
    "TYPE_CODE": "COLONO",
    "TYPE_NAME": "Colonoscopy",
    "TYPE_BASE_MINUTES": 40,
    "TYPE_PREP": "SPLIT_DOSE",
    "TYPE_SCOPE": "COLONOSCOPE",
    "ROOM_NAME": "R-STD",
    "ROOM_CLASS": "STANDARD",
    "AP_NAME": "Ann Esthesia",
    "SCOPE_SERIAL": "SC-0001",
    "SCOPE_TYPE": "COLONOSCOPE",
    "START": "2026-08-03T09:00:00Z",
    "INDICATION": "SCREENING",
    "ANESTHESIA": "NONE",
}


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": DEFAULTS["PATIENT_MRN"],
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["PATIENT_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "specialty": DEFAULTS["PROVIDER_SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_procedure_type_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["TYPE_CODE"],
        "display_name": DEFAULTS["TYPE_NAME"],
        "base_duration_minutes": DEFAULTS["TYPE_BASE_MINUTES"],
        "prep_protocol": DEFAULTS["TYPE_PREP"],
        "colonoscopy_family": True,
        "adr_relevant": True,
        "required_scope_type": DEFAULTS["TYPE_SCOPE"],
    }
    defaults.update(overrides)
    return defaults


def create_egd_type_payload(**overrides) -> dict:
    """Upper-endoscopy type: CLEAR_LIQUIDS prep, gastroscope, not in metric families."""
    defaults = {
        "code": "EGD",
        "display_name": "Upper endoscopy",
        "base_duration_minutes": 25,
        "prep_protocol": "CLEAR_LIQUIDS",
        "colonoscopy_family": False,
        "adr_relevant": False,
        "required_scope_type": "GASTROSCOPE",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROOM_NAME"],
        "room_class": DEFAULTS["ROOM_CLASS"],
        "supports_anesthesia": True,
    }
    defaults.update(overrides)
    return defaults


def create_anesthesia_provider_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["AP_NAME"]}
    defaults.update(overrides)
    return defaults


def create_scope_payload(**overrides) -> dict:
    defaults = {
        "serial_number": DEFAULTS["SCOPE_SERIAL"],
        "scope_type": DEFAULTS["SCOPE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(patient_id, provider_id, procedure_type_id, room_id,
                           **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "procedure_type_id": procedure_type_id,
        "room_id": room_id,
        "scheduled_start": DEFAULTS["START"],
        "indication": DEFAULTS["INDICATION"],
        "anesthesia_type": DEFAULTS["ANESTHESIA"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(booking_id, anesthesia_provider_id, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "anesthesia_provider_id": anesthesia_provider_id,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(scope_id, **overrides) -> dict:
    defaults = {"scope_id": scope_id}
    defaults.update(overrides)
    return defaults


def advance_step_payload(to_step, **overrides) -> dict:
    defaults = {"to_step": to_step}
    defaults.update(overrides)
    return defaults


def create_culture_payload(scope_id, reprocessing_cycle_id, **overrides) -> dict:
    defaults = {
        "scope_id": scope_id,
        "reprocessing_cycle_id": reprocessing_cycle_id,
    }
    defaults.update(overrides)
    return defaults


def culture_result_payload(result, **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_specimen_payload(booking_id, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "specimen_type": "POLYP",
        "container_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_quality_report_payload(provider_id, period_start, period_end,
                                  metric_variant="STRICT", **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "period_start": period_start,
        "period_end": period_end,
        "metric_variant": metric_variant,
    }
    defaults.update(overrides)
    return defaults


def prep_assessment_payload(left=2, right=2, transverse=2) -> dict:
    return {"bbps_left": left, "bbps_right": right, "bbps_transverse": transverse}


def completion_payload(cecum_intubated=True, withdrawal_time_seconds=400,
                       adenomas_detected=0) -> dict:
    return {
        "cecum_intubated": cecum_intubated,
        "withdrawal_time_seconds": withdrawal_time_seconds,
        "adenomas_detected": adenomas_detected,
    }
