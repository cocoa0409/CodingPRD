"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.9, §2.10)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0


def assert_machine(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["machine_type"] in ("LATHE", "MILL", "GRINDER")
    assert isinstance(data["year_of_manufacture"], int)
    assert data["control_generation"] in ("LEGACY", "MODERN")
    assert isinstance(data["spindle_hours"], int) and data["spindle_hours"] >= 0
    assert data["status"] in (
        "REGISTERED", "UNDER_ASSESSMENT", "ASSESSED", "IN_PROJECT", "RETURNED", "TRADED_IN",
    )


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str)
    assert isinstance(data["assessor_id"], str)
    assert data["positioning_deviation_microns"] >= 0
    assert data["spindle_runout_microns"] >= 0
    assert data["backlash_microns"] >= 0
    assert isinstance(data["scope_notes"], str)
    assert 0.0 <= data["wear_index"] <= 150.0
    assert data["recommended_path"] in ("RETROFIT_ONLY", "MECHANICAL_REBUILD", "FULL_REBUILD")
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED", "SUPERSEDED")


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["assessment_id"], str)
    assert data["decision"] in ("NONE", "RETROFIT_ONLY", "MECHANICAL_REBUILD", "FULL_REBUILD")
    assert data["work_status"] in (
        "SCOPED", "DECIDED", "PARTS_SOURCING", "REBUILD_IN_PROGRESS", "AWAITING_ACCEPTANCE",
        "REWORK", "ESCALATED", "ACCEPTED", "TRAINING_IN_PROGRESS", "HANDOVER_READY",
        "WARRANTY_ACTIVE", "CLOSED", "CANCELLED",
    )
    assert data["commercial_status"] in ("QUOTE_DRAFT", "QUOTE_SENT", "APPROVED")
    assert isinstance(data["quote_revision"], int) and data["quote_revision"] >= 0
    assert isinstance(data["quote_stale"], bool)
    for money_field in (
        "base_price_cents", "parts_total_cents", "labor_cents", "discount_cents",
        "applied_trade_in_credit_cents", "quote_price_cents", "rework_cost_cents",
    ):
        assert isinstance(data[money_field], int), f"{money_field} must be integer cents"
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert isinstance(data["consecutive_fail_count"], int) and data["consecutive_fail_count"] >= 0
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["description"], str)
    assert data["oem_status"] in ("ACTIVE", "OBSOLETE", "SUPERSEDED")
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert isinstance(data["stock_quantity"], int) and data["stock_quantity"] >= 0
    assert isinstance(data["available_quantity"], int)
    assert isinstance(data["reserved_quantity"], int) and data["reserved_quantity"] >= 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert_part_stock_conservation(data)


def assert_part_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert data["obs_multiplier"] in (1.0, 1.8)
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] > 0
    assert data["status"] in (
        "PENDING", "RESERVED", "FULFILLED", "RE_PENDING", "RE_FULFILLED", "CANCELLED",
    )


def assert_re_job(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_line_id"], str)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in (
        "REQUESTED", "SPEC_CAPTURED", "PROTOTYPE_FABRICATED", "VALIDATED", "CANCELLED",
    )


def assert_downtime_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED", "CANCELLED")


def assert_shipment_stage(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["window_id"], str)
    assert isinstance(data["stage_sequence"], int) and data["stage_sequence"] > 0
    assert isinstance(data["planned_ship_date"], str)
    assert isinstance(data["planned_return_date"], str)
    assert data["status"] in ("PLANNED", "SHIPPED", "RECEIVED", "INSTALLED", "ON_HOLD", "CANCELLED")


def assert_acceptance_test(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")
    if data["status"] == "SCHEDULED":
        # PRD §3.6: the inspector supplies samples_microns and
        # repeatability_microns at recording time, and the server derives the
        # measurement fields then; a born-SCHEDULED test carries none yet, and
        # the PRD does not pin their pre-recording values.
        return
    assert isinstance(data["samples_microns"], list) and len(data["samples_microns"]) == 5
    assert data["repeatability_microns"] >= 0
    assert data["evaluation_variant"] in ("WORST_CASE", "ISO_STATISTICAL")
    assert data["max_abs_sample_microns"] >= 0
    assert data["statistic_value"] >= 0


def assert_training_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["sessions_required"], int) and data["sessions_required"] >= 1
    assert isinstance(data["sessions_completed"], int) and data["sessions_completed"] >= 0
    assert isinstance(data["documentation_delivered"], bool)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert data["claim_type"] in ("ACCURACY_DRIFT", "MECHANICAL_DEFECT")
    assert data["status"] in ("FILED", "APPROVED", "REJECTED", "CLOSED")
    assert isinstance(data["filed_at"], str)


def assert_trade_in_offer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["valuation_variant"] in ("MARKET_COMPARABLE", "COST_APPROACH")
    assert isinstance(data["market_value_cents"], int)
    assert isinstance(data["cost_value_cents"], int)
    assert isinstance(data["residual_value_cents"], int)
    assert isinstance(data["expires_at"], str)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "SUPERSEDED", "EXPIRED")


def assert_part_stock_conservation(part: dict):
    """PRD §2.9: available_quantity + reserved_quantity == stock_quantity."""
    assert part["available_quantity"] + part["reserved_quantity"] == part["stock_quantity"], (
        f"stock conservation violated: available {part['available_quantity']} + "
        f"reserved {part['reserved_quantity']} != stock {part['stock_quantity']}"
    )


def assert_quote_conservation(project: dict):
    """PRD §2.10: quote_price_cents + applied_trade_in_credit_cents ==
    base_price_cents + parts_total_cents + labor_cents - discount_cents."""
    lhs = project["quote_price_cents"] + project["applied_trade_in_credit_cents"]
    rhs = (
        project["base_price_cents"]
        + project["parts_total_cents"]
        + project["labor_cents"]
        - project["discount_cents"]
    )
    assert lhs == rhs, f"quote conservation violated: {lhs} != {rhs}"
