"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ─── Common-fields entities (id + created_at + updated_at + version) ─

def assert_common_fields(data: dict):
    """Asserts id (UUID), created_at, updated_at (ISO 8601), version (int>=1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_borrower(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 200
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["is_veteran"], bool)


def assert_loan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["borrower_id"])
    assert data["loan_type"] in ("DIRECT_SUB", "DIRECT_UNSUB", "DIRECT_PLUS")
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] >= 100
    assert isinstance(data["interest_rate_bps"], int)
    assert 1 <= data["interest_rate_bps"] <= 2000
    assert data["status"] in (
        "ORIGINATED", "IN_SCHOOL", "GRACE", "REPAYMENT",
        "DEFERMENT", "FORBEARANCE", "DEFAULT", "PAID_OFF", "DISCHARGED",
    )
    assert isinstance(data["principal_balance_cents"], int) and data["principal_balance_cents"] >= 0
    assert isinstance(data["accrued_interest_cents"], int) and data["accrued_interest_cents"] >= 0
    assert isinstance(data["capitalized_interest_cents"], int)
    assert data["capitalized_interest_cents"] >= 0


def assert_repayment_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["plan_type"] in ("STANDARD", "IBR", "PAYE", "SAVE")
    assert data["status"] in ("PENDING", "ACTIVE", "SUPERSEDED", "COMPLETED")
    assert isinstance(data["monthly_payment_cents"], int)
    assert data["monthly_payment_cents"] >= 0


def assert_income_certification(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["borrower_id"])
    assert isinstance(data["agi_cents"], int) and data["agi_cents"] >= 0
    assert isinstance(data["family_size"], int) and data["family_size"] >= 1
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in ("SUBMITTED", "CERTIFIED", "REJECTED", "EXPIRED")


def assert_qualifying_employment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["borrower_id"])
    assert data["employer_type"] in (
        "GOVERNMENT", "NONPROFIT_501C3", "OTHER_NONPROFIT", "PRIVATE_NONQUALIFYING",
    )
    assert data["status"] in ("SUBMITTED", "CERTIFIED", "REJECTED")


def assert_payment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in ("PENDING", "APPLIED", "REVERSED")


def assert_discharge_application(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["discharge_type"] in ("VETERAN_TOTAL_DISABILITY", "PSLF")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")


# ─── Append-only (no version, no updated_at) ───────────────

def assert_status_change(data: dict):
    """StatusChange — append-only audit log, carries only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["from_status"], str)
    assert isinstance(data["to_status"], str)
    assert data["reason_code"] in (
        "GRACE_AUTO_START", "GRACE_AUTO_END", "DEFERMENT_REQUEST",
        "FORBEARANCE_REQUEST", "RESUME_REPAYMENT", "DEFAULT_DECLARATION",
        "REHABILITATION_COMPLETE", "PAY_OFF", "DISCHARGE_APPROVED",
    )
    assert isinstance(data["actor_role"], str)
    assert is_iso8601_timestamp(data.get("effective_at", "")), \
        f"effective_at must be ISO 8601, got {data.get('effective_at')!r}"


# ─── Domain invariants ────────────────────────────────────

def assert_reversal_invariant(loan_before: dict, loan_after: dict,
                              applied_total_before: int, applied_total_after: int):
    """
    PRD §3.6 reversal invariant: within a single loan-status window,
    principal_balance_cents + accrued_interest_cents +
    sum(APPLIED Payments.principal_applied_cents + interest_applied_cents)
    is constant.
    """
    q_before = (loan_before["principal_balance_cents"]
                + loan_before["accrued_interest_cents"]
                + applied_total_before)
    q_after = (loan_after["principal_balance_cents"]
               + loan_after["accrued_interest_cents"]
               + applied_total_after)
    assert q_before == q_after, (
        f"Reversal invariant violated: Q_before={q_before} Q_after={q_after}"
    )
