"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_location_payload(**overrides) -> dict:
    n = _uniq()
    code = overrides.pop("code", None)
    if code is None:
        # 3-letter uppercase code; derived from a rolling counter for uniqueness.
        code = "L" + f"{n:02d}"[-2:]
    defaults = {
        "code": code,
        "name": "Test Branch",
        "one_way_drop_fee_cents": 4500,
        "young_driver_surcharge_per_day_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_class_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "code": f"CLS{n}",
        "tier_rank": 1,
        "daily_rate_cents": 5000,
        "weekly_rate_cents": 28000,
        "included_miles_per_day": 200,
        "overage_per_mile_cents": 25,
        "ldw_per_day_cents": 1500,
        "pai_per_day_cents": 800,
    }
    defaults.update(overrides)
    return defaults


def create_rate_plan_payload(location_id, class_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "class_id": class_id,
        "daily_rate_cents": 6000,
        "weekly_rate_cents": 34000,
        "effective_from": "2026-01-01T00:00:00Z",
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(location_id, class_id, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "location_id": location_id,
        "class_id": class_id,
        "plate": f"PLT-{n:04d}",
        "odometer_miles": 1000,
        "fuel_level_eighths": 8,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "email": f"m{n}@x.com",
        "full_name": "Test Member",
        "driver_age": 30,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(member_id, pickup_location_id, dropoff_location_id,
                               class_id, pickup_at, dropoff_at, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "pickup_location_id": pickup_location_id,
        "dropoff_location_id": dropoff_location_id,
        "class_id": class_id,
        "pickup_at": pickup_at,
        "dropoff_at": dropoff_at,
        "ldw_selected": False,
        "pai_selected": False,
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(reservation_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "vehicle_id": vehicle_id,
        "odometer_out": 1000,
        "fuel_out_eighths": 8,
    }
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(agreement_id, severity, assessed_damage_cents, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "severity": severity,
        "assessed_damage_cents": assessed_damage_cents,
    }
    defaults.update(overrides)
    return defaults
