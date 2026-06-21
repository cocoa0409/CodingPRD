"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict; pass **overrides to control specific fields.
Only PRD `source: input` fields are emitted; computed/system fields are never
included. Required-vs-optional follows the PRD: optional fields with a documented
default (garage.timezone/gate_mode, space.status, rate_plan.grace_minutes,
event_pricing.multiplier) are omitted by default so the server applies its default.
"""


def create_garage_payload(name="Test Garage", **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_zone_payload(garage_id, rate_plan_id, code="Z",
                        zone_type="MIXED", permit_capacity=5, **overrides) -> dict:
    payload = {
        "garage_id": garage_id,
        "code": code,
        "zone_type": zone_type,
        "permit_capacity": permit_capacity,
        "rate_plan_id": rate_plan_id,
    }
    payload.update(overrides)
    return payload


def create_space_payload(zone_id, label="S1", **overrides) -> dict:
    payload = {"zone_id": zone_id, "label": label}
    payload.update(overrides)
    return payload


def create_rate_plan_payload(name="RP", hourly_cents=500, daily_cap_cents=4000,
                             monthly_permit_cents=9000, **overrides) -> dict:
    payload = {
        "name": name,
        "hourly_cents": hourly_cents,
        "daily_cap_cents": daily_cap_cents,
        "monthly_permit_cents": monthly_permit_cents,
    }
    payload.update(overrides)
    return payload


def create_event_pricing_payload(garage_id, window_start_utc, window_end_utc,
                                 flat_surcharge_cents=1000, name="Event",
                                 **overrides) -> dict:
    payload = {
        "garage_id": garage_id,
        "name": name,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "flat_surcharge_cents": flat_surcharge_cents,
    }
    payload.update(overrides)
    return payload


def create_motorist_payload(email, full_name="Test Motorist",
                            default_plate="PLT001", **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "email": email,
        "default_plate": default_plate,
    }
    payload.update(overrides)
    return payload


def create_permit_payload(zone_id, motorist_id, plate, **overrides) -> dict:
    payload = {"zone_id": zone_id, "motorist_id": motorist_id, "plate": plate}
    payload.update(overrides)
    return payload


def create_waitlist_entry_payload(motorist_id, plate, **overrides) -> dict:
    payload = {"motorist_id": motorist_id, "plate": plate}
    payload.update(overrides)
    return payload


def create_merchant_payload(garage_id, name="MER", validation_budget_cents=10000,
                            **overrides) -> dict:
    payload = {
        "garage_id": garage_id,
        "name": name,
        "validation_budget_cents": validation_budget_cents,
    }
    payload.update(overrides)
    return payload


def create_validation_payload(garage_id, merchant_id, discount_kind, discount_value,
                              expires_at_utc, **overrides) -> dict:
    payload = {
        "garage_id": garage_id,
        "merchant_id": merchant_id,
        "discount_kind": discount_kind,
        "discount_value": discount_value,
        "expires_at_utc": expires_at_utc,
    }
    payload.update(overrides)
    return payload


def create_session_payload(garage_id, plate, entry_at_utc, **overrides) -> dict:
    payload = {"garage_id": garage_id, "plate": plate, "entry_at_utc": entry_at_utc}
    payload.update(overrides)
    return payload


def exit_session_payload(exit_at_utc, **overrides) -> dict:
    payload = {"exit_at_utc": exit_at_utc}
    payload.update(overrides)
    return payload


def create_plate_read_payload(garage_id, plate, zone_id, read_at_utc, **overrides) -> dict:
    payload = {
        "garage_id": garage_id,
        "plate": plate,
        "zone_id": zone_id,
        "read_at_utc": read_at_utc,
    }
    payload.update(overrides)
    return payload


def create_citation_payload(garage_id, plate, plate_read_id, violation_code="NO_PERMIT",
                            base_fine_cents=5000, **overrides) -> dict:
    payload = {
        "garage_id": garage_id,
        "plate": plate,
        "plate_read_id": plate_read_id,
        "violation_code": violation_code,
        "base_fine_cents": base_fine_cents,
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(citation_id, motorist_id, reason="reason", **overrides) -> dict:
    payload = {"citation_id": citation_id, "motorist_id": motorist_id, "reason": reason}
    payload.update(overrides)
    return payload
