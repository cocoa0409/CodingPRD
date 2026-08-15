"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_POLICY_STATUSES = ["ACTIVE", "LAPSED"]
_DESIGNATION_STATUSES = ["ACTIVE", "REVOKED"]
_CLAIM_STATUSES = [
    "NOTIFIED", "UNDER_REVIEW", "CONTESTABILITY_REVIEW", "LEGAL_HOLD",
    "APPROVED", "PAID", "DENIED", "RESCINDED", "INTERPLEADED", "ESCHEATED",
]
_DOC_RESULTS = ["PENDING", "VERIFIED", "REJECTED"]
_DOC_TYPES = [
    "CERTIFIED_DEATH_CERTIFICATE", "ATTENDING_PHYSICIAN_STATEMENT",
    "FUNERAL_HOME_STATEMENT",
]
_BENEFICIARY_CLAIM_STATUSES = [
    "SUBMITTED", "VALIDATED", "DISPUTED", "PAYABLE", "PAID",
    "REJECTED", "WITHDRAWN", "INTERPLEADED", "ESCHEATED",
]
_ELECTION_STATUSES = ["ELECTED", "CONFIRMED", "SUSPENDED", "SUPERSEDED"]
_ELECTION_OPTIONS = ["LUMP_SUM", "RETAINED_ASSET_ACCOUNT"]
_ACCOUNT_STATUSES = ["OPEN", "DORMANT", "CLOSED", "ESCHEATED"]
_MATCH_STATUSES = ["PENDING_REVIEW", "CONFIRMED", "FALSE_POSITIVE"]
_CASE_STATUSES = ["MONITORING", "DUE_DILIGENCE", "ESCHEATED", "RESOLVED"]
_CASE_SUBJECTS = ["CLAIM_PROCEEDS", "RETAINED_ASSET_ACCOUNT"]
_INTEREST_BASES = ["DATE_OF_DEATH", "PROOF_OF_LOSS_COMPLETE"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["insured_name"], str) and data["insured_name"]
    assert isinstance(data["face_amount_cents"], int) and data["face_amount_cents"] > 0
    assert isinstance(data["contestability_months"], int)
    assert data["status"] in _POLICY_STATUSES
    assert data["lapse_date"] is None or isinstance(data["lapse_date"], str)


def assert_beneficiary_designation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["beneficiary_name"], str) and data["beneficiary_name"]
    assert data["beneficiary_type"] in ["PRIMARY", "CONTINGENT"]
    assert 0 < float(data["share_percent"]) <= 100
    assert isinstance(data["effective_date"], str)
    assert data["status"] in _DESIGNATION_STATUSES
    assert data["revoked_at"] is None or isinstance(data["revoked_at"], str)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["date_of_death"], str)
    assert isinstance(data["notification_date"], str)
    assert isinstance(data["face_amount_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)
    assert isinstance(data["contestability_flag"], bool)
    assert data["status"] in _CLAIM_STATUSES
    assert data["proof_complete_date"] is None or isinstance(data["proof_complete_date"], str)
    assert data["total_payable_cents"] is None or isinstance(data["total_payable_cents"], int)
    assert data["approved_at"] is None or isinstance(data["approved_at"], str)
    assert data["paid_at"] is None or isinstance(data["paid_at"], str)


def assert_death_document(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["doc_type"] in _DOC_TYPES
    assert isinstance(data["uploaded_by_id"], str) and data["uploaded_by_id"]
    assert data["review_result"] in _DOC_RESULTS
    assert data["reviewed_by_id"] is None or isinstance(data["reviewed_by_id"], str)


def assert_beneficiary_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["claimant_name"], str) and data["claimant_name"]
    assert data["claimant_type"] in ["NAMED_BENEFICIARY", "ESTATE"]
    assert data["status"] in _BENEFICIARY_CLAIM_STATUSES
    assert data["allocated_amount_cents"] is None \
        or isinstance(data["allocated_amount_cents"], int)
    assert data["paid_amount_cents"] is None or isinstance(data["paid_amount_cents"], int)


def assert_payout_election(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["beneficiary_claim_id"], str)
    assert data["option"] in _ELECTION_OPTIONS
    assert data["status"] in _ELECTION_STATUSES
    assert is_iso8601_timestamp(data["elected_at"])
    assert data["confirmed_at"] is None or is_iso8601_timestamp(data["confirmed_at"])


def assert_retained_asset_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["beneficiary_claim_id"], str)
    assert isinstance(data["deposited_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["withdrawn_total_cents"], int)
    assert isinstance(data["provisional_interest_cents"], int)
    assert isinstance(data["interest_paid_cents"], int)
    assert data["status"] in _ACCOUNT_STATUSES


def assert_state_statute(data: dict):
    # Configuration record: only id + created_at, no updated_at/version (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["annual_interest_rate_bp"], int)
    assert data["interest_basis"] in _INTEREST_BASES
    assert isinstance(data["grace_days"], int)
    assert isinstance(data["dormancy_years"], int)
    assert isinstance(data["raa_minimum_cents"], int)
    assert isinstance(data["raa_annual_interest_rate_bp"], int)


def assert_death_master_match(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["deceased_name"], str)
    assert isinstance(data["deceased_dob"], str)
    assert isinstance(data["deceased_death_date"], str)
    assert isinstance(data["match_score"], int) and 0 <= data["match_score"] <= 100
    assert data["status"] in _MATCH_STATUSES
    assert data["generated_claim_id"] is None or isinstance(data["generated_claim_id"], str)


def assert_escheatment_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["subject_type"] in _CASE_SUBJECTS
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["trigger_date"], str)
    assert isinstance(data["escheat_due_date"], str)
    assert isinstance(data["due_diligence_start_date"], str)
    assert data["status"] in _CASE_STATUSES
    assert data["account_id"] is None or isinstance(data["account_id"], str)


def assert_raa_principal_invariant(account: dict):
    """PRD §3.9 principal conservation: deposits equal balance plus withdrawals."""
    assert account["balance_cents"] + account["withdrawn_total_cents"] \
        == account["deposited_cents"], (
            f"principal invariant broken: {account['balance_cents']} + "
            f"{account['withdrawn_total_cents']} != {account['deposited_cents']}"
        )
