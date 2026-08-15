"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_style(data):
    _assert_common_fields(data)
    assert isinstance(data.get("style_code"), str) and data["style_code"]
    assert data.get("status") in ("DRAFT", "ACTIVE")
    assert data.get("certification_status") in ("UNCERTIFIED", "CERTIFIED", "REVOKED")
    assert data.get("content_qualification") in (
        "UNDETERMINED", "QUALIFIED_STRICT", "QUALIFIED_COST_ONLY", "NOT_QUALIFIED",
    )
    assert data.get("target_content_claim") in ("NONE", "MADE_IN_USA")
    assert isinstance(data.get("size_run"), list) and data["size_run"]
    assert isinstance(data.get("declared_fabric_domestic"), bool)
    assert isinstance(data.get("created_by_user_id"), str) and data["created_by_user_id"]


def assert_tech_pack(data):
    _assert_common_fields(data)
    assert data.get("status") in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "SUPERSEDED")
    assert isinstance(data.get("version_no"), int) and data["version_no"] >= 1
    assert isinstance(data.get("style_id"), str) and data["style_id"]
    assert isinstance(data.get("base_measurements"), list)
    assert isinstance(data.get("grade_rules"), list)
    assert isinstance(data.get("labor_cost_cents_per_unit"), int)
    assert isinstance(data.get("fabric_cost_cents_per_unit"), int)


def assert_operation_spec(data):
    _assert_common_fields(data)
    assert isinstance(data.get("sequence_no"), int) and data["sequence_no"] >= 1
    assert data.get("machine_type") in (
        "SINGLE_NEEDLE", "OVERLOCK", "COVERSTITCH", "BUTTONHOLE", "MANUAL",
    )
    assert isinstance(data.get("sam_seconds"), int) and data["sam_seconds"] > 0
    assert isinstance(data.get("piece_rate_cents"), int) and data["piece_rate_cents"] >= 0


def assert_trim_item(data):
    _assert_common_fields(data)
    assert isinstance(data.get("sku_code"), str) and data["sku_code"]
    assert isinstance(data.get("origin_country"), str) and data["origin_country"]
    assert isinstance(data.get("unit_cost_cents"), int) and data["unit_cost_cents"] >= 0
    assert isinstance(data.get("qty_on_hand"), int)
    assert isinstance(data.get("qty_reserved"), int)
    assert isinstance(data.get("qty_available"), int)
    assert data["qty_available"] == data["qty_on_hand"] - data["qty_reserved"], (
        f"qty_available must equal qty_on_hand - qty_reserved, got "
        f"{data['qty_available']} != {data['qty_on_hand']} - {data['qty_reserved']}"
    )


def assert_trim_requirement(data):
    _assert_common_fields(data)
    assert isinstance(data.get("units_per_garment"), int) and data["units_per_garment"] >= 1
    assert 0 <= data.get("wastage_pct", -1) <= 0.5


def assert_fabric_roll(data):
    _assert_common_fields(data)
    assert data.get("status") in ("RECEIVED", "AVAILABLE", "REJECTED", "DEPLETED")
    assert isinstance(data.get("roll_code"), str) and data["roll_code"]
    for f in ("received_yards", "usable_yards", "allocated_yards", "consumed_yards", "available_yards"):
        assert isinstance(data.get(f), (int, float)), f"{f} must be numeric, got {data.get(f)!r}"


def assert_production_order(data):
    _assert_common_fields(data)
    assert data.get("production_status") in ("PLANNED", "CUTTING", "SEWING", "FINISHED")
    assert data.get("trim_hold_status") in ("MATERIALS_OK", "TRIM_HOLD")
    assert data.get("quality_status") in ("QC_PENDING", "QC_PASSED", "QC_FAILED", "REWORK_IN_PROGRESS")
    assert isinstance(data.get("size_quantities"), list) and data["size_quantities"]
    assert isinstance(data.get("total_order_qty"), int)
    assert isinstance(data.get("trim_shortages"), list)


