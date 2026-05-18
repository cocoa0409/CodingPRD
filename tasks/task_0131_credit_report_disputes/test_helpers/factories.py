"""Payload factories — one per endpoint that accepts an input body.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.
"""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name() -> str:
    return f"Test Consumer {random_suffix(6)}"


def random_email() -> str:
    return f"test.{random_suffix(8)}@example.com"


def random_ssn_last4() -> str:
    """PRD §3.1: 'last four digits of social security number as
    ssn_last4 (which must be exactly four digits)'."""
    return f"{random.randint(0, 9999):04d}"


def random_account_ref() -> str:
    return f"ACCT-{random_suffix(8).upper()}"


def random_legal_name() -> str:
    return f"Test Furnisher LLC {random_suffix(4)}"


def random_sha256() -> str:
    return "".join(random.choices("0123456789abcdef", k=64))


# ===========================================================================
# Consumer — PRD §3.1
# ===========================================================================
def create_consumer_payload(
    *,
    full_name: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name, ssn_last4 (exactly 4 digits),
    email (unique across consumers)."""
    return {
        "full_name": full_name or random_full_name(),
        "ssn_last4": ssn_last4 if ssn_last4 is not None else random_ssn_last4(),
        "email": email or random_email(),
    }


# ===========================================================================
# Furnisher — PRD §3.1
# ===========================================================================
def create_furnisher_payload(
    *,
    legal_name: Optional[str] = None,
    ecoa_code: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: legal_name and immutable ecoa_code."""
    return {
        "legal_name": legal_name or random_legal_name(),
        "ecoa_code": ecoa_code if ecoa_code is not None else "1",
    }


# ===========================================================================
# CreditReport — PRD §3.1
# ===========================================================================
def create_credit_report_payload(*, bureau: str = "EQUIFAX") -> Dict[str, Any]:
    """PRD §3.1 inputs: bureau (EQUIFAX, EXPERIAN, TRANSUNION)."""
    return {"bureau": bureau}


# ===========================================================================
# TradelineItem — PRD §3.1
# ===========================================================================
def create_tradeline_item_payload(
    *,
    furnisher_id: str,
    account_ref: Optional[str] = None,
    original_dofd_day: int = 100,
    balance_cents: int = 500_000,
    payment_status: str = "LATE_90",
) -> Dict[str, Any]:
    """PRD §3.1 inputs: furnisher_id, account_ref (unique per
    (credit_report_id, furnisher_id)), original_dofd_day (non-negative
    integer day), balance_cents (non-negative), payment_status."""
    return {
        "furnisher_id": furnisher_id,
        "account_ref": account_ref or random_account_ref(),
        "original_dofd_day": original_dofd_day,
        "balance_cents": balance_cents,
        "payment_status": payment_status,
    }


# ===========================================================================
# Dispute — PRD §3.2
# ===========================================================================
def supporting_doc(kind: str = "RECEIPT") -> Dict[str, str]:
    """PRD §3.2: 'Each document descriptor in the array is an object
    carrying a kind label and the document's sha256 digest.'"""
    return {"kind": kind, "sha256": random_sha256()}


def create_dispute_payload(
    *,
    credit_report_id: str,
    tradeline_item_id: str,
    channel: str = "ONLINE",
    supporting_documents: Optional[List[Dict[str, str]]] = None,
    requested_action: str = "CORRECT_BALANCE",
    requested_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.2 inputs: credit_report_id, tradeline_item_id, channel
    (ONLINE | MAIL, immutable), supporting_documents (non-empty array
    of {kind, sha256}), requested_action (CORRECT_BALANCE |
    CORRECT_STATUS | DELETE_ITEM | CORRECT_DOFD), requested_payload
    (action-specific)."""
    if supporting_documents is None:
        supporting_documents = [supporting_doc("RECEIPT")]
    if requested_payload is None:
        requested_payload = (
            {"new_balance_cents": 100} if requested_action == "CORRECT_BALANCE"
            else {} if requested_action == "DELETE_ITEM"
            else {"new_dofd_day": 90} if requested_action == "CORRECT_DOFD"
            else {"new_payment_status": "CURRENT"}
        )
    return {
        "credit_report_id": credit_report_id,
        "tradeline_item_id": tradeline_item_id,
        "channel": channel,
        "supporting_documents": supporting_documents,
        "requested_action": requested_action,
        "requested_payload": requested_payload,
    }


def additional_info_payload(
    *,
    supporting_documents: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """PRD §3.2: 'The request body re-supplies a supporting_documents
    array containing the new descriptors.'"""
    if supporting_documents is None:
        supporting_documents = [supporting_doc("ADDENDUM")]
    return {"supporting_documents": supporting_documents}


def furnisher_response_payload(
    *,
    response: str,
    response_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.3: 'supplying a response value from the enumeration
    VERIFIED, UPDATED, or DELETED and a response_payload object whose
    shape mirrors the dispute's requested_action'."""
    return {
        "response": response,
        "response_payload": response_payload if response_payload is not None else {},
    }


# ===========================================================================
# RegulatoryComplaint — PRD §3.10
# ===========================================================================
def create_regulatory_complaint_payload(
    *,
    dispute_id: str,
    narrative: str = "Bureau failed to resolve the dispute properly.",
    parent_complaint_id: Optional[str] = None,
    agency: str = "CFPB",
) -> Dict[str, Any]:
    """PRD §3.10 inputs: dispute_id (FK to Dispute being escalated),
    parent_complaint_id (must be supplied iff refiling a REJECTED
    complaint), agency (defaults to CFPB, only value in v1),
    narrative (1..4000 chars)."""
    body: Dict[str, Any] = {
        "dispute_id": dispute_id,
        "narrative": narrative,
        "agency": agency,
    }
    if parent_complaint_id is not None:
        body["parent_complaint_id"] = parent_complaint_id
    return body


# ===========================================================================
# CreditFreeze / CreditLock — PRD §3.11
# ===========================================================================
def create_credit_freeze_payload(*, bureau: str = "EQUIFAX") -> Dict[str, Any]:
    """PRD §3.11: 'A consumer protects their credit file by placing a
    CreditFreeze for a specific bureau.'"""
    return {"bureau": bureau}


def lift_credit_freeze_payload(*, pin: str) -> Dict[str, Any]:
    """PRD §3.11: 'A consumer lifts a freeze by supplying the
    previously minted freeze_pin in the request body's pin field.'"""
    return {"pin": pin}


def create_credit_lock_payload(*, bureau: str = "EQUIFAX") -> Dict[str, Any]:
    """PRD §3.11: 'A consumer engages a CreditLock for a specific
    bureau.'"""
    return {"bureau": bureau}


# ===========================================================================
# HardInquiry — PRD §3.12
# ===========================================================================
def create_hard_inquiry_payload(
    *,
    requesting_furnisher_id: str,
) -> Dict[str, Any]:
    """PRD §3.12: 'the request body carries the requesting_furnisher_id.'"""
    return {"requesting_furnisher_id": requesting_furnisher_id}


# ===========================================================================
# Clock + sweep — PRD §2.4, §2.11
# ===========================================================================
def clock_advance_payload(*, days: int) -> Dict[str, Any]:
    """PRD §2.4: 'A test-driving capability accepts a positive integer
    days argument and advances the logical clock by that many days.'"""
    return {"days": days}


__all__ = [
    "random_suffix",
    "random_full_name",
    "random_email",
    "random_ssn_last4",
    "random_account_ref",
    "random_legal_name",
    "random_sha256",
    "create_consumer_payload",
    "create_furnisher_payload",
    "create_credit_report_payload",
    "create_tradeline_item_payload",
    "supporting_doc",
    "create_dispute_payload",
    "additional_info_payload",
    "furnisher_response_payload",
    "create_regulatory_complaint_payload",
    "create_credit_freeze_payload",
    "lift_credit_freeze_payload",
    "create_credit_lock_payload",
    "create_hard_inquiry_payload",
    "clock_advance_payload",
]
