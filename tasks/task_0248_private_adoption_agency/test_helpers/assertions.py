"""Entity assertions and domain invariant checkers (Private Adoption Agency API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["licensed_state"], str)
    assert isinstance(data["fee_schedule_cents"], int) and data["fee_schedule_cents"] >= 0


def assert_case(data: dict):
    _assert_common(data)
    assert data["phase"] in [
        "INTAKE", "HOME_STUDY", "MATCHED", "CONSENTED",
        "ICPC_CLEARED", "PLACED", "FINALIZED", "DISRUPTED",
    ]
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["reimbursable_expense_cents"], int)
    assert isinstance(data["interstate"], bool)


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["primary_applicant_name"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0


def assert_home_study(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "RESUBMITTED", "DEFICIENT", "APPROVED", "EXPIRED",
    ]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_birth_parent(data: dict):
    _assert_common(data)
    assert data["parent_role"] in ["BIRTH_MOTHER", "BIRTH_FATHER", "LEGAL_GUARDIAN"]


def assert_counseling_session(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "HELD", "CANCELLED"]


def assert_match(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "DECLINED", "DISSOLVED"]


def assert_consent_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "SIGNED", "REVOKED", "IRREVOCABLE"]
    assert data["revocation_basis"] in ["CALENDAR_DAYS", "BUSINESS_DAYS"]


def assert_icpc_clearance(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "NOT_REQUIRED", "DRAFT", "SUBMITTED",
        "SENDING_APPROVED", "RECEIVING_APPROVED", "REJECTED",
    ]


def assert_placement(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "ACTIVE", "FINALIZED", "DISRUPTED"]
    assert isinstance(data["required_visits"], int)
    assert isinstance(data["completed_visit_count"], int)


def assert_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED"]


def assert_expense(data: dict):
    _assert_common(data)
    assert data["status"] in ["LOGGED", "APPROVED", "REJECTED", "DISBURSED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "PAID", "VOID"]
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)


def assert_escrow_transaction(data: dict):
    """EscrowTransaction is an append-only ledger record (PRD §2.4): only id and
    created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["txn_type"] in ["DEPOSIT", "DISBURSEMENT", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
