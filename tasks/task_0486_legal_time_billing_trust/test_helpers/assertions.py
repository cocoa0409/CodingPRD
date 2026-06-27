"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. All field names are exactly as the PRD names them. The leaner
entities (BillingCode, TrustTransaction) are asserted WITHOUT version/updated_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def _assert_lean(data: dict):
    """For BillingCode / TrustTransaction: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["client_type"] in ("INDIVIDUAL", "ORGANIZATION")
    assert data["status"] in ("PROSPECT", "ACTIVE", "INACTIVE")
    assert isinstance(data["ar_balance_cents"], int)


def assert_timekeeper(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role_kind"] in ("PARTNER", "ASSOCIATE", "PARALEGAL")
    assert isinstance(data["standard_rate_cents"], int)
    assert isinstance(data["is_active"], bool)


def assert_matter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["responsible_timekeeper_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in (
        "INTAKE", "CONFLICT_PENDING", "CONFLICT_CLEARED",
        "CONFLICT_BLOCKED", "OPEN", "CLOSED",
    )
    assert isinstance(data["wip_fees_cents"], int)
    assert isinstance(data["wip_expenses_cents"], int)


def assert_conflict_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["adverse_party_name"], str) and len(data["adverse_party_name"]) > 0
    assert data["result"] in ("CLEAR", "FLAGGED", "WAIVED")


def assert_time_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["timekeeper_id"])
    assert isinstance(data["minutes"], int) and data["minutes"] > 0
    assert isinstance(data["resolved_rate_cents"], int)
    assert isinstance(data["billable_amount_cents"], int)
    assert data["status"] in ("CAPTURED", "INVOICED", "WRITTEN_DOWN")


def assert_expense_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("CAPTURED", "INVOICED", "WRITTEN_DOWN")


def assert_billing_code(data: dict):
    _assert_lean(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["kind"] in ("TASK", "ACTIVITY", "EXPENSE")
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    # leaner entity: no version, no updated_at
    assert "version" not in data, "BillingCode must not expose version"
    assert "updated_at" not in data, "BillingCode must not expose updated_at"


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["fees_subtotal_cents"], int)
    assert isinstance(data["expenses_subtotal_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert data["billing_status"] in (
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF", "VOID",
    )
    assert data["collection_status"] in (
        "CURRENT", "DUE", "OVERDUE", "IN_COLLECTIONS", "SETTLED",
    )


def assert_trust_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["book_balance_cents"], int)
    assert isinstance(data["bank_balance_cents"], int)


def assert_client_trust_ledger(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["trust_account_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["retainer_floor_cents"], int)


def assert_retainer_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_trust_ledger_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_trust_transaction(data: dict):
    _assert_lean(data)
    assert is_valid_uuid(data["client_trust_ledger_id"])
    assert data["kind"] in ("DEPOSIT", "DISBURSEMENT", "SWEEP_TO_OPERATING")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PENDING", "CONFIRMED", "VOIDED")
    # leaner entity: no version, no updated_at
    assert "version" not in data, "TrustTransaction must not expose version"
    assert "updated_at" not in data, "TrustTransaction must not expose updated_at"


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CHECK", "ACH", "CARD")
    assert data["status"] in ("APPLIED", "REVERSED")


def assert_three_way_book_equals_client(recon: dict):
    """Hard invariant (PRD §2.8): book leg always equals sum of client sub-ledgers."""
    assert recon["leg_book_cents"] == recon["leg_client_cents"], \
        f"book leg {recon['leg_book_cents']} must equal client leg {recon['leg_client_cents']}"
