"""Payload factories — one per entity, input fields only.

PRD-exact field names are used here. The server fills in system fields.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_PLATFORM_NAME,
    DEFAULT_JURISDICTION,
    DEFAULT_REGULATORY_ENDPOINT,
    FAR_FUTURE_ISO,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _short() -> str:
    return uuid.uuid4().hex[:8]


def unique_ndc() -> str:
    """Return an NDC matching ^\\d{4,5}-\\d{3,4}-\\d{1,2}$ (PRD §2.9).

    Uses a 5-digit + 4-digit + 2-digit shape, with a uniqueness guarantee
    from the process-global counter so collisions across tests are avoided.
    """
    n = uuid.uuid4().int
    a = n % 100000              # 0..99999 → up to 5 digits
    b = (n // 100000) % 10000   # 0..9999 → exactly 4 digits via :04d
    c = (n // 1000000000) % 99  # 0..98 → +1 → 1..99 → up to 2 digits
    return f"{a:05d}-{b:04d}-{c + 1:02d}"


def unique_id_doc() -> str:
    return f"ID-{_short().upper()}"


def unique_license_no(prefix: str = "LIC") -> str:
    return f"{prefix}-{_short().upper()}"


def unique_certificate_no(prefix: str = "CERT") -> str:
    return f"{prefix}-{_short().upper()}"


# -----------------------------------------------------------------------
# Platform / Vendor / Pharmacist / Customer
# -----------------------------------------------------------------------

def create_platform_payload(**overrides) -> Dict[str, Any]:
    """PRD §2.4: name, jurisdiction, regulatory_endpoint."""
    payload: Dict[str, Any] = {
        "name": f"{DEFAULT_PLATFORM_NAME} {_short()}",
        "jurisdiction": DEFAULT_JURISDICTION,
        "regulatory_endpoint": DEFAULT_REGULATORY_ENDPOINT,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: name, business_license_no, business_license_expires_at,
    drug_operation_permit_no, drug_operation_permit_expires_at.
    """
    payload: Dict[str, Any] = {
        "name": f"Vendor {_short()}",
        "business_license_no": unique_license_no("BL"),
        "business_license_expires_at": FAR_FUTURE_ISO,
        "drug_operation_permit_no": unique_license_no("DOP"),
        "drug_operation_permit_expires_at": FAR_FUTURE_ISO,
    }
    payload.update(overrides)
    return payload


def create_pharmacist_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3: full_name, certificate_no, certificate_expires_at,
    optional courier_qualified.
    """
    payload: Dict[str, Any] = {
        "full_name": f"Pharmacist {_short()}",
        "certificate_no": unique_certificate_no(),
        "certificate_expires_at": FAR_FUTURE_ISO,
    }
    # courier_qualified is optional; default false on server side per §3.3
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> Dict[str, Any]:
    """PRD §2.10: real_name, id_document_no, special_population_flags,
    real_name_verified (default false).
    """
    payload: Dict[str, Any] = {
        "real_name": f"Customer {_short()}",
        "id_document_no": unique_id_doc(),
        "special_population_flags": [],
        "real_name_verified": True,
    }
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Drug
# -----------------------------------------------------------------------

def create_drug_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    """PRD §2.9: ndc, name, classification, control_category, cold_chain_required,
    indications, contraindications, per_order_qty_cap (>=1), per_period_qty_cap, vendor_id.
    """
    payload: Dict[str, Any] = {
        "ndc": unique_ndc(),
        "name": f"Drug {_short()}",
        "classification": "OTC",
        "control_category": "NONE",
        "cold_chain_required": False,
        "indications": ["headache"],
        "contraindications": [],
        "per_order_qty_cap": 10,
        "per_period_qty_cap": 50,
        "vendor_id": vendor_id,
    }
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Prescription
# -----------------------------------------------------------------------

def create_prescription_payload(customer_id: str,
                                 drug_items: List[Dict[str, Any]],
                                 **overrides) -> Dict[str, Any]:
    """PRD §3.4: customer_id, prescriber_name, prescriber_license_no,
    image_url, issued_at, validity_days, drug_items.
    """
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "prescriber_name": f"Dr {_short()}",
        "prescriber_license_no": unique_license_no("PRESC"),
        "image_url": f"https://example.com/rx/{_short()}.jpg",
        # issued_at must be supplied per the test's clock context
        "issued_at": "2025-01-01T00:00:00.000Z",
        "validity_days": 30,
        "drug_items": drug_items,
    }
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Purchase limit rule
# -----------------------------------------------------------------------

def create_purchase_limit_rule_payload(control_category: str,
                                        window_days: int,
                                        max_units_per_window: int,
                                        blocks_special_populations: Optional[List[str]] = None,
                                        **overrides) -> Dict[str, Any]:
    """PRD §3.5: control_category, window_days, max_units_per_window,
    blocks_special_populations.
    """
    payload: Dict[str, Any] = {
        "control_category": control_category,
        "window_days": window_days,
        "max_units_per_window": max_units_per_window,
        "blocks_special_populations": blocks_special_populations or [],
    }
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Order
# -----------------------------------------------------------------------

def create_order_payload(customer_id: str,
                          items: List[Dict[str, Any]],
                          prescription_id: Optional[str] = None,
                          **overrides) -> Dict[str, Any]:
    """PRD §3.5: customer_id, optional prescription_id, items array of
    {drug_id, qty, unit_price_cents}.
    """
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "items": items,
    }
    if prescription_id is not None:
        payload["prescription_id"] = prescription_id
    payload.update(overrides)
    return payload


def order_item(drug_id: str, qty: int = 1, unit_price_cents: int = 1000) -> Dict[str, Any]:
    """PRD §2.12: integer cents, integer qty."""
    return {
        "drug_id": drug_id,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
    }


def prescription_item(drug_id: str, qty: int = 1) -> Dict[str, Any]:
    """Element of Prescription.drug_items per PRD §3.4."""
    return {"drug_id": drug_id, "qty": qty}


# -----------------------------------------------------------------------
# Pharmacist Review actions
# -----------------------------------------------------------------------

def open_pharmacist_review_payload(assigned_pharmacist_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.6: payload carries assigned_pharmacist_id."""
    payload: Dict[str, Any] = {"assigned_pharmacist_id": assigned_pharmacist_id}
    payload.update(overrides)
    return payload


