"""Entity -> JSON serialization (PRD 2.5 common fields + per-entity fields).

Caller-supplied instants are echoed verbatim; server-generated instants are
rendered with three fractional digits (see clock.py).
"""

import clock as clockmod
import services
from store import db


def _common(row):
    return {
        "id": row["id"],
        "created_at": clockmod.render_instant(row["created_at"]),
        "updated_at": clockmod.render_instant(row["updated_at"]),
        "version": row["version"],
    }


def program(row):
    data = _common(row)
    data.update({
        "name": row["name"],
        "program_status": row["program_status"],
        "aggregate_cap_watts": row["aggregate_cap_watts"],
        "metering_variant": row["metering_variant"],
        "true_up_mode": row["true_up_mode"],
        "true_up_month": row["true_up_month"],
        "screening_basis": row["screening_basis"],
        "bank_cap_wh": row["bank_cap_wh"],
        "interconnected_watts": row["interconnected_watts"],
        "reserved_watts": row["reserved_watts"],
        "available_capacity_watts": services.program_available(row),
        "queued_count": row["queued_count"],
    })
    return data


def tariff(row):
    data = _common(row)
    data.update({
        "program_id": row["program_id"],
        "schedule_code": row["schedule_code"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "import_rate_millicents_per_kwh": row["import_rate_millicents_per_kwh"],
        "export_rate_millicents_per_kwh": row["export_rate_millicents_per_kwh"],
        "net_surplus_rate_millicents_per_kwh": row["net_surplus_rate_millicents_per_kwh"],
    })
    return data


def feeder(row):
    data = _common(row)
    data.update({
        "feeder_code": row["feeder_code"],
        "peak_load_watts": row["peak_load_watts"],
        "pre_existing_der_watts": row["pre_existing_der_watts"],
        "aggregate_der_watts": services.node_aggregate_der("feeder", row),
    })
    return data


def transformer(row):
    data = _common(row)
    data.update({
        "feeder_id": row["feeder_id"],
        "transformer_code": row["transformer_code"],
        "nameplate_watts": row["nameplate_watts"],
        "pre_existing_der_watts": row["pre_existing_der_watts"],
        "aggregate_der_watts": services.node_aggregate_der("transformer", row),
    })
    return data


def customer(row):
    data = _common(row)
    data.update({
        "full_name": row["full_name"],
        "email": row["email"],
    })
    return data


def service_account(row):
    credit_balance_cents, banked_wh = services.account_balances(row["id"])
    data = _common(row)
    data.update({
        "customer_id": row["customer_id"],
        "transformer_id": row["transformer_id"],
        "account_number": row["account_number"],
        "service_class": row["service_class"],
        "prior_annual_usage_wh": row["prior_annual_usage_wh"],
        "account_status": row["account_status"],
        "metering_status": row["metering_status"],
        "meter_serial": row["meter_serial"],
        "credit_balance_cents": credit_balance_cents,
        "banked_wh": banked_wh,
    })
    return data


def application(row):
    data = _common(row)
    data.update({
        "program_id": row["program_id"],
        "service_account_id": row["service_account_id"],
        "technology": row["technology"],
        "system_size_watts_ac": row["system_size_watts_ac"],
        "estimated_annual_production_wh": row["estimated_annual_production_wh"],
        "application_status": row["application_status"],
        "denial_reason": row["denial_reason"],
        "withdrawal_reason": row["withdrawal_reason"],
        "queue_position": row["queue_position"],
        "capacity_reserved_watts": row["capacity_reserved_watts"],
        "reservation_expires_at": clockmod.render_instant(row["reservation_expires_at"]),
        "submission_round": row["submission_round"],
        "submitted_at": clockmod.render_instant(row["submitted_at"]),
        "pto_granted_at": clockmod.render_instant(row["pto_granted_at"]),
    })
    return data


def document(row):
    data = _common(row)
    data.update({
        "application_id": row["application_id"],
        "doc_type": row["doc_type"],
        "title": row["title"],
        "review_status": row["review_status"],
        "review_note": row["review_note"],
    })
    return data


def screening_report(row):
    data = _common(row)
    data.update({
        "application_id": row["application_id"],
        "screening_round": row["screening_round"],
        "report_status": row["report_status"],
        "aggregate_basis": row["aggregate_basis"],
        "transformer_aggregate_after_watts": row["transformer_aggregate_after_watts"],
        "transformer_limit_watts": row["transformer_limit_watts"],
        "transformer_screen_passed": row["transformer_screen_passed"],
        "feeder_aggregate_after_watts": row["feeder_aggregate_after_watts"],
        "feeder_limit_watts": row["feeder_limit_watts"],
        "feeder_screen_passed": row["feeder_screen_passed"],
        "size_within_fast_track": row["size_within_fast_track"],
        "outcome": row["outcome"],
        "failing_screens": list(row["failing_screens"]),
    })
    return data


def supplemental_review(row):
    data = _common(row)
    data.update({
        "application_id": row["application_id"],
        "review_type": row["review_type"],
        "review_status": row["review_status"],
        "outcome": row["outcome"],
        "findings": row["findings"],
    })
    return data


def cost_estimate(row):
    data = _common(row)
    data.update({
        "application_id": row["application_id"],
        "supplemental_review_id": row["supplemental_review_id"],
        "items": row["items"],
        "contingency_pct": row["contingency_pct"],
        "total_cents": row["total_cents"],
        "estimate_status": row["estimate_status"],
        "valid_until": clockmod.render_instant(row["valid_until"]),
        "decided_at": clockmod.render_instant(row["decided_at"]),
    })
    return data


def inspection(row):
    data = _common(row)
    data.update({
        "application_id": row["application_id"],
        "scheduled_date": row["scheduled_date"],
        "inspection_status": row["inspection_status"],
        "outcome": row["outcome"],
        "occurred_at": row["occurred_at"],
        "defects": row["defects"],
        "inspector_user_id": row["inspector_user_id"],
    })
    return data


def meter_exchange(row):
    data = _common(row)
    data.update({
        "application_id": row["application_id"],
        "crew_id": row["crew_id"],
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "exchange_status": row["exchange_status"],
        "installed_meter_serial": row["installed_meter_serial"],
        "technician_user_id": row["technician_user_id"],
        "fail_reason": row["fail_reason"],
    })
    return data


def meter_reading(row):
    data = _common(row)
    data.update({
        "service_account_id": row["service_account_id"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "import_wh": row["import_wh"],
        "export_wh": row["export_wh"],
        "reading_status": row["reading_status"],
        "tariff_id": row["tariff_id"],
        "bill_cents": row["bill_cents"],
        "credit_applied_cents": row["credit_applied_cents"],
        "bank_drawn_wh": row["bank_drawn_wh"],
        "bank_deposited_wh": row["bank_deposited_wh"],
    })
    return data


def ledger_entry(row):
    return {
        "id": row["id"],
        "created_at": clockmod.render_instant(row["created_at"]),
        "service_account_id": row["service_account_id"],
        "meter_reading_id": row["meter_reading_id"],
        "annual_reconciliation_id": row["annual_reconciliation_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "quantity_wh": row["quantity_wh"],
        "posted_at": clockmod.render_instant(row["posted_at"]),
    }


def annual_reconciliation(row):
    data = _common(row)
    data.update({
        "service_account_id": row["service_account_id"],
        "reconciliation_year": row["reconciliation_year"],
        "reconciliation_status": row["reconciliation_status"],
        "window_start": clockmod.render_instant(row["window_start"]),
        "window_end": clockmod.render_instant(row["window_end"]),
        "surplus_wh": row["surplus_wh"],
        "credit_balance_at_compute_cents": row["credit_balance_at_compute_cents"],
        "nsc_cents": row["nsc_cents"],
        "payout_cents": row["payout_cents"],
        "forfeited_cents": row["forfeited_cents"],
        "forfeited_wh": row["forfeited_wh"],
        "tariff_id": row["tariff_id"],
    })
    return data
