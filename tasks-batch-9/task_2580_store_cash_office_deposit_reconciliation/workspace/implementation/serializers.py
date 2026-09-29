"""Resource projections. Derived fields are computed from the records that support them."""
import calc
import clock
import domain


def _common(record):
    return {
        "id": record["id"],
        "created_at": clock.fmt(record["created_at"]),
        "updated_at": clock.fmt(record.get("updated_at")),
        "version": record.get("version"),
    }


def store(record):
    data = {
        "store_code": record["store_code"],
        "name": record["name"],
        "region_code": record["region_code"],
        "safe_time_delay_minutes": record["safe_time_delay_minutes"],
        "safe_open_window_minutes": record["safe_open_window_minutes"],
        "dual_control_required": record["dual_control_required"],
        "pickup_buffer_minutes": record["pickup_buffer_minutes"],
        "max_daily_pickups": record["max_daily_pickups"],
        "single_event_variance_threshold_cents": record["single_event_variance_threshold_cents"],
        "rolling_variance_threshold_cents": record["rolling_variance_threshold_cents"],
        "rolling_window_days": record["rolling_window_days"],
        "theft_escalation_threshold_cents": record["theft_escalation_threshold_cents"],
        "provisional_credit_cap_cents": record["provisional_credit_cap_cents"],
        "seasonal_profile": record["seasonal_profile"],
    }
    data.update(_common(record))
    return data


def cashier(record):
    data = {
        "store_id": record["store_id"],
        "employee_code": record["employee_code"],
        "display_name": record["display_name"],
        "till_eligibility": record["till_eligibility"],
        "coaching_state": record["coaching_state"],
        "coaching_due_at": clock.fmt(record["coaching_due_at"]),
        "rolling_absolute_variance_cents": record["rolling_absolute_variance_cents"],
        "rolling_net_variance_cents": record["rolling_net_variance_cents"],
        "reconciled_session_count": record["reconciled_session_count"],
        "open_case_count": domain.cashier_open_case_count(record["id"]),
    }
    data.update(_common(record))
    return data


def safe(record):
    data = {
        "store_id": record["store_id"],
        "safe_code": record["safe_code"],
        "safe_type": record["safe_type"],
        "open_state": record["open_state"],
        "posture": record["posture"],
        "open_requested_at": clock.fmt(record["open_requested_at"]),
        "open_requested_by_user_id": record["open_requested_by_user_id"],
        "unlocked_at": clock.fmt(record["unlocked_at"]),
        "balance_cents": domain.safe_balance(record["id"]),
        "provisional_credit_balance_cents": domain.safe_provisional_credit_balance(record["id"]),
        "suspect_note_cents": domain.safe_suspect_note_cents(record["id"]),
    }
    data.update(_common(record))
    return data


def sales_journal(record):
    journal_id = record["id"]
    data = {
        "store_id": record["store_id"],
        "business_date": record["business_date"],
        "status": record["status"],
        "journal_cash_sales_cents": record["journal_cash_sales_cents"],
        "journal_card_sales_cents": record["journal_card_sales_cents"],
        "session_count": domain.journal_session_count(journal_id),
        "reconciled_session_count": len(domain.journal_reconciled_sessions(journal_id)),
        "settlement_count": len(domain.journal_settlements(journal_id)),
        "register_cash_tieout_cents": domain.journal_register_cash_tieout_cents(record),
        "settlement_variance_total_cents": domain.journal_settlement_variance_total_cents(journal_id),
        "open_case_count": domain.journal_open_case_count(journal_id),
        "net_unexplained_cents": domain.journal_net_unexplained_cents(journal_id),
    }
    data.update(_common(record))
    return data


def till_session(record):
    masked = record["status"] in ("PENDING_COUNT", "COUNTED")
    data = {
        "sales_journal_id": record["sales_journal_id"],
        "cashier_id": record["cashier_id"],
        "safe_id": record["safe_id"],
        "register_number": record["register_number"],
        "shift_start_at": clock.fmt(record["shift_start_at"]),
        "shift_end_at": clock.fmt(record["shift_end_at"]),
        "status": record["status"],
        "starting_bank_cents": record["starting_bank_cents"],
        "pos_cash_sales_cents": record["pos_cash_sales_cents"],
        "pos_card_sales_cents": record["pos_card_sales_cents"],
        "pos_paid_out_cents": record["pos_paid_out_cents"],
        "dropped_declared_cents": domain.dropped_declared_cents(record["id"]),
        "dropped_verified_cents": domain.dropped_verified_cents(record["id"]),
        "counted_lines": record["counted_lines"],
        "counted_cash_cents": record["counted_cash_cents"],
        "expected_cash_cents": None if masked else record["expected_cash_cents"],
        "variance_cents": None if masked else record["variance_cents"],
        "variance_basis": record["variance_basis"],
        "recount_count": record["recount_count"],
        "counted_by_user_id": record["counted_by_user_id"],
        "forced_close": record["forced_close"],
    }
    data.update(_common(record))
    return data


def close_projection(record):
    return {
        "id": record["id"],
        "status": record["status"],
        "register_number": record["register_number"],
        "shift_end_at": clock.fmt(record["shift_end_at"]),
        "dropped_declared_cents": domain.dropped_declared_cents(record["id"]),
        "version": record["version"],
    }


