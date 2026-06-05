"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only source:input fields are emitted; computed and
system fields (status, priority_score, reserved_qty, etc.) are never sent.
"""


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "maintenance_budget_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_spare_part_payload(**overrides) -> dict:
    defaults = {
        "sku": "TEST-SKU-1",
        "name": "Test Part",
        "on_hand_qty": 10,
        "unit_cost_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Technician",
        "skill_level": "SENIOR",
        "weekly_capacity_hours": 40,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "name": "Test Asset",
        "acquisition_cost_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_pm_schedule_payload(trigger_type, **overrides) -> dict:
    defaults = {
        "trigger_type": trigger_type,
        "estimated_labor_hours": 2,
        "severity": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(value, reading_at, **overrides) -> dict:
    defaults = {"value": value, "reading_at": reading_at}
    defaults.update(overrides)
    return defaults


def create_work_order_payload(asset_id, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "wo_type": "CORRECTIVE",
        "severity": "ROUTINE",
        "estimated_labor_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(spare_part_id, qty, expected_spare_part_version, **overrides) -> dict:
    defaults = {
        "spare_part_id": spare_part_id,
        "qty": qty,
        "expected_spare_part_version": expected_spare_part_version,
    }
    defaults.update(overrides)
    return defaults


def create_downtime_event_payload(reason_code, started_at, **overrides) -> dict:
    defaults = {"reason_code": reason_code, "started_at": started_at}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(asset_id, work_order_id, claim_type, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "work_order_id": work_order_id,
        "claim_type": claim_type,
    }
    defaults.update(overrides)
    return defaults
