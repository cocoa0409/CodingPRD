"""Payload factories — one per write endpoint, request-input fields only."""

from .constants import TEST_DEFAULTS


# --------------------------------------------------------------------------
# Accounts and property
# --------------------------------------------------------------------------
def homeowner_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["HOMEOWNER_NAME"],
        "email": TEST_DEFAULTS["HOMEOWNER_EMAIL"],
        "phone_e164": TEST_DEFAULTS["HOMEOWNER_PHONE"],
    }
    payload.update(overrides)
    return payload


def buyer_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["BUYER_NAME"],
        "email": TEST_DEFAULTS["BUYER_EMAIL"],
        "phone_e164": TEST_DEFAULTS["BUYER_PHONE"],
    }
    payload.update(overrides)
    return payload


def emergency_contact_payload(priority_rank: int = 1, **overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["CONTACT_NAME"],
        "phone_e164": TEST_DEFAULTS["CONTACT_PHONE"],
        "priority_rank": priority_rank,
    }
    payload.update(overrides)
    return payload


def property_payload(homeowner_id: str, **overrides) -> dict:
    payload = {
        "homeowner_id": homeowner_id,
        "address_line1": TEST_DEFAULTS["ADDRESS_LINE1"],
        "city": TEST_DEFAULTS["CITY"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "postal_code": TEST_DEFAULTS["POSTAL_CODE"],
        "year_built": TEST_DEFAULTS["YEAR_BUILT"],
        "irrigation_present": True,
    }
    payload.update(overrides)
    return payload


def second_property_payload(homeowner_id: str, **overrides) -> dict:
    payload = {
        "homeowner_id": homeowner_id,
        "address_line1": TEST_DEFAULTS["SECOND_ADDRESS_LINE1"],
        "city": TEST_DEFAULTS["SECOND_CITY"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "postal_code": TEST_DEFAULTS["SECOND_POSTAL_CODE"],
        "year_built": TEST_DEFAULTS["SECOND_YEAR_BUILT"],
        "irrigation_present": False,
    }
    payload.update(overrides)
    return payload


def irrigation_window_payload(
    start_at: str, end_at: str, expected_max_flow_gpm: float = 4.0, **overrides
) -> dict:
    payload = {
        "label": "front lawn",
        "start_at": start_at,
        "end_at": end_at,
        "expected_max_flow_gpm": expected_max_flow_gpm,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Devices
# --------------------------------------------------------------------------
def device_payload(property_id: str, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "serial_number": TEST_DEFAULTS["SERIAL_NUMBER"],
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
    }
    payload.update(overrides)
    return payload


def verify_install_payload(**overrides) -> dict:
    payload = {
        "installed_static_pressure_psi": TEST_DEFAULTS["INSTALL_PSI"],
        "pressure_drop_psi": TEST_DEFAULTS["INSTALL_DROP_PSI"],
    }
    payload.update(overrides)
    return payload


def telemetry_payload(
    reading_at: str,
    static_pressure_psi: float,
    flow_gpm: float,
    duration_minutes: float,
    total_gallons: float,
    **overrides,
) -> dict:
    payload = {
        "reading_at": reading_at,
        "static_pressure_psi": static_pressure_psi,
        "flow_gpm": flow_gpm,
        "duration_minutes": duration_minutes,
        "total_gallons": total_gallons,
    }
    payload.update(overrides)
    return payload


def valve_command_payload(command: str, expected_device_version: int, **overrides) -> dict:
    payload = {
        "command": command,
        "expected_device_version": expected_device_version,
    }
    payload.update(overrides)
    return payload


def monitor_mode_payload(mode: str, **overrides) -> dict:
    payload = {"mode": mode}
    payload.update(overrides)
    return payload


def firmware_update_payload(target_firmware_version: str = "3.2.1", **overrides) -> dict:
    payload = {"target_firmware_version": target_firmware_version}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Alerting
# --------------------------------------------------------------------------
def feedback_payload(label: str, **overrides) -> dict:
    payload = {"label": label}
    payload.update(overrides)
    return payload


def resolve_payload(resolution_note: str = "Burst hose bib replaced", **overrides) -> dict:
    payload = {"resolution_note": resolution_note}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Insurer credit program
# --------------------------------------------------------------------------
def policy_payload(
    property_id: str,
    expected_property_version: int,
    policy_year_start_at: str,
    **overrides,
) -> dict:
    payload = {
        "property_id": property_id,
        "insurer_code": TEST_DEFAULTS["INSURER_CODE"],
        "policy_number": TEST_DEFAULTS["POLICY_NUMBER"],
        "annual_premium_cents": TEST_DEFAULTS["ANNUAL_PREMIUM_CENTS"],
        "policy_year_start_at": policy_year_start_at,
        "expected_property_version": expected_property_version,
        "deductible_cents": TEST_DEFAULTS["DEDUCTIBLE_CENTS"],
    }
    payload.update(overrides)
    return payload


def attestation_payload(period_start_at: str, period_end_at: str, **overrides) -> dict:
    payload = {
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def claim_payload(
    policy_id: str,
    device_id: str,
    claim_type: str,
    documented_loss_cents: int,
    **overrides,
) -> dict:
    payload = {
        "policy_id": policy_id,
        "device_id": device_id,
        "claim_type": claim_type,
        "documented_loss_cents": documented_loss_cents,
    }
    payload.update(overrides)
    return payload


def claim_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
def device_transfer_payload(
    device_id: str, to_homeowner_id: str, expected_device_version: int, **overrides
) -> dict:
    payload = {
        "device_id": device_id,
        "to_homeowner_id": to_homeowner_id,
        "expected_device_version": expected_device_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
