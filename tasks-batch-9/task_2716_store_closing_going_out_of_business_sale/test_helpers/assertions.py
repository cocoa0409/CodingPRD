"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvertisingClaimCode,
    BonusStatus,
    CompliancePosture,
    ConsignmentStatus,
    DayStatus,
    DispositionStatus,
    EconomicsModel,
    EmploymentStatus,
    EngagementStatus,
    ExpenseCategory,
    ExpenseResponsibility,
    ExpenseStatus,
    LicenseStatus,
    LotSource,
    LotStatus,
    MerchandiseCategory,
    MerchandiseCategory as _Category,
    SettlementBasis,
    SettlementStatus,
    StageClosedReason,
    StageStatus,
    StoreStatus,
    SuspensionReason,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------
# Shared field assertions
# --------------------------------------------------------------------------

def assert_common_fields(data: dict, entity_label: str = "entity"):
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label} id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label} created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label} updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label} version must be a positive integer, got {data.get('version')!r}"


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant so sub-second width does not matter."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    if not text.endswith("Z"):
        text = text + "Z"
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = frac.rstrip("0")
        body = head if not frac else head + "." + frac
    return body + "Z"


def assert_instant_equals(actual, expected, label="instant"):
    """Compare two UTC instants ignoring fractional-second serialisation width."""
    assert canonical_instant(actual) == canonical_instant(expected), \
        f"{label}: expected {expected}, got {actual}"


def assert_ratio_precision(value, label="ratio"):
    """Ratios are carried to four decimal places."""
    assert value is not None, f"{label} must be present"
    scaled = round(float(value) * 10000)
    assert abs(float(value) * 10000 - scaled) < 1e-6, \
        f"{label} must carry at most four decimal places, got {value}"


def assert_cents(value, label="amount"):
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"{label} must be an integer number of cents, got {value!r}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_jurisdiction(data: dict):
    assert_common_fields(data, "jurisdiction")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["gob_license_required"], bool)
    assert isinstance(data["max_sale_days"], int)
    assert isinstance(data["license_cooling_off_days"], int)
    assert isinstance(data["max_augmentation_ratio"], (int, float))
    assert isinstance(data["augmentation_disclosure_required"], bool)
    assert isinstance(data["augmentation_prohibited"], bool)
    assert isinstance(data["prohibited_claim_codes"], list)
    for code in data["prohibited_claim_codes"]:
        assert code in _values(AdvertisingClaimCode), f"unknown claim code {code}"
    assert isinstance(data["advertising_disclosure_required"], bool)
    assert isinstance(data["surrender_notice_days"], int)


def assert_engagement(data: dict):
    assert_common_fields(data, "engagement")
    assert isinstance(data["retailer_name"], str) and data["retailer_name"]
    assert isinstance(data["liquidator_name"], str) and data["liquidator_name"]
    assert data["economics_model"] in _values(EconomicsModel)
    assert data["expense_responsibility"] in _values(ExpenseResponsibility)
    assert data["engagement_status"] in _values(EngagementStatus)
    assert data["compliance_posture"] in _values(CompliancePosture)
    assert isinstance(data["compliance_strike_count"], int)
    assert data["compliance_strike_count"] >= 0
    assert 0 <= float(data["guaranty_pct"]) <= 1.5, \
        f"guaranty_pct must sit between 0 and 1.5, got {data['guaranty_pct']}"
    for field in (
        "original_cost_value_cents", "guaranty_amount_cents",
        "projected_gross_recovery_cents", "projected_shortfall_cents",
        "original_net_sales_cents", "augmentation_net_sales_cents",
        "gross_recovery_cents", "expense_total_cents",
        "expense_liquidator_share_cents", "expense_retailer_share_cents",
        "retention_accrual_cents",
    ):
        assert_cents(data[field], f"engagement.{field}")
    assert data["projected_shortfall_cents"] >= 0, \
        "projected_shortfall_cents is floored at zero"
    assert_engagement_expense_identity(data)


def assert_engagement_expense_identity(data: dict):
    """expense_total_cents equals the two share aggregates added together."""
    assert data["expense_total_cents"] == (
        data["expense_liquidator_share_cents"] + data["expense_retailer_share_cents"]
    ), (
        "expense_total_cents must equal liquidator plus retailer share, got "
        f"{data['expense_total_cents']} vs "
        f"{data['expense_liquidator_share_cents']} + "
        f"{data['expense_retailer_share_cents']}"
    )


