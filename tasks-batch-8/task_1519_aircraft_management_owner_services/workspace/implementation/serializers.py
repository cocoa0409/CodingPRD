"""Entity serializers. Field names follow SCAFFOLD §1.1 exactly."""
from util import fmt_ts


def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def owner_view(rec):
    out = _base(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "contact_email": rec["contact_email"],
    })
    return out


def aircraft_view(rec):
    out = _base(rec)
    out.update({
        "owner_id": rec["owner_id"],
        "tail_number": rec["tail_number"],
        "model": rec["model"],
        "home_base_icao": rec["home_base_icao"],
        "total_time_hours": rec["total_time_hours"],
    })
    return out


def agreement_view(rec):
    out = _base(rec)
    out.update({
        "owner_id": rec["owner_id"],
        "aircraft_id": rec["aircraft_id"],
        "monthly_management_fee_cents": rec["monthly_management_fee_cents"],
        "variable_fee_pct": rec["variable_fee_pct"],
        "charter_owner_share_pct": rec["charter_owner_share_pct"],
        "tax_allocation_method": rec["tax_allocation_method"],
        "status": rec["status"],
        "notice_given_at": rec["notice_given_at"],
        "records_total": rec["records_total"],
        "records_released": rec["records_released"],
    })
    return out


def budget_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "fiscal_year": rec["fiscal_year"],
        "fuel_cents": rec["fuel_cents"],
        "maintenance_cents": rec["maintenance_cents"],
        "crew_cents": rec["crew_cents"],
        "hangar_cents": rec["hangar_cents"],
        "insurance_cents": rec["insurance_cents"],
        "other_cents": rec["other_cents"],
        "status": rec["status"],
        "rejection_reason": rec["rejection_reason"],
    })
    return out


def expense_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "statement_id": rec["statement_id"],
        "trip_id": rec["trip_id"],
        "category": rec["category"],
        "amount_cents": rec["amount_cents"],
        "service_date": rec["service_date"],
        "paid_date": rec["paid_date"],
        "vendor_name": rec["vendor_name"],
        "tax_use": rec["tax_use"],
        "status": rec["status"],
    })
    return out


def statement_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "period": rec["period"],
        "prepared_by_user_id": rec["prepared_by_user_id"],
        "certified_by_user_id": rec["certified_by_user_id"],
        "accrual_total_cents": rec["accrual_total_cents"],
        "cash_total_cents": rec["cash_total_cents"],
        "management_fee_cents": rec["management_fee_cents"],
        "charter_offset_cents": rec["charter_offset_cents"],
        "budget_variance_cents": rec["budget_variance_cents"],
        "mixed_owner_share_cents": rec["mixed_owner_share_cents"],
        "mixed_charter_share_cents": rec["mixed_charter_share_cents"],
        "tax_method_used": rec["tax_method_used"],
        "status": rec["status"],
    })
    return out


def crew_view(rec, duty_7d=None, duty_28d=None, flight_total=None):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "full_name": rec["full_name"],
        "crew_role": rec["crew_role"],
        "hire_date": rec["hire_date"],
        "status": rec["status"],
        "training_hours_accumulated": rec["training_hours_accumulated"],
        "duty_hours_7d": duty_7d if duty_7d is not None else rec.get("duty_hours_7d", 0.0),
        "duty_hours_28d": duty_28d if duty_28d is not None else rec.get("duty_hours_28d", 0.0),
        "flight_hours_total": flight_total if flight_total is not None else rec.get("flight_hours_total", 0.0),
    })
    return out


def trip_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "trip_use": rec["trip_use"],
        "depart_icao": rec["depart_icao"],
        "arrive_icao": rec["arrive_icao"],
        "departure_at": rec["departure_at"],
        "block_hours_est": rec["block_hours_est"],
        "block_hours_actual": rec["block_hours_actual"],
        "charter_quote_cents": rec["charter_quote_cents"],
        "owner_credit_cents": rec["owner_credit_cents"],
        "charter_shortfall_cents": rec["charter_shortfall_cents"],
        "decline_reason": rec["decline_reason"],
        "status": rec["status"],
    })
    return out


def assignment_view(rec):
    out = _base(rec)
    out.update({
        "trip_id": rec["trip_id"],
        "crew_member_id": rec["crew_member_id"],
        "duty_role": rec["duty_role"],
        "duty_start_at": rec["duty_start_at"],
        "duty_end_at": rec["duty_end_at"],
        "duty_hours": rec["duty_hours"],
        "status": rec["status"],
    })
    return out


def program_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "program_name": rec["program_name"],
        "rate_per_hour_cents": rec["rate_per_hour_cents"],
        "status": rec["status"],
    })
    return out


def event_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "previous_event_id": rec["previous_event_id"],
        "event_code": rec["event_code"],
        "interval_hours": rec["interval_hours"],
        "due_at_aircraft_hours": rec["due_at_aircraft_hours"],
        "scheduled_date": rec["scheduled_date"],
        "completed_at": rec["completed_at"],
        "actual_aircraft_hours": rec["actual_aircraft_hours"],
        "handed_over_at": rec["handed_over_at"],
        "status": rec["status"],
    })
    return out


def filing_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "filing_kind": rec["filing_kind"],
        "authority": rec["authority"],
        "reference_no": rec["reference_no"],
        "valid_until": rec["valid_until"],
        "filed_at": rec["filed_at"],
        "decision_notes": rec["decision_notes"],
        "handed_over_at": rec["handed_over_at"],
        "status": rec["status"],
    })
    return out


def contract_view(rec):
    out = _base(rec)
    out.update({
        "aircraft_id": rec["aircraft_id"],
        "vendor_kind": rec["vendor_kind"],
        "vendor_name": rec["vendor_name"],
        "unit": rec["unit"],
        "rate_cents_per_unit": rec["rate_cents_per_unit"],
        "term_start": rec["term_start"],
        "term_end": rec["term_end"],
        "status": rec["status"],
    })
    return out
