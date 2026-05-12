"""Payload factories — one per entity / endpoint, input fields only.

Field names are PRD-exact (PRD §2.4, §3). Every factory accepts
**overrides so individual tests can pin the exact values needed for a
boundary or precondition.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_DISCREPANCY_FEE_MINOR,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Unique helpers
# ---------------------------------------------------------------------------
def unique_swift_bic(prefix: str = "AAAA") -> str:
    """ISO 9362 BIC: 8 or 11 alphanumeric characters (PRD §2.5).

    Generates a random 11-character BIC for collision-resistant uniqueness
    across Bank rows (PRD §2.5 / §3.1 require global BIC uniqueness).
    The runtime only checks length 8 or 11 and global uniqueness.
    """
    suffix = uuid.uuid4().hex[:7].upper()
    # Replace digits with letters since BIC alphabetic positions are typical.
    trans = str.maketrans({"0": "A", "1": "B", "2": "C", "3": "D",
                           "4": "E", "5": "F", "6": "G", "7": "H",
                           "8": "I", "9": "J"})
    return (prefix[:4] + suffix).translate(trans)[:11]


def unique_idempotency_key(prefix: str = "idem") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def non_existent_uuid() -> str:
    """Return a UUID that no real entity will share."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Bank / Applicant / Beneficiary (PRD §3.1)
