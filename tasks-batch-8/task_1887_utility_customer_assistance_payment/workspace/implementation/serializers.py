"""Entity -> wire-dict serializers.

Timestamps: ISO 8601 UTC, three fractional digits (PRD §2.4). Date-valued
fields render as midnight UTC of the date. Payment carries no updated_at and
no version (PRD §2.5).
"""

from db import fmt_ts, fmt_date
from services.common import delinquency_tier


def _ts(dt):
    return fmt_ts(dt) if dt is not None else None


def _date(d):
    return fmt_date(d) if d is not None else None


def account(a):
    return {
        "id": a["id"],
        "service_address": a["service_address"],
        "service_class": a["service_class"],
        "heating_fuel_type": a["heating_fuel_type"],
        "deposit_held_cents": a["deposit_held_cents"],
        "arrearage_balance_cents": a["arrearage_balance_cents"],
        "current_charges_balance_cents": a["current_charges_balance_cents"],
        "credit_balance_cents": a["credit_balance_cents"],
        "arrearage_since": _date(a["arrearage_since"]),
        "reconnection_fee_due_cents": a["reconnection_fee_due_cents"],
        "reconnection_fee_base_cents": a["reconnection_fee_base_cents"],
        "reconnection_fee_surcharge_cents": a["reconnection_fee_surcharge_cents"],
        "reconnection_deposit_topup_cents": a["reconnection_deposit_topup_cents"],
        "reconnection_surcharge_applied": a["reconnection_surcharge_applied"],
        "service_status": a["service_status"],
        "protection_status": a["protection_status"],
        "delinquency_tier": delinquency_tier(a),
        "last_activity_at": _ts(a["last_activity_at"]),
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def application(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "household_size": x["household_size"],
        "gross_annual_income_cents": x["gross_annual_income_cents"],
        "current_month_income_cents": x["current_month_income_cents"],
        "income_source": x["income_source"],
        "status": x["status"],
        "submitted_by_user_id": x["submitted_by_user_id"],
        "reviewed_by_user_id": x["reviewed_by_user_id"],
        "docs_requested": x["docs_requested"],
        "documents_received": x["documents_received"],
        "provisional_benefit_tier": x["provisional_benefit_tier"],
        "benefit_tier": x["benefit_tier"],
        "income_measure_used": x["income_measure_used"],
        "denial_reason": x["denial_reason"],
        "decided_at": _ts(x["decided_at"]),
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def enrollment(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "application_id": x["application_id"],
        "tier": x["tier"],
        "discount_pct": x["discount_pct"],
        "status": x["status"],
        "activated_on": _date(x["activated_on"]),
        "recert_due_on": _date(x["recert_due_on"]),
        "lapsed_on": _date(x["lapsed_on"]),
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def dpa(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "status": x["status"],
        "covered_arrearage_cents": x["covered_arrearage_cents"],
        "down_payment_required_cents": x["down_payment_required_cents"],
        "down_payment_received_cents": x["down_payment_received_cents"],
        "installment_count": x["installment_count"],
        "installment_amount_cents": x["installment_amount_cents"],
        "final_installment_amount_cents": x["final_installment_amount_cents"],
        "forgiveness_pool_cents": x["forgiveness_pool_cents"],
        "forgiven_posted_cents": x["forgiven_posted_cents"],
        "projected_forgiveness_cents": x["projected_forgiveness_cents"],
        "paid_to_arrearage_cents": x["paid_to_arrearage_cents"],
        "remaining_balance_cents": x["remaining_balance_cents"],
        "installments_settled_count": x["installments_settled_count"],
        "on_time_payment_count": x["on_time_payment_count"],
        "missed_payment_count": x["missed_payment_count"],
        "activated_on": _date(x["activated_on"]),
        "first_installment_due_on": _date(x["first_installment_due_on"]),
        "defaulted_on": _date(x["defaulted_on"]),
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def payment(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "dpa_id": x["dpa_id"],
        "amount_cents": x["amount_cents"],
        "tender_type": x["tender_type"],
        "paid_at": _ts(x["paid_at"]),
        "applied_breakdown": x["applied_breakdown"],
        "installments_settled_count": x["installments_settled_count"],
        "on_time": x["on_time"],
        "credit_accrued_cents": x["credit_accrued_cents"],
        "created_at": _ts(x["created_at"]),
    }


def forgiveness_credit(x):
    return {
        "id": x["id"],
        "dpa_id": x["dpa_id"],
        "installment_number": x["installment_number"],
        "amount_cents": x["amount_cents"],
        "status": x["status"],
        "posted_at": _ts(x["posted_at"]),
        "reversed_at": _ts(x["reversed_at"]),
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def certificate(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "physician_name": x["physician_name"],
        "physician_license_number": x["physician_license_number"],
        "condition_class": x["condition_class"],
        "effective_from": _date(x["effective_from"]),
        "effective_to": _date(x["effective_to"]),
        "renewal_count": x["renewal_count"],
        "status": x["status"],
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def shutoff_order(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "reason": x["reason"],
        "scheduled_date": _date(x["scheduled_date"]),
        "status": x["status"],
        "origin": x["origin"],
        "blocked_reason": x["blocked_reason"],
        "executed_at": _ts(x["executed_at"]),
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def funding_source(x):
    return {
        "id": x["id"],
        "name": x["name"],
        "funder_type": x["funder_type"],
        "fiscal_year": x["fiscal_year"],
        "appropriated_cents": x["appropriated_cents"],
        "priority_rank": x["priority_rank"],
        "eligible_tiers": x["eligible_tiers"],
        "requires_completed_referral": x["requires_completed_referral"],
        "status": x["status"],
        "pledged_cents": x["pledged_cents"],
        "disbursed_cents": x["disbursed_cents"],
        "released_cents": x["released_cents"],
        "available_cents": x["available_cents"],
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def fund_allocation(x):
    return {
        "id": x["id"],
        "funding_source_id": x["funding_source_id"],
        "account_id": x["account_id"],
        "enrollment_id": x["enrollment_id"],
        "amount_cents": x["amount_cents"],
        "status": x["status"],
        "batch_id": x["batch_id"],
        "allocation_sequence": x["allocation_sequence"],
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def referral(x):
    return {
        "id": x["id"],
        "account_id": x["account_id"],
        "agency_code": x["agency_code"],
        "status": x["status"],
        "initiated_on": _date(x["initiated_on"]),
        "completed_on": _date(x["completed_on"]),
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }
