"""Resource serialisers.  Derived fields are computed at read time."""

from decimal import Decimal

import derive
from store import fmt_dt


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def program(row):
    pid = row["id"]
    gross = derive.supplier_gross_payable_cents(pid)
    settled = derive.supplier_settled_cents(pid)
    data = {
        "client_name": row["client_name"],
        "group_name": row["group_name"],
        "arrival_date": fmt_dt(row["arrival_date"]),
        "departure_date": fmt_dt(row["departure_date"]),
        "guaranteed_count": row["guaranteed_count"],
        "markup_pct": _num(row["markup_pct"]),
        "execution_status": row["execution_status"],
        "settlement_status": row["settlement_status"],
        "element_count": derive.element_count(pid),
        "open_element_count": derive.open_element_count(pid),
        "actual_attendance_total": derive.actual_attendance_total(pid),
        "estimated_client_total_cents": row["estimated_client_total_cents"],
        "final_subtotal_cents": derive.final_subtotal_cents(pid),
        "disclosed_markup_cents": derive.disclosed_markup_cents(pid),
        "management_fee_cents": row["management_fee_cents"],
        "final_client_total_cents": row["final_client_total_cents"],
        "supplier_gross_payable_cents": gross,
        "supplier_settled_cents": settled,
        "supplier_open_payable_cents": gross - settled,
        "credit_note_cents": row["credit_note_cents"],
        "seated_guest_count": derive.seated_guest_count(pid),
        "staffing_gap_count": row["staffing_gap_count"],
        "unseated_guest_count": row["unseated_guest_count"],
        "invoice_issued_at": fmt_dt(row["invoice_issued_at"]),
    }
    data.update(_common(row))
    return data


def cost_summary(row):
    pid = row["id"]
    gross = derive.supplier_gross_payable_cents(pid)
    settled = derive.supplier_settled_cents(pid)
    return {
        "program_id": pid,
        "estimated_client_total_cents": row["estimated_client_total_cents"],
        "final_subtotal_cents": derive.final_subtotal_cents(pid),
        "disclosed_markup_cents": derive.disclosed_markup_cents(pid),
        "management_fee_cents": row["management_fee_cents"],
        "fee_pct_applied": _num(row["fee_pct_applied"]),
        "final_client_total_cents": row["final_client_total_cents"],
        "supplier_gross_payable_cents": gross,
        "supplier_settled_cents": settled,
        "supplier_open_payable_cents": gross - settled,
    }


def venue(row):
    data = {
        "name": row["name"],
        "capacity_seated": row["capacity_seated"],
        "capacity_reception": row["capacity_reception"],
        "turnover_buffer_minutes": row["turnover_buffer_minutes"],
        "requires_special_venue_permit": row["requires_special_venue_permit"],
        "status": row["status"],
    }
    data.update(_common(row))
    return data


def supplier(row):
    data = {
        "legal_name": row["legal_name"],
        "supplier_type": row["supplier_type"],
        "insurance_expires_on": fmt_dt(row["insurance_expires_on"]),
        "insurance_liability_limit_cents": row["insurance_liability_limit_cents"],
        "coi_verified": row["coi_verified"],
        "status": row["status"],
    }
    data.update(_common(row))
    return data


def contract(row):
    data = {
        "program_id": row["program_id"],
        "supplier_id": row["supplier_id"],
        "contract_value_cents": row["contract_value_cents"],
        "deposit_pct": _num(row["deposit_pct"]),
        "cancellation_tier": row["cancellation_tier"],
        "required_liability_limit_cents": row["required_liability_limit_cents"],
        "status": row["status"],
        "round_count": row["round_count"],
        "deposit_due_cents": row["deposit_due_cents"],
        "deposit_paid_cents": row["deposit_paid_cents"],
        "sent_by_user_id": row["sent_by_user_id"],
        "countersigned_by_user_id": row["countersigned_by_user_id"],
    }
    data.update(_common(row))
    return data


def element(row):
    data = {
        "program_id": row["program_id"],
        "supplier_id": row["supplier_id"],
        "venue_id": row["venue_id"],
        "predecessor_element_id": row["predecessor_element_id"],
        "alternative_for_element_id": row["alternative_for_element_id"],
        "element_type": row["element_type"],
        "title": row["title"],
        "starts_at": fmt_dt(row["starts_at"]),
        "ends_at": fmt_dt(row["ends_at"]),
        "planned_headcount": row["planned_headcount"],
        "guaranteed_headcount": row["guaranteed_headcount"],
        "per_person_cost_cents": row["per_person_cost_cents"],
        "is_weather_dependent": row["is_weather_dependent"],
        "actual_headcount": row["actual_headcount"],
        "status": row["status"],
        "delivered_at": fmt_dt(row["delivered_at"]),
        "cancellation_penalty_cents": row["cancellation_penalty_cents"],
    }
    data.update(_common(row))
    return data


