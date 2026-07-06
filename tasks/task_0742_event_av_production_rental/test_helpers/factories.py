"""Payload factories — one per entity, input fields only (PRD §3).

Optional input fields are omitted unless explicitly supplied so that "default
applied" behaviour can be exercised.
"""


def create_customer_payload(name="Acme Productions", contact_email="ops@acme.test",
                            credit_limit_cents=100_000_000, **overrides) -> dict:
    payload = {
        "name": name,
        "contact_email": contact_email,
        "credit_limit_cents": credit_limit_cents,
    }
    payload.update(overrides)
    return payload


def create_venue_payload(name="Grand Hall", address="1 Main St",
                         required_coverage_cents=0, dock_type=None, **overrides) -> dict:
    payload = {
        "name": name,
        "address": address,
        "required_coverage_cents": required_coverage_cents,
    }
    if dock_type is not None:
        payload["dock_type"] = dock_type
    payload.update(overrides)
    return payload


def create_equipment_payload(name="LED Panel P3", category="LED", total_units=20,
                             daily_rate_cents=12000, replacement_value_cents=500000,
                             requires_operator=None, **overrides) -> dict:
    payload = {
        "name": name,
        "category": category,
        "total_units": total_units,
        "daily_rate_cents": daily_rate_cents,
        "replacement_value_cents": replacement_value_cents,
    }
    if requires_operator is not None:
        payload["requires_operator"] = requires_operator
    payload.update(overrides)
    return payload


def create_crew_member_payload(name="Tech One", crew_role="TECH",
                               hourly_rate_cents=4000, **overrides) -> dict:
    payload = {
        "name": name,
        "crew_role": crew_role,
        "hourly_rate_cents": hourly_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, venue_id, event_name="Gala",
                         event_start_date="2026-06-10", event_end_date="2026-06-12",
                         **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "venue_id": venue_id,
        "event_name": event_name,
        "event_start_date": event_start_date,
        "event_end_date": event_end_date,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(equipment_id, qty=1, reserve_start_date="2026-06-10",
                               reserve_end_date="2026-06-12", is_standby=None,
                               **overrides) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "qty": qty,
        "reserve_start_date": reserve_start_date,
        "reserve_end_date": reserve_end_date,
    }
    if is_standby is not None:
        payload["is_standby"] = is_standby
    payload.update(overrides)
    return payload


def create_crew_assignment_payload(crew_member_id, assignment_role="TECH",
                                   shift_start="2026-06-10T08:00:00Z",
                                   shift_end="2026-06-10T16:00:00Z",
                                   scheduled_hours=8, is_standby=None, **overrides) -> dict:
    payload = {
        "crew_member_id": crew_member_id,
        "assignment_role": assignment_role,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "scheduled_hours": scheduled_hours,
    }
    if is_standby is not None:
        payload["is_standby"] = is_standby
    payload.update(overrides)
    return payload


def create_sub_rental_payload(equipment_id, vendor_name="PeerAV", qty=1, cost_cents=20000,
                              reservation_id=None, direction=None, **overrides) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "vendor_name": vendor_name,
        "qty": qty,
        "cost_cents": cost_cents,
    }
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    if direction is not None:
        payload["direction"] = direction
    payload.update(overrides)
    return payload


def create_coi_payload(insurer="Lloyd", coverage_amount_cents=100000,
                       expiry_date="2026-12-31", **overrides) -> dict:
    payload = {
        "insurer": insurer,
        "coverage_amount_cents": coverage_amount_cents,
        "expiry_date": expiry_date,
    }
    payload.update(overrides)
    return payload


def create_damage_report_payload(reservation_id, damaged_units=None, lost_units=None,
                                 notes=None, **overrides) -> dict:
    payload = {"reservation_id": reservation_id}
    if damaged_units is not None:
        payload["damaged_units"] = damaged_units
    if lost_units is not None:
        payload["lost_units"] = lost_units
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload
