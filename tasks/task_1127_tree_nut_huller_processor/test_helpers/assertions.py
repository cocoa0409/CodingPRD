"""Entity assertions and domain invariant checkers (PRD Common Resource Properties)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common field assertions
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict):
    """PRD: every resource carries id (UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def _assert_number(value, name, allow_none=False):
    if value is None and allow_none:
        return
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{name} must be a number, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_grower(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ranch_code"], str) and data["ranch_code"]
    assert isinstance(data["base_price_cents_per_lb"], int)
    assert data["base_price_cents_per_lb"] > 0
    _assert_number(data.get("premium_rate_pct"), "premium_rate_pct")
    assert isinstance(data["payable_outstanding_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)


def assert_buyer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["buyer_code"], str) and data["buyer_code"]


def assert_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("grower_id", "")), "grower_id must be a UUID"
    assert isinstance(data["variety"], str) and data["variety"]
    _assert_number(data["gross_weight_lbs"], "gross_weight_lbs")
    assert data["gross_weight_lbs"] > 0
    assert data["status"] in [
        "RECEIVED", "SAMPLED", "GRADED", "ROUTED_IN_SHELL", "ROUTED_KERNEL",
        "PROCESSING", "PROCESSED", "REJECTED", "DISPOSED", "SETTLED",
    ]
    for f in ("intake_moisture_pct", "intake_kernel_pct", "intake_fm_pct",
              "aflatoxin_ppb", "edible_kernel_pct", "post_dry_moisture_pct",
              "provisional_kernel_lbs", "graded_kernel_weight_lbs"):
        _assert_number(data.get(f), f, allow_none=True)
    assert data.get("size_spec") in (None, "SPEC_20_22", "SPEC_23_25", "SPEC_25_27", "UNSIZED")
    assert data.get("requires_drying") in (None, True, False)
    for f in ("kernel_out_lbs", "shell_out_lbs", "hull_out_lbs"):
        _assert_number(data.get(f), f)


def assert_lab_test(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a UUID"
    assert data["test_type"] in ["MOISTURE_KERNEL", "AFLATOXIN", "KERNEL_GRADE"]
    assert data.get("aflatoxin_verdict") in (None, "PASS", "FAIL")
    assert is_iso8601_timestamp(data.get("recorded_at", "")), (
        "recorded_at must be an ISO 8601 timestamp"
    )


def assert_processing_run(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a UUID"
    _assert_number(data.get("input_weight_lbs"), "input_weight_lbs")
    assert data["status"] in ["QUEUED", "RUNNING", "COMPLETED", "CANCELLED"]
    for f in ("kernel_out_lbs", "shell_out_lbs", "hull_out_lbs"):
        _assert_number(data.get(f), f, allow_none=True)


def assert_dryer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["dryer_code"], str) and data["dryer_code"]
    assert isinstance(data["capacity_lbs"], int) and data["capacity_lbs"] > 0


def assert_drying_batch(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("dryer_id", "")), "dryer_id must be a UUID"
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["status"] in ["SCHEDULED", "DRYING", "COMPLETED", "CANCELLED"]
    _assert_number(data.get("final_moisture_pct"), "final_moisture_pct", allow_none=True)


def assert_bin(data: dict):
    assert_common_fields(data)
    assert isinstance(data["bin_code"], str) and data["bin_code"]
    assert isinstance(data["capacity_lbs"], int) and data["capacity_lbs"] > 0
    forms = data["allowed_product_forms"]
    assert isinstance(forms, list) and len(forms) > 0
    for f in forms:
        assert f in ["IN_SHELL", "KERNEL", "HULL", "SHELL"]
    assert data["status"] in ["AVAILABLE", "FUMIGATING", "AERATING"]
    for f in ("occupied_lbs", "available_now_lbs", "projected_available_lbs"):
        _assert_number(data.get(f), f)


def assert_placement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("bin_id", "")), "bin_id must be a UUID"
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a UUID"
    assert data["product_form"] in ["IN_SHELL", "KERNEL", "HULL", "SHELL"]
    _assert_number(data["quantity_lbs"], "quantity_lbs")
    assert data["quantity_lbs"] > 0
    _assert_number(data.get("remaining_lbs"), "remaining_lbs")
    _assert_number(data.get("allocated_planned_lbs"), "allocated_planned_lbs")
    assert is_iso8601_timestamp(data.get("placed_at", "")), "placed_at must be ISO 8601"
    assert data["status"] in [
        "STORED", "FUMIGATION_HOLD", "QUARANTINED", "WITHDRAWN", "DISPOSED",
    ]


def assert_withdrawal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("bin_id", "")), "bin_id must be a UUID"
    assert data["product_form"] in ["IN_SHELL", "KERNEL", "HULL", "SHELL"]
    _assert_number(data["quantity_lbs"], "quantity_lbs")
    assert isinstance(data.get("allocations"), list)
    for entry in data["allocations"]:
        assert is_valid_uuid(entry.get("placement_id", ""))
        _assert_number(entry.get("quantity_lbs"), "allocations[].quantity_lbs")
    assert is_iso8601_timestamp(data.get("withdrawn_at", "")), (
        "withdrawn_at must be ISO 8601"
    )


def assert_fumigation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("bin_id", "")), "bin_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert isinstance(data["aeration_hours"], int) and data["aeration_hours"] > 0
    if data.get("cleared_at") is not None:
        assert is_iso8601_timestamp(data["cleared_at"]), "cleared_at must be ISO 8601"
    assert data["status"] in ["SCHEDULED", "ACTIVE", "AERATING", "CLEARED", "CANCELLED"]


