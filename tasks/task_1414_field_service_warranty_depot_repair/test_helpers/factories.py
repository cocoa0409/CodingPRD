"""Payload factories — one per entity, input fields only (PRD §3, §4).

Unique suffixes keep codes/serials/emails collision-free within a test.
"""
import itertools
import uuid

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}-{uuid.uuid4().hex[:8]}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Cust A",
        "email": f"{_uniq('cust')}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_product_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": _uniq("M"),
        "description": "Depot model",
        "standard_warranty_days": 365,
        "replacement_cost_cents": 100000,
        "flat_rate_repair_cents": 15000,
        "labor_rate_cents_per_minute": 200,
        "replace_threshold_pct": 60,
        "sla_turnaround_business_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(model_id, customer_id, **overrides) -> dict:
    defaults = {
        "serial_number": _uniq("SN"),
        "model_id": model_id,
        "customer_id": customer_id,
        "channel": "RETAIL",
        "purchase_date": "2026-01-01",
        "ship_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("P"),
        "name": "Power board",
        "unit_cost_cents": 5000,
        "initial_stock": 10,
    }
    defaults.update(overrides)
    return defaults


def create_failure_code_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("F-PWR"),
        "description": "No power",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_depot_bay_payload(**overrides) -> dict:
    defaults = {"bay_code": _uniq("BAY")}
    defaults.update(overrides)
    return defaults


def create_loaner_unit_payload(model_id, **overrides) -> dict:
    defaults = {
        "asset_tag": _uniq("LU"),
        "model_id": model_id,
        "condition_grade": "A",
        "deposit_value_cents": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_rma_payload(customer_id, unit_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "reported_issue": "dead",
    }
    defaults.update(overrides)
    return defaults


def diagnose_payload(labor_minutes_est=10, repairability="REPAIRABLE",
                     planned_parts=None, **overrides) -> dict:
    defaults = {
        "labor_minutes_est": labor_minutes_est,
        "repairability": repairability,
        "planned_parts": planned_parts if planned_parts is not None else [],
    }
    defaults.update(overrides)
    return defaults


def planned_part_line(part_id, quantity) -> dict:
    return {"part_id": part_id, "quantity": quantity}


def consume_part_payload(part_id, quantity, failure_code_id,
                         expected_rma_version, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "quantity": quantity,
        "failure_code_id": failure_code_id,
        "expected_rma_version": expected_rma_version,
    }
    defaults.update(overrides)
    return defaults


def quote_revision_payload(labor_minutes, parts_lines, expected_rma_version,
                           **overrides) -> dict:
    defaults = {
        "labor_minutes": labor_minutes,
        "parts_lines": parts_lines,
        "expected_rma_version": expected_rma_version,
    }
    defaults.update(overrides)
    return defaults


def loaner_reservation_payload(start_date="2026-08-01", end_date="2026-08-20",
                               **overrides) -> dict:
    defaults = {"start_date": start_date, "end_date": end_date}
    defaults.update(overrides)
    return defaults


def escalation_payload(rma_id, failure_code_id, **overrides) -> dict:
    defaults = {"rma_id": rma_id, "failure_code_id": failure_code_id}
    defaults.update(overrides)
    return defaults


def warranty_override_payload(override_coverage, reason="goodwill", **overrides) -> dict:
    defaults = {"override_coverage": override_coverage, "reason": reason}
    defaults.update(overrides)
    return defaults
