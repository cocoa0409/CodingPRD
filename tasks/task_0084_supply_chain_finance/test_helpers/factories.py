"""Payload factories — one per endpoint that takes a body.

Each factory emits ONLY the input fields declared by the PRD for the
corresponding endpoint, and accepts ``**overrides`` so individual tests
can vary just the values they care about.

Each Unified Social Credit Code, invoice number, and contract number is
made unique-per-call so creation does not collide with previously
inserted rows in a single test session.
"""
from __future__ import annotations
import secrets
import string
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Unique-string helpers
# ---------------------------------------------------------------------------
def _unique_uscc() -> str:
    """A globally unique 18-character uppercase alphanumeric string
    matching the Unified Social Credit Code regex (PRD §2.8)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(18))


def _unique_token(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


# ===========================================================================
# CoreEnterprise (PRD §3.1)
# Onboard input: legal_name, unified_credit_code, erp_endpoint_url,
#                joint_liability_flag (optional, default true),
#                risk_rating (optional, default BBB).
# ===========================================================================
def create_core_enterprise_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'A CreditOfficer onboards a buyer-side enterprise by
    submitting legal_name, unified_credit_code, erp_endpoint_url,
    optionally joint_liability_flag (defaulting to true), and optionally
    risk_rating (one of AAA, AA, A, BBB, BB, defaulting to BBB).'"""
    payload: Dict[str, Any] = {
        "legal_name": TEST_DEFAULTS["CE_LEGAL_NAME"],
        "unified_credit_code": _unique_uscc(),
        "erp_endpoint_url": TEST_DEFAULTS["ERP_ENDPOINT"],
    }
    payload.update(overrides)
    return payload


