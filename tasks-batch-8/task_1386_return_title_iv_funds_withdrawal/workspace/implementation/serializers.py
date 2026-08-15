"""Serialize internal entity dicts to public JSON-safe payloads.

Internal records carry a `_seq` tiebreaker key that must never leak, and
ledger entries / breaks deliberately omit `updated_at`/`version` (PRD §2.4).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, fields):
    return {k: record.get(k) for k in fields}


def term(t):
    return _pick(t, _COMMON + [
        "name", "start_date", "end_date", "attendance_taking_required",
        "refund_method", "refund_schedule",
        "calendar_days", "deductible_break_days", "total_days",
    ])


def scheduled_break(b):
    # Breaks carry only id + created_at (no updated_at/version).
    return _pick(b, ["id", "created_at", "term_id", "start_date", "end_date",
                     "length_days", "deductible_days"])


def student(s):
    return _pick(s, _COMMON + ["external_ref", "full_name", "email"])


def enrollment(e):
    return _pick(e, _COMMON + [
        "student_id", "term_id", "institutional_charges_cents", "status",
        "balance_cents", "balance_notification_sent", "balance_notified_at",
        "current_withdrawal_case_id",
    ])


def award(a):
    return _pick(a, _COMMON + [
        "enrollment_id", "program", "amount_cents", "is_grant", "status",
        "disbursed_amount_cents", "scheduled_amount_cents",
    ])


def disbursement(d):
    return _pick(d, _COMMON + [
        "award_id", "pwd_offer_id", "amount_cents", "status", "disbursed_on",
    ])


def withdrawal_case(c):
    return _pick(c, _COMMON + [
        "enrollment_id", "withdrawal_type", "notification_date",
        "last_attendance_date", "withdrawal_date", "determination_date",
        "total_days", "completed_days", "percentage_completed", "earned_pct",
        "aid_disbursable_cents", "aid_disbursed_cents", "aid_earned_cents",
        "aid_unearned_cents", "return_amount_cents", "school_return_cents",
        "student_grant_return_cents", "student_loan_deferred_cents",
        "pwd_grant_cents", "pwd_loan_cents", "status",
        "calculated_by_user_id", "calculated_at",
    ])


def obligation(o):
    return _pick(o, _COMMON + [
        "withdrawal_case_id", "party", "amount_cents", "due_date", "status",
        "returned_at", "returned_amount_cents", "recorded_by_user_id",
    ])


def offer(o):
    return _pick(o, _COMMON + [
        "withdrawal_case_id", "award_id", "amount_cents", "offered_at",
        "response_deadline", "late_offer", "status", "responded_at",
    ])


def account_entry(e):
    # Ledger entries carry only id + created_at (no updated_at/version).
    return _pick(e, ["id", "created_at", "enrollment_id", "entry_type",
                     "amount_cents", "reversal_of_entry_id", "source_ref",
                     "posted_at"])
