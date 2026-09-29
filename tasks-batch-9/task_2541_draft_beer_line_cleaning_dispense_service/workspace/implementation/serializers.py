"""Entity -> JSON projections."""
import projections
from common import date_str, jnum, now_iso


def _common(row, mutable=True):
    out = {"id": row["id"], "created_at": now_iso(row["created_at"])}
    if mutable:
        out["updated_at"] = now_iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def account(row):
    out = {
        "venue_name": row["venue_name"],
        "status": row["status"],
        "access_window_start_minute": row["access_window_start_minute"],
        "access_window_end_minute": row["access_window_end_minute"],
        "glycol_system_present": row["glycol_system_present"],
        "billing_mode": row["billing_mode"],
        "lines_out_of_service_count": row["lines_out_of_service_count"],
        "open_complaint_count": row["open_complaint_count"],
        "suspended_reason": row["suspended_reason"],
    }
    out.update(_common(row))
    return out


def contract(row):
    out = {
        "account_id": row["account_id"],
        "brewer_program_id": row["brewer_program_id"],
        "status": row["status"],
        "cleaning_frequency_days": row["cleaning_frequency_days"],
        "contracted_line_count": row["contracted_line_count"],
        "per_line_rate_cents": row["per_line_rate_cents"],
        "visit_base_fee_cents": row["visit_base_fee_cents"],
        "effective_from": now_iso(row["effective_from"]),
        "funding_status": row["funding_status"],
        "frequency_multiplier": jnum(row["frequency_multiplier"]),
    }
    out.update(_common(row))
    return out


def beer_line(row):
    applied = projections.newest_applied_balance(row["id"])
    out = {
        "account_id": row["account_id"],
        "line_number": row["line_number"],
        "run_length_feet": jnum(row["run_length_feet"]),
        "vertical_rise_feet": jnum(row["vertical_rise_feet"]),
        "inner_diameter_inches": jnum(row["inner_diameter_inches"]),
        "beer_style_group": row["beer_style_group"],
        "average_daily_throughput_liters": jnum(row["average_daily_throughput_liters"]),
        "status": row["status"],
        "compliance_flag": projections.line_compliance_flag(row),
        "last_chemical_type": row["last_chemical_type"],
        "last_cleaned_at": now_iso(row["last_cleaned_at"]),
        "next_due_at": now_iso(projections.line_next_due_at(row)),
        "days_overdue": projections.line_days_overdue(row),
        "applied_psi": jnum(applied["proposed_applied_psi"]) if applied else None,
        "applied_co2_pct": jnum(applied["proposed_co2_pct"]) if applied else None,
    }
    out.update(_common(row))
    return out


