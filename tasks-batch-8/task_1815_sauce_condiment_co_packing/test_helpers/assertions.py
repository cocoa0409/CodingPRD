"""Entity assertions and domain invariant checkers.

Each assert_* checks the system-managed fields of PRD §2.4 plus the status
membership and always-present PRD-named fields for the resource. Fields the
PRD describes as unset until a later lifecycle point (e.g. final_charge_cents,
disposition) are only examined via .get() so that both "absent" and "null"
serializations satisfy the check.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer_account(data: dict):
    _assert_common(data)
    assert isinstance(data["brand_name"], str) and data["brand_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["default_disposition_owner"] in ("CUSTOMER", "COPACKER")
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_billed_cents"], int)


def assert_formula(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert data["process_category"] in ("ACIDIFIED", "LOW_ACID", "ACID")
    assert data["allergen_class"] in ("NONE", "GLUTEN", "SOY", "NUT", "DAIRY")
    assert isinstance(data["min_run_units"], int) and data["min_run_units"] >= 1
    assert isinstance(data["unit_rate_cents"], int) and data["unit_rate_cents"] >= 0
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ("DRAFT", "IN_TRIAL", "TRIAL_PASSED", "APPROVED")


def assert_ingredient_supply(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["ingredient_name"], str) and data["ingredient_name"]
    assert data["sourcing_mode"] in ("CUSTOMER_SUPPLIED", "COPACKER_SUPPLIED")
    assert data["quantity_per_unit"] > 0
    assert data["consigned_units_on_hand"] >= 0


def assert_pilot_cell(data: dict):
    _assert_common(data)
    assert isinstance(data["cell_name"], str) and data["cell_name"]
    assert isinstance(data["max_batch_units"], int) and data["max_batch_units"] >= 1


def assert_scale_up_trial(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("pilot_cell_id", ""))
    assert isinstance(data["batch_size_units"], int) and data["batch_size_units"] >= 1
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")


def assert_process_authority_letter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["formula_revision"], int) and data["formula_revision"] >= 1
    assert isinstance(data["authority_name"], str) and data["authority_name"]
    assert isinstance(data["letter_number"], str) and data["letter_number"]
    assert 0 < data["max_ph"] < 4.6
    assert 0 < data["max_water_activity"] < 1.0
    assert data["status"] in ("SUBMITTED", "ACTIVE", "SUPERSEDED")


def assert_kettle_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_name"], str) and data["line_name"]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1


def assert_packaging_component(data: dict):
    _assert_common(data)
    assert isinstance(data["component_name"], str) and data["component_name"]
    assert data["component_type"] in ("BOTTLE", "CAP", "LABEL", "CASE")
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)
    # PRD §3.4 invariant: on_hand_units never drops below reserved_units.
    assert data["on_hand_units"] >= data["reserved_units"], (
        f"on_hand_units {data['on_hand_units']} below reserved_units "
        f"{data['reserved_units']}"
    )
    if data.get("available_units") is not None:
        assert data["available_units"] == data["on_hand_units"] - data["reserved_units"]


def assert_production_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("kettle_line_id", ""))
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 1
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["formula_revision"], int) and data["formula_revision"] >= 1
    assert data["status"] in (
        "PLANNED", "CONFIRMED", "COMPLETED", "ON_HOLD",
        "REWORK", "RELEASED", "CANCELLED", "DESTROYED",
    )


def assert_quality_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("production_run_id", ""))
    assert data["reason_category"] in (
        "PH_DEVIATION", "AW_DEVIATION", "FOREIGN_MATERIAL", "LABEL_MISMATCH"
    )
    assert data["disposition_owner"] in ("CUSTOMER", "COPACKER")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in ("OPEN", "DISPOSITIONED")


def assert_label_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["label_version"], str) and data["label_version"]
    assert isinstance(data["brand_display_name"], str) and data["brand_display_name"]
    assert isinstance(data["net_quantity_statement"], str)
    assert data["allergen_declaration"] in ("NONE", "GLUTEN", "SOY", "NUT", "DAIRY")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
