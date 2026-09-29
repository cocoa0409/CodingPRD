"""Row -> JSON. Field names are exactly those of SCAFFOLD §1.1."""
from decimal import Decimal

import db
from db import store
from services import derive

MS = db.iso_ms
TS = db.iso_instant


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": MS(row["created_at"]),
        "updated_at": MS(row["updated_at"]),
        "version": row["version"],
    }


def supplier(row):
    out = _common(row)
    out.update(
        {
            "supplier_code": row["supplier_code"],
            "name": row["name"],
            "component_categories": list(row["component_categories"]),
            "quality_score": num(row["quality_score"]),
            "supplier_status": row["supplier_status"],
            "open_recall_count": row["open_recall_count"],
            "penalty_event_count": row["penalty_event_count"],
        }
    )
    return out


def floor_plan(row):
    out = _common(row)
    out.update(
        {
            "model_code": row["model_code"],
            "chassis_class": row["chassis_class"],
            "length_ft": row["length_ft"],
            "base_msrp_cents": row["base_msrp_cents"],
            "base_station_hours": num(row["base_station_hours"]),
            "base_dry_weight_lbs": row["base_dry_weight_lbs"],
            "gvwr_lbs": row["gvwr_lbs"],
            "required_wheelbase_in": row["required_wheelbase_in"],
            "electrical_service_amps": row["electrical_service_amps"],
            "fresh_water_capacity_gal": row["fresh_water_capacity_gal"],
            "max_payload_lbs": row["max_payload_lbs"],
            "status": row["status"],
        }
    )
    return out


def option_item(row):
    out = _common(row)
    out.update(
        {
            "option_code": row["option_code"],
            "category": row["category"],
            "install_station": row["install_station"],
            "price_cents": row["price_cents"],
            "weight_lbs": row["weight_lbs"],
            "added_station_hours": num(row["added_station_hours"]),
            "amp_draw": row["amp_draw"],
            "water_demand_gal": row["water_demand_gal"],
            "requires_option_codes": list(row["requires_option_codes"]),
            "excludes_option_codes": list(row["excludes_option_codes"]),
            "status": row["status"],
        }
    )
    return out


def dealer(row):
    out = _common(row)
    out.update(
        {
            "dealer_code": row["dealer_code"],
            "region": row["region"],
            "allocation_share_bp": row["allocation_share_bp"],
            "floor_plan_credit_limit_cents": row["floor_plan_credit_limit_cents"],
            "goodwill_budget_cents": row["goodwill_budget_cents"],
            "status": row["status"],
        }
    )
    position = derive.dealer_position(row)
    out["financed_exposure_cents"] = position["financed_exposure_cents"]
    out["credit_utilization_bp"] = position["credit_utilization_bp"]
    out["credit_status"] = position["credit_status"]
    out["goodwill_used_cents"] = position["goodwill_used_cents"]
    out["entitlement_hours"] = num(position["entitlement_hours"])
    out["allocation_hours_consumed"] = num(position["allocation_hours_consumed"])
    out["allocation_slots_reserved"] = position["allocation_slots_reserved"]
    return out


def unit_order(row):
    out = _common(row)
    out.update(
        {
            "dealer_id": row["dealer_id"],
            "floor_plan_id": row["floor_plan_id"],
            "order_type": row["order_type"],
            "customer_reference": row.get("customer_reference"),
            "selected_option_ids": list(row["selected_option_ids"]),
            "requested_delivery_date": TS(row["requested_delivery_date"]),
            "status": row["status"],
            "financing_status": row["financing_status"],
            "option_price_total_cents": row["option_price_total_cents"],
            "config_weight_lbs": row["config_weight_lbs"],
            "payload_remaining_lbs": row["payload_remaining_lbs"],
            "total_amp_draw": row["total_amp_draw"],
            "total_water_demand_gal": row["total_water_demand_gal"],
            "required_station_hours": num(row["required_station_hours"]),
            "provisional_invoice_cents": row["provisional_invoice_cents"],
            "final_invoice_cents": row["final_invoice_cents"],
            "locked_floor_plan_version": row["locked_floor_plan_version"],
            "locked_option_versions": [dict(entry) for entry in row["locked_option_versions"]],
            "financed_principal_cents": row["financed_principal_cents"],
            "curtailment_paid_cents": row["curtailment_paid_cents"],
            "curtailment_due_cents": derive.order_curtailment_due(row),
            "funded_at": TS(row.get("funded_at")),
            "shipped_at": TS(row.get("shipped_at")),
            "ship_hold_reason": row["ship_hold_reason"],
        }
    )
    return out


def production_line(row):
    out = _common(row)
    out.update(
        {
            "line_code": row["line_code"],
            "chassis_class_supported": row["chassis_class_supported"],
            "daily_station_hour_capacity": num(row["daily_station_hour_capacity"]),
            "max_units_per_day": row["max_units_per_day"],
            "status": row["status"],
        }
    )
    return out


def production_slot(row):
    out = _common(row)
    out.update(
        {
            "line_id": row["line_id"],
            "unit_order_id": row["unit_order_id"],
            "slot_date": TS(row["slot_date"]),
            "sequence_position": row["sequence_position"],
            "station_hours_committed": num(row["station_hours_committed"]),
            "expires_at": TS(row["expires_at"]),
            "status": row["status"],
        }
    )
    return out


