"""Entity assertions and domain invariant checkers (PRD §2.6, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every resource carries the four system-managed properties (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data}"
    )
    assert isinstance(data.get("version"), int), f"version must be an integer: {data}"


def assert_tenant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert isinstance(data["acdbe_certified"], bool)


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tenant_id"], str) and len(data["tenant_id"]) > 0
    assert isinstance(data["premises_code"], str) and len(data["premises_code"]) > 0
    assert data["category"] in ["FOOD", "RETAIL", "SERVICES"]
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    for field in (
        "mag_annual_cents",
        "pct_rate_below_bp",
        "pct_breakpoint_cents",
        "pct_rate_above_bp",
        "acdbe_goal_bp",
        "ti_allowance_cents",
        "min_spe_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents/bp"
    assert data["status"] in [
        "DRAFT",
        "ACTIVE",
        "DEFAULTED",
        "TERMINATED",
        "EXPIRED",
        "REMARKETING",
    ]
    assert data.get("default_reason") is None or data["default_reason"] in [
        "NONPAYMENT",
        "HOURS_SHORTFALL",
        "ACDBE_NONCOMPLIANCE",
        "OTHER",
    ]
    assert isinstance(data["arrears_cents"], int)
    assert isinstance(data["ti_remaining_cents"], int)


def assert_sales_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["gross_sales_cents"], int) and data["gross_sales_cents"] >= 0
    assert data.get("restated_gross_sales_cents") is None or isinstance(
        data["restated_gross_sales_cents"], int
    )
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "DISPUTED", "ADJUSTED"]
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])


def assert_rent_settlement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert isinstance(data["period_year"], int)
    assert data["variant_used"] in ["PROVISIONAL", "FINAL"]
    for field in (
        "mag_due_cents",
        "percentage_due_cents",
        "true_up_due_cents",
        "amount_due_cents",
        "amount_paid_cents",
        "balance_due_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data.get("due_date") is None or isinstance(data["due_date"], str)
    assert data["status"] in [
        "ACCRUING",
        "INVOICED",
        "PARTIALLY_PAID",
        "OVERDUE",
        "PAID",
    ]


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["settlement_id"], str) and len(data["settlement_id"]) > 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ["ACH", "CHECK", "WIRE", "CARD"]
    assert data["status"] in ["POSTED", "VOIDED"]


def assert_audit_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert isinstance(data["period_start_month"], str)
    assert isinstance(data["period_end_month"], str)
    assert data["status"] in ["OPENED", "FINDINGS_ISSUED", "CLOSED"]
    assert isinstance(data["understatement_cents"], int)


def assert_acdbe_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert isinstance(data["period_year"], int)
    assert data["status"] in ["SCHEDULED", "COMPLIANT", "DEFICIENT", "CURED"]


def assert_ti_draw(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["milestone"] in ["DESIGN", "CONSTRUCTION", "FIXTURES", "GRAND_OPENING"]
    assert data["status"] in [
        "REQUESTED",
        "APPROVED",
        "REJECTED",
        "DISBURSED",
        "CANCELLED",
    ]


def assert_policy_violation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert data["kind"] in ["STREET_PRICING", "OPERATING_HOURS"]
    assert isinstance(data["observed_date"], str)
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    assert data["status"] in ["OPEN", "RESOLVED"]


def assert_operating_hours_waiver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and len(data["lease_id"]) > 0
    assert isinstance(data["closure_start_date"], str)
    assert isinstance(data["closure_end_date"], str)
    assert isinstance(data["reason"], str)
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED"]


def assert_enplanement_snapshot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["month"], str) and len(data["month"]) == 7
    assert isinstance(data["enplanements"], int) and data["enplanements"] > 0


def assert_settlement_ledger_invariants(data: dict):
    """The rent-ledger identity must hold on every settlement read (PRD §3.4):
    amount_due == mag_due + true_up and balance_due == amount_due - amount_paid.
    """
    assert data["amount_due_cents"] == data["mag_due_cents"] + data["true_up_due_cents"], (
        f"amount_due must equal mag_due + true_up: {data}"
    )
    assert (
        data["balance_due_cents"]
        == data["amount_due_cents"] - data["amount_paid_cents"]
    ), f"balance_due must equal amount_due - amount_paid: {data}"
    assert data["true_up_due_cents"] == max(
        0, data["percentage_due_cents"] - data["mag_due_cents"]
    ), f"true_up is the excess of percentage over MAG, floored at zero: {data}"


def assert_lease_balance_invariants(data: dict):
    """Continuously reconciled lease balances stay within sane bounds (PRD §2.9)."""
    assert data["arrears_cents"] >= 0
    assert 0 <= data["ti_remaining_cents"] <= data["ti_allowance_cents"]