def approve_review_payload(interaction_check_passed: bool = True,
                            dosage_rationality_passed: bool = True,
                            decision_notes: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    """PRD §3.6 approve: interaction_check_passed and dosage_rationality_passed
    must be true; decision_notes is optional.
    """
    payload: Dict[str, Any] = {
        "interaction_check_passed": interaction_check_passed,
        "dosage_rationality_passed": dosage_rationality_passed,
    }
    if decision_notes is not None:
        payload["decision_notes"] = decision_notes
    payload.update(overrides)
    return payload


def reject_review_payload(decision_notes: str = "Insufficient justification provided",
                           **overrides) -> Dict[str, Any]:
    """PRD §3.6 reject: decision_notes string length >= 10."""
    payload: Dict[str, Any] = {"decision_notes": decision_notes}
    payload.update(overrides)
    return payload


def request_change_payload(decision_notes: str = "Need clarification on dose schedule",
                            **overrides) -> Dict[str, Any]:
    """PRD §3.6 request-change: decision_notes string length >= 10."""
    payload: Dict[str, Any] = {"decision_notes": decision_notes}
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Cold Chain Shipment
# -----------------------------------------------------------------------

def create_shipment_payload(order_id: str, courier_pharmacist_id: str,
                              device_id: Optional[str] = None,
                              **overrides) -> Dict[str, Any]:
    """PRD §3.7: order_id, courier_pharmacist_id, device_id."""
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "courier_pharmacist_id": courier_pharmacist_id,
        "device_id": device_id or f"DEV-{_short()}",
    }
    payload.update(overrides)
    return payload


def reading_payload(recorded_at: str, celsius_tenths: int) -> Dict[str, Any]:
    """PRD §3.7: temperature_readings element {recorded_at, celsius_tenths}."""
    return {"recorded_at": recorded_at, "celsius_tenths": celsius_tenths}


# -----------------------------------------------------------------------
# Adverse Reaction Report
# -----------------------------------------------------------------------

def create_adr_payload(drug_id: str, customer_id: str,
                        reporter_kind: str = "PATIENT",
                        severity: str = "NON_SERIOUS",
                        order_id: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    """PRD §3.8: drug_id, customer_id, optional order_id, reporter_kind, severity."""
    payload: Dict[str, Any] = {
        "drug_id": drug_id,
        "customer_id": customer_id,
        "reporter_kind": reporter_kind,
        "severity": severity,
    }
    if order_id is not None:
        payload["order_id"] = order_id
    payload.update(overrides)
    return payload


# -----------------------------------------------------------------------
# Prescriber denylist
# -----------------------------------------------------------------------

def denylist_entry_payload(prescriber_license_no: str, reason: str = "Test reason") -> Dict[str, Any]:
    """PRD §3.4 denylist: prescriber_license_no + reason."""
    return {"prescriber_license_no": prescriber_license_no, "reason": reason}
