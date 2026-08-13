"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["tier"] in ["STANDARD", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["ytd_purchase_cents"], int) and data["ytd_purchase_cents"] >= 0
    assert isinstance(data["coop_accrual_provisional_cents"], int)
    assert isinstance(data["coop_accrual_final_cents"], int)
    assert isinstance(data["training_credit_balance_hours"], int)
    assert data["compliance_standing"] in ["GOOD", "WATCH", "HOLD"]
    assert isinstance(data["heel_violation_count_12m"], int)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_equipment_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_number"], str) and data["model_number"]
    assert data["equipment_type"] in ["CONDENSER", "HEAT_PUMP", "COIL", "FURNACE", "AIR_HANDLER"]
    assert data["refrigerant_type"] in ["R410A", "R454B", "R32", "NONE"]
    assert isinstance(data["capacity_btuh"], int)
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in ["ACTIVE", "DISCONTINUED", "ALLOCATED_ONLY"]


def assert_ahri_rating(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ahri_reference_number"], str) and data["ahri_reference_number"]
    assert is_valid_uuid(data.get("outdoor_unit_id", ""))
    assert is_valid_uuid(data.get("indoor_unit_id", ""))
    assert isinstance(data["seer2"], (int, float))
    assert isinstance(data["eer2"], (int, float))
    assert data["efficiency_class"] in ["STANDARD", "HIGH", "PREMIUM"]
    assert isinstance(data["tax_credit_eligible"], bool)
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_prebuy_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert is_iso8601_timestamp(data.get("ship_by_date", ""))
    assert 0 < data["deposit_pct"] <= 0.5
    assert 0 < data["discount_pct"] <= 0.20
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED", "SETTLED"]


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "BACKORDERED", "ALLOCATED", "SHIPPED", "DELIVERED", "CANCELLED",
    ]
    assert data["billing_status"] in [
        "UNBILLED", "DEPOSIT_INVOICED", "DEPOSIT_PAID", "FINAL_INVOICED", "PAID", "FORFEITED",
    ]
    for field in ("subtotal_cents", "discount_cents", "total_cents", "deposit_due_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_discount_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_allocation_pool(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert is_iso8601_timestamp(data.get("season_start", ""))
    assert is_iso8601_timestamp(data.get("season_end", ""))
    assert isinstance(data["total_qty"], int)
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["committed_qty"], int) and data["committed_qty"] >= 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_warranty_registration(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert is_valid_uuid(data.get("equipment_model_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_iso8601_timestamp(data.get("install_date", ""))
    assert is_iso8601_timestamp(data.get("registration_deadline", ""))
    assert data["extended_coverage_years"] in (5, 10)
    assert data["status"] in ["PENDING_REGISTRATION", "REGISTERED", "LAPSED", "VOID"]


def assert_parts_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_number"], str) and data["claim_number"].startswith("PC-")
    assert is_valid_uuid(data.get("warranty_registration_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_iso8601_timestamp(data.get("failure_date", ""))
    for field in ("part_cost_cents", "labor_cost_cents", "covered_part_cents",
                  "covered_labor_cents", "total_award_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["revision_count"], int)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED", "DENIED", "PAID",
    ]


def assert_cylinder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cylinder_tag"], str) and data["cylinder_tag"]
    assert data["refrigerant_type"] in ["R410A", "R454B", "R32"]
    for field in ("tare_weight_lbs", "full_weight_lbs", "current_weight_lbs"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["status"] in ["IN_STOCK", "ISSUED", "RETURN_PENDING", "RETURNED", "RECLAIMED"]


def assert_refrigerant_event(data: dict):
    """Ledger entries carry id + created_at only; no updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not expose updated_at"
    assert "version" not in data, "ledger entries must not expose version"
    assert is_valid_uuid(data.get("cylinder_id", ""))
    assert data["event_type"] in ["ISSUE", "RECOVERY_IN", "RETURN", "RECLAIM", "ADJUSTMENT"]
    assert isinstance(data["weight_delta_lbs"], (int, float))
    assert is_iso8601_timestamp(data.get("recorded_at", ""))


def assert_rebate_submission(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("ahri_rating_id", ""))
    assert data["program_type"] in ["FEDERAL_TAX_CREDIT", "UTILITY_REBATE"]
    assert isinstance(data["qualified_amount_cents"], int)
    assert isinstance(data.get("docs", []), list)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "DOCS_COMPLETE", "QUALIFIED", "REJECTED", "PAID", "EXPIRED",
    ]


def assert_training_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["credit_hours"], int)
    assert isinstance(data["instructor_name"], str) and data["instructor_name"]
    assert isinstance(data["max_seats"], int)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_training_credit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["credit_hours"], int)
    assert isinstance(data["consumed_hours"], int)
    assert data["status"] in ["ACTIVE", "PARTIALLY_CONSUMED", "CONSUMED", "EXPIRED"]


def assert_coop_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert isinstance(data["invoice_reference"], str) and data["invoice_reference"]
    assert isinstance(data["period"], str) and data["period"]
    assert isinstance(data["spend_cents"], int)
    assert isinstance(data["eligible_amount_cents"], int)
    assert data["status"] in ["SUBMITTED", "VERIFIED", "APPROVED", "PAID", "DISPUTED", "REJECTED"]


def assert_pool_quantities_conserved(before: dict, after: dict):
    """Reserved-plus-committed conservation across a submit-then-cancel pair (PRD §3.4)."""
    assert (after["reserved_qty"] + after["committed_qty"]) == (
        before["reserved_qty"] + before["committed_qty"]
    ), (
        f"Pool quantities drifted: before reserved={before['reserved_qty']} "
        f"committed={before['committed_qty']}; after reserved={after['reserved_qty']} "
        f"committed={after['committed_qty']}"
    )
