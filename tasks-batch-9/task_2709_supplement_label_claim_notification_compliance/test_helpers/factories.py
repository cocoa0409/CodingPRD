"""Payload factories.

Each factory returns a valid request body that the caller may override field by
field with ``**overrides``. Numeric money-like values (kilogram masses, assay
percentages, scores) are emitted as JSON numbers, never as strings.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CLAIM_TYPE_STRUCTURE_FUNCTION,
    DECISION_ACCEPT,
    DECISION_QUALIFY,
    IDENTITY_METHOD_HPLC,
    OUTCOME_HOSPITALIZATION,
    PANEL_FORMAT_STANDARD,
    REPORTER_CONSUMER,
    RESPONSE_ACKNOWLEDGE,
    STUDY_RCT_HUMAN,
    WARNING_PEDIATRIC,
)

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def ingredient_payload(**overrides: Any) -> Dict[str, Any]:
    """A grandfatherable VITAMIN monograph (PRD §3.1)."""
    n = _next()
    payload: Dict[str, Any] = {
        "ingredient_name": f"Ascorbic Acid {n}",
        "ingredient_class": "VITAMIN",
        "pre_dshea_marketed": True,
        "chemical_alteration": False,
        "daily_intake_mg": 500,
        "rdi_mg": 90,
    }
    payload.update(overrides)
    return payload


def ndi_ingredient_payload(**overrides: Any) -> Dict[str, Any]:
    """A monograph whose determination must land on ``NDI_REQUIRED`` (PRD §3.1)."""
    n = _next()
    payload: Dict[str, Any] = {
        "ingredient_name": f"Fermented Beta-Glucan XR {n}",
        "ingredient_class": "BOTANICAL",
        "pre_dshea_marketed": False,
        "chemical_alteration": True,
        "daily_intake_mg": 250,
    }
    payload.update(overrides)
    return payload


def product_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "brand_name": "NutraCore",
        "product_name": f"C-500 Lot {n}",
        "net_quantity_g": 120,
        "servings_per_container": 60,
    }
    payload.update(overrides)
    return payload


def product_ingredient_payload(
    product_id: str, ingredient_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "ingredient_id": ingredient_id,
        "amount_per_serving_mg": 500,
        "panel_position": 1,
    }
    payload.update(overrides)
    return payload


def ndi_notification_payload(ingredient_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "ingredient_id": ingredient_id,
        "submitter_reference": f"NDI-2026-{n:04d}",
        "safety_narrative": "History of safe use at the intended daily intake.",
    }
    payload.update(overrides)
    return payload


def agency_response_payload(
    response: str = RESPONSE_ACKNOWLEDGE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response": response}
    payload.update(overrides)
    return payload


def claim_payload(product_id: str, ingredient_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "ingredient_id": ingredient_id,
        "claim_text": f"Supports immune function {n}",
        "claim_type": CLAIM_TYPE_STRUCTURE_FUNCTION,
    }
    payload.update(overrides)
    return payload


def dossier_payload(
    claim_id: str, expected_claim_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "expected_claim_version": expected_claim_version,
        "dossier_summary": "Totality of the evidence relied on for this claim.",
    }
    payload.update(overrides)
    return payload


def evidence_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "study_type": STUDY_RCT_HUMAN,
        "subject_count": 200,
        "dose_match": True,
        "peer_reviewed": True,
        "citation": f"J Nutr Sci 2025;{n}:11-20",
    }
    payload.update(overrides)
    return payload


def review_payload(decision: str = DECISION_ACCEPT, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def label_panel_payload(
    product_id: str,
    expected_product_version: int,
    declared_warning_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "expected_product_version": expected_product_version,
        "panel_format": PANEL_FORMAT_STANDARD,
        "serving_size_text": "1 capsule",
        "serving_weight_g": 2,
        "servings_per_container_declared": 60,
        "effective_from": "2026-09-01",
        "effective_until": "2027-08-31",
        "declared_warning_codes": (
            list(declared_warning_codes)
            if declared_warning_codes is not None
            else [WARNING_PEDIATRIC]
        ),
    }
    payload.update(overrides)
    return payload


def adverse_event_payload(product_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "reporter_type": REPORTER_CONSUMER,
        "received_date": "2026-08-03",
        "narrative": "Admitted overnight for observation after three days of use.",
        "outcome_codes": [OUTCOME_HOSPITALIZATION],
    }
    payload.update(overrides)
    return payload


def supplier_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "supplier_name": f"Hebei Botanicals {n}",
        "country_code": "CN",
        "audit_score": 85,
    }
    payload.update(overrides)
    return payload


def qualification_decision_payload(
    decision: str = DECISION_QUALIFY, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def ingredient_lot_payload(
    supplier_id: str, ingredient_id: str, **overrides: Any
) -> Dict[str, Any]:
    n = _next()
    payload: Dict[str, Any] = {
        "supplier_id": supplier_id,
        "ingredient_id": ingredient_id,
        "lot_code": f"L-2026-{n:04d}",
        "quantity_kg": 100,
    }
    payload.update(overrides)
    return payload


def coa_payload(lot_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lot_id": lot_id,
        "lab_name": "Argus Labs",
        "identity_test_method": IDENTITY_METHOD_HPLC,
        "identity_match": True,
        "assay_percent_of_label": 99.5,
        "heavy_metals_pass": True,
        "microbial_pass": True,
    }
    payload.update(overrides)
    return payload


def start_marketing_payload(
    marketing_start_date: str = "2026-09-10", **overrides: Any
) -> Dict[str, Any]:
    """The launch request carries the declared launch date (PRD §3.6)."""
    payload: Dict[str, Any] = {"marketing_start_date": marketing_start_date}
    payload.update(overrides)
    return payload


def notify_fda_payload(
    submission_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """The claim notification carries the agency's receipt identifier (PRD §3.6)."""
    n = _next()
    payload: Dict[str, Any] = {
        "submission_reference": submission_reference or f"FDA-SF-2026-{n:05d}"
    }
    payload.update(overrides)
    return payload


def aer_submission_payload(
    submission_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """The serious-report filing carries the agency's reference (PRD §3.8)."""
    n = _next()
    payload: Dict[str, Any] = {
        "submission_reference": submission_reference or f"FDA-AER-2026-{n:05d}"
    }
    payload.update(overrides)
    return payload


def triage_payload(serious_override: Optional[bool] = None, **overrides: Any) -> Dict[str, Any]:
    """Triage may force the serious branch with ``serious_override`` (PRD §3.8)."""
    payload: Dict[str, Any] = {}
    if serious_override is not None:
        payload["serious_override"] = serious_override
    payload.update(overrides)
    return payload


def recall_payload(recall_reason: str = "Downstream stability failure", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"recall_reason": recall_reason}
    payload.update(overrides)
    return payload


def withdrawal_payload(
    withdrawal_reason: str = "Claim retired from the marketing plan", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload
