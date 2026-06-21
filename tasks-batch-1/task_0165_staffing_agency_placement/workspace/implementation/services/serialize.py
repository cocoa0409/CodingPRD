"""Serializers — produce the public JSON shape for each entity.

We store records as plain dicts that already hold every public field, so the
serializers mostly copy. Centralizing them keeps the field set explicit and
lets read endpoints recompute live derived fields where the PRD says reads are
"live" (Client exposure/balance, JobOrder.filled_count).
"""

import db
from services import recompute


def client(rec):
    return {
        "id": rec["id"],
        "name": rec["name"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "conversion_fee_pct": rec["conversion_fee_pct"],
        "status": rec["status"],
        "outstanding_balance_cents": rec["outstanding_balance_cents"],
        "open_exposure_cents": rec["open_exposure_cents"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def skill(rec):
    return {
        "id": rec["id"],
        "code": rec["code"],
        "category": rec["category"],
        "created_at": rec["created_at"],
    }


def candidate(rec):
    return {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "skill_codes": list(rec["skill_codes"]),
        "base_pay_rate_cents": rec["base_pay_rate_cents"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def job_order(rec):
    return {
        "id": rec["id"],
        "client_id": rec["client_id"],
        "title": rec["title"],
        "employment_type": rec["employment_type"],
        "required_skill_code": rec["required_skill_code"],
        "openings": rec["openings"],
        "bill_rate_cents": rec["bill_rate_cents"],
        "target_pay_rate_cents": rec["target_pay_rate_cents"],
        "annual_salary_cents": rec["annual_salary_cents"],
        "filled_count": rec["filled_count"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def submission(rec):
    return {
        "id": rec["id"],
        "job_order_id": rec["job_order_id"],
        "candidate_id": rec["candidate_id"],
        "submitted_pay_rate_cents": rec["submitted_pay_rate_cents"],
        "status": rec["status"],
        "rejection_reason": rec.get("rejection_reason"),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def interview(rec):
    return {
        "id": rec["id"],
        "submission_id": rec["submission_id"],
        "scheduled_start": rec["scheduled_start"],
        "scheduled_end": rec["scheduled_end"],
        "outcome": rec["outcome"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def placement(rec):
    return {
        "id": rec["id"],
        "submission_id": rec["submission_id"],
        "job_order_id": rec["job_order_id"],
        "candidate_id": rec["candidate_id"],
        "predecessor_placement_id": rec.get("predecessor_placement_id"),
        "placement_type": rec["placement_type"],
        "bill_rate_cents": rec["bill_rate_cents"],
        "pay_rate_cents": rec["pay_rate_cents"],
        "standard_weekly_hours": rec["standard_weekly_hours"],
        "start_date": rec["start_date"],
        "end_date": rec["end_date"],
        "projected_weekly_bill_cents": rec["projected_weekly_bill_cents"],
        "projected_weekly_margin_cents": rec["projected_weekly_margin_cents"],
        "actual_margin_cents": rec["actual_margin_cents"],
        "assignment_status": rec["assignment_status"],
        "conversion_status": rec["conversion_status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def timesheet(rec):
    return {
        "id": rec["id"],
        "placement_id": rec["placement_id"],
        "week_start": rec["week_start"],
        "week_end": rec["week_end"],
        "hours": rec["hours"],
        "pay_cents": rec["pay_cents"],
        "bill_cents": rec["bill_cents"],
        "margin_cents": rec["margin_cents"],
        "status": rec["status"],
        "invoice_id": rec.get("invoice_id"),
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def invoice(rec):
    return {
        "id": rec["id"],
        "client_id": rec["client_id"],
        "subtotal_cents": rec["subtotal_cents"],
        "volume_discount_cents": rec["volume_discount_cents"],
        "processing_fee_cents": rec["processing_fee_cents"],
        "total_cents": rec["total_cents"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def invoice_line_item(rec):
    return {
        "id": rec["id"],
        "invoice_id": rec["invoice_id"],
        "timesheet_id": rec["timesheet_id"],
        "line_total_cents": rec["line_total_cents"],
        "created_at": rec["created_at"],
    }


def conversion_fee(rec):
    return {
        "id": rec["id"],
        "placement_id": rec["placement_id"],
        "client_id": rec["client_id"],
        "annual_salary_cents": rec["annual_salary_cents"],
        "fee_cents": rec["fee_cents"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }
