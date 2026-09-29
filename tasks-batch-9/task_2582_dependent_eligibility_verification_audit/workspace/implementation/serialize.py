"""Field-whitelisted resource serializers (section 2.4 field inventories)."""

import clock

_PROGRAM_FIELDS = (
    "program_name",
    "plan_year",
    "scope_type",
    "status",
    "amnesty_days",
    "response_days",
    "reminder_min_gap_days",
    "max_reminders",
    "poe_verification_enabled",
    "announcement_at",
    "amnesty_end_at",
    "response_deadline_at",
    "sweep_epoch",
    "in_scope_case_count",
    "in_scope_dependent_count",
    "pending_dependent_count",
    "verified_dependent_count",
    "amnesty_removed_count",
    "termination_pending_count",
    "terminated_dependent_count",
    "responded_case_count",
    "non_responsive_case_count",
    "provisional_annual_savings_cents",
    "audited_annual_savings_cents",
    "last_savings_variant",
    "recovery_ledger_cents",
    "recovered_total_cents",
    "refund_due_total_cents",
)

_EMPLOYEE_FIELDS = (
    "full_name",
    "work_email",
    "coverage_tier",
    "employer_monthly_premium_cents",
    "hire_date",
    "enrolled_dependent_count",
)

_DEPENDENT_FIELDS = (
    "employee_id",
    "relationship_type",
    "full_name",
    "date_of_birth",
    "enrolled_at",
    "coverage_status",
    "coverage_end_date",
    "poe_program_id",
    "poe_deadline_at",
    "monthly_cost_cents",
    "accepted_proof_type_count",
    "documentation_complete",
    "recovery_revision",
    "paid_claims_total_cents",
    "reinstated_at",
)

_RULE_FIELDS = (
    "program_id",
    "relationship_type",
    "phase",
    "acceptable_proof_types",
    "min_accepted_documents",
    "affidavit_allowed",
    "requires_recency_days",
    "grace_days",
    "auto_terminate_on_lapse",
)

_CASE_FIELDS = (
    "program_id",
    "employee_id",
    "status",
    "in_scope_dependent_ids",
    "in_scope_dependent_count",
    "unverified_dependent_count",
    "proof_submission_count",
    "reminders_sent_count",
    "priority_score",
    "notified_at",
    "last_reminder_at",
    "communication_sequence_no",
    "non_responsive_at",
    "escalated_at",
    "completed_at",
)

_SUBMISSION_FIELDS = (
    "case_id",
    "dependent_id",
    "proof_type",
    "document_reference",
    "document_date",
    "redaction_applied",
    "review_status",
    "privacy_status",
    "privacy_class",
    "reviewed_by_user_id",
    "decision_reason_code",
    "decided_at",
    "redacted_document_reference",
)

_REMOVAL_FIELDS = (
    "dependent_id",
    "case_id",
    "reason_code",
    "attestation_signed",
    "recorded_at",
    "coverage_end_date",
    "penalty_waived",
    "claims_recovery_waived",
    "audited_savings_contribution_cents",
)

_APPEAL_FIELDS = (
    "case_id",
    "dependent_id",
    "grounds",
    "statement",
    "affidavit_reference",
    "custody_order_reference",
    "status",
    "round_number",
    "reviewer_user_id",
    "assigned_at",
    "decided_at",
    "decision_rationale",
    "remand_reason",
)

_NOTICE_FIELDS = (
    "dependent_id",
    "case_id",
    "origin",
    "status",
    "issued_at",
    "effective_date",
    "batch_sequence_no",
    "grace_days_applied",
    "continuation_election_status",
    "continuation_election_deadline",
    "continuation_start_date",
    "continuation_end_date",
    "continuation_monthly_premium_cents",
    "continuation_elected_at",
    "rescinded_at",
    "rescission_reason",
)

_RECOVERY_FIELDS = (
    "dependent_id",
    "termination_notice_id",
    "recovery_variant",
    "ineligibility_onset_date",
    "recoverable_subtotal_cents",
    "admin_fee_pct",
    "admin_fee_cents",
    "waiver_credit_cents",
    "net_demand_cents",
    "recovered_cents",
    "refund_due_cents",
    "status",
    "demand_issued_at",
)

_CLAIM_LINE_FIELDS = (
    "dependent_id",
    "service_date",
    "paid_cents",
    "employee_premium_offset_cents",
    "claim_reference",
    "provider_type",
)

_COMMUNICATION_FIELDS = (
    "case_id",
    "kind",
    "channel",
    "sequence_no",
    "sent_at",
    "template_code",
)


def _value(raw):
    if hasattr(raw, "tzinfo"):
        return clock.fmt_dt(raw)
    if isinstance(raw, list):
        return list(raw)
    return raw


def _build(rec, fields, versioned):
    out = {"id": rec["id"]}
    for name in fields:
        out[name] = _value(rec.get(name))
    out["created_at"] = clock.fmt_dt(rec["created_at"])
    if versioned:
        out["updated_at"] = clock.fmt_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def program(rec):
    return _build(rec, _PROGRAM_FIELDS, True)


def employee(rec):
    return _build(rec, _EMPLOYEE_FIELDS, True)


def dependent(rec):
    return _build(rec, _DEPENDENT_FIELDS, True)


def doc_rule(rec):
    return _build(rec, _RULE_FIELDS, True)


def case(rec):
    return _build(rec, _CASE_FIELDS, True)


def submission(rec):
    return _build(rec, _SUBMISSION_FIELDS, True)


def appeal(rec):
    return _build(rec, _APPEAL_FIELDS, True)


def notice(rec):
    return _build(rec, _NOTICE_FIELDS, True)


def recovery(rec):
    return _build(rec, _RECOVERY_FIELDS, True)


# The three append-only evidence types carry only id and created_at.


def amnesty_removal(rec):
    return _build(rec, _REMOVAL_FIELDS, False)


def claim_line(rec):
    return _build(rec, _CLAIM_LINE_FIELDS, False)


def communication(rec):
    return _build(rec, _COMMUNICATION_FIELDS, False)
