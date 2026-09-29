"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ELEMENT_ORDER,
    ELEMENT_SEVERITY,
    STANDARD_UNIT_COST_CENTS,
)


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict):
    """Every persisted row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert "-" in data["id"], "id must be a bare UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_envelope_meta(body: dict):
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {meta['api_request_id']!r}"
    )
    assert isinstance(meta.get("api_request_timestamp"), str)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_brief(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and 4 <= len(data["sku_code"]) <= 32
    assert isinstance(data["product_name"], str)
    assert data["regulatory_scheme"] in ["FDA_FOOD", "EU_FIC", "HEALTH_CANADA"]
    assert data["status"] in ["DRAFT", "APPROVED", "REJECTED"]
    assert 1 <= len(data["market_codes"]) <= 6
    assert 1 <= len(data["language_codes"]) <= 6
    assert 1 <= len(data["required_element_codes"]) <= 7
    assert isinstance(data["structural_spec"], dict)
    assert isinstance(data["net_contents_declaration"], dict)
    assert isinstance(data["asset_count"], int) and data["asset_count"] >= 0


def assert_marketing_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data["claim_code"], str)
    assert data["claim_type"] in [
        "NUTRIENT_CONTENT",
        "STRUCTURE_FUNCTION",
        "ORGANIC",
        "FREE_FROM",
        "SUSTAINABILITY",
    ]
    assert data["legal_status"] in ["DRAFT", "CLEARED", "REJECTED"]
    assert len(data["market_code"]) == 2
    assert isinstance(data["usage_count"], int) and data["usage_count"] >= 0


def assert_artwork_asset(data: dict):
    assert_common_fields(data)
    assert data["component_type"] in ["CARTON", "LABEL", "FILM", "SHIPPER"]
    assert data["substrate_class"] in [
        "COATED_PAPER",
        "UNCOATED_PAPER",
        "FILM",
        "METALLIZED",
    ]
    assert data["obsolescence_state"] in ["ACTIVE", "SUPERSEDE_PENDING", "SUPERSEDED"]
    assert isinstance(data["brand_critical_color"], bool)
    assert data["plate_budget_cents"] >= 0
    assert data["standard_unit_cost_cents"] == STANDARD_UNIT_COST_CENTS[
        data["component_type"]
    ], "standard_unit_cost_cents is derived from the component type"
    assert data["committed_plate_cost_cents"] >= 0
    assert data["obsolete_units_total"] >= 0
    assert data["changeover_cost_committed_cents"] >= 0
    assert isinstance(data["version_counter"], int) and data["version_counter"] >= 0
    assert 1 <= len(data["language_codes"]) <= 6


def assert_artwork_version(data: dict):
    assert_common_fields(data)
    assert data["state"] in [
        "DRAFT",
        "ELEMENTS_VERIFIED",
        "IN_REVIEW",
        "REVISION_REQUESTED",
        "APPROVED",
        "RELEASED_TO_PRINT",
        "OBSOLETE_PENDING",
        "OBSOLETE",
    ]
    assert data["reason_for_change_code"] in [
        "NEW_LAUNCH",
        "REGULATORY_UPDATE",
        "CLAIM_CHANGE",
        "MARKETING_REFRESH",
        "PRINTER_CHANGE",
        "ERROR_CORRECTION",
    ]
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]
    assert 10 <= len(data["change_description"]) <= 500
    assert isinstance(data["claim_ids"], list) and len(data["claim_ids"]) <= 8
    assert isinstance(data["check_run_no"], int) and data["check_run_no"] >= 0
    assert isinstance(data["failed_element_count"], int)
    assert isinstance(data["waived_element_count"], int)
    assert isinstance(data["revision_cycle_count"], int)
    assert isinstance(data["route_count"], int)
    assert isinstance(data["requires_reverification"], bool)
    assert isinstance(data["open_condition_codes"], list)
    assert isinstance(data["pinned_claim_snapshot"], list)
    if data["compliance_score"] is not None:
        assert 0.0 <= data["compliance_score"] <= 100.0


def assert_element_check(data: dict):
    assert_common_fields(data)
    assert data["element_code"] in ELEMENT_ORDER
    assert data["severity"] == ELEMENT_SEVERITY[data["element_code"]], (
        "severity is a fixed property of the element"
    )
    assert data["result"] in ["PASS", "FAIL", "WAIVED"]
    assert isinstance(data["detail"], str) and data["detail"]
    assert data["deduction_points"] >= 0
    assert isinstance(data["check_run_no"], int) and data["check_run_no"] >= 1


def assert_review_route(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PENDING",
        "IN_PROGRESS",
        "COMPLETE_APPROVED",
        "COMPLETE_REJECTED",
    ]
    assert isinstance(data["route_no"], int) and data["route_no"] >= 1
    assert data["current_stage_no"] in [1, 2, 3]
    assert isinstance(data["stage_plan"], list) and len(data["stage_plan"]) == 3
    assert isinstance(data["conditional_count"], int)


def assert_review_task(data: dict):
    assert_common_fields(data)
    assert data["discipline"] in ["BRAND", "LEGAL", "REGULATORY", "QUALITY"]
    assert data["mode"] in ["PARALLEL", "SEQUENTIAL"]
    assert data["stage_no"] in [1, 2, 3]
    assert isinstance(data["is_active"], bool)
    assert data["decision"] in [
        "PENDING",
        "APPROVED",
        "REJECTED",
        "CONDITIONAL",
        "SKIPPED",
    ]


def assert_printer(data: dict):
    assert_common_fields(data)
    assert 3 <= len(data["name"]) <= 80
    assert data["color_standard"] in ["G7_MASTER", "ISO12647"]
    assert 1 <= len(data["certified_substrates"]) <= 4
    assert data["certification_status"] in ["CERTIFIED", "PROBATION"]
    assert 0.0 <= data["performance_score"] <= 100.0
    assert data["recovery_liability_cap_cents"] >= 0
    assert isinstance(data["recovery_balance_cents"], int)
    assert isinstance(data["escape_count"], int)


def assert_printer_proof(data: dict):
    assert_common_fields(data)
    assert data["color_status"] in ["COLOR_PENDING", "COLOR_PASS", "COLOR_FAIL"]
    assert data["substrate_status"] in [
        "SUBSTRATE_PENDING",
        "SUBSTRATE_APPROVED",
        "SUBSTRATE_REJECTED",
    ]
    assert data["press_check_status"] in [
        "NOT_REQUIRED",
        "PRESS_CHECK_REQUIRED",
        "PRESS_CHECK_SCHEDULED",
        "PRESS_CHECK_ATTENDED",
    ]
    assert data["proof_state"] in [
        "PROOF_IN_REVIEW",
        "PROOF_APPROVED",
        "PROOF_REJECTED",
    ]
    assert isinstance(data["press_check_required"], bool)
    assert isinstance(data["requires_recheck"], bool)
    assert isinstance(data["proof_no"], int) and data["proof_no"] >= 1
    assert data["effective_tolerance"] > 0


def assert_plate_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ORDERED", "CANCELLED"]
    assert 1 <= data["plate_set_count"] <= 24
    assert isinstance(data["auto_cancelled"], bool)
    assert data["cost_cents"] == (
        data["plate_subtotal_cents"] + data["setup_fee_cents"] + data["expedite_fee_cents"]
    ), "cost_cents is subtotal plus setup fee plus expedite fee"


def assert_inventory_runout(data: dict):
    assert_common_fields(data)
    assert data["state"] in ["PLANNED", "MONITORING", "RUNOUT_COMPLETE", "SCRAPPED"]
    assert data["disposition"] in [None, "RUNOUT", "SCRAP"]
    assert data["on_hand_qty"] >= 0
    assert data["weekly_usage_qty"] >= 0
    assert data["remaining_qty"] >= 0
    assert isinstance(data["depletion_records"], list)
    assert isinstance(data["reversal_count"], int)
    assert len(data["projected_runout_date"]) == 10, (
        "dates are rendered as YYYY-MM-DD"
    )
    if data["trailing_avg_usage_qty"] is not None:
        assert data["trailing_avg_usage_qty"] >= 1


def assert_error_escape(data: dict):
    assert_common_fields(data)
    assert data["defect_code"] in [
        "WRONG_ALLERGEN",
        "MISSING_NET_CONTENTS",
        "WRONG_LANGUAGE_VARIANT",
        "COLOR_OUT_OF_TOLERANCE",
        "WRONG_DATE_CODE",
        "OLD_ARTWORK_USED",
    ]
    assert data["discovered_stage"] in ["PRESS", "PACKING", "DISTRIBUTION", "MARKET"]
    assert data["state"] in [
        "OPEN",
        "ROOT_CAUSE_ASSIGNED",
        "RECOVERY_CLAIMED",
        "DISPUTED",
        "SETTLED",
        "WRITTEN_OFF",
    ]
    assert data["root_cause_party"] in [None, "PRINTER", "BRAND", "AGENCY", "SHARED"]
    assert data["resolution"] in [None, "SETTLED", "WRITTEN_OFF"]
    assert data["units_affected"] >= 1
    assert isinstance(data["liability_cap_applied"], bool)
    assert data["investigation_fee_cents"] in (60000, 150000)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_element_rows_in_fixed_order(rows: list):
    """Verdict rows are returned in the fixed element order, not insertion order."""
    codes = [row["element_code"] for row in rows]
    expected = [code for code in ELEMENT_ORDER if code in codes]
    assert codes == expected, (
        f"element rows must follow the fixed element order; got {codes}"
    )


def assert_committed_plate_ledger(asset: dict, ordered_orders: list):
    """committed_plate_cost_cents is the sum of cost_cents over ORDERED orders."""
    expected = sum(
        order["cost_cents"] for order in ordered_orders if order["status"] == "ORDERED"
    )
    assert asset["committed_plate_cost_cents"] == expected, (
        f"committed_plate_cost_cents should be {expected}, "
        f"got {asset['committed_plate_cost_cents']}"
    )


def assert_unit_conservation(runout: dict):
    """on_hand_qty equals remaining_qty plus the sum of all consumed units."""
    consumed = sum(r["units_consumed"] for r in runout["depletion_records"])
    assert runout["on_hand_qty"] == runout["remaining_qty"] + consumed, (
        f"on_hand_qty {runout['on_hand_qty']} must equal remaining_qty "
        f"{runout['remaining_qty']} + consumed {consumed}"
    )


def assert_integer_cents(*values):
    for value in values:
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"monetary amounts are integer cents, got {value!r}"
        )


def assert_one_decimal_place(value: float):
    assert round(float(value), 1) == float(value), (
        f"{value!r} must carry at most one decimal place"
    )


def assert_version_bumped_by(before: dict, after: dict, delta: int = 1):
    assert after["version"] == before["version"] + delta, (
        f"version should move from {before['version']} to "
        f"{before['version'] + delta}, got {after['version']}"
    )
