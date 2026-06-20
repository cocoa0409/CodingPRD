"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_lender(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["program"] in ("7A", "504")
    assert isinstance(data["ongoing_fee_pool_cents"], int)
    assert isinstance(data["sold_guaranty_balance_cents"], int)
    assert data["ongoing_fee_pool_cents"] >= 0
    assert data["sold_guaranty_balance_cents"] >= 0


def assert_borrower(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lender_id"])
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["naics_code"], str)
    assert isinstance(data["is_eligible_business_type"], bool)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["borrower_id"])
    assert is_valid_uuid(data["lender_id"])
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["guaranty_pct"], (int, float))
    assert 0 < data["guaranty_pct"] <= 0.90
    assert data["status"] in (
        "DRAFT", "UNDERWRITING", "REVISION", "PENDING_APPROVAL", "APPROVED",
        "AUTHORIZED", "DISBURSING", "CLOSED", "WITHDRAWN", "DECLINED",
    )
    assert data["servicing_status"] in (
        "NOT_SERVICING", "CURRENT", "DELINQUENT", "DEFAULTED", "LIQUIDATED", "PAID_IN_FULL",
    )
    assert data["guaranty_status"] in ("RETAINED", "SOLD", "REPURCHASED", "PURCHASED_BY_SBA")
    assert isinstance(data["size_eligible"], bool)


def assert_application_invariants(data: dict):
    """Conservation invariants that hold after any operation (PRD §2.7)."""
    assert data["outstanding_principal_cents"] >= 0, "outstanding principal must not go negative"
    assert data["disbursed_amount_cents"] >= 0, "disbursed amount must not go negative"
    assert data["disbursed_amount_cents"] <= data["requested_amount_cents"], \
        "disbursed must never exceed requested"
    assert data["sold_guaranteed_principal_cents"] >= 0


def assert_proceeds_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["use_category"] in (
        "WORKING_CAPITAL", "EQUIPMENT", "REAL_ESTATE", "REFINANCE", "INVENTORY", "GOODWILL",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["is_fixed_asset"], bool)


def assert_collateral_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["asset_type"] in ("REAL_ESTATE", "EQUIPMENT", "INVENTORY", "RECEIVABLES")
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["discounted_value_cents"], int)
    assert data["discounted_value_cents"] >= 0, "discounted value floored at 0"


def assert_form_package(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("INCOMPLETE", "SUBMITTED", "CLEARED", "FLAGGED")


def assert_credit_memo(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["recommendation"] in ("APPROVE", "DECLINE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert 1 <= data["risk_rating"] <= 8


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("REQUESTED", "POSTED", "REVERSED")


def assert_guaranty_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["lender_id"])
    assert isinstance(data["sold_principal_cents"], int)
    assert 0 <= data["premium_bps"] <= 1500
    assert data["status"] in ("OFFERED", "SETTLED", "REPURCHASED")


def assert_servicing_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["principal_paid_cents"], int)
    assert isinstance(data["ongoing_fee_cents"], int)
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED")


def assert_liquidation_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["recovery_cents"], int)
    assert data["status"] in ("OPEN", "SETTLED")


def assert_guaranty_purchase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["claimed_principal_cents"], int)
    assert 0 <= data["repair_pct"] <= 1
    assert data["status"] in ("FILED", "PAID", "DENIED")