def permit(row):
    data = {
        "element_id": row["element_id"],
        "permit_type": row["permit_type"],
        "authority_name": row["authority_name"],
        "lead_time_days_required": row["lead_time_days_required"],
        "status": row["status"],
        "submitted_at": fmt_dt(row["submitted_at"]),
        "decision_at": fmt_dt(row["decision_at"]),
        "conditions_note": row["conditions_note"],
        "resubmission_count": row["resubmission_count"],
    }
    data.update(_common(row))
    return data


def segment(row):
    data = {
        "program_id": row["program_id"],
        "segment_type": row["segment_type"],
        "vehicle_code": row["vehicle_code"],
        "origin": row["origin"],
        "destination": row["destination"],
        "depart_at": fmt_dt(row["depart_at"]),
        "arrive_at": fmt_dt(row["arrive_at"]),
        "seat_capacity": row["seat_capacity"],
        "wheelchair_accessible": row["wheelchair_accessible"],
        "booked_seat_count": derive.booked_seat_count(row["id"]),
        "status": row["status"],
        "departed_at": fmt_dt(row["departed_at"]),
    }
    data.update(_common(row))
    return data


def manifest_entry(row):
    data = {
        "segment_id": row["segment_id"],
        "guest_ref": row["guest_ref"],
        "guest_name": row["guest_name"],
        "seat_count": row["seat_count"],
        "mobility_assist": row["mobility_assist"],
        "status": row["status"],
        "move_count": row["move_count"],
    }
    data.update(_common(row))
    return data


def staff_member(row):
    data = {
        "full_name": row["full_name"],
        "role_type": row["role_type"],
        "badge_expires_on": fmt_dt(row["badge_expires_on"]),
        "first_aid_expires_on": fmt_dt(row["first_aid_expires_on"]),
        "pay_rate_cents_per_hour": row["pay_rate_cents_per_hour"],
        "min_rest_minutes": row["min_rest_minutes"],
        "max_daily_minutes": row["max_daily_minutes"],
        "status": row["status"],
        "credential_status": derive.staff_credential_status(row),
        "confirmed_minutes_total": derive.confirmed_minutes_total(row["id"]),
    }
    data.update(_common(row))
    return data


def staff_assignment(row):
    data = {
        "staff_id": row["staff_id"],
        "program_id": row["program_id"],
        "element_id": row["element_id"],
        "segment_id": row["segment_id"],
        "target_type": row["target_type"],
        "role_type": row["role_type"],
        "starts_at": fmt_dt(row["starts_at"]),
        "ends_at": fmt_dt(row["ends_at"]),
        "status": row["status"],
        "check_in_at": fmt_dt(row["check_in_at"]),
        "completed_at": fmt_dt(row["completed_at"]),
        "planned_labor_cost_cents": row["planned_labor_cost_cents"],
        "actual_labor_cost_cents": row["actual_labor_cost_cents"],
    }
    data.update(_common(row))
    return data


def reconciliation_line(row):
    data = {
        "program_id": row["program_id"],
        "element_id": row["element_id"],
        "supplier_id": row["supplier_id"],
        "line_kind": row["line_kind"],
        "guaranteed_headcount": row["guaranteed_headcount"],
        "actual_headcount": row["actual_headcount"],
        "billed_headcount": row["billed_headcount"],
        "supplier_cost_cents": row["supplier_cost_cents"],
        "markup_cents": row["markup_cents"],
        "client_charge_cents": row["client_charge_cents"],
        "variance_pct": _num(row["variance_pct"]),
        "variance_reason": row["variance_reason"],
        "status": row["status"],
    }
    data.update(_common(row))
    return data


def settlement_payment(row):
    data = {
        "program_id": row["program_id"],
        "supplier_id": row["supplier_id"],
        "contract_id": row["contract_id"],
        "gross_cents": row["gross_cents"],
        "deposit_applied_cents": row["deposit_applied_cents"],
        "net_payable_cents": row["net_payable_cents"],
        "overpayment_credit_cents": row["overpayment_credit_cents"],
        "status": row["status"],
        "approved_by_user_id": row["approved_by_user_id"],
        "released_by_user_id": row["released_by_user_id"],
    }
    data.update(_common(row))
    return data
