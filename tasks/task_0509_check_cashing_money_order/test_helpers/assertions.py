"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id (UUID, no prefix) + created_at/updated_at (ISO 8601) + version (int >=1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["id_type"] in ["DRIVERS_LICENSE", "STATE_ID", "PASSPORT", "MILITARY_ID"]
    assert data["kyc_status"] in ["PENDING", "VERIFIED", "OFAC_BLOCKED", "REJECTED"]
    assert data["risk_tier"] in ["STANDARD", "ELEVATED", "HIGH"]
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 1000
    assert isinstance(data["daily_cashed_amount_cents"], int)
    assert isinstance(data["daily_transaction_count"], int)
    assert isinstance(data["outstanding_recovery_cents"], int)


def assert_compliance_screen(data: dict):
    """ComplianceScreen is immutable: id + created_at only, NO version/updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["outcome"] in ["VERIFIED", "OFAC_BLOCKED", "REJECTED"]


def assert_fee_schedule(data: dict):
    _assert_common_fields(data)
    assert data["check_type"] in ["PAYROLL", "GOVERNMENT", "PERSONAL", "MONEY_ORDER_CHECK", "INSURANCE"]
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["max_fee_cents"], int)
    assert isinstance(data["active"], bool)


def assert_cash_drawer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "RECONCILING", "CLOSED", "OVER_SHORT"]
    assert isinstance(data["opening_float_cents"], int)
    assert isinstance(data["expected_cash_cents"], int)


def assert_transaction(data: dict):
    _assert_common_fields(data)
    assert data["txn_type"] in ["CHECK_CASH", "MONEY_ORDER", "WIRE", "BILL_PAY", "PREPAID_LOAD"]
    assert isinstance(data["face_amount_cents"], int) and data["face_amount_cents"] >= 1
    assert isinstance(data["fee_cents"], int)
    assert data["lifecycle_state"] in ["DRAFT", "POSTED", "VOIDED"]
    assert data["settlement_state"] in ["UNSETTLED", "SETTLED", "RETURNED", "RECOVERED"]


def assert_check_item(data: dict):
    _assert_common_fields(data)
    assert data["verification_state"] in ["VERIFYING", "CLEARED", "RISK_HELD", "REJECTED"]
    assert data["maker_account_risk"] in ["LOW", "MEDIUM", "HIGH"]
    assert data.get("hold_reason") in [None, "AMOUNT_THRESHOLD", "MAKER_RISK", "VELOCITY"]


def assert_returned_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OUTSTANDING", "PARTIALLY_RECOVERED", "RECOVERED", "WRITTEN_OFF"]
    assert isinstance(data["return_fee_cents"], int)
    assert isinstance(data["recovered_cents"], int)