def chassis_receipt(row):
    out = _common(row)
    out.update(
        {
            "supplier_id": row["supplier_id"],
            "chassis_serial": row["chassis_serial"],
            "chassis_class": row["chassis_class"],
            "gvwr_lbs": row["gvwr_lbs"],
            "wheelbase_in": row["wheelbase_in"],
            "received_at": TS(row["received_at"]),
            "matched_unit_order_id": row.get("matched_unit_order_id"),
            "status": row["status"],
        }
    )
    return out


def component_lot(row):
    out = _common(row)
    out.update(
        {
            "supplier_id": row["supplier_id"],
            "part_number": row["part_number"],
            "lot_code": row["lot_code"],
            "category": row["category"],
            "quantity_received": row["quantity_received"],
            "quantity_available": row["quantity_available"],
            "quantity_installed": row["quantity_installed"],
            "quantity_quarantined": row["quantity_quarantined"],
            "status": row["status"],
        }
    )
    return out


def unit_build(row):
    out = _common(row)
    out.update(
        {
            "unit_order_id": row["unit_order_id"],
            "chassis_receipt_id": row["chassis_receipt_id"],
            "vin": row["vin"],
            "build_sequence": row["build_sequence"],
            "current_station": row["current_station"],
            "actual_station_hours": num(row["actual_station_hours"]),
            "rework_count": row["rework_count"],
            "defect_points_total": row["defect_points_total"],
            "water_test_passed": row["water_test_passed"],
            "pdi_passed": row["pdi_passed"],
            "recall_hold": row["recall_hold"],
        }
    )
    return out


def component_installation(row):
    out = _common(row)
    out.update(
        {
            "unit_build_id": row["unit_build_id"],
            "component_lot_id": row["component_lot_id"],
            "station": row["station"],
            "quantity": row["quantity"],
            "recall_campaign_id": row.get("recall_campaign_id"),
            "status": row["status"],
        }
    )
    return out


def test_booth(row):
    out = _common(row)
    out.update(
        {
            "booth_code": row["booth_code"],
            "booth_type": row["booth_type"],
            "bay_count": row["bay_count"],
            "turnaround_minutes": row["turnaround_minutes"],
            "status": row["status"],
        }
    )
    return out


def quality_inspection(row):
    out = _common(row)
    out.update(
        {
            "unit_build_id": row["unit_build_id"],
            "test_booth_id": row.get("test_booth_id"),
            "inspection_type": row["inspection_type"],
            "window_start": TS(row.get("window_start")),
            "window_end": TS(row.get("window_end")),
            "inspector_user_id": row["inspector_user_id"],
            "completed_by_user_id": row.get("completed_by_user_id"),
            "defect_points": row["defect_points"],
            "leak_detected": row["leak_detected"],
            "result": row.get("result"),
            "status": row["status"],
        }
    )
    return out


def warranty_claim(row):
    out = _common(row)
    out.update(
        {
            "dealer_id": row["dealer_id"],
            "unit_build_id": row["unit_build_id"],
            "component_lot_id": row.get("component_lot_id"),
            "claim_type": row["claim_type"],
            "labor_hours": num(row["labor_hours"]),
            "parts_cost_cents": row["parts_cost_cents"],
            "goodwill_requested_cents": row["goodwill_requested_cents"],
            "narrative": row["narrative"],
            "in_warranty": row["in_warranty"],
            "labor_reimbursement_cents": row["labor_reimbursement_cents"],
            "parts_reimbursement_cents": row["parts_reimbursement_cents"],
            "authority_tier": row.get("authority_tier"),
            "goodwill_authorized_cents": row["goodwill_authorized_cents"],
            "total_reimbursement_cents": row["total_reimbursement_cents"],
            "supplier_chargeback_cents": row["supplier_chargeback_cents"],
            "info_request_count": row["info_request_count"],
            "resubmission_count": row["resubmission_count"],
            "approved_by_user_id": row.get("approved_by_user_id"),
            "paid_by_user_id": row.get("paid_by_user_id"),
            "denial_reason": row.get("denial_reason"),
            "status": row["status"],
        }
    )
    return out


def recall_campaign(row):
    out = _common(row)
    out.update(
        {
            "supplier_id": row["supplier_id"],
            "campaign_code": row["campaign_code"],
            "part_number": row["part_number"],
            "lot_codes": list(row["lot_codes"]),
            "severity": row["severity"],
            "opened_at": TS(row.get("opened_at")),
            "affected_installation_count": row["affected_installation_count"],
            "remedied_installation_count": row["remedied_installation_count"],
            "quarantined_piece_count": row["quarantined_piece_count"],
            "ship_stop": row["ship_stop"],
            "status": row["status"],
        }
    )
    return out


SERIALIZERS = {
    "suppliers": supplier,
    "floor_plans": floor_plan,
    "option_items": option_item,
    "dealers": dealer,
    "unit_orders": unit_order,
    "production_lines": production_line,
    "production_slots": production_slot,
    "chassis_receipts": chassis_receipt,
    "component_lots": component_lot,
    "unit_builds": unit_build,
    "component_installations": component_installation,
    "test_booths": test_booth,
    "quality_inspections": quality_inspection,
    "warranty_claims": warranty_claim,
    "recall_campaigns": recall_campaign,
}
