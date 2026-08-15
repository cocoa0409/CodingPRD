"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


CLAIM_STATUSES = [
    "SUBMITTED", "ELIGIBILITY_PASSED", "RECORDS_PENDING", "INJURY_VERIFIED",
    "TIER_ASSIGNED", "LIENS_PENDING", "LIENS_RESOLVED", "READY_FOR_DISBURSEMENT",
    "DISBURSED", "CLOSED", "DENIED", "WITHDRAWN",
]


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be int >= 1"


def assert_settlement_program(data: dict):
    _assert_common(data, "SettlementProgram")
    assert isinstance(data["program_code"], str) and len(data["program_code"]) > 0
    assert isinstance(data["tort_name"], str) and len(data["tort_name"]) > 0
    assert isinstance(data["qsf_principal_cents"], int)
    assert isinstance(data["qsf_remaining_cents"], int)
    assert isinstance(data["matrix_published"], bool)
    assert data["qsf_remaining_cents"] <= data["qsf_principal_cents"], "QSF remainder cannot exceed principal"


def assert_claimant(data: dict):
    _assert_common(data, "Claimant")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4 and data["ssn_last4"].isdigit()
    assert data["injury_category"] in ["QUALIFYING_CAT_A", "QUALIFYING_CAT_B", "NON_QUALIFYING"]
    assert isinstance(data["represented_by_counsel"], bool)
    assert data.get("duplicate_of_claimant_id") is None or is_valid_uuid(data["duplicate_of_claimant_id"])


def assert_claim(data: dict):
    _assert_common(data, "Claim")
    assert data["status"] in CLAIM_STATUSES
    assert data["eligibility_status"] in ["PENDING", "PASSED", "FAILED"]
    assert data["injury_verification_status"] in ["PENDING", "VERIFIED", "REJECTED"]
    assert data["lien_posture"] in ["NOT_STARTED", "IDENTIFYING", "NEGOTIATING", "ALL_RESOLVED"]
    assert isinstance(data["claim_number"], str) and data["claim_number"].startswith("CLM-")
    for f in ("gross_award_cents", "total_lien_cents", "attorney_fee_cents", "net_award_cents", "qsf_reservation_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"Claim.{f} must be non-negative int"
    assert data.get("active_appeal_id") is None or is_valid_uuid(data["active_appeal_id"])


def assert_claim_invariants(data: dict):
    """Net-award reconciliation must hold after every money-affecting event (PRD §3.7)."""
    assert_claim(data)
    assert data["net_award_cents"] == max(
        0, data["gross_award_cents"] - data["total_lien_cents"] - data["attorney_fee_cents"]
    ), "net_award_cents must equal gross - liens - fee, floored at zero"


def assert_tier_matrix(data: dict):
    _assert_common(data, "TierMatrix")
    assert data["injury_category"] in ["QUALIFYING_CAT_A", "QUALIFYING_CAT_B"]
    assert isinstance(data["severity_score_min"], int)
    assert isinstance(data["severity_score_max"], int)
    assert data["severity_score_min"] <= data["severity_score_max"]
    assert isinstance(data["base_award_cents"], int) and data["base_award_cents"] >= 0
    assert data["matrix_state"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]


def assert_medical_record(data: dict):
    _assert_common(data, "MedicalRecord")
    assert isinstance(data["provider_name"], str) and len(data["provider_name"]) > 0
    assert data["record_type"] in ["DIAGNOSTIC", "TREATMENT", "PHARMACY", "HOSPITALIZATION"]
    assert isinstance(data["severity_score"], int) and 0 <= data["severity_score"] <= 100
    assert isinstance(data["confirms_qualifying_injury"], bool)
    assert data["review_state"] in ["PENDING_REVIEW", "ACCEPTED", "REJECTED"]
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"


def assert_lien(data: dict):
    _assert_common(data, "Lien")
    assert data["lien_type"] in ["MEDICARE", "MEDICAID", "PRIVATE_INSURER", "MEDICAL_PROVIDER", "VA_TRICARE"]
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert isinstance(data["asserted_amount_cents"], int) and data["asserted_amount_cents"] >= 0
    assert data["state"] in ["IDENTIFIED", "NOTIFIED", "IN_NEGOTIATION", "RESOLVED", "WAIVED", "DISPUTED"]


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert is_valid_uuid(data.get("appealed_tier_matrix_id", "")), "appealed_tier_matrix_id must be UUID"
    assert is_valid_uuid(data.get("requested_tier_matrix_id", "")), "requested_tier_matrix_id must be UUID"
    assert isinstance(data["grounds"], str) and len(data["grounds"]) >= 20
    assert data["state"] in ["FILED", "UNDER_REVIEW", "UPHELD", "DENIED", "WITHDRAWN"]


def assert_disbursement(data: dict):
    _assert_common(data, "Disbursement")
    assert isinstance(data["payee_name"], str) and len(data["payee_name"]) > 0
    assert data["payee_role"] in ["CLAIMANT", "ATTORNEY", "LIEN_HOLDER"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["state"] in ["PENDING", "APPROVED", "RELEASED", "VOIDED"]
    assert data.get("released_at") is None or is_iso8601_timestamp(data["released_at"])


def assert_closing_statement(data: dict):
    """Append-only artifact: id + created_at only — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ClosingStatement.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ClosingStatement must not carry version"
    assert "updated_at" not in data, "ClosingStatement must not carry updated_at"
    for f in ("gross_award_cents", "total_lien_cents", "attorney_fee_cents", "net_award_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"ClosingStatement.{f} must be non-negative int"
    assert isinstance(data["statement_body"], str)
    assert is_iso8601_timestamp(data.get("sealed_at", "")), "sealed_at must be ISO 8601"


def assert_disbursement_conservation(disbursements: list, expected_net_award_cents: int):
    """Sum of a claim's disbursement amounts equals net_award_cents exactly (PRD §3.7)."""
    total = sum(d["amount_cents"] for d in disbursements)
    assert total == expected_net_award_cents, (
        f"Disbursement amounts must sum to net_award_cents ({expected_net_award_cents}), got {total}"
    )
