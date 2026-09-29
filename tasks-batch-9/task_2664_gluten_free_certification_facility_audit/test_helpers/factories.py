"""Payload factories for the gluten-free certification API.

Each factory returns a valid, fully populated payload; keyword arguments override
individual fields and ``None`` values are dropped by the client so optional
inputs can be omitted deliberately.
"""

import itertools
from typing import Any, Dict

from .types import (
    AirHandlingClass,
    AuditType,
    ChangeType,
    Decision,
    DocType,
    GlutenContainingOperations,
    LotTestType,
    MarkTier,
    NcCategory,
    NcSeverity,
    NcSourceType,
    RiskClass,
    SymptomSeverity,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short monotone suffix for names and codes that must not collide."""
    return f"{next(_counter):04d}"


def applicant_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "legal_name": "Northgate Bakehouse Ltd",
        "contact_email": "qa@northgate.example",
        "country_code": "US",
    }
    payload.update(overrides)
    return payload


def facility_payload(applicant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "applicant_id": applicant_id,
        "site_name": "Plant 4",
        "air_handling_class": AirHandlingClass.FILTERED_ZONED,
        "shared_equipment_present": True,
        "gluten_containing_operations": GlutenContainingOperations.ADJACENT_LINES,
    }
    payload.update(overrides)
    return payload


def sanitation_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "swab_ppm": 4.0,
        "method": "R5_ELISA",
        "validated_on": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def supplier_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "Prairie Mills",
        "country_code": "CA",
        "gluten_handling_disclosed": False,
    }
    payload.update(overrides)
    return payload


def ingredient_payload(applicant_id: str, supplier_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "applicant_id": applicant_id,
        "supplier_id": supplier_id,
        "name": "Brown Rice Flour",
        "risk_class": RiskClass.INHERENTLY_GF,
    }
    payload.update(overrides)
    return payload


def supplier_document_payload(
    supplier_id: str, ingredient_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "supplier_id": supplier_id,
        "ingredient_id": ingredient_id,
        "doc_type": DocType.ALLERGEN_STATEMENT,
        "issued_on": "2026-07-01T00:00:00Z",
        "expires_on": "2029-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def product_payload(applicant_id: str, facility_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "applicant_id": applicant_id,
        "facility_id": facility_id,
        "name": "Rice Sandwich Loaf",
        "sku": "RSL-001",
        "requested_mark_tier": MarkTier.STANDARD,
    }
    payload.update(overrides)
    return payload


def product_ingredient_payload(
    product_id: str, ingredient_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "ingredient_id": ingredient_id,
        "inclusion_pct": 40,
    }
    payload.update(overrides)
    return payload


def lot_test_payload(product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "lot_code": f"L-{unique_suffix()}",
        "test_type": LotTestType.SCHEDULED,
        "sample_collected_on": "2026-08-12T00:00:00Z",
        "ppm_result": 3.0,
        "lab_method": "R5_ELISA",
    }
    payload.update(overrides)
    return payload


def audit_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "facility_id": facility_id,
        "audit_type": AuditType.INITIAL,
        "onsite_start_at": "2026-08-10T08:00:00Z",
        "onsite_end_at": "2026-08-10T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def audit_close_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "shared_equipment_verified": True,
        "air_handling_verified": True,
        "sanitation_validation_reviewed": True,
    }
    payload.update(overrides)
    return payload


def nonconformance_payload(applicant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "applicant_id": applicant_id,
        "source_type": NcSourceType.AUDIT,
        "category": NcCategory.DOCUMENTATION,
        "severity": NcSeverity.MINOR,
        "description": "Allergen control record incomplete for the audited line.",
    }
    payload.update(overrides)
    return payload


def corrective_action_plan_payload(expected_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "expected_nonconformance_version": expected_version,
        "ca_plan_text": "Retrain the line crew and re-issue the allergen control record.",
    }
    payload.update(overrides)
    return payload


def certificate_payload(product_id: str, expected_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "expected_product_version": expected_version,
    }
    payload.update(overrides)
    return payload


def complaint_payload(certificate_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "certificate_id": certificate_id,
        "exposure_date": "2026-09-01T00:00:00Z",
        "symptom_severity": SymptomSeverity.MODERATE,
    }
    payload.update(overrides)
    return payload


def investigation_outcome_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "outcome": "SUBSTANTIATED",
        "outcome_evidence": "CROSS_CONTACT",
    }
    payload.update(overrides)
    return payload


def change_notification_payload(certificate_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "certificate_id": certificate_id,
        "change_type": ChangeType.FORMULA_PCT_CHANGE,
        "effective_on": "2026-12-01T00:00:00Z",
        "description": "Second sieving stage added ahead of the mixer.",
    }
    payload.update(overrides)
    return payload


def assessment_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"decision": Decision.ACCEPT, "impact_level": "LOW"}
    payload.update(overrides)
    return payload
