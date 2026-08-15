"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FACILITY_NAME": "Sending General",
    "TRAUMA_LEVEL": "LEVEL_3",
    "CAPABILITIES": ["TRAUMA"],
    "BED_CODE": "ICU-01",
    "UNIT_TYPE": "ICU",
    "PHYSICIAN_NAME": "Dr Send",
    "SPECIALTY": "EMERGENCY",
    "PATIENT_REF": "PT-1",
    "ACUITY": "EMERGENT",
    "REQUIRED_CAPABILITY": "CARDIAC_CATH",
    "CONTACT_METHOD": "PHONE",
    "PAYER_ID": "PAYER-9",
    "CHANNEL": "PORTAL",
    "MODE": "GROUND_ALS",
    "CREW": "ALS",
    "DISTANCE": 20.0,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "facility_code": "SND",
        "trauma_level": DEFAULTS["TRAUMA_LEVEL"],
        "capabilities": list(DEFAULTS["CAPABILITIES"]),
    }
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides) -> dict:
    defaults = {
        "bed_code": DEFAULTS["BED_CODE"],
        "unit_type": DEFAULTS["UNIT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(facility_id, **overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PHYSICIAN_NAME"],
        "facility_id": facility_id,
        "specialty": DEFAULTS["SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_case_payload(sending_facility_id, sending_physician_id,
                                 **overrides) -> dict:
    defaults = {
        "patient_ref": DEFAULTS["PATIENT_REF"],
        "sending_facility_id": sending_facility_id,
        "sending_physician_id": sending_physician_id,
        "acuity_level": DEFAULTS["ACUITY"],
        "required_unit_type": DEFAULTS["UNIT_TYPE"],
        "required_capability": DEFAULTS["REQUIRED_CAPABILITY"],
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(has_emergency_medical_condition, is_stabilized,
                             **overrides) -> dict:
    payload = {
        "has_emergency_medical_condition": has_emergency_medical_condition,
        "is_stabilized": is_stabilized,
    }
    payload.update(overrides)
    return payload


def create_request_acceptance_payload(receiving_facility_id, receiving_physician_id,
                                      **overrides) -> dict:
    payload = {
        "receiving_facility_id": receiving_facility_id,
        "receiving_physician_id": receiving_physician_id,
        "contact_method": DEFAULTS["CONTACT_METHOD"],
    }
    payload.update(overrides)
    return payload


def create_refusal_payload(refusal_category, narrative, **overrides) -> dict:
    payload = {
        "refusal_category": refusal_category,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def create_bed_hold_payload(bed_id, expected_transfer_case_version) -> dict:
    return {
        "bed_id": bed_id,
        "expected_transfer_case_version": expected_transfer_case_version,
    }


def create_dispatch_payload(mode=DEFAULTS["MODE"],
                            crew_capability=DEFAULTS["CREW"],
                            distance_miles=DEFAULTS["DISTANCE"], **overrides) -> dict:
    payload = {
        "mode": mode,
        "crew_capability": crew_capability,
        "distance_miles": distance_miles,
    }
    payload.update(overrides)
    return payload


def create_arrival_payload(arrival_condition="STABLE", deterioration_en_route=False,
                           receiving_physician_confirmed=True, **overrides) -> dict:
    payload = {
        "arrival_condition": arrival_condition,
        "deterioration_en_route": deterioration_en_route,
        "receiving_physician_confirmed": receiving_physician_confirmed,
    }
    payload.update(overrides)
    return payload


def create_insurance_notification_payload(**overrides) -> dict:
    defaults = {
        "payer_id": DEFAULTS["PAYER_ID"],
        "channel": DEFAULTS["CHANNEL"],
    }
    defaults.update(overrides)
    return defaults


def create_clinical_packet_payload(required_documents=("H_AND_P",),
                                   imaging_studies=None, **overrides) -> dict:
    payload = {"required_documents": list(required_documents)}
    if imaging_studies is not None:
        payload["imaging_studies"] = imaging_studies
    payload.update(overrides)
    return payload


def create_diversion_event_payload(scope, starts_at, ends_at, reason,
                                   **overrides) -> dict:
    payload = {
        "scope": scope,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_review_close_payload(outcome, findings, **overrides) -> dict:
    payload = {"outcome": outcome, "findings": findings}
    payload.update(overrides)
    return payload
