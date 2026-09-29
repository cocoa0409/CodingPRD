"""Entity assertions and domain invariant checkers for the aftermarket API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationStatus, ApplicabilityStatus, ApprovalStatus, CampaignStatus,
    CriticalityClass, DealerStatus, DealerTier, Disposition, DowntimePriority,
    ForecastMethod, ForecastStatus, FulfillmentMode, InstalledUnitStatus,
    LedgerEntryType, LineStatus, LogisticsStatus, LtbMethod, OrderType,
    PartLifecycleState, Region, ReplenishmentStatus, ReturnReason, ReturnStatus,
    RuleStatus, SourceRefType, StockingPolicy, WorkOrderStatus, WorkType,
)


def _members(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at + updated_at + version (PRD section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer starting at 1"


def assert_part(data: dict) -> None:
    assert_common_fields(data, "Part")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["description"], str)
    assert data["lifecycle_state"] in _members(PartLifecycleState)
    assert data["criticality_class"] in _members(CriticalityClass)
    assert data["stocking_policy"] in _members(StockingPolicy)
    assert data["replenishment_status"] in _members(ReplenishmentStatus)
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 1
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert float(data["weight_kg"]) > 0
    assert isinstance(data["hazmat"], bool)
    assert isinstance(data["max_stock_units"], int) and data["max_stock_units"] >= 0
    for counter in ("on_hand_units", "allocated_units", "quarantine_units",
                    "in_transit_units", "safety_stock_units", "reorder_point_units",
                    "available_units"):
        assert isinstance(data[counter], int), f"Part.{counter} must be an integer"
    assert isinstance(data["current_list_unit_price_cents"], int)
    if data["lifecycle_state"] != PartLifecycleState.SUPERSEDED.value:
        assert data.get("superseded_by_part_id") is None, \
            "superseded_by_part_id is non-null only while the part is SUPERSEDED"
    assert_part_stock_invariants(data)


def assert_part_stock_invariants(data: dict) -> None:
    """available_units is always on_hand_units minus allocated_units
    (PRD section 2.8)."""
    assert data["available_units"] == data["on_hand_units"] - data["allocated_units"], (
        f"available_units {data['available_units']} must equal on_hand_units "
        f"{data['on_hand_units']} - allocated_units {data['allocated_units']}"
    )


def assert_equipment_model(data: dict) -> None:
    assert_common_fields(data, "EquipmentModel")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["production_end_date"])
    assert is_iso8601_timestamp(data["support_end_date"])


def assert_installed_unit(data: dict) -> None:
    assert_common_fields(data, "InstalledUnit")
    assert is_valid_uuid(data["model_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["build_revision"], int) and data["build_revision"] >= 0
    assert is_iso8601_timestamp(data["commission_date"])
    assert data["region"] in _members(Region)
    assert data["status"] in _members(InstalledUnitStatus)


def assert_part_applicability(data: dict) -> None:
    assert_common_fields(data, "PartApplicability")
    assert is_valid_uuid(data["part_id"])
    assert is_valid_uuid(data["model_id"])
    assert isinstance(data["effective_from_build_revision"], int)
    assert data["effective_from_build_revision"] >= 0
    upper = data.get("effective_to_build_revision")
    assert upper is None or isinstance(upper, int)
    assert isinstance(data["qty_per_unit"], int) and data["qty_per_unit"] >= 1
    assert data["applicability_status"] in _members(ApplicabilityStatus)


def assert_dealer(data: dict) -> None:
    assert_common_fields(data, "Dealer")
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert data["tier"] in _members(DealerTier)
    assert data["region"] in _members(Region)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["lifetime_restocking_fee_cents"], int)
    assert isinstance(data["lifetime_rebate_cents"], int)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in _members(DealerStatus)
    assert_dealer_credit_hold_invariant(data)


def assert_dealer_credit_hold_invariant(data: dict) -> None:
    """credit_hold is true exactly when outstanding_balance_cents is strictly
    greater than credit_limit_cents (PRD section 3.1)."""
    expected = data["outstanding_balance_cents"] > data["credit_limit_cents"]
    assert data["credit_hold"] is expected, (
        f"credit_hold {data['credit_hold']} does not match "
        f"outstanding_balance_cents {data['outstanding_balance_cents']} > "
        f"credit_limit_cents {data['credit_limit_cents']}"
    )


def assert_work_order(data: dict) -> None:
    assert_common_fields(data, "ServiceWorkOrder")
    assert is_valid_uuid(data["installed_unit_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert data["work_type"] in _members(WorkType)
    assert data["downtime_priority"] in _members(DowntimePriority)
    assert data["status"] in _members(WorkOrderStatus)
    assert is_iso8601_timestamp(data["opened_at"])
    closed = data.get("closed_at")
    assert closed is None or is_iso8601_timestamp(closed)


def assert_part_line(data: dict) -> None:
    assert_common_fields(data, "WorkOrderPartLine")
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["part_id"])
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] >= 1
    assert isinstance(data["qty_consumed"], int) and data["qty_consumed"] >= 0
    assert data["line_status"] in _members(LineStatus)
    assert data["fulfillment_mode"] in _members(FulfillmentMode)
    for money in ("decision_net_benefit_cents", "freight_cost_cents",
                  "list_unit_price_cents", "list_line_total_cents",
                  "quoted_line_total_cents", "variant_delta_cents",
                  "charged_amount_cents"):
        assert isinstance(data[money], int), f"WorkOrderPartLine.{money} must be cents"
    consumed_at = data.get("consumed_at")
    assert consumed_at is None or is_iso8601_timestamp(consumed_at)
    assert_line_variant_invariants(data)


def assert_line_variant_invariants(data: dict) -> None:
    """LIST multiplies the already-rounded unit price by the quantity, and
    variant_delta_cents is list_line_total_cents minus quoted_line_total_cents
    (PRD section 3.5)."""
    assert data["list_line_total_cents"] == \
        data["list_unit_price_cents"] * data["qty_requested"], (
            "list_line_total_cents must be list_unit_price_cents * qty_requested")
    assert data["variant_delta_cents"] == \
        data["list_line_total_cents"] - data["quoted_line_total_cents"], (
            "variant_delta_cents must be list_line_total_cents - "
            "quoted_line_total_cents")


def assert_forecast(data: dict) -> None:
    assert_common_fields(data, "DemandForecast")
    assert is_valid_uuid(data["part_id"])
    assert data["horizon_months"] in (12, 24, 60)
    assert isinstance(data["lookback_days"], int) and data["lookback_days"] >= 1
    assert data["method"] in _members(ForecastMethod)
    assert isinstance(data["wo_history_units"], int)
    assert isinstance(data["installed_base_units"], int)
    assert isinstance(data["forecast_units"], int)
    assert data["forecast_status"] in _members(ForecastStatus)
    assert is_iso8601_timestamp(data["computed_at"])


def assert_campaign(data: dict) -> None:
    assert_common_fields(data, "LastTimeBuyCampaign")
    assert is_valid_uuid(data["part_id"])
    assert data["method"] in _members(LtbMethod)
    assert 1 <= data["coverage_years"] <= 15
    assert is_iso8601_timestamp(data["ltb_window_start"])
    assert is_iso8601_timestamp(data["ltb_window_end"])
    assert isinstance(data["annual_demand_units"], int)
    assert isinstance(data["proposed_qty"], int) and data["proposed_qty"] >= 0
    assert isinstance(data["approved_qty"], int)
    assert isinstance(data["remaining_qty"], int)
    assert data["status"] in _members(CampaignStatus)
    assert isinstance(data["revision_index"], int) and data["revision_index"] >= 0


def assert_allocation_request(data: dict) -> None:
    assert_common_fields(data, "AllocationRequest")
    assert is_valid_uuid(data["campaign_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert isinstance(data["granted_units"], int) and data["granted_units"] >= 0
    assert isinstance(data["priority_score"], int) and data["priority_score"] >= 0
    assert isinstance(data["dealer_installed_units"], int)
    assert data["status"] in _members(AllocationStatus)


def assert_campaign_entitlement_conserved(campaign: dict, requests: list) -> None:
    """approved_qty equals remaining_qty plus the sum of granted_units across
    every request now in GRANTED or PARTIALLY_GRANTED (PRD section 3.8)."""
    awarded = sum(
        r["granted_units"] for r in requests
        if r["status"] in (AllocationStatus.GRANTED.value,
                           AllocationStatus.PARTIALLY_GRANTED.value)
    )
    assert campaign["approved_qty"] == campaign["remaining_qty"] + awarded, (
        f"approved_qty {campaign['approved_qty']} must equal remaining_qty "
        f"{campaign['remaining_qty']} + granted total {awarded}"
    )


def assert_replenishment_order(data: dict) -> None:
    assert_common_fields(data, "ReplenishmentOrder")
    assert is_valid_uuid(data["part_id"])
    assert data["order_type"] in _members(OrderType)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["freight_cost_cents"], int)
    assert isinstance(data["total_landed_cost_cents"], int)
    assert data["approval_status"] in _members(ApprovalStatus)
    assert data["logistics_status"] in _members(LogisticsStatus)
    assert isinstance(data["auto_generated"], bool)
    assert data["total_landed_cost_cents"] == \
        data["unit_cost_cents"] * data["qty"] + data["freight_cost_cents"], (
            "total_landed_cost_cents must be unit_cost_cents * qty + "
            "freight_cost_cents")


def assert_return_authorization(data: dict) -> None:
    assert_common_fields(data, "ReturnAuthorization")
    assert is_valid_uuid(data["work_order_part_line_id"])
    assert is_valid_uuid(data["part_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["qty_returned"], int) and data["qty_returned"] >= 1
    assert data["return_reason"] in _members(ReturnReason)
    assert isinstance(data["age_days"], int) and data["age_days"] >= 0
    for money in ("gross_credit_cents", "restocking_fee_cents",
                  "net_before_rebate_cents", "loyalty_rebate_cents",
                  "final_credit_cents", "credit_posted_cents"):
        assert isinstance(data[money], int), f"ReturnAuthorization.{money} must be cents"
    assert data["status"] in _members(ReturnStatus)
    disposition = data.get("disposition")
    assert disposition is None or disposition in _members(Disposition)
    assert_return_credit_chain(data)


def assert_return_credit_chain(data: dict) -> None:
    """The five pinned steps must reconcile with each other (PRD section 3.9)."""
    assert data["net_before_rebate_cents"] == max(
        0, data["gross_credit_cents"] - data["restocking_fee_cents"]), (
            "net_before_rebate_cents must be gross_credit_cents less "
            "restocking_fee_cents, floored at 0")
    assert data["final_credit_cents"] == \
        data["net_before_rebate_cents"] + data["loyalty_rebate_cents"], (
            "final_credit_cents must be net_before_rebate_cents plus "
            "loyalty_rebate_cents")


def assert_price_rule(data: dict) -> None:
    assert_common_fields(data, "AftermarketPriceRule")
    assert data["criticality_class"] in _members(CriticalityClass)
    assert float(data["base_uplift_pct"]) >= 0
    assert float(data["max_uplift_pct"]) >= float(data["base_uplift_pct"])
    assert 0 <= float(data["min_margin_pct"]) < 1
    assert data["rule_status"] in _members(RuleStatus)


def assert_ledger_entry(data: dict) -> None:
    """A stock ledger entry carries only id and created_at from the common set
    (PRD section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), "StockLedgerEntry.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "StockLedgerEntry.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "StockLedgerEntry must have no updated_at field"
    assert "version" not in data, "StockLedgerEntry must have no version field"
    assert is_valid_uuid(data["part_id"])
    assert data["entry_type"] in _members(LedgerEntryType)
    assert isinstance(data["delta_units"], int)
    assert isinstance(data["balance_after_units"], int)
    assert data["source_ref_type"] in _members(SourceRefType)
    assert isinstance(data["source_ref_id"], str) and data["source_ref_id"]
    assert is_iso8601_timestamp(data["occurred_at"])
    if data["entry_type"] in (LedgerEntryType.RECEIPT.value,
                              LedgerEntryType.RETURN_RECEIPT.value):
        assert data["delta_units"] > 0, "RECEIPT and RETURN_RECEIPT deltas are positive"
    else:
        assert data["delta_units"] < 0, "ISSUE and SCRAP deltas are negative"


def assert_ledger_balances_stock(entries: list, part: dict) -> None:
    """on_hand_units plus quarantine_units equals the running sum of
    delta_units (PRD section 2.8)."""
    total = sum(e["delta_units"] for e in entries)
    assert total == part["on_hand_units"] + part["quarantine_units"], (
        f"ledger delta sum {total} must equal on_hand_units "
        f"{part['on_hand_units']} + quarantine_units {part['quarantine_units']}"
    )
