"""Payload factories — one per entity, input fields only. Callers supply foreign keys."""


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Ada Ember",
        "service_address": "1 Hearth Ln",
        "phone": "555-0100",
    }
    payload.update(overrides)
    return payload


def create_chimney_payload(**overrides) -> dict:
    payload = {
        "chimney_type": "MASONRY",
        "appliance_type": "WOOD_STOVE",
        "flue_count": 1,
    }
    payload.update(overrides)
    return payload


def create_technician_payload(**overrides) -> dict:
    payload = {
        "name": "Tom Soot",
        "cert_level": "CSIA_ADVANCED",
    }
    payload.update(overrides)
    return payload


def create_route_day_payload(**overrides) -> dict:
    payload = {
        "service_date": "2026-05-04",
        "window_start_ts": 1746342000,
        "window_end_ts": 1746374400,
        "capacity_minutes": 300,
    }
    payload.update(overrides)
    return payload


def create_service_job_payload(**overrides) -> dict:
    payload = {
        "inspection_level": 1,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(**overrides) -> dict:
    payload = {
        "start_ts": 1746345600,
        "end_ts": 1746351000,
    }
    payload.update(overrides)
    return payload


def create_sweep_log_payload(**overrides) -> dict:
    payload = {
        "measured_creosote_class": 1,
    }
    payload.update(overrides)
    return payload


def create_safety_check_payload(**overrides) -> dict:
    payload = {
        "co_ppm": 3,
        "draft_ok": True,
    }
    payload.update(overrides)
    return payload


def create_repair_order_payload(**overrides) -> dict:
    payload = {
        "repair_type": "CAP",
        "quoted_cost_cents": 9000,
    }
    payload.update(overrides)
    return payload


def create_warranty_payload(**overrides) -> dict:
    payload = {
        "coverage_type": "LABOR_ONLY",
        "term_months": 12,
    }
    payload.update(overrides)
    return payload


def create_reminder_schedule_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload
