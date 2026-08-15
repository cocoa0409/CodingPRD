"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4 system-managed properties carried by every resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def _assert_optional_iso8601(value, field: str):
    if value is not None:
        assert is_iso8601_timestamp(value), (
            f"{field} must be ISO 8601 UTC when set, got {value!r}"
        )


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["account_tier"] in ("STANDARD", "CONTRACT")
    assert isinstance(data["branding_required"], bool)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0


def assert_material(data: dict):
    assert_common_fields(data)
    assert data["foam_family"] in ("PE", "EPE", "PU", "XLPE")
    assert isinstance(data["density_pcf"], (int, float)) and data["density_pcf"] > 0
    assert isinstance(data["ild_lb_25"], int)
    assert isinstance(data["sheet_length_in"], (int, float))
    assert isinstance(data["sheet_width_in"], (int, float))
    assert isinstance(data["sheet_thickness_in"], (int, float))
    assert isinstance(data["cost_per_board_ft_cents"], int)
    assert isinstance(data["recyclable"], bool)
    assert isinstance(data["scrap_credit_per_lb_cents"], int)


def assert_package_spec(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["material_id"], str)
    assert isinstance(data["part_name"], str) and data["part_name"]
    assert isinstance(data["part_length_in"], (int, float))
    assert isinstance(data["part_width_in"], (int, float))
    assert isinstance(data["product_weight_lb"], (int, float))
    assert isinstance(data["required_drop_height_in"], int)
    assert isinstance(data["max_fragility_g"], int)
    assert isinstance(data["required_ild_lb"], int)
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "IN_VALIDATION", "VALIDATED", "APPROVED",
    )
    if data["status"] == "APPROVED":
        _assert_optional_iso8601(data["signed_off_at"], "signed_off_at")
        assert data["signed_off_at"] is not None
    else:
        assert data.get("signed_off_at") is None


def assert_cut_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["package_spec_id"], str)
    assert data["method"] in ("DIE_CUT", "CNC_ROUTE")
    if data["method"] == "CNC_ROUTE":
        assert isinstance(data["machine_seconds_per_part"], int)
    if data.get("supersedes_cut_program_id") is not None:
        assert isinstance(data["supersedes_cut_program_id"], str)
    assert data["status"] in ("DRAFT", "NESTED", "LOCKED", "OBSOLETE")
    if data["status"] in ("NESTED", "LOCKED"):
        assert isinstance(data["parts_per_sheet"], int)
        assert isinstance(data["sheet_utilization_pct"], (int, float))
        assert isinstance(data["offcut_sqft_per_sheet"], (int, float))


def assert_tooling(data: dict):
    assert_common_fields(data)
    assert isinstance(data["cut_program_id"], str)
    assert isinstance(data["die_cost_cents"], int)
    assert isinstance(data["amortization_qty"], int)
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["amortized_cents"], int)
    assert data["status"] in ("ORDERED", "IN_SERVICE", "RETIRED")


def assert_drop_test(data: dict):
    assert_common_fields(data)
    assert isinstance(data["package_spec_id"], str)
    _assert_optional_iso8601(data["scheduled_start"], "scheduled_start")
    _assert_optional_iso8601(data["scheduled_end"], "scheduled_end")
    assert isinstance(data["drop_height_in"], int)
    assert data["orientation"] in ("FLAT", "EDGE", "CORNER")
    assert isinstance(data["pass_limit_g"], int)
    assert isinstance(data["spec_revision_no"], int)
    assert data["status"] in ("SCHEDULED", "RECORDED")
    if data["status"] == "RECORDED":
        assert isinstance(data["measured_peak_g"], int)
        assert data["result"] in ("PASS", "FAIL")
    else:
        assert data.get("measured_peak_g") is None
        assert data.get("result") is None


def assert_production_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["package_spec_id"], str)
    assert isinstance(data["cut_program_id"], str)
    if data.get("inventory_program_id") is not None:
        assert isinstance(data["inventory_program_id"], str)
    assert data["order_kind"] in ("CUSTOMER", "REPLENISHMENT")
    assert isinstance(data["qty"], int) and data["qty"] > 0
    assert isinstance(data["provisional_unit_price_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert data["fab_status"] in (
        "QUOTED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert data["quality_hold"] in ("NONE", "ON_HOLD")
    if data["fab_status"] in ("CONFIRMED", "IN_PROGRESS", "COMPLETED"):
        assert isinstance(data["final_unit_price_cents"], int)
        assert isinstance(data["final_total_cents"], int)
        assert isinstance(data["tooling_amort_cents"], int)


def assert_inventory_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["package_spec_id"], str)
    assert data["pricing_mode"] in ("LOCKED", "CURRENT")
    assert isinstance(data["max_stock_qty"], int)
    assert isinstance(data["reorder_point_qty"], int)
    assert isinstance(data["min_release_qty"], int)
    if data.get("locked_material_cost_bf_cents") is not None:
        assert isinstance(data["locked_material_cost_bf_cents"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED", "CLOSED")
    for counter in ("produced_qty", "on_hand_qty", "reserved_qty", "shipped_qty"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must be non-negative"


def assert_release_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["inventory_program_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] > 0
    _assert_optional_iso8601(data["requested_ship_date"], "requested_ship_date")
    assert data["status"] in ("PENDING", "ALLOCATED", "SHIPPED", "CANCELLED")
    if data["status"] in ("ALLOCATED", "SHIPPED"):
        assert isinstance(data["unit_price_cents"], int)
        assert isinstance(data["total_price_cents"], int)


def assert_scrap_batch(data: dict):
    assert_common_fields(data)
    assert isinstance(data["production_order_id"], str)
    assert isinstance(data["gross_weight_lb"], (int, float))
    assert isinstance(data["contamination_pct"], (int, float))
    assert 0 <= data["contamination_pct"] <= 100
    assert isinstance(data["net_recyclable_lb"], (int, float))
    assert data["status"] in ("COLLECTED", "PROCESSED", "CREDITED")
    if data["status"] == "CREDITED":
        assert isinstance(data["credit_cents"], int)
        _assert_optional_iso8601(data["credited_at"], "credited_at")
        assert data["credited_at"] is not None
    else:
        assert data.get("credit_cents") is None
        assert data.get("credited_at") is None


def assert_program_stock_invariant(program: dict):
    """Stock conservation: units enter via completed replenishment production
    and leave via shipment, so produced == on_hand + shipped at all times."""
    assert program["produced_qty"] == program["on_hand_qty"] + program["shipped_qty"], (
        f"stock drift: produced {program['produced_qty']} != on_hand "
        f"{program['on_hand_qty']} + shipped {program['shipped_qty']}"
    )
    assert 0 <= program["reserved_qty"] <= program["on_hand_qty"]


def assert_tooling_amortization_within_cost(tooling: dict):
    """A die can never amortize more cents than its total die cost."""
    assert 0 <= tooling["amortized_cents"] <= tooling["die_cost_cents"]
