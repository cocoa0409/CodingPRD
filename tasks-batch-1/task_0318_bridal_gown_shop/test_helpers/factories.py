"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STYLIST_NAME": "Test Stylist",
    "ROOM_LABEL": "Test Suite",
    "PARTY_NAME": "Test Wedding",
    "EVENT_DATE": "2026-12-01T00:00:00.000Z",
    "GOWN_STYLE_CODE": "ATELIER",
    "ORDERED_SIZE": 10,
    "BASE_PRICE_CENTS": 180000,
    "STANDARD_LEAD_DAYS": 60,
    "ACCESSORY_PRICE_CENTS": 12000,
    "ESTIMATED_LABOR_MINUTES": 30,
    "CAPACITY": 3,
    "PARTY_SIZE": 1,
}


def create_stylist_payload(**overrides) -> dict:
    """Required input: full_name. Optional: turnaround_buffer_minutes, active."""
    payload = {"full_name": DEFAULTS["STYLIST_NAME"]}
    payload.update(overrides)
    return payload


def create_fitting_room_payload(**overrides) -> dict:
    """Required inputs: room_label, capacity. Optional: out_of_service."""
    payload = {"room_label": DEFAULTS["ROOM_LABEL"], "capacity": DEFAULTS["CAPACITY"]}
    payload.update(overrides)
    return payload


def create_bridal_party_payload(**overrides) -> dict:
    """Required inputs: party_name, event_date. Optional: lead_gown_order_id."""
    payload = {"party_name": DEFAULTS["PARTY_NAME"], "event_date": DEFAULTS["EVENT_DATE"]}
    payload.update(overrides)
    return payload


def create_appointment_payload(stylist_id, **overrides) -> dict:
    """Required inputs: stylist_id, appointment_type, start_at, end_at. Optional: bridal_party_id."""
    payload = {
        "stylist_id": stylist_id,
        "appointment_type": "CONSULTATION",
        "start_at": "2026-08-01T10:00:00.000Z",
        "end_at": "2026-08-01T11:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_fitting_room_booking_payload(appointment_id, fitting_room_id, **overrides) -> dict:
    """Required inputs: appointment_id, fitting_room_id, party_size, slot_start_at, slot_end_at."""
    payload = {
        "appointment_id": appointment_id,
        "fitting_room_id": fitting_room_id,
        "party_size": DEFAULTS["PARTY_SIZE"],
        "slot_start_at": "2026-08-01T10:00:00.000Z",
        "slot_end_at": "2026-08-01T11:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_gown_order_payload(**overrides) -> dict:
    """Required inputs: gown_style_code, ordered_size, base_price_cents, standard_lead_days.
    Optional: is_rush, bridal_party_id, origin_appointment_id."""
    payload = {
        "gown_style_code": DEFAULTS["GOWN_STYLE_CODE"],
        "ordered_size": DEFAULTS["ORDERED_SIZE"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "standard_lead_days": DEFAULTS["STANDARD_LEAD_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_accessory_addon_payload(gown_order_id, **overrides) -> dict:
    """Required inputs: gown_order_id, accessory_type, price_cents."""
    payload = {
        "gown_order_id": gown_order_id,
        "accessory_type": "VEIL",
        "price_cents": DEFAULTS["ACCESSORY_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_alteration_job_payload(gown_order_id, **overrides) -> dict:
    """Required inputs: gown_order_id, estimated_labor_minutes. Optional: fitting_room_id."""
    payload = {
        "gown_order_id": gown_order_id,
        "estimated_labor_minutes": DEFAULTS["ESTIMATED_LABOR_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_payment_plan_payload(gown_order_id, **overrides) -> dict:
    """Required inputs: gown_order_id, term_installments, deposit_cents."""
    payload = {
        "gown_order_id": gown_order_id,
        "term_installments": 2,
        "deposit_cents": 90000,
    }
    payload.update(overrides)
    return payload


def post_payment_payload(amount_cents, expected_plan_version, **overrides) -> dict:
    """Required inputs: amount_cents, expected_plan_version."""
    payload = {"amount_cents": amount_cents, "expected_plan_version": expected_plan_version}
    payload.update(overrides)
    return payload


def refund_payload(expected_plan_version, **overrides) -> dict:
    """Required input: expected_plan_version."""
    payload = {"expected_plan_version": expected_plan_version}
    payload.update(overrides)
    return payload
