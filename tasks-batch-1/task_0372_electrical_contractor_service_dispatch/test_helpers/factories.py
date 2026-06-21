"""Payload factories — one per entity, input fields only.

Field names are exactly as named in the PRD.
"""
import itertools

# Monotonic counter so factory-minted unique strings never collide within a run.
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": _uniq("cust") + "@x.com",
        "service_zip": "10001",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Technician",
        "license_class": "JOURNEYMAN",
        "service_zone": "100",
        "hourly_rate_cents": 10000,
        "on_call": False,
    }
    defaults.update(overrides)
    return defaults


def create_membership_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Plan",
        "tier": "BASIC",
        "monthly_fee_cents": 1000,
        "labor_discount_pct": 0.10,
        "waives_dispatch_fee": False,
        "priority_dispatch": False,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(customer_id, plan_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def create_material_sku_payload(**overrides) -> dict:
    defaults = {
        "sku_code": _uniq("SKU"),
        "description": "Test Part",
        "unit_price_cents": 1000,
        "taxable": True,
    }
    defaults.update(overrides)
    return defaults


def create_truck_stock_item_payload(technician_id, sku_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "sku_id": sku_id,
        "quantity_on_hand": 10,
        "reorder_threshold": 0,
    }
    defaults.update(overrides)
    return defaults


def create_service_job_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "scope": "OUTLET",
        "job_class": "SERVICE",
        "priority": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(job_id, expected_job_version, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "pricing_mode": "FLAT_RATE",
        "expected_job_version": expected_job_version,
        "flat_rate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(job_id, technician_id, expected_job_version,
                            window_start, window_end, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "technician_id": technician_id,
        "expected_job_version": expected_job_version,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "jurisdiction": "Test City",
        "permit_number": _uniq("PN"),
    }
    defaults.update(overrides)
    return defaults


def create_material_usage_payload(job_id, technician_id, sku_id, quantity, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "technician_id": technician_id,
        "sku_id": sku_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_callback_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "reason": "reported defect"}
    defaults.update(overrides)
    return defaults
