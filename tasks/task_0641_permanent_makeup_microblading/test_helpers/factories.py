"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
- Studio: min_client_age is optional (default 18); name, state_code,
  sterile_kit_total required.
- Client: medical_flag_count, prior_adverse_reactions, skin_sensitivity_self
  are optional (default 0); studio_id, full_name, date_of_birth required.
- Appointment (initial): is_corrective optional (default false).
- HealingLog: notes optional.
"""

DEFAULTS = {
    "STUDIO_NAME": "Ink Studio",
    "STATE_CODE": "CA",
    "STERILE_KIT_TOTAL": 10,
    "TECH_NAME": "Tech A",
    "LICENSE_NUMBER": "L1",
    "BBP_CERT_EXPIRY": "2030-01-01T00:00:00Z",
    "LICENSE_EXPIRY": "2030-01-01T00:00:00Z",
    "CLIENT_NAME": "Client A",
    "DATE_OF_BIRTH": "1990-01-01T00:00:00Z",
    "FORMULA_NAME": "Warm Taupe",
    "PROCEDURE_TYPE": "BROWS",
    "PIGMENT_COUNT": 2,
    "SIGNED_BY_NAME": "Client A",
}


def create_studio_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STUDIO_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "sterile_kit_total": DEFAULTS["STERILE_KIT_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(studio_id: str, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "full_name": DEFAULTS["TECH_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "bbp_cert_expiry": DEFAULTS["BBP_CERT_EXPIRY"],
        "license_expiry": DEFAULTS["LICENSE_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(studio_id: str, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "full_name": DEFAULTS["CLIENT_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "consent_type": "PROCEDURE_CONSENT",
        "age_verified": True,
        "signed_by_name": DEFAULTS["SIGNED_BY_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_patch_test_payload(client_id: str, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults


def read_patch_test_payload(reaction_grade: int = 1, **overrides) -> dict:
    defaults = {"reaction_grade": reaction_grade}
    defaults.update(overrides)
    return defaults


def create_color_formula_payload(studio_id: str, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "name": DEFAULTS["FORMULA_NAME"],
        "procedure_type": DEFAULTS["PROCEDURE_TYPE"],
        "pigment_count": DEFAULTS["PIGMENT_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(
    client_id: str,
    technician_id: str,
    color_formula_id: str,
    patch_test_id: str,
    procedure_type: str = "BROWS",
    scheduled_start: str = "2026-01-06T10:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "client_id": client_id,
        "technician_id": technician_id,
        "color_formula_id": color_formula_id,
        "patch_test_id": patch_test_id,
        "procedure_type": procedure_type,
        "scheduled_start": scheduled_start,
    }
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def pay_balance_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_healing_log_payload(
    appointment_id: str, day_offset: int = 14, outcome_flag: str = "GOOD", **overrides
) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "day_offset": day_offset,
        "outcome_flag": outcome_flag,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(
    client_id: str,
    source_appointment_id: str,
    included_sessions: int = 2,
    pricing_mode: str = "PAYG",
    **overrides,
) -> dict:
    defaults = {
        "client_id": client_id,
        "source_appointment_id": source_appointment_id,
        "included_sessions": included_sessions,
        "pricing_mode": pricing_mode,
    }
    defaults.update(overrides)
    return defaults


def create_touch_up_payload(
    package_order_id: str,
    technician_id: str,
    color_formula_id: str,
    patch_test_id: str,
    scheduled_start: str,
    expected_package_version: int,
    procedure_type: str = "BROWS",
    **overrides,
) -> dict:
    defaults = {
        "package_order_id": package_order_id,
        "technician_id": technician_id,
        "color_formula_id": color_formula_id,
        "patch_test_id": patch_test_id,
        "procedure_type": procedure_type,
        "scheduled_start": scheduled_start,
        "expected_package_version": expected_package_version,
    }
    defaults.update(overrides)
    return defaults


def create_annual_refresh_payload(
    parent_appointment_id: str,
    technician_id: str,
    color_formula_id: str,
    patch_test_id: str,
    scheduled_start: str,
    procedure_type: str = "BROWS",
    **overrides,
) -> dict:
    defaults = {
        "parent_appointment_id": parent_appointment_id,
        "technician_id": technician_id,
        "color_formula_id": color_formula_id,
        "patch_test_id": patch_test_id,
        "procedure_type": procedure_type,
        "scheduled_start": scheduled_start,
    }
    defaults.update(overrides)
    return defaults


def create_redo_request_payload(appointment_id: str, reason: str = "patchy retention", **overrides) -> dict:
    defaults = {"appointment_id": appointment_id, "reason": reason}
    defaults.update(overrides)
    return defaults


def schedule_redo_payload(
    technician_id: str,
    color_formula_id: str,
    patch_test_id: str,
    expected_appointment_version: int,
    scheduled_start: str = "2026-02-10T10:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "scheduled_start": scheduled_start,
        "technician_id": technician_id,
        "color_formula_id": color_formula_id,
        "patch_test_id": patch_test_id,
        "expected_appointment_version": expected_appointment_version,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
