"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    VendorStatus,
    BankAccountStatus,
    CallbackStatus,
    DocumentStatus,
    DocType,
    WatchlistSeverity,
    WatchlistStatus,
    ScreeningSubjectType,
    ScreeningResult,
    CaseStatus,
    CaseOpenedReason,
    InvoiceStatus,
    MatrixRuleStatus,
    PaymentRunStatus,
    PaymentStatus,
    PaymentMethod,
    VoidReason,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp from the API into an aware datetime."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_timestamp_equals(actual: str, expected_iso: str, context: str = ""):
    """Assert an API timestamp equals an expected instant (logical-clock time)."""
    expected = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    assert parse_timestamp(actual) == expected, (
        f"Expected timestamp {expected_iso}, got {actual} {context}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(VendorStatus)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["remit_email"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["address_line1"], str)
    assert isinstance(data["city"], str)
    assert isinstance(data["country"], str)
    assert isinstance(data["payment_terms_days"], int)
    assert isinstance(data["early_pay_discount_pct"], (int, float))
    assert isinstance(data["discount_window_days"], int)
    assert isinstance(data["duplicate_review_required"], bool)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_bank_account(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(BankAccountStatus)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["account_number"], str)
    assert isinstance(data["routing_number"], str)
    assert isinstance(data["account_holder_name"], str)
    assert isinstance(data["is_primary"], bool)
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]


def assert_callback_verification(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(CallbackStatus)
    assert isinstance(data["bank_account_id"], str)
    assert isinstance(data["attempts"], int)
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_vendor_document(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(DocumentStatus)
    assert data["doc_type"] in _enum_values(DocType)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)


def assert_watchlist_entry(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(WatchlistStatus)
    assert data["severity"] in _enum_values(WatchlistSeverity)
    assert isinstance(data["name_pattern"], str)
    assert isinstance(data["list_source"], str)


def assert_screening_check(data: dict):
    _assert_append_only_fields(data)
    assert data["subject_type"] in _enum_values(ScreeningSubjectType)
    assert data["result"] in _enum_values(ScreeningResult)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["match_score"], (int, float))
    assert is_iso8601_timestamp(data.get("screened_at", "")), "screened_at must be ISO 8601"


def assert_sanctions_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(CaseStatus)
    assert data["opened_reason"] in _enum_values(CaseOpenedReason)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["screening_check_id"], str)


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(InvoiceStatus)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["invoice_number"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["cost_center"], str)
    assert isinstance(data["approval_round"], int)


def assert_invoice_approval(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["round_no"], int)
    assert data["tier"] in (1, 2, 3)
    assert isinstance(data["approver_user_id"], str)
    assert isinstance(data["approver_role"], str)


def assert_matrix_rule(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(MatrixRuleStatus)
    assert isinstance(data["cost_center"], str)
    assert isinstance(data["min_amount_cents"], int)
    assert data["tier"] in (1, 2, 3)


def assert_payment_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(PaymentRunStatus)
    assert data["payment_method"] in _enum_values(PaymentMethod)
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["item_count"], int)
    assert isinstance(data["created_by_user_id"], str)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _enum_values(PaymentStatus)
    assert isinstance(data["payment_run_id"], str)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["discount_applied_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    if data.get("void_reason") is not None:
        assert data["void_reason"] in _enum_values(VoidReason)


def assert_merge_record(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["survivor_vendor_id"], str)
    assert isinstance(data["merged_vendor_id"], str)
    assert isinstance(data["match_score"], (int, float))
    assert isinstance(data["invoices_repointed_count"], int)
    assert isinstance(data["bank_accounts_disabled_count"], int)
    assert isinstance(data["merged_by_user_id"], str)


def assert_audit_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)
    assert data["event_type"] in [
        "CREATE", "UPDATE", "STATUS_CHANGE", "VERIFY", "MERGE", "RETIRE", "DISPOSITION",
    ]
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)


def assert_payment_invariants(payment: dict):
    """net = gross - discount + fee must hold on every payment (PRD §3.6)."""
    assert payment["net_amount_cents"] == (
        payment["amount_cents"] - payment["discount_applied_cents"] + payment["fee_cents"]
    ), (
        f"net_amount_cents {payment['net_amount_cents']} != "
        f"{payment['amount_cents']} - {payment['discount_applied_cents']} + {payment['fee_cents']}"
    )


def assert_run_totals_consistent(run: dict, payments: list):
    """Run totals aggregate over non-VOIDED payments (PRD §3.6)."""
    live = [p for p in payments if p["status"] != "VOIDED"]
    assert run["total_amount_cents"] == sum(p["net_amount_cents"] for p in live), (
        f"run total {run['total_amount_cents']} != sum of live nets "
        f"{sum(p['net_amount_cents'] for p in live)}"
    )
    assert run["item_count"] == len(live), (
        f"run item_count {run['item_count']} != live payment count {len(live)}"
    )
