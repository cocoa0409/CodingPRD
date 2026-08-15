"""Response projections: only declared fields (plus common fields) are exposed.

Internal bookkeeping fields are prefixed with "_" in the store and never leak.
Caller-supplied timestamps are echoed verbatim; server-written timestamps are
rendered by the logical clock with three fractional digits (db.render_server).
"""

from __future__ import annotations

COMMON = ("id", "created_at", "updated_at", "version")

CLAIM = COMMON + (
    "policy_number", "state_code", "adjuster_id", "claimed_amount_cents",
    "status", "payment_hold_reason", "paid_amount_cents",
)

ADJUSTER = COMMON + ("full_name", "email", "state_licenses", "active")

REFERRAL = COMMON + (
    "claim_id", "submitted_by_role", "red_flag_codes", "narrative",
    "suspicion_score", "score_band", "status", "decline_reason",
    "duplicate_of_referral_id",
)

CASE = COMMON + (
    "claim_id", "opened_by_referral_id", "case_number", "status", "priority",
    "suspicion_score", "investigation_deadline_at", "decision_due_at",
    "assigned_investigator_id", "substantiated_fraud_cents", "euo_required",
    "bureau_referral_required", "closed_reason",
)

INVESTIGATOR = COMMON + (
    "full_name", "email", "badge_number", "state_certifications",
    "max_active_cases", "active_case_count", "status", "training_current_through",
)

ASSIGNMENT = COMMON + (
    "case_id", "investigator_id", "assigned_by_user_id", "status",
    "assigned_at", "completed_at",
)

EVIDENCE = COMMON + (
    "case_id", "submitted_by_investigator_id", "evidence_type", "collected_at",
    "custodian", "materiality", "fraud_amount_cents", "status", "sealed_at",
)

EUO_SESSION = COMMON + (
    "case_id", "scheduled_start_at", "scheduled_end_at", "location",
    "insured_attendee_name", "status", "notice_sent_at", "conducted_at",
    "transcript_received", "no_show_count",
)

BUREAU_REFERRAL = COMMON + (
    "case_id", "state_code", "filed_at", "deadline_at", "status",
    "ack_received_at", "late_filing",
)

PROVIDER_PATTERN = COMMON + (
    "provider_npi", "provider_name", "ring_signature", "linked_case_ids",
    "pattern_score", "escalation_status", "parent_pattern_id",
)

LEDGER = COMMON + (
    "case_id", "target_amount_cents", "recovered_amount_cents",
    "outstanding_amount_cents", "status",
)

PAYMENT = COMMON + (
    "ledger_id", "amount_cents", "received_at", "method", "status", "reversed_at",
)

TRAINING_RECORD = COMMON + (
    "investigator_id", "course_code", "completed_at", "valid_until", "credit_hours",
)

REPORT = COMMON + (
    "period_start_at", "period_end_at", "state_code", "report_type",
    "total_cases_opened", "total_cases_closed_substantiated",
    "total_restitution_recovered_cents", "late_bureau_filings", "status",
)


def _pub(row: dict, fields) -> dict:
    return {name: row.get(name) for name in fields}


def pub_claim(row):
    return _pub(row, CLAIM)


def pub_adjuster(row):
    return _pub(row, ADJUSTER)


def pub_referral(row):
    return _pub(row, REFERRAL)


def pub_case(row):
    return _pub(row, CASE)


def pub_investigator(row):
    return _pub(row, INVESTIGATOR)


def pub_assignment(row):
    return _pub(row, ASSIGNMENT)


def pub_evidence(row):
    return _pub(row, EVIDENCE)


def pub_euo(row):
    return _pub(row, EUO_SESSION)


def pub_bureau(row):
    return _pub(row, BUREAU_REFERRAL)


def pub_pattern(row):
    return _pub(row, PROVIDER_PATTERN)


def pub_ledger(row):
    return _pub(row, LEDGER)


def pub_payment(row):
    return _pub(row, PAYMENT)


def pub_training(row):
    return _pub(row, TRAINING_RECORD)


def pub_report(row):
    return _pub(row, REPORT)
