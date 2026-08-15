"""Entity serializers — exact field sets per SCAFFOLD entity table."""

from util import public


def _base(rec):
    d = public(rec)
    return d


def loan_out(r):
    keys = ("id", "loan_number", "borrower_name", "principal_balance_cents",
            "monthly_pi_cents", "escrow_required", "closing_date", "status",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def account_out(r):
    keys = ("id", "loan_id", "account_status", "hold_status", "balance_cents",
            "target_cushion_cents", "monthly_escrow_cents", "next_analysis_due_date",
            "last_analysis_year", "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def ledger_out(r):
    keys = ("id", "escrow_account_id", "entry_type", "amount_cents", "effective_date",
            "running_balance_cents", "source_entity_type", "source_entity_id", "note",
            "created_at")
    return {k: r[k] for k in keys}


def line_item_out(r):
    keys = ("id", "escrow_account_id", "payee_id", "expense_type",
            "expected_annual_amount_cents", "installments_per_year", "first_due_date",
            "status", "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def payee_out(r):
    keys = ("id", "payee_type", "legal_name", "remit_to_address", "ach_routing_mask",
            "created_by_user_id", "verification_status", "verified_by_user_id",
            "verified_at", "verification_expires_at", "created_at", "updated_at",
            "version")
    return {k: r[k] for k in keys}


def disbursement_out(r):
    keys = ("id", "escrow_account_id", "line_item_id", "payee_id", "amount_cents",
            "due_date", "scheduled_release_date", "status", "scheduled_by_user_id",
            "released_by_user_id", "released_at", "cleared_at", "returned_at",
            "late_release", "ledger_entry_id", "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def policy_out(r):
    keys = ("id", "loan_id", "policy_type", "carrier_name", "policy_number",
            "coverage_start_date", "coverage_end_date", "annual_premium_cents",
            "status", "notice_1_sent_at", "notice_2_sent_at", "force_placed_at",
            "fp_premium_cents", "fp_coverage_end", "day_count_convention",
            "fp_refund_cents", "refund_processed_at", "refund_timeliness",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def tax_record_out(r):
    keys = ("id", "loan_id", "parcel_number", "tax_year", "installment_sequence",
            "amount_due_cents", "due_date", "grace_period_days",
            "monthly_penalty_rate_bps", "penalty_method", "status", "delinquent_since",
            "accrued_penalty_cents", "paid_via_disbursement_id",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def analysis_out(r):
    keys = ("id", "escrow_account_id", "analysis_year", "projection_start_date",
            "method", "status", "window_end_date", "computed_at", "statement_issued_at",
            "statement_due_date", "statement_timeliness", "start_balance_cents",
            "projected_annual_disbursements_cents", "cushion_target_cents",
            "lowest_projected_balance_cents", "shortage_cents", "deficiency_cents",
            "surplus_cents", "base_monthly_escrow_cents", "spread_monthly_cents",
            "spread_first_month_cents", "new_monthly_escrow_cents",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def notice_out(r):
    keys = ("id", "analysis_id", "notice_type", "old_monthly_escrow_cents",
            "new_monthly_escrow_cents", "shortage_option", "effective_date",
            "send_by_date", "sent_at", "timeliness", "status",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def advance_out(r):
    keys = ("id", "escrow_account_id", "disbursement_id", "reason", "amount_cents",
            "recovered_cents", "written_off_cents", "outstanding_cents", "status",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}


def error_case_out(r):
    keys = ("id", "loan_id", "error_type", "description", "asserted_amount_cents",
            "status", "received_at", "acknowledged_at", "ack_deadline",
            "ack_timeliness", "assigned_to_user_id", "resolution_deadline",
            "resolved_at", "resolution_timeliness", "resolved_by_user_id", "outcome",
            "correction_amount_cents", "resolution_note",
            "created_at", "updated_at", "version")
    return {k: r[k] for k in keys}