def approve_core_enterprise_payload(credit_line_total_cents: int,
                                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Approval requires credit_line_total_cents in the
    request body to be an integer strictly greater than zero.'"""
    payload: Dict[str, Any] = {
        "credit_line_total_cents": credit_line_total_cents,
    }
    payload.update(overrides)
    return payload


def suspend_core_enterprise_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'the suspend request carries a reason string.'"""
    payload: Dict[str, Any] = {
        "reason": TEST_DEFAULTS["SUSPEND_REASON"],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Supplier (PRD §3.2)
# Onboard input: legal_name, unified_credit_code, tier_to_core,
#                parent_supplier_id?, bank_account_number.
# ===========================================================================
def create_supplier_payload(tier_to_core: int = 1,
                            parent_supplier_id: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'A PlatformAdmin onboards each Supplier with legal_name,
    unified_credit_code, tier_to_core, an optional parent_supplier_id,
    and bank_account_number.'"""
    payload: Dict[str, Any] = {
        "legal_name": TEST_DEFAULTS["SUP_LEGAL_NAME"],
        "unified_credit_code": _unique_uscc(),
        "tier_to_core": tier_to_core,
        "bank_account_number": TEST_DEFAULTS["SUP_BANK_ACCOUNT"],
    }
    if parent_supplier_id is not None:
        payload["parent_supplier_id"] = parent_supplier_id
    payload.update(overrides)
    return payload


def kyc_supplier_payload(kyc_status: str = "PASSED",
                         aml_risk_score: float = 0.10,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'A ComplianceOfficer records a KYC/AML screening by
    posting kyc_status (one of NOT_RUN, PASSED, FAILED, EXPIRED) and
    aml_risk_score (a continuous value in the closed interval from 0.00
    to 1.00, rounded to two decimal places).'"""
    payload: Dict[str, Any] = {
        "kyc_status": kyc_status,
        "aml_risk_score": aml_risk_score,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# PayableConfirmation (PRD §3.3)
# Upload input: core_enterprise_id, supplier_id, invoice_number,
#               contract_number, amount_cents, due_date.
# ===========================================================================
def create_payable_confirmation_payload(core_enterprise_id: str,
                                        supplier_id: str,
                                        amount_cents: int,
                                        due_date: str,
                                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'each request carries core_enterprise_id, supplier_id,
    invoice_number, contract_number, amount_cents, and due_date.'"""
    payload: Dict[str, Any] = {
        "core_enterprise_id": core_enterprise_id,
        "supplier_id": supplier_id,
        "invoice_number": _unique_token("INV"),
        "contract_number": _unique_token("CN"),
        "amount_cents": amount_cents,
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def revoke_payable_confirmation_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'The request body must carry a free-text
    revoke_reason.'"""
    payload: Dict[str, Any] = {
        "revoke_reason": TEST_DEFAULTS["REVOKE_REASON"],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Receivable (PRD §3.4)
# Register input: confirmation_id, invoice_doc_id, contract_doc_id.
# ===========================================================================
def create_receivable_payload(confirmation_id: str,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'A SupplierUser registers a receivable against an
    existing PayableConfirmation in CONFIRMED state by posting
    confirmation_id, invoice_doc_id, and contract_doc_id.'"""
    payload: Dict[str, Any] = {
        "confirmation_id": confirmation_id,
        "invoice_doc_id": _unique_token("DOC-INV"),
        "contract_doc_id": _unique_token("DOC-CN"),
    }
    payload.update(overrides)
    return payload


def central_registry_file_payload(filing_no: Optional[str] = None,
                                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'a separate filing step run by a PlatformAdmin records
    the registry-issued central_registry_filing_no.'"""
    payload: Dict[str, Any] = {
        "central_registry_filing_no": filing_no or _unique_token("REG"),
    }
    payload.update(overrides)
    return payload


def transfer_receivable_payload(new_supplier_id: str,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'Transferring by a supplier user moves
    REGISTERED → TRANSFERRED and reassigns supplier_id to a
    new_supplier_id carried in the request body.'"""
    payload: Dict[str, Any] = {"new_supplier_id": new_supplier_id}
    payload.update(overrides)
    return payload


# ===========================================================================
# TradeBackgroundVerification (PRD §3.9)
# Open input: receivable_id, waybill_doc_id?, customs_declaration_doc_id?,
#             third_party_score.
# ===========================================================================
def create_verification_payload(receivable_id: str,
                                third_party_score: float = 0.90,
                                waybill_doc_id: Optional[str] = None,
                                customs_declaration_doc_id: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'A RiskReviewer opens a TradeBackgroundVerification for
    a receivable by posting receivable_id, an optional waybill_doc_id,
    an optional customs_declaration_doc_id, and third_party_score.'"""
    payload: Dict[str, Any] = {
        "receivable_id": receivable_id,
        "third_party_score": third_party_score,
    }
    if waybill_doc_id is not None:
        payload["waybill_doc_id"] = waybill_doc_id
    if customs_declaration_doc_id is not None:
        payload["customs_declaration_doc_id"] = customs_declaration_doc_id
    payload.update(overrides)
    return payload


# ===========================================================================
# FinancingApplication (PRD §3.5)
# Draft input: receivable_id, mode, requested_amount_cents, term_days,
#              supporting_doc_ids.
# ===========================================================================
def create_financing_application_payload(receivable_id: str,
                                         mode: str = "FACTORING",
                                         requested_amount_cents: int = TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
                                         term_days: int = TEST_DEFAULTS["TERM_DAYS"],
                                         supporting_doc_ids: Optional[List[str]] = None,
                                         **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'A SupplierUser drafts a FinancingApplication by
    posting receivable_id, mode (one of FACTORING, REVERSE_FACTORING,
    DYNAMIC_DISCOUNTING, RECEIVABLE_PLEDGE), requested_amount_cents,
    term_days, and an array of supporting_doc_ids.'"""
    payload: Dict[str, Any] = {
        "receivable_id": receivable_id,
        "mode": mode,
        "requested_amount_cents": requested_amount_cents,
        "term_days": term_days,
        "supporting_doc_ids": list(supporting_doc_ids)
        if supporting_doc_ids is not None
        else list(TEST_DEFAULTS["SUPPORTING_DOC_IDS"]),
    }
    payload.update(overrides)
    return payload


def return_financing_application_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'supplying revision_notes in the request body.'"""
    payload: Dict[str, Any] = {
        "revision_notes": TEST_DEFAULTS["REVISION_NOTES"],
    }
    payload.update(overrides)
    return payload


def approve_financing_application_payload(approved_amount_cents: int,
                                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'approval requires approved_amount_cents in the
    body.'"""
    payload: Dict[str, Any] = {
        "approved_amount_cents": approved_amount_cents,
    }
    payload.update(overrides)
    return payload


def reject_financing_application_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'rejection requires reject_reason.'"""
    payload: Dict[str, Any] = {
        "reject_reason": TEST_DEFAULTS["REJECT_REASON"],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Disbursement (PRD §3.6)
# Input: application_id, funder_account_id.
# ===========================================================================
def create_disbursement_payload(application_id: str,
                                funder_account_id: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'A Funder releases funds against an APPROVED
    application by posting application_id and funder_account_id.'"""
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "funder_account_id": funder_account_id
        or TEST_DEFAULTS["FUNDER_ACCOUNT_ID"],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# RepaymentSchedule.repay (PRD §3.7)
# Input: repay_amount_cents, partial?, early_settle?.
# ===========================================================================
def repay_repayment_schedule_payload(repay_amount_cents: int,
                                     partial: Optional[bool] = None,
                                     early_settle: Optional[bool] = None,
                                     **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'The request body carries repay_amount_cents and two
    optional flags: partial (true for a partial prepayment, false or
    absent for a full balance settlement) and early_settle (true to
    request a rebate, false or absent otherwise).'"""
    payload: Dict[str, Any] = {
        "repay_amount_cents": repay_amount_cents,
    }
    if partial is not None:
        payload["partial"] = partial
    if early_settle is not None:
        payload["early_settle"] = early_settle
    payload.update(overrides)
    return payload


# ===========================================================================
# CollectionCase.write_off (PRD §3.8)
# Input: write_off_reason.
# ===========================================================================
def write_off_collection_case_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'the manager performs the write-off (LEGAL → WRITTEN_OFF)
    with a write_off_reason in the request body.'"""
    payload: Dict[str, Any] = {
        "write_off_reason": TEST_DEFAULTS["WRITE_OFF_REASON"],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Test-driving capabilities (PRD §3.10)
# ===========================================================================
def clock_advance_payload(to_iso: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.10: 'the clock-advance capability advances the logical
    clock to a supplied to instant.'"""
    payload: Dict[str, Any] = {"to": to_iso}
    payload.update(overrides)
    return payload


def emit_event_payload(event_type: str,
                       payload: Dict[str, Any],
                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.10: 'a separate event-emission capability open to
    PlatformAdmin accepts event_type and payload.'"""
    body: Dict[str, Any] = {"event_type": event_type, "payload": payload}
    body.update(overrides)
    return body


__all__ = [
    "create_core_enterprise_payload",
    "approve_core_enterprise_payload",
    "suspend_core_enterprise_payload",
    "create_supplier_payload",
    "kyc_supplier_payload",
    "create_payable_confirmation_payload",
    "revoke_payable_confirmation_payload",
    "create_receivable_payload",
    "central_registry_file_payload",
    "transfer_receivable_payload",
    "create_verification_payload",
    "create_financing_application_payload",
    "return_financing_application_payload",
    "approve_financing_application_payload",
    "reject_financing_application_payload",
    "create_disbursement_payload",
    "repay_repayment_schedule_payload",
    "write_off_collection_case_payload",
    "clock_advance_payload",
    "emit_event_payload",
]
