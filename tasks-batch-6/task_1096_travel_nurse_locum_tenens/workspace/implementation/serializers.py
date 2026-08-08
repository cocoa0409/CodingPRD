"""Public JSON representations for each entity."""
from common import num


def _common(e):
    return {"id": e["id"], "created_at": e["created_at"],
            "updated_at": e["updated_at"], "version": e["version"]}


def ser_clinician(e):
    d = _common(e)
    d.update({
        "full_name": e["full_name"],
        "discipline": e["discipline"],
        "specialty": e["specialty"],
        "employment_type": e["employment_type"],
        "primary_residence_state": e["primary_residence_state"],
        "tax_home_verified": e["tax_home_verified"],
        "status": e["status"],
        "active_assignment_count": e["active_assignment_count"],
        "ytd_taxable_wages_cents": e["ytd_taxable_wages_cents"],
        "ytd_nontaxable_stipend_cents": e["ytd_nontaxable_stipend_cents"],
    })
    return d


def ser_license(e):
    d = _common(e)
    d.update({
        "clinician_id": e["clinician_id"],
        "state_code": e["state_code"],
        "license_type": e["license_type"],
        "license_number": e["license_number"],
        "is_compact": e["is_compact"],
        "expires_on": e["expires_on"],
        "status": e["status"],
        "verified_by_user_id": e["verified_by_user_id"],
        "verified_at": e["verified_at"],
    })
    return d


def ser_facility(e):
    d = _common(e)
    d.update({
        "name": e["name"],
        "state_code": e["state_code"],
        "is_compact_member": e["is_compact_member"],
        "per_diem_locality_code": e["per_diem_locality_code"],
        "max_concurrent_travelers": e["max_concurrent_travelers"],
        "billing_contact_email": e["billing_contact_email"],
    })
    return d


def ser_per_diem(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "locality_code": e["locality_code"],
        "state_code": e["state_code"],
        "daily_lodging_cents": e["daily_lodging_cents"],
        "daily_mie_cents": e["daily_mie_cents"],
        "effective_from": e["effective_from"],
    }


def ser_assignment(e):
    d = _common(e)
    d.update({
        "clinician_id": e["clinician_id"],
        "facility_id": e["facility_id"],
        "covering_license_id": e["covering_license_id"],
        "specialty": e["specialty"],
        "required_license_type": e["required_license_type"],
        "shift": e["shift"],
        "start_date": e["start_date"],
        "term_weeks": e["term_weeks"],
        "end_date": e["end_date"],
        "staffing_status": e["staffing_status"],
        "compliance_status": e["compliance_status"],
        "guaranteed_hours_total": num(e["guaranteed_hours_total"]),
        "guaranteed_hours_consumed": num(e["guaranteed_hours_consumed"]),
        "guaranteed_hours_remaining": num(e["guaranteed_hours_remaining"]),
        "guaranteed_hours_waived": num(e["guaranteed_hours_waived"]),
        "realized_gross_bill_cents": e["realized_gross_bill_cents"],
        "realized_pay_cost_cents": e["realized_pay_cost_cents"],
        "realized_margin_cents": e["realized_margin_cents"],
        "realized_margin_pct": num(e["realized_margin_pct"]),
        "projected_gross_bill_cents": e["projected_gross_bill_cents"],
        "projected_pay_cost_cents": e["projected_pay_cost_cents"],
        "projected_margin_cents": e["projected_margin_cents"],
        "projected_margin_pct": num(e["projected_margin_pct"]),
        "extension_round_count": e["extension_round_count"],
        "cancellation_effective_date": e["cancellation_effective_date"],
        "cancellation_notice_days": e["cancellation_notice_days"],
        "cancellation_penalty_cents": e["cancellation_penalty_cents"],
    })
    return d


def ser_contract(e):
    d = _common(e)
    d.update({
        "assignment_id": e["assignment_id"],
        "status": e["status"],
        "term_weeks": e["term_weeks"],
        "weekly_guaranteed_hours": num(e["weekly_guaranteed_hours"]),
        "base_pay_rate_cents_per_hour": e["base_pay_rate_cents_per_hour"],
        "bill_rate_cents_per_hour": e["bill_rate_cents_per_hour"],
        "revision_count": e["revision_count"],
        "countersign_note": e["countersign_note"],
        "clinician_signed_at": e["clinician_signed_at"],
        "voided_reason": e["voided_reason"],
    })
    return d


