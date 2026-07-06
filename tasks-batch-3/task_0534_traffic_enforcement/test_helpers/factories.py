"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "JURISDICTION_NAME": "Metro",
    "BASE_RED_LIGHT_FINE_CENTS": 10000,
    "BASE_SPEED_FINE_CENTS": 8000,
    "ADMIN_FEE_CENTS": 2500,
    "LATE_FEE_CENTS": 4000,
    "RESPONSE_WINDOW_DAYS": 30,
    "REPEAT_OFFENDER_WINDOW_DAYS": 365,
    "REPEAT_OFFENDER_SURCHARGE_PCT": 0.5,
    "INTERSECTION_CODE": "INT-1",
    "PLATE_NUMBER": "ABC123",
    "FULL_NAME": "Pat Owner",
    "MAILING_ADDRESS": "1 St",
    "TECHNICIAN_REF": "T1",
    "EVENT_AT_UTC": "2026-05-01T08:00:00Z",
    "PERFORMED_AT_UTC": "2026-04-01T00:00:00Z",
    "VALID_UNTIL_UTC": "2026-12-01T00:00:00Z",
}


def create_program_payload(**overrides) -> dict:
    """POST /programs input (PRD 3.1). Three window/surcharge params have defaults."""
    defaults = {
        "jurisdiction_name": DEFAULTS["JURISDICTION_NAME"],
        "base_red_light_fine_cents": DEFAULTS["BASE_RED_LIGHT_FINE_CENTS"],
        "base_speed_fine_cents": DEFAULTS["BASE_SPEED_FINE_CENTS"],
        "admin_fee_cents": DEFAULTS["ADMIN_FEE_CENTS"],
        "late_fee_cents": DEFAULTS["LATE_FEE_CENTS"],
        "response_window_days": DEFAULTS["RESPONSE_WINDOW_DAYS"],
        "repeat_offender_window_days": DEFAULTS["REPEAT_OFFENDER_WINDOW_DAYS"],
        "repeat_offender_surcharge_pct": DEFAULTS["REPEAT_OFFENDER_SURCHARGE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_camera_payload(program_id: str, **overrides) -> dict:
    """POST /cameras input (PRD 3.1)."""
    defaults = {
        "program_id": program_id,
        "intersection_code": DEFAULTS["INTERSECTION_CODE"],
        "camera_type": "RED_LIGHT",
    }
    defaults.update(overrides)
    return defaults


def create_calibration_payload(**overrides) -> dict:
    """POST /cameras/{id}/calibrations input (PRD 3.1)."""
    defaults = {
        "performed_at_utc": DEFAULTS["PERFORMED_AT_UTC"],
        "valid_until_utc": DEFAULTS["VALID_UNTIL_UTC"],
        "technician_ref": DEFAULTS["TECHNICIAN_REF"],
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(program_id: str, **overrides) -> dict:
    """POST /owners input (PRD 3.2)."""
    defaults = {
        "program_id": program_id,
        "plate_number": DEFAULTS["PLATE_NUMBER"],
        "full_name": DEFAULTS["FULL_NAME"],
        "mailing_address": DEFAULTS["MAILING_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(program_id: str, camera_id: str, **overrides) -> dict:
    """POST /citations input (PRD 3.3)."""
    defaults = {
        "program_id": program_id,
        "camera_id": camera_id,
        "captured_plate_number": DEFAULTS["PLATE_NUMBER"],
        "event_at_utc": DEFAULTS["EVENT_AT_UTC"],
    }
    defaults.update(overrides)
    return defaults


def review_payload(decision: str, **overrides) -> dict:
    """POST /citations/{id}/review input (PRD 3.3)."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_contest_payload(owner_id: str, pin: str, expected_citation_version: int,
                           **overrides) -> dict:
    """POST /citations/{id}/contests input (PRD 3.5)."""
    defaults = {
        "registered_owner_id": owner_id,
        "portal_access_pin": pin,
        "ground": "PLATE_MISREAD",
        "statement": "not me",
        "expected_citation_version": expected_citation_version,
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(scheduled_at_utc: str, adjudicator_ref: str, **overrides) -> dict:
    """POST /contests/{id}/hearings input (PRD 3.5)."""
    defaults = {
        "scheduled_at_utc": scheduled_at_utc,
        "adjudicator_ref": adjudicator_ref,
    }
    defaults.update(overrides)
    return defaults


def rule_payload(outcome: str, expected_hearing_version: int, **overrides) -> dict:
    """POST /hearings/{hid}/rule input (PRD 3.5)."""
    defaults = {
        "outcome": outcome,
        "expected_hearing_version": expected_hearing_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, method: str = "CARD", **overrides) -> dict:
    """POST /citations/{id}/payments input (PRD 3.7)."""
    defaults = {
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_contract_payload(program_id: str, revenue_share_pct: float,
                                   **overrides) -> dict:
    """POST /vendor-contracts input (PRD 3.7)."""
    defaults = {
        "program_id": program_id,
        "vendor_name": "CamCo",
        "revenue_share_pct": revenue_share_pct,
    }
    defaults.update(overrides)
    return defaults


def settle_payload(payment_id: str, outcome: str) -> dict:
    """POST /_payments/settle input (PRD 3.7)."""
    return {"payment_id": payment_id, "outcome": outcome}


def clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc input (PRD 2.9)."""
    return {"to_iso8601": to_iso8601}
