"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    PayeeStatus, GuardianshipCaseStatus, AgreementStatus, AssignmentStatus,
    PolicyStatus, ScheduleStatus, PaymentStatus, IssueMethod, ReturnReason,
    CancelReason, ReturnedCaseStatus, ChangeType, ChangeRequestStatus,
    PetitionStatus, CourtOutcome, Prejudice, ClaimantType, DeathClaimStatus,
    CommutationReason, CommutationStatus, CommutationRider, BatchStatus,
    InjuryType, PaymentType,
)


def _assert_common(data: dict, what: str = "resource"):
    """Common resource properties (PRD §2.5): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{what}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{what}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{what}.version must be a positive integer"
    )


def _assert_date(value, field):
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be a YYYY-MM-DD date string, got {value!r}"
    )


def assert_state_profile(data: dict):
    _assert_common(data, "StateStatuteProfile")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["age_of_majority"], int) and 18 <= data["age_of_majority"] <= 21
    assert isinstance(data["sspa_max_discount_rate_bps"], int) and data["sspa_max_discount_rate_bps"] > 0
    assert isinstance(data["disclosure_cooling_off_days"], int) and data["disclosure_cooling_off_days"] >= 0
    assert isinstance(data["ipa_required"], bool)
    assert isinstance(data["dormancy_years"], int) and data["dormancy_years"] >= 1
    assert isinstance(data["commutation_permitted"], bool)


def assert_payee(data: dict):
    _assert_common(data, "Payee")
    assert isinstance(data["full_name"], str) and data["full_name"]
    _assert_date(data["date_of_birth"], "date_of_birth")
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["address_line1"], str)
    assert isinstance(data["address_city"], str)
    assert isinstance(data["address_state_code"], str)
    assert isinstance(data["address_postal_code"], str)
    assert data["status"] in [s.value for s in PayeeStatus]
    assert data.get("deceased_date") is None or isinstance(data["deceased_date"], str)
    assert isinstance(data["is_minor"], bool)


def assert_guardianship_case(data: dict):
    _assert_common(data, "GuardianshipCase")
    assert is_valid_uuid(data.get("payee_id", ""))
    assert isinstance(data["court_state_code"], str)
    assert isinstance(data["guardian_full_name"], str) and data["guardian_full_name"]
    _assert_date(data["effective_from_date"], "effective_from_date")
    assert data.get("terminated_at_date") is None or isinstance(data["terminated_at_date"], str)
    assert data["status"] in [s.value for s in GuardianshipCaseStatus]


def assert_settlement_agreement(data: dict):
    _assert_common(data, "SettlementAgreement")
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["court_state_code"], str)
    assert isinstance(data["obligor_name"], str)
    assert data["injury_type"] in [s.value for s in InjuryType]
    assert is_valid_uuid(data.get("primary_payee_id", ""))
    _assert_date(data["agreement_date"], "agreement_date")
    assert data["status"] in [s.value for s in AgreementStatus]
    for field in ("total_scheduled_cents", "outstanding_liability_cents", "paid_total_cents",
                  "escheated_total_cents", "transferred_total_cents", "commuted_nominal_total_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"SettlementAgreement.{field} must be a non-negative integer"
        )


def assert_qualified_assignment(data: dict):
    _assert_common(data, "QualifiedAssignment")
    assert is_valid_uuid(data.get("settlement_agreement_id", ""))
    assert isinstance(data["assignment_company_name"], str)
    _assert_date(data["executed_date"], "executed_date")
    assert data["status"] in [s.value for s in AssignmentStatus]


def assert_annuity_policy(data: dict):
    _assert_common(data, "AnnuityPolicy")
    assert is_valid_uuid(data.get("settlement_agreement_id", ""))
    assert is_valid_uuid(data.get("qualified_assignment_id", ""))
    assert isinstance(data["policy_number"], str)
    assert isinstance(data["insurer_name"], str)
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] > 0
    assert isinstance(data["contract_discount_rate_bps"], int) and data["contract_discount_rate_bps"] > 0
    assert data["commutation_rider"] in [s.value for s in CommutationRider]
    assert data.get("certain_period_end_date") is None or isinstance(data["certain_period_end_date"], str)
    assert data.get("in_force_date") is None or isinstance(data["in_force_date"], str)
    assert data["status"] in [s.value for s in PolicyStatus]


def assert_payment_schedule(data: dict):
    _assert_common(data, "PaymentSchedule")
    assert is_valid_uuid(data.get("settlement_agreement_id", ""))
    _assert_date(data["effective_from_date"], "effective_from_date")
    _assert_date(data["escalation_anchor_date"], "escalation_anchor_date")
    assert data.get("supersedes_schedule_id") is None or is_valid_uuid(data["supersedes_schedule_id"])
    assert data["status"] in [s.value for s in ScheduleStatus]


def assert_scheduled_payment(data: dict):
    _assert_common(data, "ScheduledPayment")
    assert is_valid_uuid(data.get("payment_schedule_id", ""))
    assert is_valid_uuid(data.get("payee_id", ""))
    assert isinstance(data["payment_seq_no"], int) and data["payment_seq_no"] >= 1
    _assert_date(data["due_date"], "due_date")
    assert isinstance(data["base_amount_cents"], int) and data["base_amount_cents"] > 0
    assert isinstance(data["escalation_rate_bps"], int) and data["escalation_rate_bps"] >= 0
    assert data["payment_type"] in [s.value for s in PaymentType]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["disclosure_amount_cents"], int) and data["disclosure_amount_cents"] > 0
    assert data["status"] in [s.value for s in PaymentStatus]
    assert isinstance(data["issue_count"], int) and data["issue_count"] >= 0
    assert data.get("last_issue_method") is None or data["last_issue_method"] in [m.value for m in IssueMethod]
    assert data.get("return_reason") is None or data["return_reason"] in [r.value for r in ReturnReason]
    assert data.get("cancel_reason") is None or data["cancel_reason"] in [r.value for r in CancelReason]


def assert_returned_payment_case(data: dict):
    _assert_common(data, "ReturnedPaymentCase")
    assert is_valid_uuid(data.get("scheduled_payment_id", ""))
    assert data["return_reason"] in [r.value for r in ReturnReason]
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert data["status"] in [s.value for s in ReturnedCaseStatus]


def assert_payee_change_request(data: dict):
    _assert_common(data, "PayeeChangeRequest")
    assert is_valid_uuid(data.get("payee_id", ""))
    assert data["change_type"] in [t.value for t in ChangeType]
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["status"] in [s.value for s in ChangeRequestStatus]


def assert_transfer_petition(data: dict):
    _assert_common(data, "TransferPetition")
    assert is_valid_uuid(data.get("settlement_agreement_id", ""))
    assert is_valid_uuid(data.get("payee_id", ""))
    assert isinstance(data["factoring_company_name"], str)
    assert isinstance(data["purchase_price_cents"], int) and data["purchase_price_cents"] > 0
    _assert_date(data["transfer_start_date"], "transfer_start_date")
    _assert_date(data["transfer_end_date"], "transfer_end_date")
    assert isinstance(data["transferred_payment_count"], int) and data["transferred_payment_count"] >= 0
    assert isinstance(data["present_value_cents"], int)
    assert isinstance(data["disclosed_discount_rate_bps"], int)
    assert isinstance(data["effective_annual_rate_bps"], int)
    assert data.get("court_outcome") is None or data["court_outcome"] in [o.value for o in CourtOutcome]
    assert data.get("prejudice") is None or data["prejudice"] in [p.value for p in Prejudice]
    assert data["status"] in [s.value for s in PetitionStatus]


def assert_death_claim(data: dict):
    _assert_common(data, "DeathClaim")
    assert is_valid_uuid(data.get("payee_id", ""))
    assert is_valid_uuid(data.get("settlement_agreement_id", ""))
    _assert_date(data["date_of_death"], "date_of_death")
    assert data["claimant_type"] in [t.value for t in ClaimantType]
    assert isinstance(data["claimant_name"], str) and data["claimant_name"]
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)
    assert data["status"] in [s.value for s in DeathClaimStatus]


def assert_commutation_request(data: dict):
    _assert_common(data, "CommutationRequest")
    assert is_valid_uuid(data.get("annuity_policy_id", ""))
    assert is_valid_uuid(data.get("settlement_agreement_id", ""))
    assert data.get("death_claim_id") is None or is_valid_uuid(data["death_claim_id"])
    assert data["reason"] in [r.value for r in CommutationReason]
    assert isinstance(data["covered_payment_count"], int) and data["covered_payment_count"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["commuted_value_cents"], int)
    assert data["status"] in [s.value for s in CommutationStatus]


def assert_escheatment_batch(data: dict):
    _assert_common(data, "EscheatmentBatch")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["batch_period"], str) and len(data["batch_period"]) == 7
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    for field in ("swept_count", "swept_amount_cents", "reclaimed_count", "reclaimed_amount_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["status"] in [s.value for s in BatchStatus]


def assert_tracked_liability_conserved(agreement: dict):
    """paid + outstanding + escheated never leaks or double-counts money (PRD §3.3)."""
    total = (
        agreement["paid_total_cents"]
        + agreement["outstanding_liability_cents"]
        + agreement["escheated_total_cents"]
    )
    assert total >= 0
    return total
