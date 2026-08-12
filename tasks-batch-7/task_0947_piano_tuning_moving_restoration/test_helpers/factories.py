"""Payload factories — one per entity, caller-supplied input fields only."""

import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):05d}"


def client_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "display_name": f"Client {n}",
        "email": f"client{n}@example.com",
        "phone": f"555-{n}",
        "home_zone_code": "ZONE_A",
    }
    payload.update(overrides)
    return payload


def location_payload(client_id: str, **overrides) -> dict:
    n = unique_suffix()
    payload = {
        "client_id": client_id,
        "label": f"Site {n}",
        "zone_code": "ZONE_A",
        "address_key": f"address-key-{n}",
        "distance_miles_from_shop": 5.0,
    }
    payload.update(overrides)
    return payload


def instrument_payload(client_id: str, current_location_id: str, **overrides) -> dict:
    n = unique_suffix()
    payload = {
        "client_id": client_id,
        "current_location_id": current_location_id,
        "make": "Yamaha",
        "model": "U1",
        "serial_number": f"SN-{n}",
        "instrument_class": "UPRIGHT",
        "usage_tier": "HOME",
    }
    payload.update(overrides)
    return payload


def technician_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "display_name": f"Technician {n}",
        "certification_level": "JOURNEYMAN",
        "zone_codes": ["ZONE_A"],
    }
    payload.update(overrides)
    return payload


def route_day_payload(technician_id: str, service_date: str, **overrides) -> dict:
    payload = {"technician_id": technician_id, "service_date": service_date}
    payload.update(overrides)
    return payload


def climate_reading_payload(location_id: str, recorded_at_utc: str,
                            relative_humidity_pct: float, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "recorded_at_utc": recorded_at_utc,
        "relative_humidity_pct": relative_humidity_pct,
        "temperature_f": 68.0,
    }
    payload.update(overrides)
    return payload


def appointment_payload(instrument_id: str, route_day_id: str, location_id: str,
                        scheduled_start_utc: str, service_type: str,
                        expected_route_day_version: int, **overrides) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "route_day_id": route_day_id,
        "location_id": location_id,
        "scheduled_start_utc": scheduled_start_utc,
        "service_type": service_type,
        "expected_route_day_version": expected_route_day_version,
    }
    payload.update(overrides)
    return payload


def quote_payload(instrument_id: str, service_type: str,
                  expected_instrument_version: int, **overrides) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "service_type": service_type,
        "expected_instrument_version": expected_instrument_version,
    }
    payload.update(overrides)
    return payload


def service_order_payload(quote_id: str, **overrides) -> dict:
    payload = {"quote_id": quote_id}
    payload.update(overrides)
    return payload


def move_job_payload(instrument_id: str, origin_location_id: str,
                     destination_location_id: str, distance_miles: float,
                     scheduled_window_start_utc: str, scheduled_window_end_utc: str,
                     **overrides) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "origin_location_id": origin_location_id,
        "destination_location_id": destination_location_id,
        "distance_miles": distance_miles,
        "scheduled_window_start_utc": scheduled_window_start_utc,
        "scheduled_window_end_utc": scheduled_window_end_utc,
    }
    payload.update(overrides)
    return payload


def parts_lot_payload(part_type: str = "HAMMER_SET", initial_qty: int = 4,
                      **overrides) -> dict:
    payload = {
        "part_type": part_type,
        "lot_code": f"LOT-{unique_suffix()}",
        "initial_qty": initial_qty,
    }
    payload.update(overrides)
    return payload


def parts_allocation_payload(parts_lot_id: str, requested_qty: int,
                             expected_parts_lot_version: int, **overrides) -> dict:
    payload = {
        "parts_lot_id": parts_lot_id,
        "requested_qty": requested_qty,
        "expected_parts_lot_version": expected_parts_lot_version,
    }
    payload.update(overrides)
    return payload


def warranty_claim_payload(warranty_id: str, expected_warranty_version: int,
                           **overrides) -> dict:
    payload = {
        "warranty_id": warranty_id,
        "reported_issue": "unison drift in the tenor break",
        "expected_warranty_version": expected_warranty_version,
    }
    payload.update(overrides)
    return payload


def consignment_agreement_payload(instrument_id: str, consignor_client_id: str,
                                  reserve_price_cents: int,
                                  expected_instrument_version: int, **overrides) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "consignor_client_id": consignor_client_id,
        "reserve_price_cents": reserve_price_cents,
        "expected_instrument_version": expected_instrument_version,
    }
    payload.update(overrides)
    return payload


def credit_adjustment_payload(amount_cents: int, memo: str = "opening funds") -> dict:
    return {"amount_cents": amount_cents, "memo": memo}
