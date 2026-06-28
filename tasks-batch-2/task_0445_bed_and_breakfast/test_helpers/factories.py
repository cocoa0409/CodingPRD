"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Required vs optional follows the PRD: factories supply
all required input fields by default and let tests override via **overrides.
"""

DEFAULTS = {
    "INN_NAME": "Test Inn",
    "LODGING_TAX_RATE_BPS": 0,
    "ROOM_NAME": "Rose Suite",
    "BASE_RATE_CENTS": 10000,
    "MAX_OCCUPANCY": 2,
    "RATE_LABEL": "Test Period",
    "RATE_MULTIPLIER_BPS": 10000,
    "PACKAGE_NAME": "Test Package",
    "GUEST_NAME": "Test Guest",
    "GUEST_EMAIL": "guest@example.com",
}


def create_inn_payload(**overrides) -> dict:
    """POST /inns. Required: name, lodging_tax_rate_bps. Optional: checkin_time,
    checkout_time, gift_cert_expiry_days, turnover_minutes."""
    payload = {
        "name": DEFAULTS["INN_NAME"],
        "lodging_tax_rate_bps": DEFAULTS["LODGING_TAX_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(inn_id: str, **overrides) -> dict:
    """POST /inns/{inn_id}/rooms. Required: inn_id, name, base_rate_cents,
    max_occupancy. Optional: is_taxable (default true)."""
    payload = {
        "inn_id": inn_id,
        "name": DEFAULTS["ROOM_NAME"],
        "base_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
        "max_occupancy": DEFAULTS["MAX_OCCUPANCY"],
    }
    payload.update(overrides)
    return payload


def create_rate_period_payload(inn_id: str, start_date: str, end_date: str, **overrides) -> dict:
    """POST /inns/{inn_id}/rate-periods. Required: inn_id, label, start_date,
    end_date, rate_multiplier_bps. Optional: min_nights (default 1)."""
    payload = {
        "inn_id": inn_id,
        "label": DEFAULTS["RATE_LABEL"],
        "start_date": start_date,
        "end_date": end_date,
        "rate_multiplier_bps": DEFAULTS["RATE_MULTIPLIER_BPS"],
    }
    payload.update(overrides)
    return payload


def create_package_payload(inn_id: str, **overrides) -> dict:
    """POST /inns/{inn_id}/packages. Required: inn_id, name. Optional:
    flat_add_cents (0), per_night_add_cents (0), is_taxable (false)."""
    payload = {
        "inn_id": inn_id,
        "name": DEFAULTS["PACKAGE_NAME"],
    }
    payload.update(overrides)
    return payload


def create_guest_payload(inn_id: str, **overrides) -> dict:
    """POST /inns/{inn_id}/guests. Required: inn_id, full_name, email."""
    payload = {
        "inn_id": inn_id,
        "full_name": DEFAULTS["GUEST_NAME"],
        "email": DEFAULTS["GUEST_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_gift_certificate_payload(inn_id: str, face_value_cents: int, **overrides) -> dict:
    """POST /inns/{inn_id}/gift-certificates. Required: inn_id, face_value_cents."""
    payload = {
        "inn_id": inn_id,
        "face_value_cents": face_value_cents,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(
    inn_id: str,
    room_id: str,
    guest_id: str,
    checkin_date: str,
    checkout_date: str,
    **overrides,
) -> dict:
    """POST /inns/{inn_id}/bookings. Required: inn_id, room_id, guest_id, channel,
    checkin_date, checkout_date, guest_count. Optional: package_id, ota_commission_bps."""
    payload = {
        "inn_id": inn_id,
        "room_id": room_id,
        "guest_id": guest_id,
        "channel": "DIRECT",
        "checkin_date": checkin_date,
        "checkout_date": checkout_date,
        "guest_count": 1,
    }
    payload.update(overrides)
    return payload


def create_breakfast_plan_payload(booking_id: str, party_size: int, **overrides) -> dict:
    """POST /inns/{inn_id}/breakfast-plans. Required: booking_id, party_size.
    Optional: dietary_flags."""
    payload = {
        "booking_id": booking_id,
        "party_size": party_size,
    }
    payload.update(overrides)
    return payload


def create_tax_remittance_payload(
    inn_id: str, period_start: str, period_end: str, variant: str, **overrides
) -> dict:
    """POST /inns/{inn_id}/tax-remittances. Required: inn_id, period_start,
    period_end, variant."""
    payload = {
        "inn_id": inn_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
    }
    payload.update(overrides)
    return payload
