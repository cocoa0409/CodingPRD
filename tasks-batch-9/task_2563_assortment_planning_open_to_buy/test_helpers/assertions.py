"""Entity assertions and the domain invariants the PRD declares normative."""
from fractions import Fraction

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActiveBasis,
    AssortmentItemStatus,
    CategoryPlanStatus,
    CommitStatus,
    DecisionStatus,
    FulfillmentStatus,
    OptionPlanStatus,
    OtbPosture,
    OverlayStatus,
    PlanMonthStatus,
    ReforecastCycleStatus,
    VarianceStatus,
    VendorAuthorizationStatus,
    VendorStatus,
)


def round_half_up(value) -> int:
    """Round half up away from zero, the PRD's rounding convention."""
    frac = Fraction(value)
    if frac >= 0:
        return int((frac.numerator * 2 + frac.denominator) // (frac.denominator * 2))
    return -int(((-frac).numerator * 2 + frac.denominator) // (frac.denominator * 2))


def retail_to_cost_cents(retail_cents: int, planned_margin_bps: int) -> int:
    """Retail dollars converted to cost by retaining the complement of margin."""
    return round_half_up(Fraction(retail_cents * (10000 - planned_margin_bps), 10000))


def _assert_governed_row(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC with three fractional digits"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def _assert_append_only_row(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_department(data: dict):
    _assert_governed_row(data, "Department")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert 2000 <= data["fiscal_year"] <= 2100
    assert data["sales_target_cents"] >= 1
    assert 0 <= data["margin_target_bps"] <= 9999
    assert data["turn_target_x100"] >= 1


def assert_category(data: dict):
    _assert_governed_row(data, "Category")
    assert is_valid_uuid(data["department_id"])
    assert data["role"] in [
        "TRAFFIC_DRIVER", "DESTINATION", "CONVENIENCE", "SEASONAL", "OCCASIONAL",
    ]
    assert 1 <= data["sales_share_bps"] <= 10000


def assert_store_cluster(data: dict):
    _assert_governed_row(data, "StoreCluster")
    assert data["climate_zone"] in ["COLD", "TEMPERATE", "HOT"]
    assert data["volume_tier"] in ["A", "B", "C"]
    assert data["store_count"] >= 1
    assert 3000 <= data["sales_index_bps"] <= 25000
    assert 5000 <= data["demographic_index_bps"] <= 20000


def assert_vendor(data: dict):
    _assert_governed_row(data, "Vendor")
    assert data["status"] in [s.value for s in VendorStatus]
    assert 1 <= data["lead_time_days"] <= 365
    assert data["weekly_unit_capacity"] >= 1
    assert data["min_order_units"] >= 1
    assert 0 <= data["cancel_cutoff_days"] <= 180


def assert_vendor_authorization(data: dict):
    _assert_governed_row(data, "VendorAuthorization")
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["category_id"])
    assert data["max_open_units"] >= 1
    assert data["status"] in [s.value for s in VendorAuthorizationStatus]


def assert_category_plan(data: dict):
    _assert_governed_row(data, "CategoryPlan")
    assert is_valid_uuid(data["category_id"])
    assert data["season_code"] in ["SPRING", "SUMMER", "FALL", "HOLIDAY"]
    assert data["status"] in [s.value for s in CategoryPlanStatus]
    assert 0 <= data["reforecast_round"] <= 3
    assert data["otb_posture"] in [p.value for p in OtbPosture]
    assert data["variance_status"] in [v.value for v in VarianceStatus]
    assert isinstance(data["sales_variance_bps"], int)
    assert isinstance(data["open_ratio_bps"], int)


def assert_plan_month(data: dict):
    _assert_governed_row(data, "PlanMonth")
    assert is_valid_uuid(data["category_plan_id"])
    assert 1 <= data["month_index"] <= 12
    assert len(data["fiscal_month_label"]) == 7
    assert data["status"] in [s.value for s in PlanMonthStatus]
    assert data["active_basis"] in [b.value for b in ActiveBasis]
    for field in (
        "provisional_sell_through_bps", "reserve_rate_bps", "markdown_reserve_cents",
        "otb_planned_cents", "otb_committed_cents", "otb_received_cents",
        "otb_open_cents",
    ):
        assert isinstance(data[field], int), f"PlanMonth.{field} must be an integer of cents/bps"
    assert_otb_conservation(data)


def assert_otb_conservation(month: dict):
    """A month's open + committed + received open-to-buy equals its planned."""
    total = (
        month["otb_open_cents"] + month["otb_committed_cents"] + month["otb_received_cents"]
    )
    assert total == month["otb_planned_cents"], (
        "Conservation identity broken: otb_open_cents "
        f"{month['otb_open_cents']} + otb_committed_cents {month['otb_committed_cents']} "
        f"+ otb_received_cents {month['otb_received_cents']} != otb_planned_cents "
        f"{month['otb_planned_cents']}"
    )


def assert_option_plan(data: dict):
    _assert_governed_row(data, "OptionPlan")
    assert data["tier"] in ["GOOD", "BETTER", "BEST"]
    assert data["status"] in [s.value for s in OptionPlanStatus]
    assert 1 <= data["breadth_target"] <= 200
    assert 1 <= data["depth_units_per_option"] <= 500
    assert data["assumed_unit_cost_cents"] >= 1
    assert isinstance(data["option_slots_assigned"], int)


def assert_slot_conservation(option_plan: dict):
    """option_slots_open equals option_slots_total less option_slots_assigned."""
    assert option_plan["option_slots_open"] == (
        option_plan["option_slots_total"] - option_plan["option_slots_assigned"]
    ), (
        f"Slot counters not conserved: total {option_plan['option_slots_total']}, "
        f"assigned {option_plan['option_slots_assigned']}, "
        f"open {option_plan['option_slots_open']}"
    )


def assert_size_curve_cell(data: dict):
    _assert_append_only_row(data, "SizeCurveCell")
    assert 1 <= len(data["size_label"]) <= 12
    assert 1 <= data["size_sort_order"] <= 99
    assert 1 <= data["pct_bps"] <= 10000


def assert_assortment_item(data: dict):
    _assert_governed_row(data, "AssortmentItem")
    assert is_valid_uuid(data["option_plan_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert 3 <= len(data["sku_code"]) <= 24
    assert 2 <= len(data["color_code"]) <= 8
    assert data["lifecycle_stage"] in ["NEW", "CARRYOVER", "CORE", "EXIT"]
    assert data["unit_cost_cents"] >= 1
    assert data["retail_price_cents"] >= 1
    assert data["status"] in [s.value for s in AssortmentItemStatus]
    assert data["effective_overlay_multiplier_bps"] >= 5000
    assert data["effective_overlay_multiplier_bps"] <= 15000


def assert_receipt_commitment(data: dict):
    _assert_governed_row(data, "ReceiptCommitment")
    assert is_valid_uuid(data["plan_month_id"])
    assert is_valid_uuid(data["assortment_item_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert data["units"] >= 1
    assert data["unit_cost_cents"] >= 1
    assert data["origin"] in ["BUYER", "CHASE_DECISION"]
    assert data["commit_status"] in [s.value for s in CommitStatus]
    assert data["fulfillment_status"] in [s.value for s in FulfillmentStatus]
    assert data["cost_cents"] == data["units"] * data["unit_cost_cents"]


def assert_commitment_money(data: dict):
    """open_cost_cents and received_cost_cents follow from the unit counters."""
    open_units = data["units"] - data["received_units"] - data["cancelled_units"]
    assert data["received_cost_cents"] == data["received_units"] * data["unit_cost_cents"], (
        "received_cost_cents must be received_units * unit_cost_cents"
    )
    if data["commit_status"] in ("PROPOSED", "COMMITTED"):
        assert data["open_cost_cents"] == open_units * data["unit_cost_cents"], (
            "open_cost_cents must be (units - received_units - cancelled_units) "
            "* unit_cost_cents"
        )


def assert_actuals_post(data: dict):
    _assert_append_only_row(data, "ActualsPost")
    assert 1 <= data["week_index"] <= 4
    assert data["actual_sales_cents"] >= 0
    assert data["actual_receipts_cents"] >= 0
    assert data["actual_units_received"] >= 0


def assert_reforecast_cycle(data: dict):
    _assert_governed_row(data, "ReforecastCycle")
    assert is_valid_uuid(data["category_plan_id"])
    assert 1 <= data["round_index"] <= 3
    assert data["trigger_reason"] in ["VARIANCE_BREACH", "DIRECTOR_REQUEST"]
    assert data["status"] in [s.value for s in ReforecastCycleStatus]


def assert_chase_cancel_decision(data: dict):
    _assert_governed_row(data, "ChaseCancelDecision")
    assert is_valid_uuid(data["reforecast_cycle_id"])
    assert is_valid_uuid(data["assortment_item_id"])
    assert data["action"] in ["CHASE", "CANCEL", "HOLD"]
    assert data["requested_units"] >= 0
    assert 1 <= len(data["rationale"]) <= 400
    assert data["status"] in [s.value for s in DecisionStatus]


def assert_localization_overlay(data: dict):
    _assert_governed_row(data, "LocalizationOverlay")
    assert data["overlay_type"] in ["CLIMATE", "DEMOGRAPHIC", "VOLUME"]
    assert data["status"] in [s.value for s in OverlayStatus]
    assert 5000 <= data["unit_multiplier_bps"] <= 15000
