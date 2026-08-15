"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_CEILING_CENTS,
    DEFAULT_COMMITTED_RATE,
    DEFAULT_PRICING_TIERS,
    DEFAULT_REBATE_TIERS,
)

_counter = {"n": 0}


def _next(tag: str) -> str:
    _counter["n"] += 1
    return f"{tag}-{_counter['n']:04d}"


def create_lta_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "ACME AEROSPACE",
        "ceiling_cents": DEFAULT_CEILING_CENTS,
        "pricing_tiers": [dict(t) for t in DEFAULT_PRICING_TIERS],
        "committed_monthly_rate_units": DEFAULT_COMMITTED_RATE,
        "escalation_pct_per_year": 0.05,
        "award_year": 2026,
        "rebate_tiers": [dict(t) for t in DEFAULT_REBATE_TIERS],
    }
    defaults.update(overrides)
    return defaults


def create_po_payload(lta_id, expected_lta_version, **overrides) -> dict:
    defaults = {
        "lta_id": lta_id,
        "po_number": _next("PO"),
        "part_number": _next("P"),
        "part_revision": "A",
        "quantity": 10,
        "flowdown_clauses": ["AS9100D_QMS"],
        "requires_special_process": False,
        "delivery_year": 2026,
        "expected_lta_version": expected_lta_version,
    }
    defaults.update(overrides)
    return defaults


def create_fai_payload(**overrides) -> dict:
    defaults = {
        "part_number": _next("P"),
        "part_revision": "A",
        "fai_type": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_characteristic_payload(**overrides) -> dict:
    defaults = {
        "balloon_number": 1,
        "nominal": 10.0,
        "tolerance_plus": 0.1,
        "tolerance_minus": 0.1,
        "is_key_characteristic": False,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(po_id, **overrides) -> dict:
    defaults = {
        "po_id": po_id,
        "quantity": 1,
        "special_processes_required": [],
    }
    defaults.update(overrides)
    return defaults


def create_serial_batch_payload(material_cert_id, **overrides) -> dict:
    defaults = {
        "material_cert_id": material_cert_id,
        "count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_spc_measurement_payload(characteristic_id, **overrides) -> dict:
    defaults = {
        "characteristic_id": characteristic_id,
        "measured_value": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_material_cert_payload(source_id, **overrides) -> dict:
    defaults = {
        "source_id": source_id,
        "heat_number": _next("H"),
        "material_spec": "AMS 5643",
        "quantity_received": 10,
    }
    defaults.update(overrides)
    return defaults


def create_source_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": _next("S"),
        "approval_scope": "RAW_MATERIAL",
        "counterfeit_risk_rating": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_process_approval_payload(source_id, **overrides) -> dict:
    defaults = {
        "source_id": source_id,
        "process_code": "HEAT_TREAT",
        "valid_from": "2026-01-01",
        "valid_to": "2027-01-01",
        "cert_reference": _next("NADCAP"),
    }
    defaults.update(overrides)
    return defaults


def create_ncr_payload(wo_id, **overrides) -> dict:
    defaults = {
        "wo_id": wo_id,
        "defect_code": "DIM_OVERSIZE",
        "description": "dimension out of tolerance",
        "quantity_affected": 1,
        "affected_serial_ids": [],
        "detected_post_shipment": False,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_payload(**overrides) -> dict:
    defaults = {
        "disposition": "REWORK",
        "rework_hours_per_unit": 0.5,
        "material_cost_per_unit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_delegation_payload(po_id, inspector_user_id, **overrides) -> dict:
    defaults = {
        "po_id": po_id,
        "inspector_user_id": inspector_user_id,
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults
