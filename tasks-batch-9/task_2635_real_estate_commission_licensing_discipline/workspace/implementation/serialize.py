"""Entity -> JSON projections. Computed fields are derived on every read."""
import computed
import store


def _common(row, out):
    out["created_at"] = row["created_at"]
    if "updated_at" in row:
        out["updated_at"] = row["updated_at"]
    if "version" in row:
        out["version"] = row["version"]
    return out


def licensee(row):
    out = {
        "id": row["id"],
        "license_number": row["license_number"],
        "person_type": row["person_type"],
        "full_name": row["full_name"],
        "prelicense_hours": row["prelicense_hours"],
        "license_status": row["license_status"],
        "discipline_status": row["discipline_status"],
        "exam_attempt_count": row["exam_attempt_count"],
        "exam_best_score": row["exam_best_score"],
        "exam_passed_at": row["exam_passed_at"],
        "sponsoring_brokerage_id": row["sponsoring_brokerage_id"],
        "supervising_broker_id": row["supervising_broker_id"],
        "license_issued_at": row["license_issued_at"],
        "license_expires_at": row["license_expires_at"],
        "inactive_since": row["inactive_since"],
        "ce_period_start_on": row["ce_period_start_on"],
        "ce_hours_valid": computed.ce_hours_valid(row),
        "ce_hours_required": computed.ce_hours_required(row),
        "ce_deficient": computed.ce_deficient(row),
        "prior_sanction_count": computed.prior_sanction_count(row["id"]),
        "recovery_paid_cents": computed.recovery_paid_cents(row["id"]),
        "suspension_ends_at": row["suspension_ends_at"],
    }
    return _common(row, out)


def brokerage(row):
    posture = computed.supervision_posture(row)
    out = {
        "id": row["id"],
        "name": row["name"],
        "designated_broker_id": row["designated_broker_id"],
        "status": row["status"],
        "trust_account_required": row["trust_account_required"],
        "record_retention_years": row["record_retention_years"],
        "supervision_posture": posture,
        "affiliated_licensee_count": computed.affiliated_licensee_count(row["id"]),
        "open_shortage_cents": computed.open_shortage_cents(row["id"]),
        "open_complaint_count": computed.open_complaint_count(row["id"]),
        "overdue_remediation_count": computed.overdue_remediation_count(row["id"]),
        "new_affiliation_blocked": posture in ("RESTRICTED", "FROZEN"),
    }
    return _common(row, out)


def trust_account(row):
    obligation, available, shortage = computed.account_triple(row)
    out = {
        "id": row["id"],
        "brokerage_id": row["brokerage_id"],
        "bank_name": row["bank_name"],
        "account_type": row["account_type"],
        "status": row["status"],
        "book_obligation_cents": obligation,
        "book_available_cents": available,
        "shortage_cents": shortage,
        "last_audited_at": row["last_audited_at"],
    }
    return _common(row, out)


def ledger_entry(row):
    return {
        "id": row["id"],
        "trust_account_id": row["trust_account_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "effective_date": row["effective_date"],
        "cleared_date": row["cleared_date"],
        "transaction_reference": row["transaction_reference"],
        "memo": row["memo"],
        "created_at": row["created_at"],
    }


def trust_audit(row):
    out = {
        "id": row["id"],
        "trust_account_id": row["trust_account_id"],
        "auditor_user_id": row["auditor_user_id"],
        "basis": row["basis"],
        "as_of_date": row["as_of_date"],
        "fieldwork_start_at": row["fieldwork_start_at"],
        "fieldwork_end_at": row["fieldwork_end_at"],
        "status": row["status"],
        "bank_statement_balance_cents": row["bank_statement_balance_cents"],
        "cleared_through_date": row["cleared_through_date"],
        "computed_shortage_cents": row["computed_shortage_cents"],
        "remediation_due_at": row["remediation_due_at"],
        "remediation_round": row["remediation_round"],
        "verified_shortage_cents": row["verified_shortage_cents"],
    }
    return _common(row, out)


def complaint(row):
    out = {
        "id": row["id"],
        "case_number": row["case_number"],
        "complainant_name": row["complainant_name"],
        "respondent_licensee_id": row["respondent_licensee_id"],
        "respondent_brokerage_id": row["respondent_brokerage_id"],
        "source_audit_id": row["source_audit_id"],
        "allegation_type": row["allegation_type"],
        "alleged_loss_cents": row["alleged_loss_cents"],
        "filed_at": row["filed_at"],
        "statute_deadline_at": row["statute_deadline_at"],
        "status": row["status"],
        "screener_user_id": row["screener_user_id"],
        "investigator_user_id": row["investigator_user_id"],
        "amendment_count": row["amendment_count"],
        "priority_score": computed.priority_score(row),
    }
    return _common(row, out)


def consent_agreement(row):
    out = {
        "id": row["id"],
        "complaint_id": row["complaint_id"],
        "offered_by_user_id": row["offered_by_user_id"],
        "round_number": row["round_number"],
        "status": row["status"],
        "proposed_sanction_type": row["proposed_sanction_type"],
        "proposed_fine_cents": row["proposed_fine_cents"],
        "proposed_suspension_days": row["proposed_suspension_days"],
        "counter_fine_cents": row["counter_fine_cents"],
        "counter_suspension_days": row["counter_suspension_days"],
        "responded_by_user_id": row["responded_by_user_id"],
        "executed_by_user_id": row["executed_by_user_id"],
    }
    return _common(row, out)


def hearing(row):
    out = {
        "id": row["id"],
        "complaint_id": row["complaint_id"],
        "panel_chair_user_id": row["panel_chair_user_id"],
        "hearing_room": row["hearing_room"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "status": row["status"],
        "continuance_count": row["continuance_count"],
        "convened_at": row["convened_at"],
        "decided_at": row["decided_at"],
        "finding": row["finding"],
    }
    return _common(row, out)


def sanction_order(row):
    out = {
        "id": row["id"],
        "complaint_id": row["complaint_id"],
        "respondent_licensee_id": row["respondent_licensee_id"],
        "consent_agreement_id": row["consent_agreement_id"],
        "hearing_id": row["hearing_id"],
        "source": row["source"],
        "sanction_type": row["sanction_type"],
        "fine_cents": row["fine_cents"],
        "suspension_days": row["suspension_days"],
        "effective_at": row["effective_at"],
        "fine_due_at": row["fine_due_at"],
        "fine_paid_cents": row["fine_paid_cents"],
        "fund_credited_cents": row["fund_credited_cents"],
        "status": row["status"],
        "vacated_at": row["vacated_at"],
    }
    return _common(row, out)


def recovery_fund(row):
    out = {
        "id": row["id"],
        "balance_cents": row["balance_cents"],
        "appropriated_cents": row["appropriated_cents"],
        "fine_credits_cents": row["fine_credits_cents"],
        "awarded_cents": row["awarded_cents"],
        "assessment_cents": row["assessment_cents"],
        "clawed_back_cents": row["clawed_back_cents"],
    }
    return _common(row, out)


def recovery_claim(row):
    out = {
        "id": row["id"],
        "sanction_order_id": row["sanction_order_id"],
        "claimant_name": row["claimant_name"],
        "claimed_loss_cents": row["claimed_loss_cents"],
        "filed_at": row["filed_at"],
        "status": row["status"],
        "awarded_cents": row["awarded_cents"],
        "denial_reason": row["denial_reason"],
        "paid_at": row["paid_at"],
    }
    return _common(row, out)


def education_provider(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "admin_user_id": row["admin_user_id"],
        "status": row["status"],
        "approved_at": row["approved_at"],
        "approval_expires_at": row["approval_expires_at"],
        "suspended_instructor_count": computed.suspended_instructor_count(row["id"]),
        "invalidated_credit_hours": computed.invalidated_credit_hours(row["id"]),
    }
    return _common(row, out)


def instructor(row):
    out = {
        "id": row["id"],
        "education_provider_id": row["education_provider_id"],
        "licensee_id": row["licensee_id"],
        "full_name": row["full_name"],
        "credential_type": row["credential_type"],
        "status": row["status"],
        "approved_at": row["approved_at"],
        "suspended_reason": row["suspended_reason"],
    }
    return _common(row, out)


def course_completion(row):
    return {
        "id": row["id"],
        "licensee_id": row["licensee_id"],
        "instructor_id": row["instructor_id"],
        "education_provider_id": row["education_provider_id"],
        "course_type": row["course_type"],
        "credit_hours": row["credit_hours"],
        "completed_on": row["completed_on"],
        "credit_status": row["credit_status"],
        "invalidated_at": row["invalidated_at"],
        "created_at": row["created_at"],
    }


def advertising_name(row):
    out = {
        "id": row["id"],
        "brokerage_id": row["brokerage_id"],
        "team_lead_licensee_id": row["team_lead_licensee_id"],
        "kind": row["kind"],
        "name_text": row["name_text"],
        "normalized_name": row["normalized_name"],
        "prohibited_term_hits": row["prohibited_term_hits"],
        "status": row["status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "rejection_reason": row["rejection_reason"],
    }
    return _common(row, out)


PROJECTORS = {
    "licensee": licensee,
    "brokerage": brokerage,
    "trust_account": trust_account,
    "ledger_entry": ledger_entry,
    "trust_audit": trust_audit,
    "complaint": complaint,
    "consent_agreement": consent_agreement,
    "hearing": hearing,
    "sanction_order": sanction_order,
    "recovery_fund": recovery_fund,
    "recovery_claim": recovery_claim,
    "education_provider": education_provider,
    "instructor": instructor,
    "course_completion": course_completion,
    "advertising_name": advertising_name,
}


def project(kind, row):
    return PROJECTORS[kind](row)
