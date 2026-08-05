"""Entity serializers.  Every datetime leaves through util.render_ts()."""

import store
from util import render_ts as ts


def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = ts(rec["created_at"])
    out["updated_at"] = ts(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def establishment(rec):
    return _common(
        rec,
        {
            "name": rec["name"],
            "street_address": rec["street_address"],
            "county_code": rec["county_code"],
            "establishment_type": rec["establishment_type"],
            "permit_status": rec["permit_status"],
            "permit_issued_on": ts(rec["permit_issued_on"]),
            "permit_expires_on": ts(rec["permit_expires_on"]),
            "operating_posture": rec["operating_posture"],
            "risk_score": rec["risk_score"],
            "open_violation_count": rec["open_violation_count"],
            "open_critical_violation_count": rec["open_critical_violation_count"],
            "sterilization_compliance_status": rec["sterilization_compliance_status"],
            "active_artist_count": rec["active_artist_count"],
            "fees_paid_cents": rec["fees_paid_cents"],
            "fees_refunded_cents": rec["fees_refunded_cents"],
            "plan_review_cycles_used": rec["plan_review_cycles_used"],
        },
    )


def artist(rec):
    confirmed = sum(
        1
        for r in store.infection_reports.values()
        if r.get("artist_id") == rec["id"] and r["investigation_status"] == "CONFIRMED"
    )
    suspensions = sum(
        1
        for a in store.enforcement_actions.values()
        if a.get("artist_id") == rec["id"] and a["action_type"] == "SUSPENSION"
    )
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "legal_name": rec["legal_name"],
            "permit_status": rec["permit_status"],
            "bbp_training_completed_on": ts(rec["bbp_training_completed_on"]),
            "bbp_training_expires_on": ts(rec["bbp_training_expires_on"]),
            "bbp_recert_required": rec["bbp_recert_required"],
            "permit_expires_on": ts(rec["permit_expires_on"]),
            "confirmed_infection_count": confirmed,
            "suspension_count": suspensions,
        },
    )


def plan_review(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "status": rec["status"],
            "floor_plan_reference": rec["floor_plan_reference"],
            "sterilization_area_sqft": rec["sterilization_area_sqft"],
            "procedure_station_count": rec["procedure_station_count"],
            "has_handwash_sink": rec["has_handwash_sink"],
            "cycle_count": rec["cycle_count"],
            "decision_notes": rec["decision_notes"],
            "decided_by_user_id": rec["decided_by_user_id"],
        },
    )


def inspection(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "source_complaint_id": rec["source_complaint_id"],
            "inspection_type": rec["inspection_type"],
            "status": rec["status"],
            "scheduled_start_at": ts(rec["scheduled_start_at"]),
            "scheduled_end_at": ts(rec["scheduled_end_at"]),
            "inspector_user_id": rec["inspector_user_id"],
            "score": rec["score"],
            "open_violation_count_at_start": rec["open_violation_count_at_start"],
            "finalized_at": ts(rec["finalized_at"]),
        },
    )


def violation(rec):
    return _common(
        rec,
        {
            "inspection_id": rec["inspection_id"],
            "violation_code": rec["violation_code"],
            "severity": rec["severity"],
            "narrative": rec["narrative"],
            "status": rec["status"],
            "issued_at": ts(rec["issued_at"]),
            "abatement_due_at": ts(rec["abatement_due_at"]),
            "repeat_multiplier_applied": rec["repeat_multiplier_applied"],
            "deduction_points": rec["deduction_points"],
            "correction_note": rec["correction_note"],
            "correction_submitted_at": ts(rec["correction_submitted_at"]),
        },
    )


def sterilization_record(rec):
    # immutable: no updated_at, no version (PRD §2.4)
    return {
        "id": rec["id"],
        "created_at": ts(rec["created_at"]),
        "establishment_id": rec["establishment_id"],
        "device_serial": rec["device_serial"],
        "cycle_completed_at": ts(rec["cycle_completed_at"]),
        "spore_test_result": rec["spore_test_result"],
        "supersedes_record_id": rec["supersedes_record_id"],
        "recorded_by_user_id": rec["recorded_by_user_id"],
    }