def assert_marker(data):
    _assert_common_fields(data)
    assert data.get("status") in ("DRAFT", "APPROVED", "CUT", "CANCELLED")
    assert isinstance(data.get("planned_pieces"), int) and data["planned_pieces"] > 0
    assert isinstance(data.get("marker_length_yards"), (int, float))


def assert_bundle(data):
    _assert_common_fields(data)
    assert data.get("status") in ("TICKETED", "RELEASED", "IN_PROGRESS", "REWORK_HOLD", "COMPLETED")
    assert isinstance(data.get("qty"), int) and data["qty"] > 0
    assert isinstance(data.get("completed_through_seq"), int)
    if data.get("pre_rework_status") is not None:
        assert data["pre_rework_status"] in ("RELEASED", "IN_PROGRESS", "COMPLETED")


def assert_sewing_line(data):
    _assert_common_fields(data)
    assert isinstance(data.get("station_count"), int) and data["station_count"] >= 1
    assert isinstance(data.get("shift_minutes"), int) and data["shift_minutes"] > 0


def assert_line_assignment(data):
    _assert_common_fields(data)
    assert 0 <= data.get("start_minute", -1) < data.get("end_minute", -1) <= 1440
    assert isinstance(data.get("assigned_pieces"), int) and data["assigned_pieces"] > 0


def assert_operator(data):
    _assert_common_fields(data)
    assert data.get("status") in ("ACTIVE", "INACTIVE")
    assert isinstance(data.get("employee_no"), str) and data["employee_no"]
    assert isinstance(data.get("efficiency_pct"), (int, float))
    assert isinstance(data.get("ytd_earnings_cents"), int)


def assert_piece_work_entry(data):
    _assert_common_fields(data)
    assert data.get("status") in ("LOGGED", "VERIFIED", "REJECTED", "PAID")
    assert isinstance(data.get("qty"), int) and data["qty"] > 0
    assert isinstance(data.get("piece_earnings_cents"), int)
    assert isinstance(data.get("earned_minutes"), (int, float))
    assert isinstance(data.get("operator_id"), str) and data["operator_id"]


def assert_payroll_run(data):
    _assert_common_fields(data)
    assert data.get("status") in ("OPEN", "CALCULATED", "APPROVED", "PAID")
    for f in ("entry_count", "total_piece_cents", "total_topup_cents",
              "total_bonus_cents", "total_payable_cents"):
        assert isinstance(data.get(f), int), f"{f} must be an integer, got {data.get(f)!r}"


def assert_quality_audit(data):
    _assert_common_fields(data)
    assert data.get("status") in ("OPEN", "CLOSED_PASS", "CLOSED_FAIL", "REWORK_RECORDED", "SUPERSEDED")
    assert data.get("result") in ("NONE", "PASS", "FAIL")
    assert data.get("inspection_level") in ("NORMAL", "TIGHTENED")
    assert data.get("aql_level") in ("AQL_2_5", "AQL_4_0")
    assert isinstance(data.get("lot_size"), int)
    assert isinstance(data.get("accept_max"), int)
    assert isinstance(data.get("reject_min"), int)
    assert data["reject_min"] == data["accept_max"] + 1, (
        f"reject_min must be accept_max + 1, got {data['accept_max']} / {data['reject_min']}"
    )


# --- Domain invariants -------------------------------------------------------

def assert_fabric_ledger_invariants(roll):
    """PRD §2.9: available_yards is always usable_yards - allocated_yards - consumed_yards."""
    assert roll["available_yards"] == round(
        roll["usable_yards"] - roll["allocated_yards"] - roll["consumed_yards"], 2
    ), (
        f"fabric ledger broken: available {roll['available_yards']} != "
        f"usable {roll['usable_yards']} - allocated {roll['allocated_yards']} "
        f"- consumed {roll['consumed_yards']}"
    )


def assert_trim_ledger_invariants(item):
    """PRD §2.9: qty_available is always exactly qty_on_hand - qty_reserved."""
    assert item["qty_available"] == item["qty_on_hand"] - item["qty_reserved"], (
        f"trim ledger broken: qty_available {item['qty_available']} != "
        f"qty_on_hand {item['qty_on_hand']} - qty_reserved {item['qty_reserved']}"
    )
