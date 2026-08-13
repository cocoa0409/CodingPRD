"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AlertStatus,
    AlertType,
    AmendmentStatus,
    AppealChannel,
    AppealOutcome,
    AppealStatus,
    CASE_TERMINAL_STATUSES,
    CaseStatus,
    ClaimRemittanceStatus,
    ContractStatus,
    EscalatorStatus,
    NetworkAgreementStatus,
    NetworkFlag,
    PayerStatus,
    PayerType,
    PricingStatus,
    PricingVariant,
    ProposalStatus,
    ProvisionType,
    RateModel,
    RemittanceSource,
    RemittanceStatus,
    ServiceCategory,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_payer(data: dict):
    _assert_common(data, "Payer")
    assert isinstance(data["name"], str) and data["name"]
    assert data["payer_type"] in {e.value for e in PayerType}
    assert isinstance(data["appeal_deadline_days"], int)
    assert data["status"] in {e.value for e in PayerStatus}


def assert_payer_contract(data: dict):
    _assert_common(data, "PayerContract")
    assert is_valid_uuid(data.get("payer_id", ""))
    assert isinstance(data["contract_code"], str) and data["contract_code"]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiration_date"], str)
    assert data["status"] in {e.value for e in ContractStatus}
    assert isinstance(data.get("open_underpayment_cents"), int)


def assert_contract_term(data: dict):
    _assert_common(data, "ContractTerm")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["service_category"] in {e.value for e in ServiceCategory}
    assert data["rate_model"] in {e.value for e in RateModel}


def assert_carve_out_provision(data: dict):
    _assert_common(data, "CarveOutProvision")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["revenue_codes"], list) and data["revenue_codes"]
    assert data["rate_model"] in ("PERCENT_OF_CHARGE", "INVOICE_COST_PLUS")


def assert_stop_loss_provision(data: dict):
    _assert_common(data, "StopLossProvision")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["provision_type"] in {e.value for e in ProvisionType}
    assert isinstance(data["threshold_cents"], int) and data["threshold_cents"] > 0
    assert isinstance(data["rate_bp"], int)


def assert_rate_escalator(data: dict):
    _assert_common(data, "RateEscalator")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["escalator_bp"], int) and data["escalator_bp"] > 0
    assert data["status"] in {e.value for e in EscalatorStatus}


def assert_rate_amendment(data: dict):
    _assert_common(data, "RateAmendment")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["term_overrides"], list) and data["term_overrides"]
    assert data["status"] in {e.value for e in AmendmentStatus}
    assert isinstance(data.get("created_by_user_id"), str)


def assert_network_agreement(data: dict):
    _assert_common(data, "NetworkAgreement")
    assert is_valid_uuid(data.get("payer_id", ""))
    assert isinstance(data["network_name"], str) and data["network_name"]
    assert 0 < data["wrap_rate_bp"] <= 10000
    assert data["status"] in {e.value for e in NetworkAgreementStatus}


def assert_claim(data: dict):
    _assert_common(data, "Claim")
    assert is_valid_uuid(data.get("payer_id", ""))
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert data["service_category"] in {e.value for e in ServiceCategory}
    assert isinstance(data["total_billed_charges_cents"], int)
    assert data["total_billed_charges_cents"] >= 0
    assert data["pricing_status"] in {e.value for e in PricingStatus}
    assert data["remittance_status"] in {e.value for e in ClaimRemittanceStatus}
    assert data["network_flag"] in {e.value for e in NetworkFlag}
    if data.get("pricing_variant") is not None:
        assert data["pricing_variant"] in {e.value for e in PricingVariant}
    if data.get("pricing_trace") is not None:
        assert isinstance(data["pricing_trace"], dict)


def assert_claim_line(data: dict):
    _assert_common(data, "ClaimLine")
    assert isinstance(data["revenue_code"], str) and data["revenue_code"]
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert isinstance(data["units"], int) and data["units"] >= 1


def assert_remittance(data: dict):
    _assert_common(data, "Remittance")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert data["source"] in {e.value for e in RemittanceSource}
    assert data["status"] in {e.value for e in RemittanceStatus}


def assert_underpayment_case(data: dict):
    _assert_common(data, "UnderpaymentCase")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert is_valid_uuid(data.get("payer_id", ""))
    assert data["status"] in {e.value for e in CaseStatus}
    assert isinstance(data["original_variance_cents"], int)
    assert isinstance(data["current_outstanding_cents"], int)
    assert isinstance(data["recovered_to_date_cents"], int)
    assert isinstance(data["write_off_amount_cents"], int)
    assert isinstance(data["escalation_level"], int)


def assert_case_money_ledger(case: dict):
    """PRD §3.7 invariant: original_variance_cents always equals
    current_outstanding_cents + recovered_to_date_cents + write_off_amount_cents."""
    lhs = case["original_variance_cents"]
    rhs = (
        case["current_outstanding_cents"]
        + case["recovered_to_date_cents"]
        + case["write_off_amount_cents"]
    )
    assert lhs == rhs, (
        f"Case money ledger broken: original {lhs} != outstanding "
        f"{case['current_outstanding_cents']} + recovered "
        f"{case['recovered_to_date_cents']} + write_off {case['write_off_amount_cents']}"
    )


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["level"] in (1, 2, 3, 4)
    assert data["channel"] in {e.value for e in AppealChannel}
    assert data["status"] in {e.value for e in AppealStatus}
    assert data["outcome"] in {e.value for e in AppealOutcome}
    assert isinstance(data["recovered_amount_cents"], int)


def assert_contract_proposal(data: dict):
    _assert_common(data, "ContractProposal")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["proposed_terms"], list) and data["proposed_terms"]
    assert isinstance(data["projected_volume_mix"], list)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in {e.value for e in ProposalStatus}


def assert_contract_alert(data: dict):
    _assert_common(data, "ContractAlert")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["alert_type"] in {e.value for e in AlertType}
    assert data["status"] in {e.value for e in AlertStatus}


def assert_claim_paid_variance_ledger(claim: dict):
    """PRD §3.6: paid_amount_cents + variance_cents == expected_reimbursement_cents
    for any priced claim."""
    expected = claim["expected_reimbursement_cents"]
    total = claim["paid_amount_cents"] + claim["variance_cents"]
    assert total == expected, (
        f"Claim ledger broken: paid {claim['paid_amount_cents']} + variance "
        f"{claim['variance_cents']} != expected {expected}"
    )


__all__ = [name for name in dir() if name.startswith("assert_")] + ["CASE_TERMINAL_STATUSES"]
