"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def building_payload(**overrides) -> dict:
    payload = {
        "name": "Tower One",
        "code": "BLD-1",
        "gross_area_sqm": TEST_DEFAULTS["GROSS_AREA_SQM"],
    }
    payload.update(overrides)
    return payload


def space_payload(**overrides) -> dict:
    payload = {
        "space_code": "S1",
        "floor": 1,
        "area_sqm": 100,
        "space_type": "OFFICE",
    }
    payload.update(overrides)
    return payload


def asset_payload(building_id, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "asset_tag": "AHU-01",
        "category": "HVAC",
        "criticality": "STANDARD",
    }
    payload.update(overrides)
    return payload


def pm_plan_payload(asset_id, **overrides) -> dict:
    payload = {
        "asset_id": asset_id,
        "interval_days": 30,
        "grace_days": 5,
        "next_due_at": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def vendor_payload(**overrides) -> dict:
    payload = {
        "name": "CoolAir",
        "trade": "HVAC",
        "hourly_rate": TEST_DEFAULTS["VENDOR_HOURLY_RATE"],
        "sla_response_minutes": TEST_DEFAULTS["SLA_RESPONSE_MINUTES"],
        "sla_resolve_minutes": TEST_DEFAULTS["SLA_RESOLVE_MINUTES"],
    }
    payload.update(overrides)
    return payload


def work_order_payload(building_id, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "wo_type": "CORRECTIVE",
        "priority": "P3",
        "estimated_labor_hours": 1,
        "estimated_parts_cost": 0,
    }
    payload.update(overrides)
    return payload


def dispatch_payload(vendor_id, expected_work_order_version, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "expected_work_order_version": expected_work_order_version,
    }
    payload.update(overrides)
    return payload


def dispatch_completion_payload(**overrides) -> dict:
    payload = {"actual_labor_hours": 1, "actual_parts_cost": 0}
    payload.update(overrides)
    return payload


def shift_payload(building_id, vendor_id, zone_space_id, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "vendor_id": vendor_id,
        "zone_space_id": zone_space_id,
        "service_type": "JANITORIAL",
        "start_at": "2026-05-06T10:00:00Z",
        "end_at": "2026-05-06T12:00:00Z",
        "planned_headcount": 2,
    }
    payload.update(overrides)
    return payload


def utility_reading_payload(building_id, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "meter_type": "ELECTRIC",
        "period_start": "2026-05-01T00:00:00Z",
        "period_end": "2026-05-31T23:59:59Z",
        "consumption_kwh": 1000,
        "cost": 100.00,
    }
    payload.update(overrides)
    return payload


def lease_payload(building_id, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "tenant_name": "Acme",
        "base_rate_per_sqm_month": TEST_DEFAULTS["BASE_RATE_PER_SQM_MONTH"],
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2027-04-30T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def allocation_payload(space_id, **overrides) -> dict:
    payload = {
        "space_id": space_id,
        "share_pct": 100,
        "effective_from": "2026-05-01T00:00:00Z",
        "effective_to": "2027-04-30T23:59:59Z",
    }
    payload.update(overrides)
    return payload


def statement_payload(period_start, period_end, expected_lease_version, **overrides) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def capital_project_payload(building_id, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "title": "Lobby refit",
        "base_cost": 1000.00,
    }
    payload.update(overrides)
    return payload