def assert_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("buyer_id", "")), "buyer_id must be a UUID"
    assert data["product_form"] in ["IN_SHELL", "KERNEL"]
    assert data["size_spec"] in ["SPEC_20_22", "SPEC_23_25", "SPEC_25_27", "UNSIZED"]
    _assert_number(data["max_defects_pct"], "max_defects_pct")
    assert isinstance(data["price_cents_per_lb"], int) and data["price_cents_per_lb"] > 0
    _assert_number(data["required_qty_lbs"], "required_qty_lbs")
    _assert_number(data.get("reserved_qty_lbs"), "reserved_qty_lbs")
    _assert_number(data.get("delivered_qty_lbs"), "delivered_qty_lbs")
    assert data["status"] in ["OPEN", "SUSPENDED", "FULFILLED", "CLOSED"]


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert is_valid_uuid(data.get("bin_id", "")), "bin_id must be a UUID"
    _assert_number(data["quantity_lbs"], "quantity_lbs")
    assert isinstance(data.get("allocations"), list)
    for entry in data["allocations"]:
        assert is_valid_uuid(entry.get("placement_id", ""))
        _assert_number(entry.get("quantity_lbs"), "allocations[].quantity_lbs")
    assert data["status"] in ["PLANNED", "BLOCKED", "DELIVERED", "CANCELLED"]


def assert_settlement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a UUID"
    assert is_valid_uuid(data.get("grower_id", "")), "grower_id must be a UUID"
    _assert_number(data.get("graded_kernel_weight_lbs"), "graded_kernel_weight_lbs")
    for f in ("base_cents", "premium_cents", "moisture_deduction_cents", "total_cents"):
        assert isinstance(data.get(f), int), f"{f} must be integer cents"
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "CANCELLED"]


def assert_byproduct_sale(data: dict):
    assert_common_fields(data)
    assert data["product_form"] in ["HULL", "SHELL"]
    _assert_number(data["quantity_lbs"], "quantity_lbs")
    assert data["quantity_lbs"] > 0
    assert isinstance(data["price_cents_per_lb"], int) and data["price_cents_per_lb"] > 0
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert isinstance(data.get("total_cents"), int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_bin_capacity_invariants(data: dict):
    """PRD: projected_available_lbs is never greater than available_now_lbs, and
    occupied_lbs never exceeds capacity_lbs."""
    assert data["occupied_lbs"] <= data["capacity_lbs"] + 1e-9
    assert data["projected_available_lbs"] <= data["available_now_lbs"] + 1e-9


def assert_settlement_invariants(data: dict):
    """PRD: total_cents is the integer sum of the already-rounded components."""
    assert data["total_cents"] == (
        data["base_cents"] + data["premium_cents"] - data["moisture_deduction_cents"]
    )


def assert_grower_balance_invariants(data: dict):
    """Grower balances are whole cents and never negative."""
    assert data["payable_outstanding_cents"] >= 0
    assert data["lifetime_paid_cents"] >= 0