def technician(row):
    out = {
        "full_name": row["full_name"],
        "certification_level": row["certification_level"],
        "caustic_certified": row["caustic_certified"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def chemical_lot(row):
    out = {
        "chemical_type": row["chemical_type"],
        "lot_code": row["lot_code"],
        "concentration_pct_stock": jnum(row["concentration_pct_stock"]),
        "liters_initial": jnum(row["liters_initial"]),
        "liters_remaining": jnum(row["liters_remaining"]),
        "expires_on": date_str(row["expires_on"]),
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def part(row):
    out = {
        "sku": row["sku"],
        "component_type": row["component_type"],
        "unit_price_cents": row["unit_price_cents"],
        "stock_on_hand": row["stock_on_hand"],
        "brewer_funded_eligible": row["brewer_funded_eligible"],
    }
    out.update(_common(row))
    return out


def program(row):
    out = {
        "brewer_name": row["brewer_name"],
        "funded_scope": row["funded_scope"],
        "co_pay_bps": row["co_pay_bps"],
        "funding_cap_cents": row["funding_cap_cents"],
        "consumed_cents": row["consumed_cents"],
        "remaining_cents": row["remaining_cents"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def visit(row):
    out = {
        "account_id": row["account_id"],
        "technician_id": row["technician_id"],
        "rescheduled_from_visit_id": row["rescheduled_from_visit_id"],
        "visit_kind": row["visit_kind"],
        "scheduled_date": date_str(row["scheduled_date"]),
        "scheduled_start_minute": row["scheduled_start_minute"],
        "scheduled_end_minute": row["scheduled_end_minute"],
        "work_status": row["work_status"],
        "verification_status": row["verification_status"],
        "settlement_state": row["settlement_state"],
        "abandon_reason": row["abandon_reason"],
        "signer_name": row["signer_name"],
        "signed_at": now_iso(row["signed_at"]),
        "work_completed_at": now_iso(row["work_completed_at"]),
        "serviced_line_count": row["serviced_line_count"],
        "billable_line_count": row["billable_line_count"],
        "cleaning_subtotal_cents": row["cleaning_subtotal_cents"],
        "parts_charge_cents": row["parts_charge_cents"],
        "provisional_charge_cents": row["provisional_charge_cents"],
        "settled_charge_cents": row["settled_charge_cents"],
        "brewer_funded_cents": row["brewer_funded_cents"],
        "account_due_cents": row["account_due_cents"],
    }
    out.update(_common(row))
    return out


def cleaning_cycle(row):
    out = {
        "visit_id": row["visit_id"],
        "line_id": row["line_id"],
        "chemical_lot_id": row["chemical_lot_id"],
        "chemical_type": row["chemical_type"],
        "logged_at": now_iso(row["logged_at"]),
        "logged_by_technician_id": row["logged_by_technician_id"],
        "contact_minutes": row["contact_minutes"],
        "recirculation_temp_f": jnum(row["recirculation_temp_f"]),
        "concentrate_liters_used": jnum(row["concentrate_liters_used"]),
        "line_volume_liters": jnum(row["line_volume_liters"]),
        "total_solution_liters": row["total_solution_liters"],
        "prescribed_concentrate_liters": jnum(row["prescribed_concentrate_liters"]),
        "effective_active_pct": jnum(row["effective_active_pct"]),
        "required_contact_minutes": row["required_contact_minutes"],
        "compliance_result": row["compliance_result"],
        "record_status": row["record_status"],
        "void_reason": row["void_reason"],
    }
    out.update(_common(row))
    return out


def balance_record(row):
    out = {
        "line_id": row["line_id"],
        "visit_id": row["visit_id"],
        "measured_temp_f": jnum(row["measured_temp_f"]),
        "proposed_applied_psi": jnum(row["proposed_applied_psi"]),
        "proposed_co2_pct": jnum(row["proposed_co2_pct"]),
        "proposed_by_technician_id": row["proposed_by_technician_id"],
        "target_co2_volumes": jnum(row["target_co2_volumes"]),
        "equilibrium_psi": jnum(row["equilibrium_psi"]),
        "total_restriction_psi": jnum(row["total_restriction_psi"]),
        "required_applied_psi": jnum(row["required_applied_psi"]),
        "required_co2_pct": jnum(row["required_co2_pct"]),
        "balance_state": row["balance_state"],
        "status": row["status"],
        "decision_note": row["decision_note"],
    }
    out.update(_common(row))
    return out


def inspection(row):
    out = {
        "visit_id": row["visit_id"],
        "line_id": row["line_id"],
        "part_sku_id": row["part_sku_id"],
        "component_type": row["component_type"],
        "condition_grade": row["condition_grade"],
        "action_taken": row["action_taken"],
        "part_charge_cents": row["part_charge_cents"],
        "inspected_by_technician_id": row["inspected_by_technician_id"],
    }
    out.update(_common(row, mutable=False))
    return out


def complaint(row):
    out = {
        "account_id": row["account_id"],
        "line_id": row["line_id"],
        "symptom": row["symptom"],
        "reported_at": now_iso(row["reported_at"]),
        "status": row["status"],
        "diagnostic_round": row["diagnostic_round"],
        "reopen_count": row["reopen_count"],
        "days_at_risk": row["days_at_risk"],
        "provisional_yield_loss_liters": jnum(row["provisional_yield_loss_liters"]),
        "provisional_yield_loss_cents": row["provisional_yield_loss_cents"],
        "settled_yield_loss_liters": jnum(row["settled_yield_loss_liters"]),
        "settled_yield_loss_cents": row["settled_yield_loss_cents"],
        "measured_waste_liters": jnum(row["measured_waste_liters"]),
        "escalated_by_user_id": row["escalated_by_user_id"],
        "closed_by_user_id": row["closed_by_user_id"],
        "resolved_at": now_iso(row["resolved_at"]),
        "last_finding_code": row["last_finding_code"],
    }
    out.update(_common(row))
    return out


def glycol_loop(row):
    derived = projections.loop_projection(row)
    out = {
        "account_id": row["account_id"],
        "glycol_pct": jnum(row["glycol_pct"]),
        "pump_psi": jnum(row["pump_psi"]),
        "bath_temp_f": jnum(row["bath_temp_f"]),
        "last_serviced_at": now_iso(row["last_serviced_at"]),
        "health_score": jnum(derived["health_score"]),
        "status": derived["status"],
        "window_avg_cooler_temp_f": jnum(derived["window_avg_cooler_temp_f"]),
    }
    out.update(_common(row))
    return out


def cooler_reading(row):
    out = {
        "glycol_loop_id": row["glycol_loop_id"],
        "reading_at": now_iso(row["reading_at"]),
        "cooler_temp_f": jnum(row["cooler_temp_f"]),
        "glycol_supply_temp_f": jnum(row["glycol_supply_temp_f"]),
        "source": row["source"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    out.update(_common(row, mutable=False))
    return out
