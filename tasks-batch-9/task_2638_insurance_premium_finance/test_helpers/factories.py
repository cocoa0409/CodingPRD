"""Payload factories.

Each factory returns a valid creation payload for one entity and accepts
`**overrides` so a test can perturb exactly the field it cares about.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import CA_RULE, TX_RULE

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ===========================================================================
# StateRateRule
# ===========================================================================
def tx_state_rate_rule(**overrides: Any) -> Dict[str, Any]:
    """The canonical TX regime: ADD_ON, RULE_OF_78, PRO_RATA."""
    payload = dict(TX_RULE)
    payload.update(overrides)
    return payload


def ca_state_rate_rule(**overrides: Any) -> Dict[str, Any]:
    """The canonical CA regime: SIMPLE_INTEREST, ACTUARIAL, SHORT_RATE."""
    payload = dict(CA_RULE)
    payload.update(overrides)
    return payload


def state_rate_rule(state_code: str = "TX", **overrides: Any) -> Dict[str, Any]:
    payload = dict(TX_RULE)
    payload["state_code"] = state_code
    payload.update(overrides)
    return payload


# ===========================================================================
# License
# ===========================================================================
def license_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "license_number": f"PFC-TX-{_seq():03d}",
        "effective_date": "2026-01-01",
        "expiration_date": "2027-12-31",
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Insured
# ===========================================================================
def insured(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Northwind Freight LLC",
        "mailing_state_code": "TX",
        "email": "ap@northwind.example",
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# ProducerAgent
# ===========================================================================
def producer_agent(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agency_name": "Lone Star Brokers",
        "state_code": "TX",
        "agent_commission_bps": 1200,
        "chargeback_basis": "COMMISSION_CAPPED",
        "chargeback_liability_cap_cents": 500000,
        "initial_reserve_balance_cents": 100000,
    }
    payload.update(overrides)
    return payload


def reserve_capped_agent(**overrides: Any) -> Dict[str, Any]:
    payload = producer_agent(
        agency_name="Gulf Coast Agency",
        chargeback_basis="RESERVE_CAPPED",
        chargeback_liability_cap_cents=25000,
        initial_reserve_balance_cents=50000,
    )
    payload.update(overrides)
    return payload


# ===========================================================================
# Insurer
# ===========================================================================
def insurer(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "carrier_name": "Meridian Casualty",
        "naic_code": "10123",
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# PremiumFinanceAgreement
# ===========================================================================
def agreement(
    insured_id: str,
    producer_agent_id: str,
    state_rule_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """The canonical 600k note terms: down 100000, fee 2000, 6 installments."""
    payload: Dict[str, Any] = {
        "insured_id": insured_id,
        "producer_agent_id": producer_agent_id,
        "state_rule_id": state_rule_id,
        "down_payment_cents": 100000,
        "service_fee_cents": 2000,
        "installment_count": 6,
        "first_installment_due_date": "2026-10-01",
    }
    payload.update(overrides)
    return payload


def tx9_agreement(
    insured_id: str,
    producer_agent_id: str,
    state_rule_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """The FIXTURE-TX9 note terms: down 300000, fee 2000, 9 installments."""
    return agreement(
        insured_id,
        producer_agent_id,
        state_rule_id,
        down_payment_cents=300000,
        service_fee_cents=2000,
        installment_count=9,
        **overrides,
    )


# ===========================================================================
# FinancedPolicy
# ===========================================================================
def financed_policy(insurer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "insurer_id": insurer_id,
        "policy_number": f"MC-GEN-{_seq():04d}",
        "gross_premium_cents": 600000,
        "effective_date": "2026-09-01",
        "expiration_date": "2027-09-01",
        "min_earned_days": 0,
        "fully_earned": False,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# PremiumVerification
# ===========================================================================
def confirmed_verification(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": "CONFIRMED"}
    payload.update(overrides)
    return payload


def corrected_verification(
    corrected_premium_cents: int,
    corrected_effective_date: str = "2026-09-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": "CORRECTED",
        "corrected_premium_cents": corrected_premium_cents,
        "corrected_effective_date": corrected_effective_date,
    }
    payload.update(overrides)
    return payload


def rejected_verification(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": "REJECTED"}
    payload.update(overrides)
    return payload


# ===========================================================================
# Payment
# ===========================================================================
def payment(amount_cents: int, received_date: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "received_date": received_date,
        "method": "ACH",
    }
    payload.update(overrides)
    return payload


def reversal(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reversal_reason": "NSF"}
    payload.update(overrides)
    return payload


# ===========================================================================
# LateFeeAssessment
# ===========================================================================
def waiver(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "justification": "one-time concession, first delinquency"
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# CarrierCancellationRequest
# ===========================================================================
def return_posting(
    carrier_returned_cents: int, posted_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "carrier_returned_cents": carrier_returned_cents,
        "posted_date": posted_date,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# PremiumEndorsement
# ===========================================================================
def endorsement(
    amount_cents: int = 50000,
    endorsement_type: str = "ADDITIONAL_PREMIUM",
    effective_date: str = "2026-09-15",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "endorsement_type": endorsement_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def decline_reason(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": "insured disputes the exposure change"}
    payload.update(overrides)
    return payload


# ===========================================================================
# AgentChargeback
# ===========================================================================
def chargeback_offset(
    offset_amount_cents: int, expected_chargeback_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "offset_amount_cents": offset_amount_cents,
        "expected_chargeback_version": expected_chargeback_version,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Restructure / rate exception
# ===========================================================================
def restructure(
    installment_count: int,
    first_installment_due_date: str,
    additional_down_payment_cents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "additional_down_payment_cents": additional_down_payment_cents,
        "installment_count": installment_count,
        "first_installment_due_date": first_installment_due_date,
    }
    payload.update(overrides)
    return payload


def rate_exception(
    override_annual_rate_bps: Optional[int] = None,
    override_service_fee_cents: Optional[int] = None,
    justification: str = "national account concession approved by pricing committee",
    **overrides: Any,
) -> Dict[str, Any]:
    """A rate-exception approval body.

    The justification is mandatory; each override is sent only when supplied, so
    that omitting one leaves the corresponding approved cap alone.
    """
    payload: Dict[str, Any] = {"justification": justification}
    if override_annual_rate_bps is not None:
        payload["override_annual_rate_bps"] = override_annual_rate_bps
    if override_service_fee_cents is not None:
        payload["override_service_fee_cents"] = override_service_fee_cents
    payload.update(overrides)
    return payload
