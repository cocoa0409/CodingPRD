"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field envelope (PRD §2.4) ──────────────────────────────────
def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for the full-envelope entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def _assert_reference_fields(data: dict):
    """id + created_at only — for ApyTier (common_fields false, PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


# ─── Per-entity assertions ─────────────────────────────────────────────
def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["tax_id_last4"], str)
    assert data["cip_status"] in ("UNVERIFIED", "VERIFIED", "REJECTED")


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["product_type"] in ("CHECKING", "SAVINGS")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_account(data: dict):
    _assert_common_fields(data)
    assert data["product_type"] in ("CHECKING", "SAVINGS")
    assert data["status"] in ("ACTIVE", "DORMANT", "FROZEN", "ESCHEATED", "CLOSED")
    assert isinstance(data["ledger_balance_cents"], int)
    assert isinstance(data["hold_total_cents"], int)
    assert isinstance(data["available_balance_cents"], int)
    assert isinstance(data["courtesy_pay_opted_in"], bool)


def assert_account_owner(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["ownership_role"] in ("PRIMARY", "JOINT", "POD_BENEFICIARY")
    assert isinstance(data["is_active"], bool)


def assert_transaction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["txn_type"] in (
        "DEPOSIT", "WITHDRAWAL", "ACH_CREDIT", "ACH_DEBIT",
        "CHECK_DEBIT", "INTEREST", "FEE", "ESCHEAT_SWEEP",
    )
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PENDING", "POSTED", "RETURNED", "STOPPED")


def assert_fee_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert data["fee_type"] in ("OVERDRAFT", "NSF")
    assert isinstance(data["tier_ordinal"], int) and data["tier_ordinal"] >= 1
    assert isinstance(data["fee_amount_cents"], int) and data["fee_amount_cents"] >= 0


def assert_stop_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["check_number"], str)
    assert isinstance(data["max_amount_cents"], int)
    assert data["status"] in ("ACTIVE", "CONSUMED", "EXPIRED")


def assert_ach_origination(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("debtor_account_id", "")), "debtor_account_id must be a UUID"
    assert is_valid_uuid(data.get("creditor_account_id", "")), "creditor_account_id must be a UUID"
    assert data["posting_order"] in ("CHRONOLOGICAL", "HIGH_TO_LOW")
    assert data["status"] in ("STAGED", "SETTLED", "REVERSED")


def assert_ach_leg(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("ach_origination_id", "")), "ach_origination_id must be a UUID"
    assert data["leg_role"] in ("DEBIT", "CREDIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_interest_posting(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["posted_interest_cents"], int)


def assert_escheat_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["swept_amount_cents"], int)


def assert_apy_tier(data: dict):
    """ApyTier is reference config (PRD §2.4): id + created_at, no version/updated_at."""
    _assert_reference_fields(data)
    assert isinstance(data["code"], str)
    assert data["product_type"] in ("CHECKING", "SAVINGS")
    assert isinstance(data["annual_rate_bps"], int)


# ─── Domain invariant checkers (PRD §3.4) ──────────────────────────────
def assert_balance_identity(account: dict):
    """available_balance_cents == ledger_balance_cents - hold_total_cents (PRD §3.4)."""
    assert (
        account["available_balance_cents"]
        == account["ledger_balance_cents"] - account["hold_total_cents"]
    ), (
        "available_balance_cents must equal ledger_balance_cents - hold_total_cents "
        f"(got {account['available_balance_cents']} vs "
        f"{account['ledger_balance_cents']} - {account['hold_total_cents']})"
    )
