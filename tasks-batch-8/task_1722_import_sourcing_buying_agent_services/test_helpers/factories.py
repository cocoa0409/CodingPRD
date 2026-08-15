"""Payload factories — one per writable endpoint, input fields only."""
from .constants import (
    DEFAULT_DELIVERY_MONTH,
    DEFAULT_DOC_EXPIRES_AT,
    DEFAULT_DOC_ISSUED,
    DEFAULT_INSPECTION_DATE,
    DEFAULT_VALID_UNTIL,
    GRADE_A_AUDIT,
    TEST_DEFAULTS,
)


def create_buyer_payload(**overrides) -> dict:
    defaults = {"name": "Buyer One", "country_code": "US"}
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {"name": "Agent One", "agency_name": "AgencyCo"}
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {"name": "Inspector One", "region": "CN-South"}
    defaults.update(overrides)
    return defaults


def create_factory_payload(**overrides) -> dict:
    defaults = {
        "name": "Factory One",
        "country_code": "CN",
        "monthly_capacity_units": TEST_DEFAULTS["MONTHLY_CAPACITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = dict(GRADE_A_AUDIT)
    defaults.update(overrides)
    return defaults


def create_compliance_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "PRODUCT_TEST",
        "issued_date": DEFAULT_DOC_ISSUED,
        "expires_at": DEFAULT_DOC_EXPIRES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_sourcing_request_payload(**overrides) -> dict:
    defaults = {
        "title": "Goods",
        "product_category": "APPAREL",
        "target_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "quantity": TEST_DEFAULTS["ORDERED_QTY"],
        "commission_mode": "FOB",
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(**overrides) -> dict:
    defaults = {"notes": "v0"}
    defaults.update(overrides)
    return defaults


def review_sample_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE"}
    defaults.update(overrides)
    return defaults


def resubmit_sample_payload(**overrides) -> dict:
    defaults = {"notes": "resubmission"}
    defaults.update(overrides)
    return defaults


def create_quotation_payload(**overrides) -> dict:
    defaults = {
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "moq": TEST_DEFAULTS["MOQ"],
        "lead_time_days": TEST_DEFAULTS["LEAD_TIME_DAYS"],
        "valid_until": DEFAULT_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def counter_quotation_payload(unit_price_cents, expected_quotation_version, **overrides) -> dict:
    payload = {
        "unit_price_cents": unit_price_cents,
        "expected_quotation_version": expected_quotation_version,
    }
    payload.update(overrides)
    return payload


def accept_quotation_payload(ordered_qty, expected_quotation_version, **overrides) -> dict:
    payload = {
        "ordered_qty": ordered_qty,
        "delivery_month": DEFAULT_DELIVERY_MONTH,
        "expected_quotation_version": expected_quotation_version,
    }
    payload.update(overrides)
    return payload


def amend_po_payload(expected_po_version, **overrides) -> dict:
    payload = {"expected_po_version": expected_po_version}
    payload.update(overrides)
    return payload


def create_milestone_payload(**overrides) -> dict:
    defaults = {"name": "FULL", "weight_pct": 100}
    defaults.update(overrides)
    return defaults


def submit_milestone_payload(**overrides) -> dict:
    defaults = {"evidence_note": "done"}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_type": "PSI",
        "scheduled_date": DEFAULT_INSPECTION_DATE,
        "duration_days": 1,
        "lot_size": TEST_DEFAULTS["ORDERED_QTY"],
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(defects_critical=0, defects_major=0, defects_minor=0) -> dict:
    return {
        "defects_critical": defects_critical,
        "defects_major": defects_major,
        "defects_minor": defects_minor,
    }


def create_shipment_payload(**overrides) -> dict:
    defaults = {"shipped_qty": TEST_DEFAULTS["ORDERED_QTY"], "vessel_ref": "V1"}
    defaults.update(overrides)
    return defaults


def handover_payload(**overrides) -> dict:
    defaults = {"doc_refs": ["BL-1"]}
    defaults.update(overrides)
    return defaults


def create_quality_claim_payload(items=None, **overrides) -> dict:
    if items is None:
        items = [{"description": "defect", "qty_defective": 1, "unit_price_cents": 100}]
    payload = {"items": items}
    payload.update(overrides)
    return payload
