"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "OPERATOR_NAME": "Coastliner",
    "OPERATOR_MODE": "BUS",
    "ORIGIN": "NYP",
    "DESTINATION": "BOS",
    "DEPART_MIN": 540,
    "ARRIVE_MIN": 780,
    "DEPARTURE_DATE": "2026-06-15",
    "SEATS_TOTAL": 10,
    "BASE_FARE_CENTS": 4000,
}


def create_operator_payload(**overrides) -> dict:
    """name + mode required; default_connection_buffer_min and exchange_fee_cents optional."""
    payload = {
        "name": DEFAULTS["OPERATOR_NAME"],
        "mode": DEFAULTS["OPERATOR_MODE"],
    }
    payload.update(overrides)
    return payload


def create_fare_class_payload(operator_id, **overrides) -> dict:
    """operator_id + code + seating_mode required; surcharge_cents and refundable optional."""
    payload = {
        "operator_id": operator_id,
        "code": "ECONOMY",
        "seating_mode": "OPEN",
    }
    payload.update(overrides)
    return payload


def create_route_payload(operator_id, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "origin_code": DEFAULTS["ORIGIN"],
        "destination_code": DEFAULTS["DESTINATION"],
        "depart_minute_of_day": DEFAULTS["DEPART_MIN"],
        "arrive_minute_of_day": DEFAULTS["ARRIVE_MIN"],
    }
    payload.update(overrides)
    return payload


def create_service_date_payload(route_id, **overrides) -> dict:
    payload = {
        "route_id": route_id,
        "departure_date": DEFAULTS["DEPARTURE_DATE"],
        "seats_total": DEFAULTS["SEATS_TOTAL"],
        "base_fare_cents": DEFAULTS["BASE_FARE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_passenger_payload(**overrides) -> dict:
    """full_name + email required; needs_accessibility optional."""
    payload = {
        "full_name": "Pat Rider",
        "email": "pat@x.com",
    }
    payload.update(overrides)
    return payload


def create_pass_payload(passenger_id, operator_id, **overrides) -> dict:
    payload = {
        "passenger_id": passenger_id,
        "operator_id": operator_id,
        "rides_total": 10,
        "expires_on": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def leg_payload(service_date_id, fare_class_id, leg_order=1, seat_number=None) -> dict:
    """One entry in a booking's `legs` array. seat_number only for RESERVED classes."""
    leg = {
        "service_date_id": service_date_id,
        "fare_class_id": fare_class_id,
        "leg_order": leg_order,
    }
    if seat_number is not None:
        leg["seat_number"] = seat_number
    return leg


def create_booking_payload(passenger_id, legs, funding_kind="CASH", pass_id=None,
                           **overrides) -> dict:
    """passenger_id + legs required; funding_kind defaults CASH; pass_id only for PASS."""
    payload = {
        "passenger_id": passenger_id,
        "funding_kind": funding_kind,
        "legs": legs,
    }
    if pass_id is not None:
        payload["pass_id"] = pass_id
    payload.update(overrides)
    return payload


def confirm_payload(expected_service_date_version) -> dict:
    return {"expected_service_date_version": expected_service_date_version}


def cancel_payload(refund_destination=None) -> dict:
    """refund_destination required only when payment_status==PAID."""
    payload: dict = {}
    if refund_destination is not None:
        payload["refund_destination"] = refund_destination
    return payload


def exchange_payload(target_service_date_id, target_fare_class_id,
                     expected_booking_version, target_seat_number=None) -> dict:
    payload = {
        "target_service_date_id": target_service_date_id,
        "target_fare_class_id": target_fare_class_id,
        "expected_booking_version": expected_booking_version,
    }
    if target_seat_number is not None:
        payload["target_seat_number"] = target_seat_number
    return payload


def baggage_payload(weight_kg) -> dict:
    return {"weight_kg": weight_kg}


def accessibility_payload(accommodation="WHEELCHAIR_SPACE") -> dict:
    return {"accommodation": accommodation}
