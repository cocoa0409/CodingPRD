"""Serialisation. Derived aggregates are computed from live state so that
every published ledger always agrees with its children (PRD 2.10)."""
import calc
from db import db


def venue_contract_view(row):
    return {
        "id": row["id"],
        "venue_code": row["venue_code"],
        "hall_code": row["hall_code"],
        "hall_gross_sqft": row["hall_gross_sqft"],
        "min_aisle_ratio_pct": row["min_aisle_ratio_pct"],
        "max_booth_height_ft": row["max_booth_height_ft"],
        "contract_year_start": row["contract_year_start"],
        "contract_year_count": row["contract_year_count"],
        "committed_net_sqft_per_year": row["committed_net_sqft_per_year"],
        "attrition_allowance_pct": row["attrition_allowance_pct"],
        "advance_order_discount_pct": row["advance_order_discount_pct"],
        "labor_rate_cents_per_hour": row["labor_rate_cents_per_hour"],
        "electrical_rate_cents_per_amp": row["electrical_rate_cents_per_amp"],
        "material_handling_rate_cents_per_cwt": row["material_handling_rate_cents_per_cwt"],
        "cancellation_fee_schedule": row["cancellation_fee_schedule"],
        "status": row["status"],
        "executed_at": row["executed_at"],
        "terminated_effective_date": row["terminated_effective_date"],
        "show_count": len([s for s in calc.venue_shows(row["id"])
                           if s["status"] != "CANCELLED"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def show_view(row):
    return {
        "id": row["id"],
        "venue_contract_id": row["venue_contract_id"],
        "name": row["name"],
        "edition_year": row["edition_year"],
        "move_in_start": row["move_in_start"],
        "event_start": row["event_start"],
        "event_end": row["event_end"],
        "move_out_end": row["move_out_end"],
        "gross_sqft": row["gross_sqft"],
        "aisle_ratio_pct": row["aisle_ratio_pct"],
        "base_rate_cents_per_sqft": row["base_rate_cents_per_sqft"],
        "selection_desk_capacity": row["selection_desk_capacity"],
        "status": row["status"],
        "selection_round": row["selection_round"],
        "floor_posture": calc.floor_posture(row),
        "net_sellable_sqft": row["net_sellable_sqft"],
        "sellable_booth_sqft": calc.sellable_booth_sqft(row),
        "held_net_sqft": calc.held_net_sqft(row),
        "assigned_net_sqft": calc.assigned_net_sqft(row),
        "available_net_sqft": calc.available_net_sqft(row),
        "committed_ratio_pct": calc.committed_ratio_pct(row),
        "upheld_violation_count": calc.upheld_violation_count(row),
        "advance_order_deadline": row["advance_order_deadline"],
        "attrition_shortfall_sqft": row["attrition_shortfall_sqft"],
        "attrition_settlement_cents": row["attrition_settlement_cents"],
        "cancellation_reason": row["cancellation_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def booth_view(row):
    return {
        "id": row["id"],
        "show_id": row["show_id"],
        "space_contract_id": row["space_contract_id"],
        "combined_parent_booth_id": row["combined_parent_booth_id"],
        "booth_number": row["booth_number"],
        "width_ft": row["width_ft"],
        "depth_ft": row["depth_ft"],
        "area_sqft": row["area_sqft"],
        "location_class": row["location_class"],
        "premium_zone": row["premium_zone"],
        "max_height_ft": row["max_height_ft"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def exhibitor_view(row):
    provisional = calc.provisional_priority_points(row)
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "contact_email": row["contact_email"],
        "consecutive_years": row["consecutive_years"],
        "status": row["status"],
        "ledger_points": row["ledger_points"],
        "sponsorship_fulfillment_points": row["sponsorship_fulfillment_points"],
        "penalty_points": row["penalty_points"],
        "space_points_provisional": calc.space_points_provisional(row["id"]),
        "space_points_certified": calc.space_points_certified(row["id"]),
        "provisional_priority_points": provisional,
        "certified_priority_points": calc.certified_priority_points(row),
        "priority_tier": calc.priority_tier(provisional),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def appointment_view(row):
    return {
        "id": row["id"],
        "show_id": row["show_id"],
        "exhibitor_id": row["exhibitor_id"],
        "round_index": row["round_index"],
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "state": row["state"],
        "rank": row["rank"],
        "certified_points_at_rank": row["certified_points_at_rank"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def space_contract_view(row):
    return {
        "id": row["id"],
        "show_id": row["show_id"],
        "exhibitor_id": row["exhibitor_id"],
        "rebooked_from_space_contract_id": row["rebooked_from_space_contract_id"],
        "status": row["status"],
        "requested_sqft": row["requested_sqft"],
        "offered_booth_ids": list(row["offered_booth_ids"]),
        "offered_net_sqft": calc.offered_net_sqft(row),
        "assigned_net_sqft": calc.contract_assigned_net_sqft(row),
        "premium_placement_requested": row["premium_placement_requested"],
        "requested_discount_pct": row["requested_discount_pct"],
        "approved_discount_pct": row["approved_discount_pct"],
        "negotiation_round": row["negotiation_round"],
        "volume_tier_pct": row["volume_tier_pct"],
        "space_fee_cents": row["space_fee_cents"],
        "sponsorship_attached_cents": row["sponsorship_attached_cents"],
        "bundle_discount_pct": row["bundle_discount_pct"],
        "bundle_discount_cents": row["bundle_discount_cents"],
        "invoice_total_cents": row["invoice_total_cents"],
        "min_deposit_cents": row["min_deposit_cents"],
        "deposit_paid_cents": row["deposit_paid_cents"],
        "cancellation_fee_cents": row["cancellation_fee_cents"],
        "fee_applied_to_deposit_cents": row["fee_applied_to_deposit_cents"],
        "refund_cents": row["refund_cents"],
        "balance_due_cents": row["balance_due_cents"],
        "points_awarded": row["points_awarded"],
        "signed_at": row["signed_at"],
        "last_offer_by_user_id": row["last_offer_by_user_id"],
        "cancellation_reason": row["cancellation_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def service_order_view(row):
    return {
        "id": row["id"],
        "space_contract_id": row["space_contract_id"],
        "service_type": row["service_type"],
        "quantity": row["quantity"],
        "billable_quantity": row["billable_quantity"],
        "unit_rate_cents": row["unit_rate_cents"],
        "rate_variant": row["rate_variant"],
        "line_total_cents": row["line_total_cents"],
        "ordered_at": row["ordered_at"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def rule_violation_view(row):
    return {
        "id": row["id"],
        "space_contract_id": row["space_contract_id"],
        "violation_type": row["violation_type"],
        "measured_value": row["measured_value"],
        "notes": row["notes"],
        "status": row["status"],
        "reported_by_user_id": row["reported_by_user_id"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "penalty_points": row["penalty_points"],
        "waiver_reason": row["waiver_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def package_view(row):
    return {
        "id": row["id"],
        "show_id": row["show_id"],
        "package_code": row["package_code"],
        "list_price_cents": row["list_price_cents"],
        "price_floor_cents": row["price_floor_cents"],
        "inventory_total": row["inventory_total"],
        "inventory_committed": calc.inventory_committed(row),
        "inventory_available": calc.inventory_available(row),
        "exclusivity_category": row["exclusivity_category"],
        "obligation_codes": list(row["obligation_codes"]),
        "priority_point_value": row["priority_point_value"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def deal_view(row):
    return {
        "id": row["id"],
        "sponsorship_package_id": row["sponsorship_package_id"],
        "exhibitor_id": row["exhibitor_id"],
        "negotiated_price_cents": row["negotiated_price_cents"],
        "deal_status": row["deal_status"],
        "fulfillment_status": calc.derived_fulfillment_status(row),
        "obligation_count": calc.obligation_count(row),
        "resolved_obligation_count": calc.resolved_obligation_count(row),
        "fulfillment_credited": row["fulfillment_credited"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "signed_by_user_id": row["signed_by_user_id"],
        "cancellation_reason": row["cancellation_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def obligation_view(row):
    return {
        "id": row["id"],
        "sponsorship_deal_id": row["sponsorship_deal_id"],
        "obligation_code": row["obligation_code"],
        "due_date": row["due_date"],
        "status": row["status"],
        "resolved_by_user_id": row["resolved_by_user_id"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def registration_view(row):
    return {
        "id": row["id"],
        "show_id": row["show_id"],
        "category": row["category"],
        "company_name": row["company_name"],
        "job_title": row["job_title"],
        "purchasing_authority": row["purchasing_authority"],
        "annual_spend_band": row["annual_spend_band"],
        "email": row["email"],
        "qualification_score": row["qualification_score"],
        "qualification_status": row["qualification_status"],
        "screening_override_reason": row["screening_override_reason"],
        "lead_scan_count": len(calc.registration_scans(row["id"])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def lead_scan_view(row):
    return {
        "id": row["id"],
        "space_contract_id": row["space_contract_id"],
        "registration_id": row["registration_id"],
        "scanned_at": row["scanned_at"],
        "created_at": row["created_at"],
    }
