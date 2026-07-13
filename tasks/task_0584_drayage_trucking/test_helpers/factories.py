"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "TERMINAL_NAME": "Pier Alpha",
    "TERMINAL_CODE": "PIERA",
    "DEMURRAGE_DAILY_RATE_CENTS": 12500,
    "CHASSIS_NUMBER": "CHX1",
    "POOL_SCAC": "POOL",
    "PER_DIEM_RATE_CENTS": 8500,
    "FREE_DAYS": 4,
    "DRIVER_NAME": "Test Driver",
    "LICENSE_NUMBER": "L1",
    "CONTAINER_NUMBER": "MSCU1",
    "DIRECTION": "IMPORT",
    "LAST_FREE_DAY": "2026-06-30T00:00:00Z",
    "LINEHAUL_BASE_CENTS": 45000,
    "PERMIT_NUMBER": "P1",
    "MAX_GROSS_WEIGHT_LBS": 95000,
    "ACCESSORIAL_KIND": "CHASSIS_RENTAL",
    "ACCESSORIAL_AMOUNT_CENTS": 12000,
}


def create_terminal_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TERMINAL_NAME"],
        "code": DEFAULTS["TERMINAL_CODE"],
        "demurrage_daily_rate_cents": DEFAULTS["DEMURRAGE_DAILY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_chassis_payload(**overrides) -> dict:
    payload = {
        "chassis_number": DEFAULTS["CHASSIS_NUMBER"],
        "pool_scac": DEFAULTS["POOL_SCAC"],
        "per_diem_rate_cents": DEFAULTS["PER_DIEM_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_driver_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DRIVER_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    payload.update(overrides)
    return payload


def create_booking_payload(origin_terminal_id, **overrides) -> dict:
    payload = {
        "container_number": DEFAULTS["CONTAINER_NUMBER"],
        "direction": DEFAULTS["DIRECTION"],
        "origin_terminal_id": origin_terminal_id,
        "last_free_day": DEFAULTS["LAST_FREE_DAY"],
        "linehaul_base_cents": DEFAULTS["LINEHAUL_BASE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(booking_id, terminal_id, purpose, window_start, window_end, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "terminal_id": terminal_id,
        "purpose": purpose,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_leg_payload(booking_id, driver_id, leg_type, window_start, window_end, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "driver_id": driver_id,
        "leg_type": leg_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_weigh_ticket_payload(booking_id, gross_weight_lbs, **overrides) -> dict:
    payload = {"booking_id": booking_id, "gross_weight_lbs": gross_weight_lbs}
    payload.update(overrides)
    return payload


def create_permit_payload(booking_id, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
        "max_gross_weight_lbs": DEFAULTS["MAX_GROSS_WEIGHT_LBS"],
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(booking_id, **overrides) -> dict:
    payload = {"booking_id": booking_id}
    payload.update(overrides)
    return payload


def create_accessorial_payload(**overrides) -> dict:
    payload = {
        "kind": DEFAULTS["ACCESSORIAL_KIND"],
        "amount_cents": DEFAULTS["ACCESSORIAL_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload
