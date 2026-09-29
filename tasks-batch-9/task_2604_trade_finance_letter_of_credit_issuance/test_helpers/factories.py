"""Request payload builders.

Every builder returns a valid payload for its endpoint and accepts ``**overrides`` so a
test can perturb exactly the field under examination. Values that must be unique across
rows (an applicant's `legal_name`/`country_code` pair, a bank's `swift_bic`) are minted
from a monotone counter so repeated calls inside one test never trip `ERR_DUPLICATE_KEY`.
"""

from itertools import count
from typing import Any, Dict, List, Optional

_seq = count(1)


def next_suffix() -> int:
    """Monotone integer used to keep unique-constrained fields distinct."""
    return next(_seq)


# ----------------------------------------------------------------------
# Parties
# ----------------------------------------------------------------------
def applicant_payload(**overrides: Any) -> Dict[str, Any]:
    n = next_suffix()
    payload: Dict[str, Any] = {
        "legal_name": f"Meridian Import Holdings {n:04d}",
        "country_code": "DE",
        "industry_code": "4669",
        "internal_risk_grade": "A",
        "kyc_status": "CLEARED",
    }
    payload.update(overrides)
    return payload


def facility_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "currency": "USD",
        "limit_cents": 50000000,
        "collateral_required_pct": 0,
        "facility_expiry_date": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def bank_payload(**overrides: Any) -> Dict[str, Any]:
    n = next_suffix()
    payload: Dict[str, Any] = {
        "bank_name": f"Hanseatic Correspondent Bank {n:04d}",
        "swift_bic": f"TSTBK{n:03d}",
        "country_code": "DE",
        "country_risk_score": 20,
        "credit_rating": "A",
        "confirmation_appetite_cents": 200000000,
    }
    payload.update(overrides)
    return payload


def beneficiary_payload(nominated_bank_id: str, **overrides: Any) -> Dict[str, Any]:
    n = next_suffix()
    payload: Dict[str, Any] = {
        "beneficiary_name": f"Kallang Export Works {n:04d}",
        "country_code": "SG",
        "nominated_bank_id": nominated_bank_id,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Documentary credit
# ----------------------------------------------------------------------
def credit_payload(
    applicant_id: str,
    beneficiary_id: str,
    facility_id: str,
    advising_bank_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "beneficiary_id": beneficiary_id,
        "facility_id": facility_id,
        "advising_bank_id": advising_bank_id,
        "currency": "USD",
        "amount_cents": 10000000,
        "available_by": "SIGHT_PAYMENT",
        "tenor_days": 0,
        "tolerance_pct": 0,
        "incoterm": "FOB",
        "incoterm_place": "Port of Singapore",
        "latest_shipment_date": "2026-10-31",
        "expiry_date": "2026-11-30",
        "expiry_place": "Frankfurt",
        "presentation_period_days": 21,
    }
    payload.update(overrides)
    return payload


def invoice_requirement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": "COMMERCIAL_INVOICE",
        "originals_required": 1,
        "copies_required": 2,
        "issuer_constraint": "Beneficiary",
        "is_mandatory": True,
    }
    payload.update(overrides)
    return payload


def transport_requirement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": "BILL_OF_LADING",
        "originals_required": 1,
        "copies_required": 1,
        "issuer_constraint": "Carrier",
        "is_mandatory": True,
    }
    payload.update(overrides)
    return payload


def insurance_requirement_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": "INSURANCE_CERTIFICATE",
        "originals_required": 1,
        "copies_required": 1,
        "issuer_constraint": "Any insurance company",
        "is_mandatory": True,
    }
    payload.update(overrides)
    return payload


def submit_for_approval_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"submission_note": "terms agreed with applicant"}
    payload.update(overrides)
    return payload


def approve_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "APPROVE",
        "approval_note": "within facility appetite",
    }
    payload.update(overrides)
    return payload


def issue_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"issue_note": "issued by SWIFT MT700"}
    payload.update(overrides)
    return payload