# ---------------------------------------------------------------------------
def create_bank_payload(
    *,
    bank_role: str = "ISSUING",
    swift_bic: Optional[str] = None,
    name: Optional[str] = None,
    country_code: str = TEST_DEFAULTS["COUNTRY_CODE_BANK"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "bank_role": bank_role,
        "swift_bic": swift_bic or unique_swift_bic(),
        "name": name or f"Test Bank {uuid.uuid4().hex[:6]}",
        "country_code": country_code,
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(
    *,
    name: Optional[str] = None,
    country_code: str = TEST_DEFAULTS["COUNTRY_CODE_APPLICANT"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Test Applicant {uuid.uuid4().hex[:6]}",
        "country_code": country_code,
    }
    payload.update(overrides)
    return payload


def create_beneficiary_payload(
    *,
    name: Optional[str] = None,
    country_code: str = TEST_DEFAULTS["COUNTRY_CODE_BENEFICIARY"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Test Beneficiary {uuid.uuid4().hex[:6]}",
        "country_code": country_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Letter of Credit draft (PRD §3.2)
# ---------------------------------------------------------------------------
def create_lc_payload(
    *,
    applicant_id: str,
    beneficiary_id: str,
    issuing_bank_id: str,
    advising_bank_id: str,
    confirming_bank_id: Optional[str] = None,
    lc_type: str = "SIGHT",
    usance_tenor_days: Optional[int] = None,
    currency: str = TEST_DEFAULTS["CURRENCY"],
    amount_minor_units: int = TEST_DEFAULTS["AMOUNT_MINOR_UNITS"],
    tolerance_pct: int = 0,
    latest_shipment_date: Optional[str] = None,
    presentation_period_days: Optional[int] = None,
    expiry_date: Optional[str] = None,
    confirmation_required: Optional[bool] = None,
    required_documents: Optional[List[str]] = None,
    discrepancy_fee_minor_units: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """LC draft payload (PRD §3.2).

    Defaults yield a SIGHT LC, USD 1,000.00, tolerance 0, with both
    mandatory required_documents (COMMERCIAL_INVOICE, BILL_OF_LADING).
    Tests override fields to drive boundaries.
    """
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "beneficiary_id": beneficiary_id,
        "issuing_bank_id": issuing_bank_id,
        "advising_bank_id": advising_bank_id,
        "lc_type": lc_type,
        "currency": currency,
        "amount_minor_units": amount_minor_units,
        "tolerance_pct": tolerance_pct,
        "latest_shipment_date": latest_shipment_date,
        "expiry_date": expiry_date,
        "required_documents": required_documents or [
            "COMMERCIAL_INVOICE", "BILL_OF_LADING",
        ],
    }
    if confirming_bank_id is not None:
        payload["confirming_bank_id"] = confirming_bank_id
    if usance_tenor_days is not None:
        payload["usance_tenor_days"] = usance_tenor_days
    if presentation_period_days is not None:
        payload["presentation_period_days"] = presentation_period_days
    if confirmation_required is not None:
        payload["confirmation_required"] = confirmation_required
    if discrepancy_fee_minor_units is not None:
        payload["discrepancy_fee_minor_units"] = discrepancy_fee_minor_units
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Amendment (PRD §3.4)
# ---------------------------------------------------------------------------
def create_amendment_payload(
    *,
    changes: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    """Amendment payload — must carry a `changes` object with at least
    one of {amount_minor_units, expiry_date, latest_shipment_date,
    tolerance_pct, required_documents} per PRD §3.4."""
    payload: Dict[str, Any] = {"changes": dict(changes)}
    payload.update(overrides)
    return payload


def consent_payload(*, decision: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'a decision field whose value is either CONSENTED or
    REJECTED'."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Presentation (PRD §3.5)
# ---------------------------------------------------------------------------
def create_presentation_payload(
    *,
    shipment_date: str,
    drawing_amount_minor_units: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shipment_date": shipment_date,
        "drawing_amount_minor_units": drawing_amount_minor_units,
    }
    payload.update(overrides)
    return payload


def attach_document_payload(
    *,
    document_type: str,
    issuer: str = "Test Issuer",
    document_date: Optional[str] = None,
    stated_amount_minor_units: Optional[int] = None,
    stated_currency: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "document_type": document_type,
        "issuer": issuer,
        "document_date": document_date,
        "payload": payload if payload is not None else {},
    }
    if stated_amount_minor_units is not None:
        body["stated_amount_minor_units"] = stated_amount_minor_units
    if stated_currency is not None:
        body["stated_currency"] = stated_currency
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Examination (PRD §3.5 / §3.6)
# ---------------------------------------------------------------------------
def start_examination_payload(
    *,
    primary_reviewer_id: str,
    secondary_reviewer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "primary_reviewer_id": primary_reviewer_id,
        "secondary_reviewer_id": secondary_reviewer_id,
    }
    payload.update(overrides)
    return payload


def primary_review_payload(
    *,
    primary_outcome: str,
    discrepancies: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"primary_outcome": primary_outcome}
    if discrepancies is not None:
        payload["discrepancies"] = discrepancies
    payload.update(overrides)
    return payload


def cross_check_payload(
    *,
    secondary_outcome: str,
    discrepancies: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"secondary_outcome": secondary_outcome}
    if discrepancies is not None:
        payload["discrepancies"] = discrepancies
    payload.update(overrides)
    return payload


def discrepancy_item(
    *,
    discrepancy_code: str,
    description: str = "Test discrepancy",
    cited_document_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "discrepancy_code": discrepancy_code,
        "description": description,
    }
    if cited_document_id is not None:
        item["cited_document_id"] = cited_document_id
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# Refusal / applicant decision (PRD §3.7)
# ---------------------------------------------------------------------------
def applicant_decision_payload(*, decision: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'a decision of either ACCEPTED or REJECTED'."""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def refuse_payload(*, refusal_reason: str = "documents discrepant", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"refusal_reason": refusal_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Settlement (PRD §3.8)
# ---------------------------------------------------------------------------
def create_settlement_payload(
    *,
    settlement_type_override: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if settlement_type_override is not None:
        payload["settlement_type_override"] = settlement_type_override
    payload.update(overrides)
    return payload


def compensate_payload(*, reason: str = "reimbursement-disputed", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reimbursement (PRD §3.9)
# ---------------------------------------------------------------------------
def dispute_claim_payload(*, reason: str = "discrepancy", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# LC cancel (PRD §3.3)
# ---------------------------------------------------------------------------
def cancel_lc_payload(*, cancelled_reason: str = "no longer needed", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancelled_reason": cancelled_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Advise / confirm (PRD §3.3)
# ---------------------------------------------------------------------------
def advise_payload(
    *,
    downstream_advising_bank_bic: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if downstream_advising_bank_bic is not None:
        payload["downstream_advising_bank_bic"] = downstream_advising_bank_bic
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# External event (PRD §3.10)
# ---------------------------------------------------------------------------
def create_external_event_payload(
    *,
    source_system: str,
    event_type: str,
    lc_id: str,
    presentation_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "source_system": source_system,
        "event_type": event_type,
        "lc_id": lc_id,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
        "payload": payload if payload is not None else {},
    }
    if presentation_id is not None:
        body["presentation_id"] = presentation_id
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Clock (PRD §3.10)
# ---------------------------------------------------------------------------
def advance_clock_payload(*, seconds: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seconds": int(seconds)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Document payload helpers (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
def commercial_invoice_payload(
    *,
    stated_amount_minor_units: int,
    currency: str = "USD",
    country_of_origin: str = "CN",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST .../documents — COMMERCIAL_INVOICE.

    PRD §3.6 I2/I3/I7 read amount/currency/country_of_origin off invoices.
    """
    body = attach_document_payload(
        document_type="COMMERCIAL_INVOICE",
        issuer="Test Beneficiary Corp",
        document_date="2026-01-15",
        stated_amount_minor_units=stated_amount_minor_units,
        stated_currency=currency,
        payload={
            "country_of_origin": country_of_origin,
            "description": "Test goods",
        },
    )
    body.update(overrides)
    return body


def bill_of_lading_payload(
    *,
    shipped_on_board_date: str,
    currency: str = "USD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST .../documents — BILL_OF_LADING.

    PRD §3.5 says 'a BILL_OF_LADING payload includes shipped_on_board_date'.
    """
    body = attach_document_payload(
        document_type="BILL_OF_LADING",
        issuer="Test Carrier",
        document_date=shipped_on_board_date,
        stated_amount_minor_units=0,
        stated_currency=currency,
        payload={"shipped_on_board_date": shipped_on_board_date},
    )
    body.update(overrides)
    return body


def certificate_of_origin_payload(
    *,
    country_of_origin: str = "CN",
    currency: str = "USD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST .../documents — CERTIFICATE_OF_ORIGIN.

    PRD §3.5 says 'a CERTIFICATE_OF_ORIGIN payload includes country_of_origin'.
    """
    body = attach_document_payload(
        document_type="CERTIFICATE_OF_ORIGIN",
        issuer="Chamber of Commerce",
        document_date="2026-01-10",
        stated_amount_minor_units=0,
        stated_currency=currency,
        payload={"country_of_origin": country_of_origin},
    )
    body.update(overrides)
    return body


def packing_list_payload(currency: str = "USD", **overrides: Any) -> Dict[str, Any]:
    body = attach_document_payload(
        document_type="PACKING_LIST",
        issuer="Test Packer",
        document_date="2026-01-12",
        stated_amount_minor_units=0,
        stated_currency=currency,
        payload={"item_count": 100},
    )
    body.update(overrides)
    return body


def insurance_policy_payload(
    *,
    stated_amount_minor_units: int = 1_000,
    currency: str = "USD",
    **overrides: Any,
) -> Dict[str, Any]:
    body = attach_document_payload(
        document_type="INSURANCE_POLICY",
        issuer="Test Insurer",
        document_date="2026-01-12",
        stated_amount_minor_units=stated_amount_minor_units,
        stated_currency=currency,
        payload={"insured_amount": stated_amount_minor_units},
    )
    body.update(overrides)
    return body


__all__ = [
    "unique_swift_bic",
    "unique_idempotency_key",
    "non_existent_uuid",
    "create_bank_payload",
    "create_applicant_payload",
    "create_beneficiary_payload",
    "create_lc_payload",
    "create_amendment_payload",
    "consent_payload",
    "create_presentation_payload",
    "attach_document_payload",
    "start_examination_payload",
    "primary_review_payload",
    "cross_check_payload",
    "discrepancy_item",
    "applicant_decision_payload",
    "refuse_payload",
    "create_settlement_payload",
    "compensate_payload",
    "dispute_claim_payload",
    "cancel_lc_payload",
    "advise_payload",
    "create_external_event_payload",
    "advance_clock_payload",
    "commercial_invoice_payload",
    "bill_of_lading_payload",
    "certificate_of_origin_payload",
    "packing_list_payload",
    "insurance_policy_payload",
]
