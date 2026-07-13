"""Payload factories — one per entity, input fields only (PRD-declared inputs)."""


def create_shipper_payload(email="shipper@x.com", full_name="Test Shipper", **overrides) -> dict:
    payload = {"email": email, "full_name": full_name}
    payload.update(overrides)
    return payload


def create_terminal_payload(
    name="Test Terminal", dock_zip="90001", dock_count=1, buffer_minutes=None, **overrides
) -> dict:
    payload = {"name": name, "dock_zip": dock_zip, "dock_count": dock_count}
    if buffer_minutes is not None:
        payload["buffer_minutes"] = buffer_minutes
    payload.update(overrides)
    return payload


def create_carrier_payload(
    legal_name="Test Carrier",
    mc_number="MC-0001",
    cargo_insurance_limit_cents=3_000_000,
    insurance_expiry_date="2027-01-01T00:00:00Z",
    equipment_type="OPEN",
    rating=None,
    **overrides,
) -> dict:
    payload = {
        "legal_name": legal_name,
        "mc_number": mc_number,
        "cargo_insurance_limit_cents": cargo_insurance_limit_cents,
        "insurance_expiry_date": insurance_expiry_date,
        "equipment_type": equipment_type,
    }
    if rating is not None:
        payload["rating"] = rating
    payload.update(overrides)
    return payload


def create_order_payload(
    origin_zip="90001",
    dest_zip="10001",
    route_miles=1200,
    transport_type="OPEN",
    pickup_window_start="2026-06-01T08:00:00Z",
    pickup_window_end="2026-06-05T18:00:00Z",
    service_level=None,
    delivery_mode=None,
    terminal_id=None,
    terminal_slot_start=None,
    terminal_slot_end=None,
    **overrides,
) -> dict:
    payload = {
        "origin_zip": origin_zip,
        "dest_zip": dest_zip,
        "route_miles": route_miles,
        "transport_type": transport_type,
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
    }
    # Only include optional enums when non-default so default behaviour can be tested.
    if service_level is not None:
        payload["service_level"] = service_level
    if delivery_mode is not None:
        payload["delivery_mode"] = delivery_mode
    if terminal_id is not None:
        payload["terminal_id"] = terminal_id
    if terminal_slot_start is not None:
        payload["terminal_slot_start"] = terminal_slot_start
    if terminal_slot_end is not None:
        payload["terminal_slot_end"] = terminal_slot_end
    payload.update(overrides)
    return payload


def create_vehicle_payload(
    make="Honda", model="Civic", year=2020, declared_value_cents=1_000_000, is_inoperable=None, **overrides
) -> dict:
    payload = {
        "make": make,
        "model": model,
        "year": year,
        "declared_value_cents": declared_value_cents,
    }
    if is_inoperable is not None:
        payload["is_inoperable"] = is_inoperable
    payload.update(overrides)
    return payload


def create_quote_payload(expected_order_version, **overrides) -> dict:
    payload = {"expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def create_ledger_entry_payload(kind, amount_cents, **overrides) -> dict:
    payload = {"kind": kind, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_listing_payload(offered_carrier_pay_cents=50000, **overrides) -> dict:
    payload = {"offered_carrier_pay_cents": offered_carrier_pay_cents}
    payload.update(overrides)
    return payload


def create_offer_payload(ask_pay_cents=50000, pickup_eta="2026-06-02T09:00:00Z", **overrides) -> dict:
    payload = {"ask_pay_cents": ask_pay_cents, "pickup_eta": pickup_eta}
    payload.update(overrides)
    return payload


def create_counter_payload(counter_pay_cents, **overrides) -> dict:
    payload = {"counter_pay_cents": counter_pay_cents}
    payload.update(overrides)
    return payload


def create_reoffer_payload(ask_pay_cents, pickup_eta=None, **overrides) -> dict:
    payload = {"ask_pay_cents": ask_pay_cents}
    if pickup_eta is not None:
        payload["pickup_eta"] = pickup_eta
    payload.update(overrides)
    return payload


def create_inspection_payload(
    phase, odometer=10000, damage_count=None, observed_inoperable_count=None, **overrides
) -> dict:
    payload = {"phase": phase, "odometer": odometer}
    if damage_count is not None:
        payload["damage_count"] = damage_count
    if observed_inoperable_count is not None:
        payload["observed_inoperable_count"] = observed_inoperable_count
    payload.update(overrides)
    return payload


def create_claim_payload(claimed_cents, **overrides) -> dict:
    payload = {"claimed_cents": claimed_cents}
    payload.update(overrides)
    return payload
