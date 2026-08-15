"""Payload factories — one per creatable resource, input fields only."""


def create_program_payload(**overrides) -> dict:
    defaults = {"name": "Test Program"}
    defaults.update(overrides)
    return defaults


def create_employee_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "badge_number": "B001",
        "full_name": "Test Employee",
        "employer_code": "ACME",
        "shift_pattern": "DAY",
        "hire_date": "2024-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "code": "CORE-A",
        "tier": "CORE",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(employee_id: str, lot_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "lot_id": lot_id,
        "vehicle_plate": "P001",
    }
    defaults.update(overrides)
    return defaults


def permit_event_payload(event_type: str, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_renewal_payload(expected_permit_version: int, **overrides) -> dict:
    defaults = {"expected_permit_version": expected_permit_version}
    defaults.update(overrides)
    return defaults


def decide_renewal_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_route_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "code": "R1",
        "headway_target_minutes": 10,
        "operating_cost_per_trip_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(route_id: str, scheduled_departure_at: str, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "scheduled_departure_at": scheduled_departure_at,
    }
    defaults.update(overrides)
    return defaults


def trip_event_payload(event_type: str, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_notice_payload(notice_type: str, headline: str, effective_from: str,
                          **overrides) -> dict:
    defaults = {
        "notice_type": notice_type,
        "headline": headline,
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return defaults


def notice_event_payload(event_type: str, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_violation_payload(permit_id: str, violation_code: str, **overrides) -> dict:
    defaults = {"permit_id": permit_id, "violation_code": violation_code}
    defaults.update(overrides)
    return defaults


def violation_event_payload(event_type: str, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_tow_event_payload(permit_id: str, violation_id: str, **overrides) -> dict:
    defaults = {"permit_id": permit_id, "violation_id": violation_id}
    defaults.update(overrides)
    return defaults


def tow_event_action_payload(event_type: str, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_billing_cycle_payload(program_id: str, period_start: str,
                                 period_end: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def close_cycle_payload(expected_billing_cycle_version: int, **overrides) -> dict:
    defaults = {"expected_billing_cycle_version": expected_billing_cycle_version}
    defaults.update(overrides)
    return defaults


def cycle_event_payload(event_type: str, **overrides) -> dict:
    defaults = {"event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_charge_entry_payload(cycle_id: str, employee_id: str, charge_type: str,
                                amount_cents: int, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "employee_id": employee_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def settle_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_peak_window_payload(lot_id: str, starts_at: str, ends_at: str,
                               **overrides) -> dict:
    defaults = {"lot_id": lot_id, "starts_at": starts_at, "ends_at": ends_at}
    defaults.update(overrides)
    return defaults