def cancel_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Applicant withdrew the underlying purchase order"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Confirmation
# ----------------------------------------------------------------------
def confirmation_request_payload(
    confirming_bank_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"request_note": "please add your confirmation"}
    if confirming_bank_id is not None:
        payload["confirming_bank_id"] = confirming_bank_id
    payload.update(overrides)
    return payload


def confirmation_response_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": "CONFIRM"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Amendments
# ----------------------------------------------------------------------
def amendment_payload(
    change_set: Dict[str, Any], expected_credit_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "change_set": change_set,
        "reason": "commercial renegotiation with the applicant",
        "expected_credit_version": expected_credit_version,
    }
    payload.update(overrides)
    return payload


def amendment_issue_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"issue_note": "amendment advised to the beneficiary"}
    payload.update(overrides)
    return payload


def consent_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "note": "beneficiary response"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Collateral and facility lifecycle
# ----------------------------------------------------------------------
def collateral_posting_payload(
    amount_cents: int, expected_facility_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "expected_facility_version": expected_facility_version,
        "posting_note": "cash margin movement",
    }
    payload.update(overrides)
    return payload


def facility_status_change_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "reason": "relationship review"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Presentations
# ----------------------------------------------------------------------
def presentation_payload(
    credit_id: str, presenting_bank_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "credit_id": credit_id,
        "presenting_bank_id": presenting_bank_id,
        "cover_letter_reference": f"CL-{next_suffix():05d}",
    }
    payload.update(overrides)
    return payload


def invoice_document_payload(invoice_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": "COMMERCIAL_INVOICE",
        "originals_presented": 1,
        "copies_presented": 2,
        "issue_date": "2026-09-08",
        "invoice_amount_cents": invoice_amount_cents,
        "goods_description": "Cotton trousers",
        "hs_code": "620342",
        "consignee_country": "DE",
        "transit_country_codes": ["SG"],
        "issuer_name": "Kallang Garments Pte Ltd",
    }
    payload.update(overrides)
    return payload


def transport_document_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": "BILL_OF_LADING",
        "originals_presented": 1,
        "copies_presented": 1,
        "issue_date": "2026-09-09",
        "shipment_date": "2026-09-09",
        "goods_description": "Cotton trousers",
        "consignee_country": "DE",
        "transit_country_codes": ["SG"],
        "issuer_name": "Pacific Liner Services",
    }
    payload.update(overrides)
    return payload


def submit_presentation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"submission_note": "complete set"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Examination, waivers, refusal
# ----------------------------------------------------------------------
def discrepancy_payload(code: str, severity: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "description": "Documents differ from the credit wording",
    }
    payload.update(overrides)
    return payload


def conclude_examination_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"conclusion_note": "examination concluded"}
    payload.update(overrides)
    return payload


def waiver_request_payload(discrepancy_codes: List[str], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "discrepancy_codes": discrepancy_codes,
        "request_note": "please advise whether these defects are acceptable",
    }
    payload.update(overrides)
    return payload


def waiver_response_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "applicant_note": "applicant instruction",
    }
    payload.update(overrides)
    return payload


def refusal_payload(
    disposal_instruction: str = "RETURN_TO_PRESENTER", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "disposal_instruction": disposal_instruction,
        "refusal_note": "UCP 600 art.16 refusal notice",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Screening and settlement
# ----------------------------------------------------------------------
def screening_payload(scope: str = "PRESENTED_DOCUMENTS", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scope": scope,
        "screening_note": "re-screen on updated list",
    }
    payload.update(overrides)
    return payload


def screening_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "review_note": "compliance adjudication"}
    payload.update(overrides)
    return payload


def settlement_claim_payload(
    claim_type: str, claimed_amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
        "claim_note": "claim under the credit",
    }
    payload.update(overrides)
    return payload


def settle_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"settlement_note": "proceeds remitted"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Operations
# ----------------------------------------------------------------------
def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def sweep_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload
