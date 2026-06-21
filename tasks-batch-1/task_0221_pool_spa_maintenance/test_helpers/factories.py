"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Owner",
    "POOL_LABEL": "Backyard pool",
    "WATER_TYPE": "CHLORINE",
    "VOLUME_GALLONS": 20000,
    "PER_VISIT_RATE_CENTS": 8000,
    "TECHNICIAN_ID": "tech-1",
    "SERVICE_DATE": "2026-06-10",
    "WINDOW_START_MINUTE": 480,
    "WINDOW_END_MINUTE": 1020,
    "CAPACITY_VISITS": 5,
    "SLOT_START_MINUTE": 540,
    "SLOT_END_MINUTE": 600,
}

_email_counter = [0]


def unique_email(prefix: str = "owner") -> str:
    """Generate a process-unique email so the unique-email constraint never
    collides across factory-built customers within a single test."""
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": unique_email(),
    }
    payload.update(overrides)
    return payload


def create_pool_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "label": DEFAULTS["POOL_LABEL"],
        "water_type": DEFAULTS["WATER_TYPE"],
        "volume_gallons": DEFAULTS["VOLUME_GALLONS"],
    }
    payload.update(overrides)
    return payload


def create_service_plan_payload(pool_id: str, **overrides) -> dict:
    payload = {
        "pool_id": pool_id,
        "plan_type": "ONE_TIME",
        "frequency": "NONE",
        "per_visit_rate_cents": DEFAULTS["PER_VISIT_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_route_payload(**overrides) -> dict:
    payload = {
        "technician_id": DEFAULTS["TECHNICIAN_ID"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "window_start_minute": DEFAULTS["WINDOW_START_MINUTE"],
        "window_end_minute": DEFAULTS["WINDOW_END_MINUTE"],
        "capacity_visits": DEFAULTS["CAPACITY_VISITS"],
    }
    payload.update(overrides)
    return payload


def create_visit_payload(pool_id: str, plan_id: str, route_id: str, **overrides) -> dict:
    payload = {
        "pool_id": pool_id,
        "plan_id": plan_id,
        "route_id": route_id,
        "slot_start_minute": DEFAULTS["SLOT_START_MINUTE"],
        "slot_end_minute": DEFAULTS["SLOT_END_MINUTE"],
    }
    payload.update(overrides)
    return payload


def create_reading_payload(**overrides) -> dict:
    payload = {
        "free_chlorine_ppm": 1.0,
        "ph": 7.5,
        "total_alkalinity_ppm": 80.0,
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(pool_id: str, **overrides) -> dict:
    payload = {
        "pool_id": pool_id,
        "component": "PUMP",
        "severity": "MAJOR",
    }
    payload.update(overrides)
    return payload


def diagnose_payload(quoted_parts_cents: int = 5000, labor_minutes: int = 90, **overrides) -> dict:
    payload = {
        "quoted_parts_cents": quoted_parts_cents,
        "labor_minutes": labor_minutes,
    }
    payload.update(overrides)
    return payload


def create_seasonal_event_payload(event_type: str = "OPEN", **overrides) -> dict:
    payload = {
        "event_type": event_type,
        "effective_date": DEFAULTS["SERVICE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(pool_id: str, **overrides) -> dict:
    payload = {"pool_id": pool_id}
    payload.update(overrides)
    return payload


def complete_payload(green_pool: bool = False, **overrides) -> dict:
    payload = {"green_pool": green_pool}
    payload.update(overrides)
    return payload


def skip_payload(skip_reason: str = "WEATHER", **overrides) -> dict:
    payload = {"skip_reason": skip_reason}
    payload.update(overrides)
    return payload


def visit_log_payload(expected_pool_version: int, note: str = "field check", **overrides) -> dict:
    payload = {
        "expected_pool_version": expected_pool_version,
        "note": note,
    }
    payload.update(overrides)
    return payload
