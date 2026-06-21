"""Entity assertions and domain invariant checkers for the Auto Title Loan API.

Uses the framework's generic format validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (entities with the full common-field set)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_borrower(data: dict):
    _assert_common_full(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["state_code"] in {"CA", "TX", "FL", "VA", "AZ"}
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 0
    assert data["status"] in {"ACTIVE", "BARRED"}


def assert_regulatory_profile(data: dict):
    # Configuration data: only id + created_at; NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["state_code"] in {"CA", "TX", "FL", "VA", "AZ"}
    assert data["valuation_basis"] in {"TRADE_IN", "AUCTION"}


def assert_vehicle(data: dict):
    _assert_common_full(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) > 0
    assert data["lien_state"] in {"CLEAR", "ENCUMBERED"}
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0


def assert_appraisal(data: dict):
    _assert_common_full(data)
    assert data["condition_grade"] in {"EXCELLENT", "GOOD", "FAIR", "POOR"}
    assert data["status"] in {"DRAFT", "FINALIZED", "CONSUMED"}
    assert isinstance(data["trade_in_value_cents"], int) and data["trade_in_value_cents"] > 0
    assert isinstance(data["auction_value_cents"], int) and data["auction_value_cents"] > 0
    assert data["auction_value_cents"] <= data["trade_in_value_cents"]


def assert_loan_application(data: dict):
    _assert_common_full(data)
    assert data["status"] in {"SUBMITTED", "APPROVED", "REJECTED"}
    assert isinstance(data["requested_principal_cents"], int) and data["requested_principal_cents"] > 0
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1


def assert_loan(data: dict):
    _assert_common_full(data)
    assert data["payoff_status"] in {"OUTSTANDING", "REDEEMED", "PAID_OFF", "CHARGED_OFF"}
    assert data["delinquency_status"] in {"CURRENT", "DELINQUENT", "DEFAULT"}
    assert isinstance(data["original_principal_cents"], int)
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)
    assert isinstance(data["fees_balance_cents"], int)
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_title_lien(data: dict):
    _assert_common_full(data)
    assert data["status"] in {"PENDING", "FILED", "RELEASED"}


def assert_installment(data: dict):
    _assert_common_full(data)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["status"] in {"SCHEDULED", "PAID", "PAST_DUE", "WAIVED"}


def assert_payment(data: dict):
    _assert_common_full(data)
    assert data["payment_type"] in {"REGULAR", "REINSTATEMENT", "REDEMPTION"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_renewal(data: dict):
    _assert_common_full(data)
    assert isinstance(data["new_principal_cents"], int)
    assert isinstance(data["renewal_index"], int) and data["renewal_index"] >= 1


def assert_repossession_order(data: dict):
    _assert_common_full(data)
    assert data["status"] in {"ORDERED", "ASSIGNED", "RECOVERED", "SOLD", "CANCELLED"}


def assert_repossession_assignment(data: dict):
    _assert_common_full(data)
    assert isinstance(data["agent_name"], str) and len(data["agent_name"]) > 0


def assert_device(data: dict):
    _assert_common_full(data)
    assert data["starter_state"] in {"ENABLED", "DISABLED"}
    assert isinstance(data["active_disable_count"], int) and data["active_disable_count"] >= 0


def assert_device_command(data: dict):
    _assert_common_full(data)
    assert data["command_type"] in {"STARTER_DISABLE", "STARTER_ENABLE", "LOCATE"}
    assert data["status"] in {"ISSUED", "REVERSED"}
