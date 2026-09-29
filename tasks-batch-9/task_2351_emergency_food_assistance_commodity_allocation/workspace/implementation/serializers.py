"""Explicit per-entity representations (SCAFFOLD §1.1).

Only the declared fields are exposed; internal bookkeeping (_seq and the
scratch keys the calculators use) never reaches the wire.
"""

from datetime import date
from decimal import Decimal

from db import iso


def num(value):
    """Serialise a fixed-place Decimal as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def day(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return value


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if versioned:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def service_area(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "county_code": row["county_code"],
            "poverty_population": row["poverty_population"],
            "urban_rural": row["urban_rural"],
            "eligible_agency_count": row["eligible_agency_count"],
        }
    )
    return out


def agency(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "service_area_id": row["service_area_id"],
            "cold_storage_pallet_capacity": row["cold_storage_pallet_capacity"],
            "prior_period_pounds_distributed": num(row["prior_period_pounds_distributed"]),
            "prior_period_allocated_cases": row["prior_period_allocated_cases"],
            "agreement_status": row["agreement_status"],
            "agreement_start_date": day(row["agreement_start_date"]),
            "agreement_end_date": day(row["agreement_end_date"]),
            "training_status": row["training_status"],
            "last_training_completed_at": iso(row["last_training_completed_at"]),
            "training_expires_at": iso(row["training_expires_at"]),
            "eligibility_posture": row["eligibility_posture"],
            "agency_cases_on_hand": row["agency_cases_on_hand"],
            "delivered_cases_ytd": row["delivered_cases_ytd"],
            "renewal_count": row["renewal_count"],
        }
    )
    return out


def commodity(row):
    # common_fields: false — no updated_at, no version.
    out = _common(row, versioned=False)
    out.update(
        {
            "code": row["code"],
            "name": row["name"],
            "storage_class": row["storage_class"],
            "net_weight_lbs_per_case": num(row["net_weight_lbs_per_case"]),
            "cases_per_pallet": row["cases_per_pallet"],
            "entitlement_value_cents_per_case": row["entitlement_value_cents_per_case"],
            "shelf_life_days": row["shelf_life_days"],
            "excess_case_ceiling": row["excess_case_ceiling"],
        }
    )
    return out


def warehouse(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "dock_count": row["dock_count"],
            "dry_pallet_capacity": row["dry_pallet_capacity"],
            "cold_pallet_capacity": row["cold_pallet_capacity"],
            "frozen_pallet_capacity": row["frozen_pallet_capacity"],
            "monitor_policy": row["monitor_policy"],
        }
    )
    return out


def inventory_lot(row):
    out = _common(row)
    out.update(
        {
            "commodity_id": row["commodity_id"],
            "warehouse_id": row["warehouse_id"],
            "federal_lot_code": row["federal_lot_code"],
            "cases_received": row["cases_received"],
            "cases_on_hand": row["cases_on_hand"],
            "cases_committed": row["cases_committed"],
            "cases_shipped_to_date": row["cases_shipped_to_date"],
            "pack_date": day(row["pack_date"]),
            "best_by_date": day(row["best_by_date"]),
            "entitlement_value_cents": row["entitlement_value_cents"],
            "status": row["status"],
            "monitor_flag": row["monitor_flag"],
            "slow_moving_index": num(row["slow_moving_index"]),
            "last_monitored_at": iso(row["last_monitored_at"]),
            "posted_at": iso(row["posted_at"]),
            "hold_recall_id": row["hold_recall_id"],
        }
    )
    return out


def allocation_cycle(row):
    out = _common(row)
    out.update(
        {
            "cycle_code": row["cycle_code"],
            "formula_variant": row["formula_variant"],
            "allocatable_cases": row["allocatable_cases"],
            "admin_funds_pool_cents": row["admin_funds_pool_cents"],
            "offered_commodity_codes": list(row["offered_commodity_codes"]),
            "order_window_open_at": iso(row["order_window_open_at"]),
            "order_window_close_at": iso(row["order_window_close_at"]),
            "status": row["status"],
            "draw_posture": row["draw_posture"],
            "allocation_locked_at": iso(row["allocation_locked_at"]),
            "total_allocated_cases": row["total_allocated_cases"],
            "eligible_agency_count": row["eligible_agency_count"],
            "admin_funds_allocated_cents": row["admin_funds_allocated_cents"],
        }
    )
    return out


def agency_allocation(row):
    out = _common(row)
    out.update(
        {
            "cycle_id": row["cycle_id"],
            "agency_id": row["agency_id"],
            "poverty_factor": num(row["poverty_factor"]),
            "poverty_share": num(row["poverty_share"]),
            "prior_share": num(row["prior_share"]),
            "raw_score": num(row["raw_score"]),
            "floor_cases": row["floor_cases"],
            "allocated_cases": row["allocated_cases"],
            "cases_committed": row["cases_committed"],
            "cases_delivered": row["cases_delivered"],
            "cases_remaining": row["cases_remaining"],
            "distributed_pounds": num(row["distributed_pounds"]),
            "distribution_record_count": row["distribution_record_count"],
            "record_compliance_pct": num(row["record_compliance_pct"]),
            "admin_funds_base_cents": row["admin_funds_base_cents"],
            "admin_funds_withheld_cents": row["admin_funds_withheld_cents"],
            "admin_funds_cents": row["admin_funds_cents"],
            "status": row["status"],
        }
    )
    return out


def commodity_order(row):
    out = _common(row)
    out.update(
        {
            "cycle_id": row["cycle_id"],
            "agency_id": row["agency_id"],
            "warehouse_id": row["warehouse_id"],
            "status": row["status"],
            "line_count": row["line_count"],
            "total_cases_requested": row["total_cases_requested"],
            "total_cases_approved": row["total_cases_approved"],
            "total_pounds": num(row["total_pounds"]),
            "total_pallets": row["total_pallets"],
            "revision_count": row["revision_count"],
            "last_returned_by_user_id": row["last_returned_by_user_id"],
            "approved_by_user_id": row["approved_by_user_id"],
            "submitted_at": iso(row["submitted_at"]),
            "approved_at": iso(row["approved_at"]),
            "cancel_reason": row["cancel_reason"],
        }
    )
    return out


def order_line(row):
    out = _common(row)
    out.update(
        {
            "order_id": row["order_id"],
            "commodity_id": row["commodity_id"],
            "cases_requested": row["cases_requested"],
            "cases_approved": row["cases_approved"],
            "line_pounds": num(row["line_pounds"]),
            "line_pallets": row["line_pallets"],
            "storage_class": row["storage_class"],
            "lot_assignments": [
                {"lot_id": entry["lot_id"], "cases": entry["cases"]}
                for entry in row["lot_assignments"]
            ],
        }
    )
    return out


def delivery_appointment(row):
    out = _common(row)
    out.update(
        {
            "order_id": row["order_id"],
            "warehouse_id": row["warehouse_id"],
            "agency_id": row["agency_id"],
            "dock_number": row["dock_number"],
            "window_start": iso(row["window_start"]),
            "window_end": iso(row["window_end"]),
            "dry_pallets": row["dry_pallets"],
            "cold_pallets": row["cold_pallets"],
            "frozen_pallets": row["frozen_pallets"],
            "delivered_pounds": num(row["delivered_pounds"]),
            "status": row["status"],
            "confirmed_by_user_id": row["confirmed_by_user_id"],
            "cancel_reason": row["cancel_reason"],
        }
    )
    return out


def inventory_transfer(row):
    out = _common(row)
    out.update(
        {
            "from_lot_id": row["from_lot_id"],
            "to_agency_id": row["to_agency_id"],
            "cases": row["cases"],
            "status": row["status"],
            "transferred_value_cents": row["transferred_value_cents"],
            "decline_reason": row["decline_reason"],
            "accepted_at": iso(row["accepted_at"]),
        }
    )
    return out


def recall(row):
    out = _common(row)
    out.update(
        {
            "source_lot_id": row["source_lot_id"],
            "commodity_code": row["commodity_code"],
            "recall_class": row["recall_class"],
            "hold_scope": row["hold_scope"],
            "reason": row["reason"],
            "initiated_by_user_id": row["initiated_by_user_id"],
            "status": row["status"],
            "held_lot_count": row["held_lot_count"],
            "action_count": row["action_count"],
            "acknowledged_count": row["acknowledged_count"],
            "dispositioned_count": row["dispositioned_count"],
            "accounted_cases": row["accounted_cases"],
            "notices_dispatched_at": iso(row["notices_dispatched_at"]),
        }
    )
    return out


def recall_action(row):
    out = _common(row)
    out.update(
        {
            "recall_id": row["recall_id"],
            "agency_id": row["agency_id"],
            "status": row["status"],
            "exposed_cases": row["exposed_cases"],
            "disposition": row["disposition"],
            "cases_accounted": row["cases_accounted"],
            "notified_at": iso(row["notified_at"]),
            "acknowledged_at": iso(row["acknowledged_at"]),
            "dispositioned_at": iso(row["dispositioned_at"]),
        }
    )
    return out


def household_distribution(row):
    out = _common(row)
    out.update(
        {
            "agency_id": row["agency_id"],
            "cycle_id": row["cycle_id"],
            "commodity_id": row["commodity_id"],
            "household_size": row["household_size"],
            "declared_monthly_income_cents": row["declared_monthly_income_cents"],
            "participates_in_snap": row["participates_in_snap"],
            "self_declaration_signed": row["self_declaration_signed"],
            "cases_distributed": row["cases_distributed"],
            "distribution_date": day(row["distribution_date"]),
            "pounds_distributed": num(row["pounds_distributed"]),
            "income_limit_cents": row["income_limit_cents"],
            "eligibility_determination": row["eligibility_determination"],
            "status": row["status"],
            "void_reason": row["void_reason"],
        }
    )
    return out