def assert_store(data: dict):
    assert_common_fields(data, "store")
    assert is_valid_uuid(data["engagement_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["address_line"], str)
    assert data["store_status"] in _values(StoreStatus)
    assert data["suspension_reason"] in _values(SuspensionReason)
    for field in (
        "original_cost_value_cents", "augmentation_cost_value_cents",
        "projected_gross_recovery_cents", "realized_gross_recovery_cents",
    ):
        assert_cents(data[field], f"store.{field}")
    for field in ("units_initial_total", "units_sold_total",
                  "augmentation_units_accounted"):
        assert isinstance(data[field], int) and data[field] >= 0
    for field in ("realized_sell_through_pct", "planned_avg_discount_pct",
                  "projected_recovery_ratio", "realized_recovery_ratio"):
        assert_ratio_precision(data[field], f"store.{field}")


def assert_inventory_lot(data: dict):
    assert_common_fields(data, "inventory lot")
    assert is_valid_uuid(data["store_id"])
    assert data["category"] in _values(MerchandiseCategory)
    assert data["source"] in _values(LotSource)
    assert data["lot_status"] in _values(LotStatus)
    for field in ("units_initial", "units_on_hand", "units_sold", "units_returned"):
        assert isinstance(data[field], int) and data[field] >= 0
    for field in ("unit_cost_cents", "unit_retail_cents", "cost_value_cents",
                  "retail_value_cents", "projected_recovery_cents"):
        assert_cents(data[field], f"inventory_lot.{field}")
    # PRD 3.2: "Its `cost_value_cents` and `retail_value_cents` are the initial
    # units less any returned units, multiplied by `unit_cost_cents` and
    # `unit_retail_cents` respectively."
    net_units = data["units_initial"] - data["units_returned"]
    assert data["cost_value_cents"] == net_units * data["unit_cost_cents"], \
        "cost_value_cents is units_initial less units_returned times unit_cost_cents"
    assert data["retail_value_cents"] == net_units * data["unit_retail_cents"], \
        "retail_value_cents is units_initial less units_returned times unit_retail_cents"


def assert_augmentation_consignment(data: dict):
    assert_common_fields(data, "consignment")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["category"] in _values(MerchandiseCategory)
    assert data["consignment_status"] in _values(ConsignmentStatus)
    assert isinstance(data["units_supplied"], int) and data["units_supplied"] >= 1
    assert isinstance(data["units_returned"], int) and data["units_returned"] >= 0
    for field in ("unit_cost_cents", "unit_retail_cents", "cost_value_cents"):
        assert_cents(data[field], f"consignment.{field}")
    assert data["cost_value_cents"] == data["units_supplied"] * data["unit_cost_cents"], \
        "cost_value_cents is units_supplied times unit_cost_cents"
    assert data["delivery_window_start_date"] <= data["delivery_window_end_date"]


def assert_markdown_stage(data: dict):
    assert_common_fields(data, "markdown stage")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["stage_index"], int) and data["stage_index"] >= 1
    assert data["stage_status"] in _values(StageStatus)
    if data.get("closed_reason") is not None:
        assert data["closed_reason"] in _values(StageClosedReason)
    assert_ratio_precision(data["discount_pct"], "markdown_stage.discount_pct")
    assert 0 <= float(data["discount_pct"]) <= 0.9000, \
        f"discount_pct may not exceed 0.9000, got {data['discount_pct']}"
    assert_ratio_precision(data["sell_through_target_pct"],
                           "markdown_stage.sell_through_target_pct")
    assert_ratio_precision(data["escalation_applied_pct"],
                           "markdown_stage.escalation_applied_pct")
    assert 0 <= float(data["escalation_applied_pct"]) <= 0.20, \
        "escalation_applied_pct is capped at 0.20"
    assert data["window_start_date"] <= data["window_end_date"]


def assert_gob_license(data: dict):
    assert_common_fields(data, "licence")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_status"] in _values(LicenseStatus)
    assert isinstance(data["requested_days"], int) and data["requested_days"] >= 1
    assert isinstance(data["advertising_claim_codes"], list)
    for code in data["advertising_claim_codes"]:
        assert code in _values(AdvertisingClaimCode), f"unknown claim code {code}"
    assert data["period_start_date"] <= data["period_end_date"]


def assert_employee(data: dict):
    assert_common_fields(data, "employee")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert data["employment_status"] in _values(EmploymentStatus)
    assert data["bonus_status"] in _values(BonusStatus)
    assert_cents(data["retention_bonus_cents"], "employee.retention_bonus_cents")
    assert data["retention_bonus_cents"] >= 0
    assert_cents(data["earned_bonus_cents"], "employee.earned_bonus_cents")
    assert data["earned_bonus_cents"] >= 0
    assert isinstance(data["served_days"], int) and data["served_days"] >= 0
    assert 0 <= float(data["attendance_rate"]) <= 1, \
        f"attendance_rate must sit between 0 and 1, got {data['attendance_rate']}"
    assert data["retention_start_date"] <= data["retention_target_date"]


def assert_sales_day(data: dict):
    assert_common_fields(data, "selling day")
    assert is_valid_uuid(data["store_id"])
    assert data["day_status"] in _values(DayStatus)
    for field in ("original_net_sales_cents", "augmentation_net_sales_cents",
                  "net_sales_cents"):
        assert_cents(data[field], f"sales_day.{field}")
    assert data["net_sales_cents"] == (
        data["original_net_sales_cents"] + data["augmentation_net_sales_cents"]
    ), "net_sales_cents is the two sales figures added together"
    for field in ("original_units_sold", "augmentation_units_sold"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_expense_item(data: dict):
    assert_common_fields(data, "expense item")
    assert is_valid_uuid(data["engagement_id"])
    assert data["expense_category"] in _values(ExpenseCategory)
    assert data["expense_status"] in _values(ExpenseStatus)
    assert isinstance(data["auto_generated"], bool)
    for field in ("amount_cents", "liquidator_share_cents", "retailer_share_cents"):
        assert_cents(data[field], f"expense_item.{field}")
    assert data["amount_cents"] >= 1


def assert_expense_shares_conserved(data: dict):
    """The retailer's share is the exact arithmetic remainder of the amount."""
    assert data["liquidator_share_cents"] + data["retailer_share_cents"] == \
        data["amount_cents"], (
            "liquidator plus retailer share must equal amount_cents, got "
            f"{data['liquidator_share_cents']} + {data['retailer_share_cents']} "
            f"!= {data['amount_cents']}"
        )


def assert_lease_disposition(data: dict):
    assert_common_fields(data, "lease disposition")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["landlord_name"], str) and data["landlord_name"]
    assert data["disposition_status"] in _values(DispositionStatus)
    assert isinstance(data["negotiation_round"], int)
    assert 0 <= data["negotiation_round"] <= 3, \
        f"negotiation_round is bounded by three, got {data['negotiation_round']}"
    for field in ("daily_holdover_rate_cents", "rent_arrears_cents",
                  "cam_arrears_cents", "restoration_cost_cents",
                  "fixture_reserve_price_cents", "surrender_credit_cents"):
        assert_cents(data[field], f"lease_disposition.{field}")
        assert data[field] >= 0, f"lease_disposition.{field} must be at least 0"
    # The PRD opens a disposition "with every negotiated, computed, and
    # allocation field unset"; the waterfall figures are written by the
    # surrender, so they are integers exactly once `surrendered_at` is stamped.
    computed = data["surrendered_at"] is not None
    for field in ("holdover_penalty_cents", "allocated_rent_cents",
                  "allocated_cam_cents", "allocated_restoration_cents",
                  "allocated_holdover_cents", "unpaid_landlord_balance_cents",
                  "residual_to_retailer_cents"):
        if computed:
            assert_cents(data[field], f"lease_disposition.{field}")
            assert data[field] >= 0, f"lease_disposition.{field} must be at least 0"
        else:
            assert data[field] is None, \
                f"lease_disposition.{field} is unset until the surrender runs"
    if computed:
        assert isinstance(data["holdover_days"], int) and data["holdover_days"] >= 0
    else:
        assert data["holdover_days"] is None, \
            "lease_disposition.holdover_days is unset until the surrender runs"


def assert_surrender_waterfall_invariants(data: dict):
    """The two closing invariants of the landlord surrender waterfall."""
    allocations = (
        data["allocated_rent_cents"] + data["allocated_cam_cents"]
        + data["allocated_restoration_cents"] + data["allocated_holdover_cents"]
    )
    available = data["fixture_sale_price_cents"] + data["surrender_credit_cents"]
    claims = (
        data["rent_arrears_cents"] + data["cam_arrears_cents"]
        + data["restoration_cost_cents"] + data["holdover_penalty_cents"]
    )
    assert allocations + data["residual_to_retailer_cents"] == available, (
        "the four allocations plus the residual must equal the available funds, got "
        f"{allocations} + {data['residual_to_retailer_cents']} != {available}"
    )
    assert allocations + data["unpaid_landlord_balance_cents"] == claims, (
        "the four allocations plus the unpaid balance must equal the total claim, got "
        f"{allocations} + {data['unpaid_landlord_balance_cents']} != {claims}"
    )
    assert (
        data["unpaid_landlord_balance_cents"] == 0
        or data["residual_to_retailer_cents"] == 0
    ), "at most one of the unpaid balance and the residual may be non-zero"


def assert_settlement(data: dict):
    assert_common_fields(data, "settlement")
    assert is_valid_uuid(data["engagement_id"])
    assert data["settlement_basis"] in _values(SettlementBasis)
    assert data["settlement_status"] in _values(SettlementStatus)
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0
    # The PRD opens a worksheet "at `settlement_status` of `DRAFT` with every
    # split figure unset", and a proposal is what "stamps `computed_at` ... and
    # writes every computed money field", so the split is integral exactly once
    # `computed_at` is stamped.
    computed = data["computed_at"] is not None
    for field in ("gross_recovery_cents", "original_net_sales_cents",
                  "liquidator_fee_cents", "guaranty_amount_cents",
                  "expense_total_cents", "liquidator_expense_cents",
                  "retailer_expense_cents", "retailer_proceeds_cents",
                  "liquidator_proceeds_cents", "retention_accrual_cents"):
        if computed:
            assert_cents(data[field], f"settlement.{field}")
        else:
            assert data[field] is None, \
                f"settlement.{field} is unset until the worksheet is proposed"
    if computed:
        assert_ratio_precision(data["recovery_ratio"], "settlement.recovery_ratio")
        assert data["fee_rate"] in (0.0, 0.0200, 0.0350, 0.0500), \
            f"fee_rate must come from the three-band tier table, got {data['fee_rate']}"
    else:
        assert data["recovery_ratio"] is None, \
            "settlement.recovery_ratio is unset until the worksheet is proposed"
        assert data["fee_rate"] is None, \
            "settlement.fee_rate is unset until the worksheet is proposed"


def assert_settlement_closing_identity(data: dict):
    """Retailer proceeds plus liquidator proceeds plus expense total equal gross."""
    assert (
        data["retailer_proceeds_cents"] + data["liquidator_proceeds_cents"]
        + data["expense_total_cents"]
    ) == data["gross_recovery_cents"], (
        "the closing identity must hold exactly: "
        f"{data['retailer_proceeds_cents']} + {data['liquidator_proceeds_cents']} + "
        f"{data['expense_total_cents']} != {data['gross_recovery_cents']}"
    )
    assert data["liquidator_expense_cents"] + data["retailer_expense_cents"] == \
        data["expense_total_cents"], (
            "the retailer expense figure is the arithmetic remainder of the total"
        )


RECOVERY_SUMMARY_FIELDS = (
    "projected_gross_recovery_cents",
    "projected_recovery_ratio",
    "realized_gross_recovery_cents",
    "realized_recovery_ratio",
    "planned_avg_discount_pct",
    "projected_shortfall_cents",
    "guaranty_amount_cents",
    "original_cost_value_cents",
    "store_count",
)


def assert_recovery_summary(data: dict):
    """The recovery summary reports the nine figures the PRD names for it."""
    for field in RECOVERY_SUMMARY_FIELDS:
        assert field in data, f"recovery summary must report {field}"
    for field in ("projected_gross_recovery_cents", "realized_gross_recovery_cents",
                  "projected_shortfall_cents", "guaranty_amount_cents",
                  "original_cost_value_cents"):
        assert_cents(data[field], f"recovery_summary.{field}")
    for field in ("projected_recovery_ratio", "realized_recovery_ratio",
                  "planned_avg_discount_pct"):
        assert_ratio_precision(data[field], f"recovery_summary.{field}")
    assert isinstance(data["store_count"], int) and data["store_count"] >= 0
    assert data["projected_shortfall_cents"] >= 0, \
        "projected_shortfall_cents is floored at zero"


def assert_compliance_sweep_tally(data: dict):
    """The sweep answers with a tally rather than a resource."""
    for field in ("expired_license_count", "closed_stage_count",
                  "suspended_store_count", "compliance_strike_count"):
        assert field in data, f"sweep tally must report {field}"
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["compliance_posture"] in _values(CompliancePosture)
