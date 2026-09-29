"""Payload factories — one per write payload, request-input fields only.

Every monetary value is emitted as a JSON integer number of cents, never a
string and never a decimal (PRD Section 2.5).
"""

from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# Builder file
# --------------------------------------------------------------------------
def create_builder_payload(**overrides) -> Dict[str, Any]:
    """The six declared underwriting inputs. Defaults score 45.00 -> class C."""
    payload: Dict[str, Any] = {
        "company_name": "Cedar Ridge Homes",
        "state_code": "TX",
        "years_in_business": 5,
        "homes_closed_last_year": 25,
        "claims_history_score": 94,
        "financial_strength_tier": "TIER_3",
    }
    payload.update(overrides)
    return payload


def submit_builder_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"attestation_signed": True}
    payload.update(overrides)
    return payload


def review_intake_payload(**overrides) -> Dict[str, Any]:
    """The intake note is optional; the default payload omits it."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def underwriting_review_payload(decision: str = "APPROVE", **overrides
                                ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def reassessment_payload(**overrides) -> Dict[str, Any]:
    """Every declared input is optional on a reassessment."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def suspension_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Adverse loss experience under monitoring"}
    payload.update(overrides)
    return payload


def reinstatement_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Remediation plan accepted"}
    payload.update(overrides)
    return payload


def default_declaration_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Builder ceased operations"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------
def create_homeowner_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Alice Baird",
        "email": "alice.baird@example.com",
        "state_code": "TX",
    }
    payload.update(overrides)
    return payload


def create_neutral_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Marta Quill",
        "credential": "BOTH",
        "state_code": "TX",
    }
    payload.update(overrides)
    return payload


def deactivate_neutral_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Retired from the panel"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Home enrollment and coverage
# --------------------------------------------------------------------------
def create_policy_payload(builder_id: str, initial_owner_id: str,
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "builder_id": builder_id,
        "initial_owner_id": initial_owner_id,
        "street_address": "118 Cedar Ridge Ct",
        "state_code": "TX",
        "purchase_price_cents": 44_500_000,
        "closing_date": "2026-08-15",
    }
    payload.update(overrides)
    return payload


def premium_invoice_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def premium_payment_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_coverage_term_payload(coverage_type: str = "WORKMANSHIP",
                                 start_date: str = "2028-09-01",
                                 end_date: str = "2030-08-31",
                                 limit_cents: int = 2_000_000,
                                 deductible_cents: int = 100_000,
                                 **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "coverage_type": coverage_type,
        "start_date": start_date,
        "end_date": end_date,
        "limit_cents": limit_cents,
        "deductible_cents": deductible_cents,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
def create_transfer_payload(new_owner_id: str, expected_policy_version: int,
                            transfer_date: str = "2028-09-05",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_owner_id": new_owner_id,
        "transfer_date": transfer_date,
        "documents_reference": "DEED-2028-0905",
        "expected_policy_version": expected_policy_version,
    }
    payload.update(overrides)
    return payload


def documentation_request_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "Deed packet incomplete"}
    payload.update(overrides)
    return payload


def resubmission_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"documents_reference": "DEED-2028-0905-REV2"}
    payload.update(overrides)
    return payload


def transfer_decision_payload(outcome: str = "APPROVE", **overrides
                              ) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------
def create_claim_payload(policy_id: str, coverage_type: str = "STRUCTURAL",
                         defect_category: str = "WATER_INTRUSION",
                         claimed_amount_cents: int = 1_000_000,
                         **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "policy_id": policy_id,
        "coverage_type": coverage_type,
        "defect_category": defect_category,
        "damage_description": "Seepage through the foundation cold joint",
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def investigation_payload(substantiation_ratio: float = 1.00,
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"substantiation_ratio": substantiation_ratio}
    payload.update(overrides)
    return payload


def structural_assessment_payload(affected_elements: Optional[List[str]] = None,
                                  deflection_ratio: float = 0.0500,
                                  load_bearing_affected: bool = True,
                                  **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "affected_elements": (["FOOTING"] if affected_elements is None
                              else affected_elements),
        "deflection_ratio": deflection_ratio,
        "load_bearing_affected": load_bearing_affected,
    }
    payload.update(overrides)
    return payload


def obligation_routing_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def builder_response_payload(response: str = "ACCEPT_OBLIGATION",
                             **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response": response}
    payload.update(overrides)
    return payload


def repair_completion_payload(completion_date: str = "2026-10-01",
                              **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"completion_date": completion_date}
    payload.update(overrides)
    return payload


def adjudication_payload(outcome: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Reserve ledger
# --------------------------------------------------------------------------
def reserve_entry_payload(amount_cents: int, expected_claim_version: int,
                          entry_type: str = "INITIAL",
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def payment_reversal_payload(reserve_entry_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reserve_entry_id": reserve_entry_id}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Escalation ladder
# --------------------------------------------------------------------------
def create_escalation_payload(neutral_id: str, stage: str = "MEDIATION",
                              window_start: str = "2028-09-10T14:00:00Z",
                              window_end: str = "2028-09-10T16:00:00Z",
                              **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "stage": stage,
        "neutral_id": neutral_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def session_outcome_payload(outcome: str = "IMPASSE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def award_payload(award_amount_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"award_amount_cents": award_amount_cents}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
