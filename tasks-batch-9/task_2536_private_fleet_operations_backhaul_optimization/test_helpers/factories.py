"""Payload factories - one per entity, input fields only."""

DEFAULTS = {
    "REGION": "MIDWEST",
    "CASES_PER_HOUR": 600,
    "DOCK_OPEN_MINUTE": 0,
    "DOCK_CLOSE_MINUTE": 1439,
    "DOCK_COUNT": 2,
    "TRAILER_CAPACITY_CASES": 1800,
    "INSPECTION_DUE_AT": "2026-12-01T00:00:00Z",
    "SENIORITY_DATE": "2019-03-01",
}


def create_store_payload(**overrides) -> dict:
    payload = {
        "store_code": "S-1001",
        "region_code": DEFAULTS["REGION"],
        "dock_count": DEFAULTS["DOCK_COUNT"],
        "cases_per_hour_unload_rate": DEFAULTS["CASES_PER_HOUR"],
        "dock_open_minute": DEFAULTS["DOCK_OPEN_MINUTE"],
        "dock_close_minute": DEFAULTS["DOCK_CLOSE_MINUTE"],
    }
    payload.update(overrides)
    return payload


def create_domicile_payload(**overrides) -> dict:
    payload = {
        "domicile_code": "DOM-BASE",
        "region_code": DEFAULTS["REGION"],
        "tractor_capacity": 20,
        "driver_headcount_target": 10,
        "fixed_ownership_cents_per_day": 10000,
        "overhead_cents_per_day": 3000,
        "dedicated_rate_cents_per_mile": 280,
        "dedicated_rate_cents_per_case": 205,
    }
    payload.update(overrides)
    return payload


def create_pay_plan_payload(**overrides) -> dict:
    payload = {
        "plan_code": "MILE-C",
        "mileage_cents_per_mile": 80,
        "stop_cents_per_stop": 2000,
        "drop_hook_cents": 1400,
        "hourly_cents_per_minute": 40,
        "minimum_daily_cents": 20000,
        "backhaul_bonus_pct": 0.04,
    }
    payload.update(overrides)
    return payload


def create_driver_payload(domicile_id: str, pay_plan_id: str, **overrides) -> dict:
    payload = {
        "driver_code": "D-BASE",
        "domicile_id": domicile_id,
        "pay_plan_id": pay_plan_id,
        "seniority_date": DEFAULTS["SENIORITY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_tractor_payload(domicile_id: str, **overrides) -> dict:
    payload = {
        "unit_code": "TR-BASE",
        "domicile_id": domicile_id,
        "odometer_miles": 50000,
        "pm_interval_miles": 25000,
        "pm_last_service_odometer": 40000,
    }
    payload.update(overrides)
    return payload


def create_trailer_payload(domicile_id: str, **overrides) -> dict:
    payload = {
        "trailer_code": "TL-BASE",
        "domicile_id": domicile_id,
        "trailer_type": "DRY_VAN",
        "capacity_cases": DEFAULTS["TRAILER_CAPACITY_CASES"],
        "inspection_due_at": DEFAULTS["INSPECTION_DUE_AT"],
    }
    payload.update(overrides)
    return payload


def create_order_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "cases": 600,
        "weight_lbs": 13200,
        "requested_window_start": "2026-08-20T06:00:00Z",
        "requested_window_end": "2026-08-20T18:00:00Z",
        "temperature_mode": "DRY",
        "priority": 1,
    }
    payload.update(overrides)
    return payload


def create_trip_payload(domicile_id: str, **overrides) -> dict:
    payload = {
        "trip_code": "TRIP-BASE",
        "domicile_id": domicile_id,
        "planned_start_at": "2026-08-20T06:00:00Z",
    }
    payload.update(overrides)
    return payload


def delivery_stop_payload(
    sequence: int,
    store_id: str,
    replenishment_order_id: str,
    scheduled_arrival_at: str,
    scheduled_departure_at: str,
    drive_minutes_from_prev: int,
    miles_from_prev: int,
    cases: int,
    segment_loaded: bool = True,
    **overrides,
) -> dict:
    payload = {
        "sequence": sequence,
        "stop_type": "DELIVERY",
        "store_id": store_id,
        "replenishment_order_id": replenishment_order_id,
        "scheduled_arrival_at": scheduled_arrival_at,
        "scheduled_departure_at": scheduled_departure_at,
        "drive_minutes_from_prev": drive_minutes_from_prev,
        "miles_from_prev": miles_from_prev,
        "segment_loaded": segment_loaded,
        "cases": cases,
    }
    payload.update(overrides)
    return payload


def non_delivery_stop_payload(
    sequence: int,
    stop_type: str,
    scheduled_arrival_at: str,
    scheduled_departure_at: str,
    drive_minutes_from_prev: int,
    miles_from_prev: int,
    segment_loaded: bool = False,
    **overrides,
) -> dict:
    """Payload for a VENDOR_PICKUP, DROP_OFF or FUEL stop: no store or order ref."""
    payload = {
        "sequence": sequence,
        "stop_type": stop_type,
        "scheduled_arrival_at": scheduled_arrival_at,
        "scheduled_departure_at": scheduled_departure_at,
        "drive_minutes_from_prev": drive_minutes_from_prev,
        "miles_from_prev": miles_from_prev,
        "segment_loaded": segment_loaded,
    }
    payload.update(overrides)
    return payload


def create_backhaul_offer_payload(dest_store_id: str, **overrides) -> dict:
    payload = {
        "origin_kind": "VENDOR_PICKUP",
        "shipper_name": "Prairie Foods",
        "origin_region_code": DEFAULTS["REGION"],
        "dest_store_id": dest_store_id,
        "revenue_cents": 60000,
        "cases": 500,
        "weight_lbs": 11000,
        "deadhead_miles": 40,
        "loaded_miles": 160,
        "temperature_mode": "DRY",
        "pickup_window_start": "2026-08-20T12:00:00Z",
        "pickup_window_end": "2026-08-20T20:00:00Z",
        "offer_expires_at": "2026-08-19T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(**overrides) -> dict:
    payload = {
        "asset_kind": "TRACTOR",
        "service_type": "REPAIR",
        "window_start_at": "2026-09-15T08:00:00Z",
        "window_end_at": "2026-09-15T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_route_posting_payload(domicile_id: str, **overrides) -> dict:
    payload = {
        "route_code": "P-BASE",
        "domicile_id": domicile_id,
        "weekly_miles": 2400,
        "weekly_stops": 18,
        "start_effective_date": "2026-10-01",
        "bid_close_at": "2026-09-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_telematics_event_payload(driver_id: str, event_type: str, severity: int,
                                    occurred_at: str, **overrides) -> dict:
    payload = {
        "driver_id": driver_id,
        "event_type": event_type,
        "severity": severity,
        "occurred_at": occurred_at,
    }
    payload.update(overrides)
    return payload