def minor_consent(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "minor_full_name": rec["minor_full_name"],
            "minor_age_at_signing": rec["minor_age_at_signing"],
            "guardian_full_name": rec["guardian_full_name"],
            "guardian_id_document_type": rec["guardian_id_document_type"],
            "guardian_id_document_number": rec["guardian_id_document_number"],
            "authorized_procedure_type": rec["authorized_procedure_type"],
            "consent_signed_at": ts(rec["consent_signed_at"]),
            "expires_at": ts(rec["expires_at"]),
            "verification_status": rec["verification_status"],
            "verified_by_user_id": rec["verified_by_user_id"],
            "rejection_reason": rec["rejection_reason"],
        },
    )


def procedure_log(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "artist_id": rec["artist_id"],
            "minor_consent_id": rec["minor_consent_id"],
            "client_age": rec["client_age"],
            "procedure_type": rec["procedure_type"],
            "started_at": ts(rec["started_at"]),
            "ended_at": ts(rec["ended_at"]),
            "aftercare_provided": rec["aftercare_provided"],
            "audit_status": rec["audit_status"],
            "audit_finding_code": rec["audit_finding_code"],
        },
    )


def complaint(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "complainant_contact": rec["complainant_contact"],
            "category": rec["category"],
            "narrative": rec["narrative"],
            "status": rec["status"],
            "received_at": ts(rec["received_at"]),
            "triage_due_at": ts(rec["triage_due_at"]),
            "triage_overdue": rec["triage_overdue"],
            "reopen_count": rec["reopen_count"],
        },
    )


def infection_report(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "artist_id": rec["artist_id"],
            "reporter_contact": rec["reporter_contact"],
            "infection_type": rec["infection_type"],
            "procedure_date": ts(rec["procedure_date"]),
            "symptom_onset_at": ts(rec["symptom_onset_at"]),
            "investigation_status": rec["investigation_status"],
            "notification_status": rec["notification_status"],
            "notification_due_at": ts(rec["notification_due_at"]),
            "notification_late": rec["notification_late"],
            "reopen_count": rec["reopen_count"],
        },
    )


def enforcement_action(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "artist_id": rec["artist_id"],
            "subject_type": rec["subject_type"],
            "action_type": rec["action_type"],
            "reason_code": rec["reason_code"],
            "status": rec["status"],
            "issued_by_user_id": rec["issued_by_user_id"],
            "issued_at": ts(rec["issued_at"]),
            "lifted_by_user_id": rec["lifted_by_user_id"],
            "lifted_at": ts(rec["lifted_at"]),
            "auto_generated": rec["auto_generated"],
            "suspension_days": rec["suspension_days"],
            "reinstatement_base_cents": rec["reinstatement_base_cents"],
            "reinstatement_admin_fee_cents": rec["reinstatement_admin_fee_cents"],
            "reinstatement_total_cents": rec["reinstatement_total_cents"],
        },
    )


def renewal_application(rec):
    return _common(
        rec,
        {
            "establishment_id": rec["establishment_id"],
            "status": rec["status"],
            "requested_term_start_on": ts(rec["requested_term_start_on"]),
            "expedite_requested": rec["expedite_requested"],
            "attested_bbp_current": rec["attested_bbp_current"],
            "attested_sterilization_logs_complete": rec[
                "attested_sterilization_logs_complete"
            ],
            "submitted_at": ts(rec["submitted_at"]),
            "artist_count_at_submit": rec["artist_count_at_submit"],
            "fee_estimate_cents": rec["fee_estimate_cents"],
            "fee_final_cents": rec["fee_final_cents"],
            "fee_balance_due_cents": rec["fee_balance_due_cents"],
            "fee_paid_cents": rec["fee_paid_cents"],
            "fee_refunded_cents": rec["fee_refunded_cents"],
            "payment_status": rec["payment_status"],
            "late_fee_applied": rec["late_fee_applied"],
            "deficiency_code": rec["deficiency_code"],
            "decided_by_user_id": rec["decided_by_user_id"],
            "decided_at": ts(rec["decided_at"]),
            "cycle_count": rec["cycle_count"],
        },
    )
