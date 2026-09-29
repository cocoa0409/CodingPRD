"""Request payload builders.

Each builder returns a valid payload for one write endpoint and accepts
``**overrides`` so a test can vary exactly the field it is exercising. Passing
``None`` as an override value removes the key entirely, which is how
missing-field rejections are expressed.
"""

from . import constants as C


def _apply(payload, overrides):
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def course_payload(**overrides):
    return _apply(
        {
            "course_name": C.COURSE_NAME_PRIMARY,
            "ems_response_minutes": C.COURSE_EMS_MINUTES,
            "ems_access_note": C.COURSE_NOTE_PRIMARY,
        },
        overrides,
    )


def element_payload(course_id, element_type="GROUND_INITIATIVE", **overrides):
    if element_type == "HIGH_ELEMENT":
        name = C.ELEMENT_NAME_HIGH
        min_kg, max_kg = C.HIGH_WEIGHT_MIN_KG, C.HIGH_WEIGHT_MAX_KG
    elif element_type == "LOW_ELEMENT":
        name = C.ELEMENT_NAME_LOW
        min_kg, max_kg = C.LOW_WEIGHT_MIN_KG, C.LOW_WEIGHT_MAX_KG
    elif element_type == "ZIP_LINE":
        name = C.ELEMENT_NAME_ZIP
        min_kg, max_kg = C.HIGH_WEIGHT_MIN_KG, C.HIGH_WEIGHT_MAX_KG
    else:
        name = C.ELEMENT_NAME_GROUND
        min_kg, max_kg = C.LOW_WEIGHT_MIN_KG, C.LOW_WEIGHT_MAX_KG
    return _apply(
        {
            "course_id": course_id,
            "element_name": name,
            "element_type": element_type,
            "installed_on": C.ELEMENT_INSTALLED_ON,
            "next_professional_inspection_due_on": C.ELEMENT_INSPECTION_DUE_ON,
            "min_participant_weight_kg": min_kg,
            "max_participant_weight_kg": max_kg,
        },
        overrides,
    )


def facilitator_payload(course_id, staff_type="STAFF_FACILITATOR", **overrides):
    if staff_type == "SAFETY_OFFICER":
        name, level, employee = C.SAFETY_OFFICER_NAME, "LEVEL_3", True
    elif staff_type == "CONTRACT_INSPECTOR":
        name, level, employee = C.INSPECTOR_NAME, "LEVEL_3", False
    else:
        name, level, employee = C.FACILITATOR_NAME, "LEVEL_2", True
    return _apply(
        {
            "course_id": course_id,
            "full_name": name,
            "staff_type": staff_type,
            "certification_level": level,
            "cert_expires_on": C.CERT_EXPIRES_ON,
            "is_operator_employee": employee,
        },
        overrides,
    )


def training_record_payload(facilitator_id, kind="RESCUE_DRILL", **overrides):
    payload = {
        "facilitator_id": facilitator_id,
        "kind": kind,
        "completed_on": C.TRAINING_COMPLETED_ON,
    }
    if kind in ("REFRESHER", "RECERTIFICATION"):
        payload["hours"] = C.REFRESHER_HOURS_REQUIRED
    return _apply(payload, overrides)


def group_client_payload(**overrides):
    return _apply(
        {
            "client_name": C.CLIENT_NAME,
            "org_type": C.CLIENT_ORG_TYPE,
            "tier": C.CLIENT_TIER,
        },
        overrides,
    )


def payment_payload(**overrides):
    return _apply(
        {
            "amount_cents": C.CLIENT_PAYMENT_CENTS,
            "reference": C.CLIENT_PAYMENT_REFERENCE,
        },
        overrides,
    )


def booking_payload(course_id, group_client_id, expected_participant_count=1, **overrides):
    return _apply(
        {
            "course_id": course_id,
            "group_client_id": group_client_id,
            "program_date": C.PROGRAM_DATE,
            "expected_participant_count": expected_participant_count,
        },
        overrides,
    )


def participant_payload(booking_id, expected_booking_version, kind="ADULT", **overrides):
    if kind == "MINOR":
        name, birth, weight, chaperone = (
            C.MINOR_NAME,
            C.MINOR_BIRTH_DATE,
            C.MINOR_WEIGHT_KG,
            False,
        )
    elif kind == "CHAPERONE":
        name, birth, weight, chaperone = (
            C.CHAPERONE_NAME,
            C.CHAPERONE_BIRTH_DATE,
            C.CHAPERONE_WEIGHT_KG,
            True,
        )
    else:
        name, birth, weight, chaperone = (
            C.ADULT_NAME,
            C.ADULT_BIRTH_DATE,
            C.ADULT_WEIGHT_KG,
            False,
        )
    return _apply(
        {
            "booking_id": booking_id,
            "expected_booking_version": expected_booking_version,
            "full_name": name,
            "birth_date": birth,
            "weight_kg": weight,
            "is_chaperone": chaperone,
        },
        overrides,
    )


def screening_packet_payload(**overrides):
    return _apply(
        {
            "agreement_signed": True,
            "guardian_signature_provided": False,
            "health_flags": ["NONE"],
        },
        overrides,
    )


def program_block_payload(booking_id, sequence_index, phase, start_at, end_at, **overrides):
    return _apply(
        {
            "booking_id": booking_id,
            "sequence_index": sequence_index,
            "phase": phase,
            "planned_start_at": start_at,
            "planned_end_at": end_at,
        },
        overrides,
    )


def belay_equipment_payload(course_id, equipment_kind="HARNESS", **overrides):
    serials = {"ROPE": "RP-001", "HARNESS": "HN-001", "CARABINER": "CB-001", "LANYARD": "LY-001"}
    max_cycles = {"ROPE": 40000, "HARNESS": 30000, "CARABINER": 60000, "LANYARD": 20000}
    return _apply(
        {
            "course_id": course_id,
            "equipment_kind": equipment_kind,
            "serial_number": serials[equipment_kind],
            "manufactured_on": "2022-06-01",
            "max_cycles": max_cycles[equipment_kind],
        },
        overrides,
    )


def weather_observation_payload(course_id, **overrides):
    return _apply(
        {
            "course_id": course_id,
            "observed_at": C.CLOCK_TEST_UTC,
            "lightning_distance_km": 25.0,
            "wind_speed_kph": 12.0,
            "air_temp_c": 19.0,
        },
        overrides,
    )


def operational_log_payload(element_id, facilitator_id, result="CLEAR", **overrides):
    payload = {
        "element_id": element_id,
        "facilitator_id": facilitator_id,
        "log_date": C.CLOCK_TEST_DATE,
        "result": result,
    }
    if result != "CLEAR":
        payload["defect_note"] = "Broken cable strand at the north anchor"
    return _apply(payload, overrides)


def professional_inspection_payload(element_id, inspector_id, **overrides):
    return _apply(
        {
            "element_id": element_id,
            "inspector_id": inspector_id,
            "performed_on": C.CLOCK_TEST_DATE,
        },
        overrides,
    )


def incident_payload(course_id, reported_by_facilitator_id, severity="SERIOUS", **overrides):
    return _apply(
        {
            "course_id": course_id,
            "reported_by_facilitator_id": reported_by_facilitator_id,
            "occurred_at": C.CLOCK_TEST_UTC,
            "severity": severity,
            "narrative": "Participant fell from the second staple and was immobilised",
            "ems_activated": severity == "SERIOUS",
        },
        overrides,
    )