def ser_packet(e):
    d = _common(e)
    d.update({
        "assignment_id": e["assignment_id"],
        "status": e["status"],
        "readiness_score_start_basis": e["readiness_score_start_basis"],
        "blocking_item_count_start_basis": e["blocking_item_count_start_basis"],
        "readiness_score_full_term_basis": e["readiness_score_full_term_basis"],
        "blocking_item_count_full_term_basis": e["blocking_item_count_full_term_basis"],
        "revision_round": e["revision_round"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "cleared_by_user_id": e["cleared_by_user_id"],
    })
    return d


def ser_item(e):
    d = _common(e)
    d.update({
        "packet_id": e["packet_id"],
        "item_type": e["item_type"],
        "document_ref": e["document_ref"],
        "expires_on": e["expires_on"],
        "status": e["status"],
        "verified_by_user_id": e["verified_by_user_id"],
    })
    return d


def ser_timesheet(e):
    d = _common(e)
    d.update({
        "assignment_id": e["assignment_id"],
        "week_start_date": e["week_start_date"],
        "daily_hours": [num(h) for h in e["daily_hours"]],
        "callback_hours": num(e["callback_hours"]),
        "status": e["status"],
        "total_raw_hours": num(e["total_raw_hours"]),
        "regular_hours": num(e["regular_hours"]),
        "overtime_hours": num(e["overtime_hours"]),
        "days_worked": e["days_worked"],
        "dispute_reason": e["dispute_reason"],
        "approved_by_user_id": e["approved_by_user_id"],
    })
    return d


def ser_statement(e):
    d = _common(e)
    d.update({
        "timesheet_id": e["timesheet_id"],
        "assignment_id": e["assignment_id"],
        "clinician_id": e["clinician_id"],
        "payroll_run_id": e["payroll_run_id"],
        "kind": e["kind"],
        "period_key_date": e["period_key_date"],
        "billable_hours": num(e["billable_hours"]),
        "stipend_variant": e["stipend_variant"],
        "taxable_wages_cents": e["taxable_wages_cents"],
        "non_taxable_stipend_cents": e["non_taxable_stipend_cents"],
        "burden_cents": e["burden_cents"],
        "total_pay_cost_cents": e["total_pay_cost_cents"],
        "contracted_bill_cents": e["contracted_bill_cents"],
        "gross_bill_cents": e["gross_bill_cents"],
        "margin_uplift_applied": e["margin_uplift_applied"],
        "gross_margin_cents": e["gross_margin_cents"],
        "margin_pct": num(e["margin_pct"]),
        "status": e["status"],
    })
    return d


def ser_payroll_run(e):
    d = _common(e)
    d.update({
        "period_start_date": e["period_start_date"],
        "period_end_date": e["period_end_date"],
        "status": e["status"],
        "statement_count": e["statement_count"],
        "total_pay_cost_cents": e["total_pay_cost_cents"],
        "total_gross_bill_cents": e["total_gross_bill_cents"],
        "total_margin_cents": e["total_margin_cents"],
        "opened_by_user_id": e["opened_by_user_id"],
        "posted_by_user_id": e["posted_by_user_id"],
    })
    return d


def ser_extension(e):
    d = _common(e)
    d.update({
        "assignment_id": e["assignment_id"],
        "status": e["status"],
        "proposed_additional_weeks": e["proposed_additional_weeks"],
        "proposed_pay_rate_cents_per_hour": e["proposed_pay_rate_cents_per_hour"],
        "proposed_bill_rate_cents_per_hour": e["proposed_bill_rate_cents_per_hour"],
        "round_count": e["round_count"],
        "initiated_by_role": e["initiated_by_role"],
        "last_actor_role": e["last_actor_role"],
        "resolved_at": e["resolved_at"],
    })
    return d
