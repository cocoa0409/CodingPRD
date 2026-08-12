"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CASE_STATUSES = ["OPEN", "ASSET_INVESTIGATION", "CLAIMS_ADMINISTRATION", "LIQUIDATION",
                 "DISTRIBUTION", "FINAL_REPORT", "CLOSED", "CONVERTED_DISMISSED"]
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "OBJECTED", "ALLOWED", "DISALLOWED", "WITHDRAWN"]
OBJECTION_STATUSES = ["PENDING", "SUSTAINED", "OVERRULED", "SETTLED", "WITHDRAWN"]
ASSET_STATUSES = ["SCHEDULED", "UNDER_INVESTIGATION", "MARKED_FOR_SALE", "IN_AUCTION",
                  "SOLD", "ABANDONED", "EXEMPT_RELEASED"]
ACTION_STATUSES = ["IDENTIFIED", "ANALYZED", "DEMANDED", "SETTLED", "JUDGMENT",
                   "RESCINDED", "ABANDONED"]
SALE_STATUSES = ["PROPOSED", "APPROVED", "CONSUMMATED", "CANCELLED"]
PROCEEDS_STATUSES = ["PENDING", "POSTED", "VOIDED"]
PLAN_STATUSES = ["PROPOSED", "CONFIRMED", "EXECUTING", "FULLY_DISTRIBUTED", "VACATED"]
DIVIDEND_STATUSES = ["COMPUTED", "POSTED", "VOIDED"]
FEE_STATUSES = ["FILED", "APPROVED", "DENIED", "PAID"]
REPORT_STATUSES = ["DRAFT", "FILED", "APPROVED"]
PRIORITY_CLASSES = ["SECURED", "PRIORITY_TAX", "PRIORITY_WAGE", "PRIORITY_CONSUMER",
                    "GENERAL_UNSECURED"]


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_case(data: dict):
    _assert_common_fields(data, "Case")
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["debtor_name"], str) and data["debtor_name"]
    assert isinstance(data["trustee_user_id"], str) and data["trustee_user_id"]
    assert data["status"] in CASE_STATUSES
    assert isinstance(data["estate_cash_on_hand_cents"], int)
    assert isinstance(data["allowed_claims_total_cents"], int)
    assert isinstance(data["bar_date_noticed"], bool)
    assert isinstance(data["no_asset_report_filed"], bool)


def assert_creditor(data: dict):
    _assert_common_fields(data, "Creditor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["creditor_ref"], str) and data["creditor_ref"]
    assert isinstance(data["insider"], bool)


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert is_valid_uuid(data.get("case_id", "")), "Claim.case_id must be a UUID"
    assert data["status"] in CLAIM_STATUSES
    assert isinstance(data["claim_number"], int)
    assert isinstance(data["filed_amount_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["late"], bool)
    assert data["priority_class"] in PRIORITY_CLASSES


def assert_objection(data: dict):
    _assert_common_fields(data, "ClaimObjection")
    assert data["status"] in OBJECTION_STATUSES
    assert is_valid_uuid(data.get("claim_id", "")), "ClaimObjection.claim_id must be a UUID"


def assert_asset(data: dict):
    _assert_common_fields(data, "Asset")
    assert data["status"] in ASSET_STATUSES
    assert isinstance(data["scheduled_value_cents"], int)
    assert isinstance(data["exempt"], bool)


def assert_avoidance_action(data: dict):
    _assert_common_fields(data, "AvoidanceAction")
    assert data["status"] in ACTION_STATUSES
    assert data["action_type"] in ["PREFERENCE_547", "FRAUDULENT_548"]
    assert isinstance(data["transfer_amount_cents"], int)
    assert isinstance(data["demand_amount_cents"], int)
    assert isinstance(data["recovered_amount_cents"], int)
    assert isinstance(data["avoidable"], bool)
    assert isinstance(data["lookback_window_days"], int)


def assert_recovery_deposit(data: dict):
    _assert_common_fields(data, "RecoveryDeposit")
    assert data["status"] in PROCEEDS_STATUSES
    assert isinstance(data["amount_cents"], int)


def assert_sale(data: dict):
    _assert_common_fields(data, "AuctionSale")
    assert data["status"] in SALE_STATUSES
    assert data["proceeds_status"] in PROCEEDS_STATUSES
    assert isinstance(data["hammer_price_cents"], int)
    assert isinstance(data["sale_costs_cents"], int)
    assert isinstance(data["net_proceeds_cents"], int)


def assert_plan(data: dict):
    _assert_common_fields(data, "DistributionPlan")
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["reserve_for_objected_cents"], int)
    assert isinstance(data["distributable_cents"], int)


def assert_allocation(data: dict):
    _assert_common_fields(data, "PlanClassAllocation")
    assert data["priority_class"] in PRIORITY_CLASSES
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["paid_total_cents"], int)


def assert_dividend(data: dict):
    _assert_common_fields(data, "Dividend")
    assert data["status"] in DIVIDEND_STATUSES
    assert isinstance(data["amount_cents"], int)


def assert_fee_application(data: dict):
    _assert_common_fields(data, "FeeApplication")
    assert data["status"] in FEE_STATUSES
    assert data["applicant_role"] in ["TRUSTEE", "AUCTIONEER", "COUNSEL"]
    assert isinstance(data["requested_amount_cents"], int)


def assert_final_report(data: dict):
    """PRD §2.5: FinalReport carries only id and created_at of the common fields;
    updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "FinalReport.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "FinalReport.created_at must be ISO 8601"
    assert "version" not in data, "FinalReport must not carry a version field"
    assert "updated_at" not in data, "FinalReport must not carry an updated_at field"
    assert data["status"] in REPORT_STATUSES
    for field in ("total_receipts_cents", "total_dividends_cents",
                  "total_fees_cents", "unclaimed_funds_cents"):
        assert isinstance(data[field], int), f"FinalReport.{field} must be an integer"


def assert_case_ledger_non_negative(case_data: dict):
    """PRD §2.7: the ledger invariant is that estate cash never goes negative."""
    assert case_data["estate_cash_on_hand_cents"] >= 0, \
        "estate_cash_on_hand_cents must never be negative"