def blind_count_projection(record):
    return {
        "id": record["id"],
        "status": record["status"],
        "counted_cash_cents": record["counted_cash_cents"],
        "recount_count": record["recount_count"],
        "version": record["version"],
    }


def safe_transaction(record):
    return {
        "id": record["id"],
        "safe_id": record["safe_id"],
        "till_session_id": record["till_session_id"],
        "deposit_id": record["deposit_id"],
        "change_order_id": record["change_order_id"],
        "txn_type": record["txn_type"],
        "declared_amount_cents": record["declared_amount_cents"],
        "verified_amount_cents": record["verified_amount_cents"],
        "effective_amount_cents": calc.effective_amount(record),
        "actor_user_id": record["actor_user_id"],
        "occurred_at": clock.fmt(record["occurred_at"]),
        "memo": record["memo"],
        "created_at": clock.fmt(record["created_at"]),
    }


def deposit(record):
    data = {
        "safe_id": record["safe_id"],
        "sales_journal_id": record["sales_journal_id"],
        "deposit_type": record["deposit_type"],
        "status": record["status"],
        "business_date": record["business_date"],
        "counted_lines": record["counted_lines"],
        "declared_total_cents": record["declared_total_cents"],
        "suspect_note_cents": record["suspect_note_cents"],
        "credit_basis": record["credit_basis"],
        "provisional_credit_cents": record["provisional_credit_cents"],
        "carrier_fee_cents": record["carrier_fee_cents"],
        "expected_credit_cents": record["expected_credit_cents"],
        "credited_total_cents": record["credited_total_cents"],
        "credit_variance_cents": record["credit_variance_cents"],
        "pickup_window_start": clock.fmt(record["pickup_window_start"]),
        "pickup_window_end": clock.fmt(record["pickup_window_end"]),
        "prepared_by_user_id": record["prepared_by_user_id"],
        "sealed_by_user_id": record["sealed_by_user_id"],
        "seal_number": record["seal_number"],
        "carrier_reference": record["carrier_reference"],
    }
    data.update(_common(record))
    return data


def bank_credit_record(record):
    data = {
        "store_id": record["store_id"],
        "deposit_id": record["deposit_id"],
        "credit_type": record["credit_type"],
        "amount_cents": record["amount_cents"],
        "value_date": record["value_date"],
        "bank_reference": record["bank_reference"],
        "match_state": record["match_state"],
    }
    data.update(_common(record))
    return data


def card_settlement(record):
    data = {
        "sales_journal_id": record["sales_journal_id"],
        "card_network": record["card_network"],
        "gross_card_sales_cents": record["gross_card_sales_cents"],
        "txn_count": record["txn_count"],
        "chargeback_cents": record["chargeback_cents"],
        "monthly_volume_cents": record["monthly_volume_cents"],
        "funded_amount_cents": record["funded_amount_cents"],
        "expected_fee_cents": record["expected_fee_cents"],
        "expected_funded_cents": record["expected_funded_cents"],
        "settlement_variance_cents": record["settlement_variance_cents"],
        "settlement_status": record["settlement_status"],
    }
    data.update(_common(record))
    return data


def variance_case(record):
    attributions = [
        {
            "bucket": entry["bucket"],
            "amount_cents": entry["amount_cents"],
            "note": entry["note"],
            "recorded_at": clock.fmt(entry["recorded_at"]),
        }
        for entry in record["attributions"]
    ]
    data = {
        "sales_journal_id": record["sales_journal_id"],
        "cashier_id": record["cashier_id"],
        "deposit_id": record["deposit_id"],
        "case_type": record["case_type"],
        "status": record["status"],
        "total_variance_cents": record["total_variance_cents"],
        "attributions": attributions,
        "attributed_register_cents": domain.bucket_total(record, "REGISTER"),
        "attributed_safe_cents": domain.bucket_total(record, "SAFE"),
        "attributed_bank_cents": domain.bucket_total(record, "BANK"),
        "unexplained_cents": domain.unexplained_cents(record),
        "suspected_theft": record["suspected_theft"],
        "escalated_by_user_id": record["escalated_by_user_id"],
        "disposition": record["disposition"],
        "closing_note": record["closing_note"],
    }
    data.update(_common(record))
    return data


def change_order(record):
    data = {
        "store_id": record["store_id"],
        "target_week_start": record["target_week_start"],
        "days_covered": record["days_covered"],
        "baseline_daily_cash_demand_cents": record["baseline_daily_cash_demand_cents"],
        "growth_pct": record["growth_pct"],
        "seasonal_profile_override": record["seasonal_profile_override"],
        "applied_seasonal_profile": record["applied_seasonal_profile"],
        "forecast_demand_cents": record["forecast_demand_cents"],
        "planned_lines": record["planned_lines"],
        "total_planned_cents": record["total_planned_cents"],
        "status": record["status"],
        "approved_by_user_id": record["approved_by_user_id"],
        "received_amount_cents": record["received_amount_cents"],
    }
    data.update(_common(record))
    return data
