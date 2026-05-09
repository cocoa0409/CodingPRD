"""Payload factories — one per entity / endpoint, input fields only."""
from .constants import THRESHOLDS, TEST_DEFAULTS


_room_counter = [0]


def _next_room_number(prefix="OR"):
    _room_counter[0] += 1
    return f"{prefix}-{_room_counter[0]:04d}"


def create_operating_room_payload(**overrides) -> dict:
    """Defaults to a GENERAL_OR room with hourly_rate=500 and 30-min turnover."""
    defaults = {
        "room_number": _next_room_number(),
        "room_type": "GENERAL_OR",
        "equipment_list": ["DEFAULT_EQUIPMENT"],
        "specialty_required": "GENERAL",
        "turnover_buffer_minutes": THRESHOLDS["DEFAULT_TURNOVER_BUFFER_MINUTES"],
        "hourly_rate": TEST_DEFAULTS["ROOM_HOURLY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    """Defaults to an anesthesiologist with [GENERAL] qualification, shift 0..1440."""
    defaults = {
        "staff_name": "Dr. Test",
        "staff_role": "ANESTHESIOLOGIST",
        "qualifications": ["GENERAL"],
        "hourly_rate": TEST_DEFAULTS["ANESTHESIOLOGIST_HOURLY_RATE"],
        "shift_start_minute": TEST_DEFAULTS["DEFAULT_SHIFT_START"],
        "shift_end_minute": TEST_DEFAULTS["DEFAULT_SHIFT_END"],
        "on_call": False,
    }
    defaults.update(overrides)
    return defaults


def create_instrument_set_payload(**overrides) -> dict:
    """Defaults to a GENERAL specialty instrument set."""
    defaults = {
        "set_name": "GENERAL_LAPAROTOMY_TRAY",
        "specialty": "GENERAL",
    }
    defaults.update(overrides)
    return defaults


def create_surgical_case_payload(**overrides) -> dict:
    """Defaults to a GENERAL specialty case with both safety flags pre-set to true."""
    defaults = {
        "patient_id": "P-TEST-1",
        "surgery_type": "TestSurgery",
        "specialty_required": "GENERAL",
        "priority": "ROUTINE",
        "pre_op_assessment_attached": True,
        "informed_consent_verified": True,
        "implant_cost_estimate": 0.00,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(
    *,
    scheduled_room_id: str,
    planned_start_minute: int,
    planned_end_minute: int,
    staff_assignments: list,
    instrument_set_id: str,
    **overrides,
) -> dict:
    """Build the body for POST /surgical-cases/{caseId}/schedule.

    staff_assignments: list of dicts each carrying staff_id and role_in_case.
    """
    payload = {
        "scheduled_room_id": scheduled_room_id,
        "planned_start_minute": planned_start_minute,
        "planned_end_minute": planned_end_minute,
        "staff_assignments": staff_assignments,
        "instrument_set_id": instrument_set_id,
    }
    payload.update(overrides)
    return payload


def make_staff_assignment(staff_id: str, role_in_case: str) -> dict:
    return {"staff_id": staff_id, "role_in_case": role_in_case}


def create_emergency_insert_payload(
    *,
    scheduled_room_id: str,
    planned_start_minute: int,
    planned_end_minute: int,
    staff_assignments: list,
    instrument_set_id: str,
    **overrides,
) -> dict:
    """Build the body for POST /surgical-cases/emergency-insert.

    Note: pre_op_assessment_attached / informed_consent_verified are forced to true
    by the server on emergency-insert, so they are not part of the payload.
    """
    payload = {
        "patient_id": "P-EM-1",
        "surgery_type": "EmergencySurgery",
        "specialty_required": "GENERAL",
        "scheduled_room_id": scheduled_room_id,
        "planned_start_minute": planned_start_minute,
        "planned_end_minute": planned_end_minute,
        "staff_assignments": staff_assignments,
        "instrument_set_id": instrument_set_id,
        "implant_cost_estimate": 0.00,
    }
    payload.update(overrides)
    return payload


def create_pre_authorize_payload(insurance_pre_auth_reference: str = "AUTH-TEST-1", **overrides) -> dict:
    payload = {"insurance_pre_auth_reference": insurance_pre_auth_reference}
    payload.update(overrides)
    return payload


def create_itemize_payload(insurance_split: list, **overrides) -> dict:
    """insurance_split: list of {payer_id, percentage} entries summing to 100."""
    payload = {"insurance_split": insurance_split}
    payload.update(overrides)
    return payload


def create_clock_advance_payload(delta_minutes: int) -> dict:
    return {"delta_minutes": delta_minutes}


def create_complete_payload(**overrides) -> dict:
    """Body for POST /surgical-cases/{caseId}/complete."""
    payload = {}
    payload.update(overrides)
    return payload
