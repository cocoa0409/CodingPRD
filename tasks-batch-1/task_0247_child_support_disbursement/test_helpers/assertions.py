"""Entity assertions and domain invariant checkers.

Field names are exactly as named in the PRD. Append-only ledger entries
(common_fields false) carry no version/updated_at and assertions must not
demand those fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for standard resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_custodial_party(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert data["assistance_status"] in (
        "NEVER_ASSISTED", "FORMERLY_ASSISTED", "CURRENTLY_ASSISTED")
    assert data["payee_status"] in ("ACTIVE", "HOLD")


def assert_noncustodial_party(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_last4"], str)
    assert isinstance(data["supports_second_family"], bool)
    assert isinstance(data["total_current_support_cents"], int)


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]
    assert data["remittance_method"] in ("EFT", "CHECK")


def assert_support_order(data: dict):
    _assert_common(data)
    assert isinstance(data["current_support_cents"], int)
    assert data["obligation_status"] in (
        "ESTABLISHED", "ACTIVE", "SUSPENDED", "MODIFIED", "TERMINATED")
    assert data["enforcement_status"] in (
        "NONE", "INTERCEPT_PENDING", "INTERCEPT_ACTIVE", "LIFTED")
    assert data["arrears_distribution_rule"] in ("FAMILY_FIRST", "STATE_FIRST")
    for fld in ("current_support_due_cents", "arrears_principal_cents",
                "interest_balance_cents", "net_disbursed_to_family_cents"):
        assert isinstance(data[fld], int), f"{fld} must be an integer"


def assert_iwo(data: dict):
    _assert_common(data)
    assert isinstance(data["ordered_amount_cents"], int)
    assert data["status"] in ("ISSUED", "ACKNOWLEDGED", "TERMINATED")


def assert_remittance(data: dict):
    _assert_common(data)
    assert isinstance(data["disposable_earnings_cents"], int)
    assert isinstance(data["gross_remitted_cents"], int)
    assert isinstance(data["ccpa_cap_cents"], int)
    assert isinstance(data["distributable_cents"], int)
    assert data["status"] in ("RECEIVED", "ALLOCATED", "RETURNED")


def assert_allocation(data: dict):
    _assert_common(data)
    for fld in ("current_support_applied_cents", "interest_applied_cents",
                "principal_applied_cents", "total_applied_cents"):
        assert isinstance(data[fld], int), f"{fld} must be an integer"


def assert_disbursement(data: dict):
    _assert_common(data)
    assert isinstance(data["family_amount_cents"], int)
    assert isinstance(data["state_retained_cents"], int)
    assert data["method"] in ("EFT", "CHECK", "DEBIT_CARD")
    assert data["status"] in ("PENDING", "SENT", "RETURNED")


def assert_modification(data: dict):
    _assert_common(data)
    assert isinstance(data["proposed_current_support_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "APPLIED")


def assert_enforcement_action(data: dict):
    _assert_common(data)
    assert data["action_type"] in ("TAX_INTERCEPT", "LICENSE_SUSPENSION")
    assert data["status"] in ("PROPOSED", "CERTIFIED", "SATISFIED", "WITHDRAWN")


def assert_ledger_entry(data: dict):
    """Append-only: id + created_at only; no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "ledger id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("CHARGE", "PAYMENT", "INTEREST", "DISBURSEMENT", "ADJUSTMENT")
    assert data["bucket"] in ("CURRENT_SUPPORT", "INTEREST", "PRINCIPAL")
    assert isinstance(data["amount_cents"], int)


def assert_order_balances_floored(data: dict):
    """Computed owed balances are floored at zero (PRD §2.4)."""
    assert data["current_support_due_cents"] >= 0
    assert data["arrears_principal_cents"] >= 0
    assert data["interest_balance_cents"] >= 0
