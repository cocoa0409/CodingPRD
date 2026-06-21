"""Payload factories — one per entity, input fields only.

Each factory returns sensible defaults that tests override via **overrides.
Only `source: input` fields appear here; system/computed fields are server-minted.
"""


def membership_plan_payload(**overrides) -> dict:
    defaults = {
        "tier_code": "NONE",
        "name": "Test Plan",
        "labor_discount_pct": 0,
        "waives_trip_fee": False,
        "annual_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def flat_rate_item_payload(**overrides) -> dict:
    defaults = {
        "code": "FR-TEST",
        "category": "LEAK",
        "base_price_cents": 10000,
        "skill_required": 1,
    }
    defaults.update(overrides)
    return defaults


def part_payload(**overrides) -> dict:
    defaults = {
        "sku": "P-TEST",
        "name": "Test Part",
        "list_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Customer",
        "service_address": "1 Test St",
        "credit_limit_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Technician",
        "skill_level": 3,
    }
    defaults.update(overrides)
    return defaults


def inspector_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Inspector",
        "jurisdiction": "CITY00",
        "max_daily_inspections": 4,
    }
    defaults.update(overrides)
    return defaults


def truck_stock_payload(technician_id, part_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "part_id": part_id,
        "quantity": 10,
        "reorder_point": 2,
    }
    defaults.update(overrides)
    return defaults


def service_job_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "category": "LEAK",
    }
    defaults.update(overrides)
    return defaults


def dispatch_assignment_payload(job_id, technician_id, expected_job_version,
                                window_start, window_end, eta, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "technician_id": technician_id,
        "window_start": window_start,
        "window_end": window_end,
        "eta": eta,
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def estimate_payload(expected_job_version, **overrides) -> dict:
    defaults = {
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def flat_rate_line_payload(flat_rate_item_id, quantity=1, **overrides) -> dict:
    defaults = {
        "line_type": "FLAT_RATE",
        "flat_rate_item_id": flat_rate_item_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def part_line_payload(part_id, quantity=1, **overrides) -> dict:
    defaults = {
        "line_type": "PART",
        "part_id": part_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def inspection_payload(inspector_id, scheduled_date, **overrides) -> dict:
    defaults = {
        "inspector_id": inspector_id,
        "scheduled_date": scheduled_date,
    }
    defaults.update(overrides)
    return defaults


def callback_payload(original_job_id, reason="Test callback reason", **overrides) -> dict:
    defaults = {
        "original_job_id": original_job_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
