"""Entity assertions and domain invariant checkers.

Each assert_{entity}() checks the system-managed fields and the field types
the PRD guarantees on a fresh read. Invariant checkers validate cross-field
relationships the PRD states must always hold.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (common_fields:true entities)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_company(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["currency"], str) and data["currency"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["billing_model"] in ("CHARGE", "CREDIT")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["available_credit_cents"], int)


def assert_spend_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["per_transaction_limit_cents"], int)
    assert isinstance(data["approval_threshold_cents"], int)
    assert isinstance(data["blocked_mcc_codes"], list)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["email"], str) and data["email"]
    assert data["employee_role"] in ("CARDHOLDER", "APPROVER", "FINANCE_ADMIN")
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_gl_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["gl_code"], str) and data["gl_code"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_card(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["spend_policy_id"], str)
    assert data["form_factor"] in ("VIRTUAL", "PHYSICAL")
    assert isinstance(data["card_limit_cents"], int)
    assert isinstance(data["held_cents"], int)
    assert data["status"] in ("REQUESTED", "ACTIVE", "FROZEN", "TERMINATED")


def assert_transaction(data: dict):
    _assert_common(data)
    assert isinstance(data["card_id"], str)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["merchant_name"], str)
    assert isinstance(data["mcc_code"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["auth_status"] in ("PENDING", "CLEARED", "SETTLED", "REVERSED")
    assert data["review_status"] in (
        "UNREVIEWED", "NEEDS_RECEIPT", "MATCHED", "APPROVED", "FLAGGED")


def assert_receipt(data: dict):
    """Receipt is immutable (PRD §2.4): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["transaction_id"], str)
    assert data["match_result"] in ("MATCH", "MISMATCH")


def assert_receipt_immutable_shape(data: dict):
    """PRD §2.4: a Receipt has no updated_at and no version field."""
    assert "version" not in data, "Receipt must not carry a version field"
    assert "updated_at" not in data, "Receipt must not carry an updated_at field"


def assert_approval_request(data: dict):
    _assert_common(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["requester_employee_id"], str)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_reimbursement_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["receipt_amount_cents"], int)
    assert isinstance(data["reimbursable_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "PAID")


def assert_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["closing_balance_cents"], int)
    assert isinstance(data["minimum_due_cents"], int)
    assert isinstance(data["amount_repaid_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED", "DUE", "PAID", "PAST_DUE")


def assert_repayment(data: dict):
    _assert_common(data)
    assert isinstance(data["statement_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("INITIATED", "CLEARED", "FAILED", "REVERSED")


def assert_reward_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["accrued_points_cents"], int)
    assert isinstance(data["redeemed_points_cents"], int)
    assert isinstance(data["balance_points_cents"], int)


def assert_spend_authorization(data: dict):
    _assert_common(data)
    assert data["scope"] in ("EMPLOYEE", "CARD")
    assert isinstance(data["employee_id"], str)
    assert isinstance(data["budget_cents"], int)
    assert data["status"] in ("ACTIVE", "CONSUMED", "CANCELLED")


def assert_erp_sync_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["statement_id"], str)
    assert isinstance(data["entry_count"], int)
    assert isinstance(data["total_debits_cents"], int)
    assert data["status"] in ("BUILT", "POSTED", "DISCARDED")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_reward_balance_consistent(data: dict):
    """PRD §3.8: balance_points_cents is accrued minus redeemed."""
    assert data["balance_points_cents"] == (
        data["accrued_points_cents"] - data["redeemed_points_cents"]
    ), "balance_points_cents must equal accrued_points_cents - redeemed_points_cents"
