"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import RETENTION_RATE


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict, entity: str = "resource"):
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version begins at 1, got {data['version']}"


def assert_identity_only_fields(data: dict, entity: str = "resource"):
    """id + created_at and nothing else from the common set."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, f"{entity} must not emit updated_at"
    assert "version" not in data, f"{entity} must not emit version"


def assert_integer_cents(value, field: str):
    assert value is None or isinstance(value, int), (
        f"{field} must be whole integer cents, got {value!r}"
    )


def assert_two_decimals(value, field: str):
    if value is None:
        return
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must be held to two decimal places, got {value!r}"
    )


def assert_one_decimal(value, field: str):
    if value is None:
        return
    assert round(float(value), 1) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must be held to one decimal place, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_facade_package(data: dict):
    assert_common_fields(data, "FacadePackage")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["floor_count"], int) and data["floor_count"] >= 1
    assert float(data["total_area_sqm"]) > 0
    assert_integer_cents(data["contract_value_cents"], "contract_value_cents")
    assert_integer_cents(data["unit_rate_cents_per_sqm"], "unit_rate_cents_per_sqm")
    assert_integer_cents(
        data["base_labor_rate_cents_per_hour"], "base_labor_rate_cents_per_hour"
    )
    assert float(data["design_temp_delta_c"]) > 0
    assert data["system_type"] in ("UNDECIDED", "UNITIZED", "STICK_BUILT")
    assert data["state"] in (
        "DESIGN_ASSIST",
        "SYSTEM_SELECTED",
        "MOCKUP_QUALIFIED",
        "IN_FABRICATION",
        "IN_INSTALLATION",
        "WEATHER_TIGHT_ACHIEVED",
        "CLOSED_OUT",
    )
    assert data["engineering_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["blocking_submittal_count"], int)
    assert isinstance(data["open_critical_defect_count"], int)
    assert isinstance(data["mockup_qualified"], bool)
    assert_two_decimals(data["planned_shop_hours"], "planned_shop_hours")
    assert_two_decimals(data["certified_area_sqm"], "certified_area_sqm")
    assert_integer_cents(data["earned_value_certified_cents"], "earned_value_certified_cents")
    assert_integer_cents(data["retention_held_cents"], "retention_held_cents")
    assert isinstance(data["weather_tight_zone_count"], int)


def assert_installation_zone(data: dict):
    assert_common_fields(data, "InstallationZone")
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["floor_number"], int) and data["floor_number"] >= 1
    assert data["elevation_label"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert float(data["area_sqm"]) > 0
    assert float(data["height_m"]) > 0
    assert isinstance(data["span_mm"], int) and data["span_mm"] >= 1
    assert data["anchor_type"] in ("SLOTTED", "PINNED", "FIXED")
    assert float(data["designed_joint_mm"]) > 0
    assert isinstance(data["planned_panel_count"], int) and data["planned_panel_count"] >= 1
    assert float(data["budget_crew_hours"]) > 0
    assert data["install_status"] in ("PLANNED", "ANCHORS_SET", "PANELS_HUNG")
    assert data["weather_status"] in ("NOT_TIGHT", "WEATHER_TIGHT", "REMEDIATION")
    assert_two_decimals(data["thermal_movement_allowance_mm"], "thermal_movement_allowance_mm")
    assert_two_decimals(data["deflection_limit_mm"], "deflection_limit_mm")
    assert_integer_cents(
        data["provisional_labor_cost_cents"], "provisional_labor_cost_cents"
    )
    assert_integer_cents(data["final_labor_cost_cents"], "final_labor_cost_cents")
    assert_integer_cents(data["certified_line_cents"], "certified_line_cents")
    assert isinstance(data["weather_tight_cycle_count"], int)
    assert_one_decimal(data["consumed_crew_hours"], "consumed_crew_hours")
    assert_one_decimal(data["remaining_crew_hours"], "remaining_crew_hours")


def assert_shop_drawing_submittal(data: dict):
    assert_common_fields(data, "ShopDrawingSubmittal")
    assert is_valid_uuid(data["package_id"])
    assert data["submittal_type"] in (
        "SHOP_DRAWING",
        "STRUCTURAL_CALCULATION",
        "COATING_SPEC",
        "MOCKUP_TEST_PLAN",
    )
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["drawing_set_ref"], str) and data["drawing_set_ref"]
    assert isinstance(data["delegated_design_scope"], bool)
    assert data["state"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "APPROVED_AS_NOTED",
        "REVISION_REQUIRED",
        "ESCALATED",
        "VOIDED",
    )
    assert isinstance(data["revision_cycle"], int) and data["revision_cycle"] >= 1
    assert isinstance(data["open_notes_count"], int) and data["open_notes_count"] >= 0


def assert_glass_order(data: dict):
    assert_common_fields(data, "GlassOrder")
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["coating_code"], str) and data["coating_code"]
    assert isinstance(data["quoted_lead_time_days"], int) and data["quoted_lead_time_days"] >= 1
    assert isinstance(data["ordered_lites"], int) and data["ordered_lites"] >= 1
    assert data["state"] in ("ORDERED", "IN_PRODUCTION", "RECEIVED", "CLOSED")
    assert data["expedite_tier"] in (0, 1, 2)
    assert isinstance(data["coating_revision_count"], int)
    assert isinstance(data["re_fire_required"], bool)
    assert data["risk_variant"] in ("NOMINAL", "EXPEDITE_ADJUSTED")
    assert isinstance(data["risk_flag"], bool)
    assert 0.0 <= float(data["risk_score"]) <= 100.0
    assert_two_decimals(data["risk_score"], "risk_score")
    assert isinstance(data["effective_lead_days"], int), (
        "effective_lead_days is a whole number of days"
    )
    assert_glass_lite_ledger(data)


def assert_fabrication_release(data: dict):
    assert_common_fields(data, "FabricationRelease")
    assert is_valid_uuid(data["package_id"])
    assert is_valid_uuid(data["submittal_id"])
    assert is_valid_uuid(data["glass_order_id"])
    assert data["state"] in ("RELEASED", "REVOKED", "CLOSED")
    assert data["revoked_reason"] in (None, "SUBMITTAL_REVISION", "GLASS_RE_FIRE")
    assert data["system_type_at_release"] in ("UNITIZED", "STICK_BUILT")
    assert isinstance(data["lot_count"], int) and data["lot_count"] >= 0
    assert isinstance(data["panels_per_zone"], int) and data["panels_per_zone"] >= 1
    assert isinstance(data["lites_per_panel"], int) and data["lites_per_panel"] >= 1


def assert_panel_lot(data: dict):
    assert_common_fields(data, "PanelLot")
    assert is_valid_uuid(data["release_id"])
    assert is_valid_uuid(data["glass_order_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["fabrication_status"] in ("BATCHED", "GLAZED", "SHIPPED", "ON_HOLD")
    assert data["hold_reason"] in (None, "SUBMITTAL_REVISION", "GLASS_RE_FIRE")
    assert data["status_before_hold"] in (None, "BATCHED", "GLAZED")
    assert isinstance(data["panel_count"], int) and data["panel_count"] >= 1
    assert isinstance(data["lite_count"], int) and data["lite_count"] >= 1
    assert isinstance(data["lot_code"], str) and data["lot_code"]


def assert_lot_code(lot: dict, floor_number: int, elevation_label: str):
    """lot_code joins the literal prefix LOT-F, the floor number, a hyphen
    and the elevation label."""
    expected = f"LOT-F{floor_number}-{elevation_label}"
    assert lot["lot_code"] == expected, (
        f"Expected lot_code {expected}, got {lot['lot_code']}"
    )


def assert_breakage_draw(data: dict):
    assert_common_fields(data, "BreakageDraw")
    assert is_valid_uuid(data["glass_order_id"])
    assert is_valid_uuid(data["panel_lot_id"])
    assert isinstance(data["quantity_lites"], int) and data["quantity_lites"] >= 1
    assert data["reason"] in (
        "FIELD_BREAKAGE",
        "COATING_DEFECT",
        "HANDLING_DAMAGE",
        "MOCKUP_CONSUMPTION",
    )
    assert data["status"] in ("DRAWN", "CANCELLED")


def assert_test_lab(data: dict):
    """A laboratory is an immutable accreditation reference: it carries only
    id and created_at."""
    assert_identity_only_fields(data, "TestLab")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["chamber_capacity"], int) and data["chamber_capacity"] >= 1
    assert isinstance(data["accreditation_ref"], str) and data["accreditation_ref"]


def assert_mockup_test(data: dict):
    assert_common_fields(data, "MockupTest")
    assert is_valid_uuid(data["package_id"])
    assert is_valid_uuid(data["test_lab_id"])
    assert data["state"] in ("SCHEDULED", "PASSED", "FAILED")
    assert isinstance(data["chambers_required"], int) and data["chambers_required"] >= 1
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert isinstance(data["chamber_hours"], int)
    assert_integer_cents(data["invoice_subtotal_cents"], "invoice_subtotal_cents")
    assert_integer_cents(data["surcharge_cents"], "surcharge_cents")
    assert_integer_cents(data["invoice_cents"], "invoice_cents")
    assert data["invoice_cents"] == data["invoice_subtotal_cents"] + data["surcharge_cents"], (
        "invoice_cents is invoice_subtotal_cents plus surcharge_cents"
    )


def assert_anchor_embed_survey(data: dict):
    assert_common_fields(data, "AnchorEmbedSurvey")
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["embed_layout_ref"], str) and data["embed_layout_ref"]
    assert isinstance(data["planned_anchor_count"], int) and data["planned_anchor_count"] >= 1
    assert float(data["tolerance_mm"]) > 0
    assert data["state"] in ("PENDING_SURVEY", "ACCEPTED", "REJECTED", "POURED")
    assert isinstance(data["survey_attempt_count"], int)


def assert_crew_day_log(data: dict):
    assert_common_fields(data, "CrewDayLog")
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert 0 < float(data["shift_hours"]) <= 16
    assert isinstance(data["panels_installed"], int) and data["panels_installed"] >= 0
    assert data["status"] in ("POSTED", "VOIDED")
    assert_integer_cents(data["day_cost_cents"], "day_cost_cents")


def assert_hoist_rig(data: dict):
    assert_common_fields(data, "HoistRig")
    assert is_valid_uuid(data["package_id"])
    assert data["rig_kind"] in ("MAST_CLIMBER", "TOWER_CRANE", "MONORAIL")
    assert (
        isinstance(data["capacity_panels_per_shift"], int)
        and data["capacity_panels_per_shift"] >= 1
    )
    assert int(data["changeover_buffer_minutes"]) >= 0
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_hoist_reservation(data: dict):
    assert_common_fields(data, "HoistReservation")
    assert is_valid_uuid(data["rig_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["status"] in ("RESERVED", "CONSUMED", "CANCELLED")
    assert (
        isinstance(data["planned_panel_count"], int) and data["planned_panel_count"] >= 1
    )


def assert_field_test(data: dict):
    assert_common_fields(data, "FieldTest")
    assert is_valid_uuid(data["zone_id"])
    assert data["test_kind"] in (
        "WATER_AAMA_501_2",
        "AIR_INFILTRATION",
        "STRUCTURAL_DEFLECTION",
    )
    assert data["state"] in ("SCHEDULED", "PASSED", "FAILED")
    assert data["outcome_reason"] in (
        None,
        "WITHIN_TOLERANCE",
        "WATER_PENETRATION",
        "AIR_LEAKAGE_EXCEEDED",
        "DEFLECTION_EXCEEDED",
    )
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1


def assert_defect_item(data: dict):
    assert_common_fields(data, "DefectItem")
    assert is_valid_uuid(data["package_id"])
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert data["status"] in ("OPEN", "REMEDIATION_SUBMITTED", "CLOSED", "WAIVED")
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["raised_by_user_id"], str) and data["raised_by_user_id"]
    assert isinstance(data["reinspect_fail_count"], int)


# ---------------------------------------------------------------------------
# Ledger invariants (PRD §2.10)
# ---------------------------------------------------------------------------
def assert_glass_lite_ledger(order: dict):
    """committable_lites == allocated_lites + breakage_stock_lites + unallocated_lites,
    and breakage_stock_lites == available_stock_lites + drawn_lites."""
    assert (
        order["committable_lites"]
        == order["allocated_lites"] + order["breakage_stock_lites"] + order["unallocated_lites"]
    ), (
        "committable_lites must equal allocated_lites plus breakage_stock_lites plus "
        f"unallocated_lites; got {order['committable_lites']} vs "
        f"{order['allocated_lites']} + {order['breakage_stock_lites']} + "
        f"{order['unallocated_lites']}"
    )
    assert (
        order["breakage_stock_lites"]
        == order["available_stock_lites"] + order["drawn_lites"]
    ), (
        "breakage_stock_lites must equal available_stock_lites plus drawn_lites; got "
        f"{order['breakage_stock_lites']} vs {order['available_stock_lites']} + "
        f"{order['drawn_lites']}"
    )


def assert_crew_hour_ledger(zone: dict):
    """budget_crew_hours == consumed_crew_hours + remaining_crew_hours."""
    assert float(zone["budget_crew_hours"]) == pytest.approx(
        float(zone["consumed_crew_hours"]) + float(zone["remaining_crew_hours"]), abs=0.01
    ), (
        "budget_crew_hours must equal consumed_crew_hours plus remaining_crew_hours; got "
        f"{zone['budget_crew_hours']} vs {zone['consumed_crew_hours']} + "
        f"{zone['remaining_crew_hours']}"
    )


def assert_earned_value_consistency(read: dict):
    """retention is five percent of the rounded subtotal, and earned value is the
    subtotal less that retention."""
    subtotal = read["certified_subtotal_cents"]
    expected_retention = int((subtotal * RETENTION_RATE) + 0.5)
    assert read["retention_held_cents"] == expected_retention, (
        f"Expected retention_held_cents {expected_retention} from subtotal {subtotal}, "
        f"got {read['retention_held_cents']}"
    )
    assert read["earned_value_certified_cents"] == subtotal - read["retention_held_cents"], (
        "earned_value_certified_cents must be the certified subtotal less retention"
    )


def assert_day_cost_sum_equals_final(zone: dict, posted_logs: list):
    """The zone total must equal the sum of the surviving logs' persisted
    day_cost_cents values exactly."""
    expected = sum(log["day_cost_cents"] for log in posted_logs)
    assert zone["final_labor_cost_cents"] == expected, (
        f"Expected final_labor_cost_cents {expected} as the sum of the posted days' "
        f"day_cost_cents, got {zone['final_labor_cost_cents']}"
    )


def assert_day_indices_packed(posted_logs: list):
    """The surviving POSTED logs are indexed from 1 with no gap."""
    indices = sorted(log["day_index"] for log in posted_logs)
    assert indices == list(range(1, len(posted_logs) + 1)), (
        f"Expected day_index sequence {list(range(1, len(posted_logs) + 1))}, got {indices}"
    )


def assert_envelope_meta(response_json: dict):
    """meta carries a server-generated api_request_id starting with req_."""
    meta = response_json["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
