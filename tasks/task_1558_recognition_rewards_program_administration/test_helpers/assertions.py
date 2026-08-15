"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ISO_DATE_LENGTH = 10  # YYYY-MM-DD


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["peer_nomination_enabled"], bool)
    assert isinstance(data["manager_nomination_enabled"], bool)
    assert isinstance(data["max_points_per_nomination"], int)
    assert data["max_points_per_nomination"] > 0
    assert isinstance(data["point_cost_rate_cents"], (int, float))
    assert data["point_cost_rate_cents"] > 0
    assert isinstance(data["state_rate_map"], dict)
    assert isinstance(data["grossup_enabled"], bool)
    assert isinstance(data["anniversary_milestones"], list)
    assert isinstance(data["nomination_review_sla_days"], int)
    assert isinstance(data["duplicate_window_days"], int)
    assert isinstance(data["velocity_limit_per_7_days"], int)
    assert data["accrual_method"] in ["STRAIGHT_LINE", "UTILIZATION_WEIGHTED"]
    assert isinstance(data["fiscal_year_start_month"], int)


def assert_department(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["chargeback_account_code"], str)


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_ref"], str) and len(data["employee_ref"]) > 0
    assert isinstance(data["full_name"], str)
    assert is_valid_uuid(data.get("department_id", ""))
    manager_id = data.get("manager_id")
    assert manager_id is None or isinstance(manager_id, str)
    assert isinstance(data["hire_date"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["program_status"] in ["ELIGIBLE", "SUSPENDED"]
    assert data["recognition_tier"] in ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
    for counter in (
        "available_points", "held_points", "lifetime_granted_points",
        "lifetime_redeemed_points", "lifetime_expired_points",
        "ytd_supplemental_wages_cents", "ytd_de_minimis_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_point_ledger_entry(data: dict):
    """Immutable journal record: id + created_at only; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["entry_type"] in [
        "GRANT_NOMINATION", "GRANT_ANNIVERSARY", "GRANT_ADJUSTMENT", "HOLD",
        "SETTLE_REDEEM", "REFUND", "RESTOCKING_FEE", "EXPIRY", "CLAWBACK",
    ]
    assert isinstance(data["points"], int)
    assert data["reference_type"] in ["AWARD", "REDEMPTION_ORDER", "ABUSE_FLAG"]


def assert_point_budget(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["allocated_points"], int) and data["allocated_points"] > 0
    assert isinstance(data["reserved_points"], int)
    assert isinstance(data["committed_points"], int)
    assert data["posture"] in ["OPEN", "RESTRICTED", "EXHAUSTED", "CLOSED"]


def assert_nomination(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("nominator_id", ""))
    assert is_valid_uuid(data.get("nominee_id", ""))
    assert data["type"] in ["PEER", "MANAGER"]
    assert isinstance(data["points_requested"], int) and data["points_requested"] >= 1
    assert data["reason_code"] in [
        "TEAMWORK", "INNOVATION", "CUSTOMER_SAVE", "DELIVERY", "MENTORSHIP", "OTHER",
    ]
    assert isinstance(data["message"], str)
    assert isinstance(data["idempotency_key"], str)
    assert data["status"] in [
        "PENDING_REVIEW", "RETURNED_FOR_REVISION", "APPROVED",
        "REJECTED", "CANCELLED", "EXPIRED",
    ]
    assert isinstance(data["revision_count"], int)


def assert_award(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data.get("nomination_id") is None or isinstance(data["nomination_id"], str)
    assert data["source"] in ["NOMINATION", "ANNIVERSARY", "ADJUSTMENT"]
    assert isinstance(data["points"], int)
    assert isinstance(data["points_remaining"], int)
    assert data["status"] in ["ACTIVE", "FULLY_REDEEMED", "EXPIRED", "REVOKED"]
    assert is_iso8601_timestamp(data.get("granted_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_fulfillment_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["vendor_code"], str)
    assert isinstance(data["daily_ship_capacity"], int)
    assert data["daily_ship_capacity"] >= 1
    assert isinstance(data["lead_time_business_days"], int)
    assert data["lead_time_business_days"] >= 0
    assert isinstance(data["restocking_fee_percent"], int)
    assert 0 <= data["restocking_fee_percent"] <= 100
    assert isinstance(data["supported_categories"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_catalog_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["category"], str)
    assert isinstance(data["point_cost"], int) and data["point_cost"] > 0
    assert isinstance(data["cash_value_cents"], int) and data["cash_value_cents"] > 0
    assert data["taxable_class"] in ["MERCHANDISE", "GIFT_CARD", "EXPERIENCE"]
    assert isinstance(data["de_minimis_eligible"], bool)
    assert isinstance(data["active_window_start"], str)
    assert isinstance(data["active_window_end"], str)
    inv = data.get("inventory_quantity")
    assert inv is None or (isinstance(inv, int) and inv >= 0)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_redemption_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 5
    assert isinstance(data["points_total"], int)
    assert data["fulfillment_status"] in [
        "PENDING_SUBMISSION", "SUBMITTED", "SHIPPED", "DELIVERED",
        "RETURN_REQUESTED", "RETURNED", "CANCELLED",
    ]
    assert data["escrow_status"] in ["HELD", "SETTLED", "REFUNDED", "SETTLED_WITH_FEE"]
    ship_date = data.get("ship_date")
    assert ship_date is None or (
        isinstance(ship_date, str) and len(ship_date) == ISO_DATE_LENGTH
    )
    assert isinstance(data["idempotency_key"], str)
    assert isinstance(data["restocking_fee_points"], int)


def assert_tax_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("redemption_order_id", ""))
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["taxable_value_cents"], int)
    assert isinstance(data["de_minimis_applied"], bool)
    assert isinstance(data["federal_rate_applied"], (int, float))
    assert isinstance(data["state_rate_applied"], (int, float))
    assert isinstance(data["estimated_gross_up_cents"], int)
    assert data.get("final_gross_up_cents") is None or isinstance(
        data["final_gross_up_cents"], int
    )
    assert data.get("delta_cents") is None or isinstance(data["delta_cents"], int)
    assert isinstance(data["employer_cost_cents"], int)
    assert data["status"] in ["ESTIMATED", "FINALIZED", "AMENDED", "VOIDED"]


def assert_accrual_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    assert data["status"] in ["OPEN", "RECONCILED", "CLOSED", "VOIDED"]
    assert data["accrual_method_used"] in ["STRAIGHT_LINE", "UTILIZATION_WEIGHTED"]
    assert isinstance(data["department_breakdown"], list)
    assert isinstance(data["total_accrual_cents"], int)
    assert isinstance(data["total_net_chargeback_cents"], int)


def assert_abuse_flag(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["rule_code"] in [
        "VELOCITY_EXCEEDED", "DUPLICATE_ATTEMPT", "SELF_NOMINATION",
        "MANAGER_QUID_PRO_QUO", "REDEMPTION_ANOMALY", "MANUAL_REVIEW",
    ]
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "CONFIRMED", "DISMISSED"]
    assert isinstance(data["raised_by"], str)


def assert_anniversary_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data["milestone_years"], int)
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in [
        "PROCESSED", "SKIPPED_INELIGIBLE", "SKIPPED_DUPLICATE",
        "SKIPPED_NO_MILESTONE", "SKIPPED_BUDGET_EXHAUSTED",
    ]
    assert data.get("award_id") is None or isinstance(data["award_id"], str)


def assert_employee_ledger_reconciles(employee: dict, ledger_entries: list):
    """Derived-balance invariant (PRD §2.9): available_points and held_points
    reconcile with the signed ledger movements.

    HOLD moves available -> held; SETTLE_REDEEM and RESTOCKING_FEE move points
    out of held into spent; CLAWBACK and EXPIRY debit available; grants and
    refunds credit available.
    """
    available = 0
    held = 0
    for entry in ledger_entries:
        points = entry["points"]
        entry_type = entry["entry_type"]
        if entry_type in ("GRANT_NOMINATION", "GRANT_ANNIVERSARY", "GRANT_ADJUSTMENT"):
            available += points
        elif entry_type == "HOLD":
            available += points
            held -= points
        elif entry_type in ("SETTLE_REDEEM", "RESTOCKING_FEE"):
            held += points
        elif entry_type == "REFUND":
            available += points
            held -= points
        elif entry_type in ("CLAWBACK", "EXPIRY"):
            available += points
        else:
            raise AssertionError(f"Unknown entry_type {entry_type}")
    assert employee["available_points"] == available, (
        f"available_points {employee['available_points']} != ledger-derived {available}"
    )
    assert employee["held_points"] == held, (
        f"held_points {employee['held_points']} != ledger-derived {held}"
    )
