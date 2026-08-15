"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every persisted resource except payments/shot reports (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Payments and shot reports carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_tool_design(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["tool_type"] in (
        "PROGRESSIVE_DIE", "TRANSFER_DIE", "INJECTION_MOLD", "BLOW_MOLD", "COMPRESSION_MOLD",
    )
    assert data["die_class"] in ("CLASS_101", "CLASS_102", "CLASS_103", "CLASS_104", "CLASS_105")
    assert isinstance(data["cavity_count"], int) and 1 <= data["cavity_count"] <= 64
    assert isinstance(data["design_complexity_score"], int) and 1 <= data["design_complexity_score"] <= 20
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["quoted_count"], int) and data["quoted_count"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "RELEASED", "SUPERSEDED")


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("tool_design_id", ""))
    assert data["quote_kind"] in ("BUDGETARY", "FIRM")
    assert isinstance(data["requested_lead_weeks"], int) and data["requested_lead_weeks"] >= 1
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED")


def assert_build_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("quote_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("tool_design_id", ""))
    assert data["die_class"] in ("CLASS_101", "CLASS_102", "CLASS_103", "CLASS_104", "CLASS_105")
    for field in (
        "contract_value_cents", "billed_cents", "paid_cents", "credit_balance_cents",
        "net_paid_cents", "outstanding_cents", "open_eco_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in (
        "BOOKED", "IN_BUILD", "TRYOUT_PHASE", "BUYOFF_PASSED",
        "READY_TO_SHIP", "SHIPPED", "CLOSED", "ON_HOLD",
    )


def assert_build_milestone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert isinstance(data["seq"], int) and 1 <= data["seq"] <= 6
    assert data["code"] in (
        "DESIGN_COMPLETE", "MATERIAL_STAGED", "MACHINING_COMPLETE",
        "T1_TRYOUT_DONE", "BUYOFF_SIGNED", "DELIVERY_ACCEPTED",
    )
    assert isinstance(data["billing_pct"], int)
    assert isinstance(data["planned_amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ("PENDING", "EARNED", "INVOICED", "PAID", "REOPENED")


def assert_progress_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert is_valid_uuid(data.get("build_milestone_id", ""))
    assert isinstance(data["invoice_number"], str) and data["invoice_number"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["issued_by_user_id"], str)
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")


def assert_payment(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["allocations"], list)
    for alloc in data["allocations"]:
        assert is_valid_uuid(alloc.get("invoice_id", ""))
        assert isinstance(alloc["applied_cents"], int) and alloc["applied_cents"] > 0
    assert isinstance(data["recorded_by_user_id"], str)


def assert_tryout_sample(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert is_valid_uuid(data.get("press_reservation_id", ""))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in ("SCHEDULED", "SUBMITTED", "BOUGHT_OFF", "REJECTED")


def assert_engineering_change(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert data["requested_by"] in ("SHOP", "CUSTOMER")
    assert isinstance(data["affects_from_milestone_seq"], int) and 1 <= data["affects_from_milestone_seq"] <= 6
    assert data["status"] in ("SUBMITTED", "IMPACT_ASSESSED", "APPROVED", "REJECTED", "VERIFIED")


def assert_rework_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engineering_change_id", ""))
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert isinstance(data["authorized_cost_cents"], int)
    assert data["status"] in ("AUTHORIZED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_tool_asset(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["die_class"] in ("CLASS_101", "CLASS_102", "CLASS_103", "CLASS_104", "CLASS_105")
    assert data["warranty_terms"] in ("LINEAR_PRORATION", "DECLINING_BALANCE")
    assert isinstance(data["warranty_shot_limit"], int) and data["warranty_shot_limit"] > 0
    for field in ("tryout_shots", "reported_shots", "lifetime_shots", "contract_snapshot_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["physical_status"] in (
        "IN_BUILD", "TRYOUT", "AWAITING_SHIPMENT", "IN_TRANSIT",
        "IN_PRODUCTION", "RETURNED_FOR_REPAIR",
    )
    assert data["ownership_status"] in ("SHOP_RETAINED", "TRANSFERRED")


def assert_shot_report(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("tool_asset_id", ""))
    assert is_iso8601_timestamp(data.get("report_period_end", ""))
    assert isinstance(data["shots_in_period"], int) and data["shots_in_period"] >= 1
    assert data["status"] in ("ACTIVE", "REVERSED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tool_asset_id", ""))
    assert isinstance(data["defect_description"], str) and data["defect_description"]
    assert isinstance(data["estimated_repair_cost_cents"], int) and data["estimated_repair_cost_cents"] >= 1
    assert isinstance(data["claimed_at_shot_count"], int) and data["claimed_at_shot_count"] >= 0
    assert data["status"] in ("FILED", "REPAIR_SCHEDULED", "DENIED", "CLOSED")


def assert_spare_insert(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tool_asset_id", ""))
    assert isinstance(data["insert_code"], str) and data["insert_code"]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["on_hand"], int) and data["on_hand"] >= 0
    assert isinstance(data["reorder_point"], int) and data["reorder_point"] >= 0
    assert isinstance(data["reorder_needed"], bool)
    assert data["status"] in ("ACTIVE", "DEPLETED", "DISCONTINUED")


def assert_press_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert data["press_id"] in ("PRESS_200T", "PRESS_500T", "PRESS_800T")
    assert is_iso8601_timestamp(data.get("start_time", ""))
    assert is_iso8601_timestamp(data.get("end_time", ""))
    assert data["status"] in ("RESERVED", "CANCELLED")


def assert_machine_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_job_id", ""))
    assert data["machine_id"] in ("CNC_1", "CNC_2", "EDM_1", "GRIND_1")
    assert is_iso8601_timestamp(data.get("start_time", ""))
    assert is_iso8601_timestamp(data.get("end_time", ""))
    assert isinstance(data["duration_hours"], (int, float)) and data["duration_hours"] > 0
    assert data["status"] in ("RESERVED", "CANCELLED")


def assert_build_job_invariants(data: dict):
    """Derived-figure identities that must hold for any job (PRD §3.4)."""
    assert data["net_paid_cents"] == data["paid_cents"] - data["credit_balance_cents"]
    assert data["outstanding_cents"] == data["contract_value_cents"] - data["net_paid_cents"]
    assert data["open_eco_count"] >= 0
