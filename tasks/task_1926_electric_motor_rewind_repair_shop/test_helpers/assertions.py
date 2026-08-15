"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Common resource properties pinned by PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_append_only_fields(data: dict, entity: str):
    """TestRecord and CoilDataRecord carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_shop(data: dict):
    _assert_common_fields(data, "Shop")
    assert isinstance(data["shop_name"], str) and data["shop_name"]
    assert isinstance(data["easa_accreditation_id"], str)
    for field in (
        "labor_rate_small_cents",
        "labor_rate_medium_cents",
        "labor_rate_large_cents",
        "labor_rate_xlarge_cents",
        "pool_slot_monthly_cents",
        "pool_loan_daily_cents",
    ):
        assert isinstance(data[field], int), f"Shop.{field} must be integer cents"
    for field in ("rush_premium_pct", "replace_threshold_pct", "supplies_low_pct", "supplies_high_pct"):
        assert isinstance(data[field], (int, float)), f"Shop.{field} must be numeric"
    assert isinstance(data["warranty_months"], int)
    assert isinstance(data["pool_loan_grace_days"], int)
    assert data["currency"] == "USD"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["account_credit_cents"], int)
    assert data["account_credit_cents"] >= 0, "account_credit_cents is never negative"
    assert data["standing"] in ("GOOD", "WATCH", "HOLD")


def assert_motor(data: dict):
    _assert_common_fields(data, "Motor")
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["rated_kw"] > 0
    assert isinstance(data["frame_mm"], int) and data["frame_mm"] > 0
    assert isinstance(data["voltage_v"], int)
    assert isinstance(data["manufacture_year"], int)
    assert data["custody"] in ("WITH_CUSTOMER", "IN_SHOP", "IN_POOL", "ON_LOAN")


def assert_work_order(data: dict):
    _assert_common_fields(data, "WorkOrder")
    assert data["status"] in (
        "INTAKE", "INCOMING_TEST", "DIAGNOSED", "QUOTED", "AWAITING_APPROVAL",
        "APPROVED", "IN_REWIND", "BALANCING", "FINAL_TEST", "READY_FOR_PICKUP",
        "DELIVERED", "CLOSED", "DECLINED", "SCRAPPED",
    )
    assert data["priority"] in ("STANDARD", "RUSH", "EMERGENCY")
    assert isinstance(data["invoice_total_cents"], int)
    assert data["invoice_total_cents"] >= 0


def assert_test_record(data: dict):
    _assert_append_only_fields(data, "TestRecord")
    assert data["kind"] in ("INCOMING", "CORE_LOSS", "FINAL")
    assert data["verdict"] in ("PASS", "FAIL")
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


def assert_quote(data: dict):
    _assert_common_fields(data, "Quote")
    assert data["status"] in (
        "DRAFT", "ISSUED", "ACCEPTED", "DECLINED", "SUPERSEDED", "EXPIRED",
    )
    assert data["recommendation"] in ("REWIND", "REPLACE")
    for field in (
        "rewind_labor_cents", "rewind_materials_cents", "shop_supplies_cents",
        "rush_premium_cents", "rewind_total_cents", "risk_cost_cents",
        "tco_total_cents",
    ):
        assert isinstance(data[field], int), f"Quote.{field} must be integer cents"
    assert isinstance(data["risk_pct"], (int, float))


def assert_coil_data_record(data: dict):
    _assert_append_only_fields(data, "CoilDataRecord")
    assert isinstance(data["wire_gauge_awg"], str) and data["wire_gauge_awg"]
    assert isinstance(data["turns_per_coil"], int) and data["turns_per_coil"] > 0
    assert isinstance(data["coils_per_phase"], int) and data["coils_per_phase"] > 0
    assert data["connection"] in ("WYE", "DELTA")
    assert isinstance(data["easa_form_version"], str) and data["easa_form_version"]
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


def assert_pool_contract(data: dict):
    _assert_common_fields(data, "SparePoolContract")
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["first_month_fee_cents"], int)
    assert is_iso8601_timestamp(data.get("activated_on", ""))


def assert_pool_loan(data: dict):
    _assert_common_fields(data, "PoolLoan")
    assert data["status"] in ("OUT", "RETURNED", "OVERDUE")
    assert isinstance(data["overdue_days"], int) and data["overdue_days"] >= 0
    assert isinstance(data["overdue_charge_cents"], int) and data["overdue_charge_cents"] >= 0


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in ("OPEN", "PAID", "OVERDUE", "VOID")
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert isinstance(data["balance_due_cents"], int)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert data["failure_mode"] in (
        "WINDING_SHORT", "GROUND_FAULT", "BEARING_FAILURE", "OVERLOAD",
        "INGRESS", "MISAPPLICATION", "UNAUTHORIZED_REPAIR",
    )
    assert data["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "RESOLVED")
    assert isinstance(data["months_elapsed"], int) and data["months_elapsed"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0


def assert_invoice_balance_invariant(data: dict):
    """PRD §3.5: balance_due_cents is the total minus the amount paid."""
    assert data["balance_due_cents"] == data["total_cents"] - data["amount_paid_cents"], (
        f"Invoice balance {data['balance_due_cents']} != "
        f"total {data['total_cents']} - paid {data['amount_paid_cents']}"
    )
