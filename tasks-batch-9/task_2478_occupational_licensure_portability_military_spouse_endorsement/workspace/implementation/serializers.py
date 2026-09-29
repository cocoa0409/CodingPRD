"""Wire representations.  Field sets follow SCAFFOLD §1.1 and PRD §2.4."""
import clock
from numbers_util import to_json_number
from services import calculations


def _audit(row, out):
    out["created_at"] = clock.fmt(row["created_at"])
    out["updated_at"] = clock.fmt(row["updated_at"])
    out["version"] = row["version"]
    return out


def profession(row):
    return _audit(row, {
        "id": row["id"],
        "profession_code": row["profession_code"],
        "title": row["title"],
        "required_scope_elements": list(row["required_scope_elements"]),
        "critical_scope_elements": list(row["critical_scope_elements"]),
        "required_practice_hours": row["required_practice_hours"],
        "requirement_hours_total": to_json_number(row["requirement_hours_total"]),
        "exam_waiver_min_score": to_json_number(row["exam_waiver_min_score"]),
        "jurisprudence_exam_required": row["jurisprudence_exam_required"],
        "universal_recognition_min_residency_months":
            row["universal_recognition_min_residency_months"],
        "standard_processing_days": row["standard_processing_days"],
        "base_fee_cents": row["base_fee_cents"],
        "endorsement_fee_cents": row["endorsement_fee_cents"],
        "exam_fee_cents": row["exam_fee_cents"],
        "jurisprudence_fee_cents": row["jurisprudence_fee_cents"],
        "permit_fee_cents": row["permit_fee_cents"],
        "expedite_surcharge_pct": to_json_number(row["expedite_surcharge_pct"]),
    })


def reciprocal_agreement(row):
    return _audit(row, {
        "id": row["id"],
        "profession_id": row["profession_id"],
        "partner_state": row["partner_state"],
        "fee_waiver_pct": to_json_number(row["fee_waiver_pct"]),
        "exam_waiver_allowed": row["exam_waiver_allowed"],
        "jurisprudence_waiver_allowed": row["jurisprudence_waiver_allowed"],
        "expires_on": clock.fmt(row["expires_on"]),
    })


def applicant(row):
    return _audit(row, {
        "id": row["id"],
        "full_name": row["full_name"],
        "state_code": row["state_code"],
        "residency_months": row["residency_months"],
        "military_status": row["military_status"],
        "disciplinary_risk_index_reported":
            to_json_number(row["disciplinary_risk_index_reported"]),
        "disciplinary_risk_index_effective":
            to_json_number(row["disciplinary_risk_index_effective"]),
        "good_standing_flag": row["good_standing_flag"],
        "fee_waiver_eligible": row["fee_waiver_eligible"],
    })


def credential(row):
    return _audit(row, {
        "id": row["id"],
        "applicant_id": row["applicant_id"],
        "issuing_state": row["issuing_state"],
        "license_number": row["license_number"],
        "scope_elements": list(row["scope_elements"]),
        "practice_hours": row["practice_hours"],
        "status": row["status"],
        "verified_good_standing": row["verified_good_standing"],
        "issued_at": clock.fmt(row["issued_at"]),
    })


def training_record(row):
    return _audit(row, {
        "id": row["id"],
        "applicant_id": row["applicant_id"],
        "category": row["category"],
        "documented_hours": row["documented_hours"],
        "source_document": row["source_document"],
        "verified": row["verified"],
    })


def disciplinary_record(row):
    return _audit(row, {
        "id": row["id"],
        "applicant_id": row["applicant_id"],
        "source_state": row["source_state"],
        "source_database": row["source_database"],
        "severity": row["severity"],
        "action_effective_at": clock.fmt(row["action_effective_at"]),
        "reported_at": clock.fmt(row["reported_at"]),
        "resolved": row["resolved"],
        "resolved_at": clock.fmt(row["resolved_at"]),
    })


def application(row):
    elapsed, standard_met = calculations.processing_time_metrics(row)
    return _audit(row, {
        "id": row["id"],
        "applicant_id": row["applicant_id"],
        "profession_id": row["profession_id"],
        "primary_credential_id": row["primary_credential_id"],
        "pathway": row["pathway"],
        "expedited": row["expedited"],
        "status": row["status"],
        "deficiency_cycle_count": row["deficiency_cycle_count"],
        "submitted_at": clock.fmt(row["submitted_at"]),
        "review_deadline_at": clock.fmt(row["review_deadline_at"]),
        "decided_at": clock.fmt(row["decided_at"]),
        "processing_elapsed_days": elapsed,
        "processing_standard_met": standard_met,
        "statutory_waiver_pct": to_json_number(row["statutory_waiver_pct"]),
        "gross_total_cents": row["gross_total_cents"],
        "fee_balance_cents": row["fee_balance_cents"],
        "requirement_hours_satisfied":
            to_json_number(row["requirement_hours_satisfied"]),
        "requirement_hours_remaining":
            to_json_number(row["requirement_hours_remaining"]),
        "national_exam_passed": row["national_exam_passed"],
        "jurisprudence_exam_passed": row["jurisprudence_exam_passed"],
        "pathway_risk_index": to_json_number(calculations.pathway_risk_index(row)),
        "scope_reviewed_by_user_id": row["scope_reviewed_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
    })


def evaluation(row):
    return _audit(row, {
        "id": row["id"],
        "application_id": row["application_id"],
        "credential_id": row["credential_id"],
        "variant": row["variant"],
        "scope_review_status": row["scope_review_status"],
        "discipline_review_status": row["discipline_review_status"],
        "overall_status": row["overall_status"],
        "matched_scope_elements": list(row["matched_scope_elements"]),
        "missing_scope_elements": list(row["missing_scope_elements"]),
        "equivalency_score": to_json_number(row["equivalency_score"]),
        "exam_waiver_granted": row["exam_waiver_granted"],
        "finalized_at": clock.fmt(row["finalized_at"]),
        "reviewed_by_user_id": row["reviewed_by_user_id"],
    })


def credit_award(row):
    return _audit(row, {
        "id": row["id"],
        "application_id": row["application_id"],
        "training_record_id": row["training_record_id"],
        "awarded_hours": to_json_number(row["awarded_hours"]),
        "status": row["status"],
        "revoked_at": clock.fmt(row["revoked_at"]),
    })


def temporary_permit(row):
    return _audit(row, {
        "id": row["id"],
        "application_id": row["application_id"],
        "effective_at": clock.fmt(row["effective_at"]),
        "expires_at": clock.fmt(row["expires_at"]),
        "permit_max_days": row["permit_max_days"],
        "permit_fee_cents": row["permit_fee_cents"],
        "status": row["status"],
        "converted_at": clock.fmt(row["converted_at"]),
        "revoked_at": clock.fmt(row["revoked_at"]),
        "revocation_reason_code": row["revocation_reason_code"],
    })


def license_row(row):
    return _audit(row, {
        "id": row["id"],
        "application_id": row["application_id"],
        "profession_id": row["profession_id"],
        "converted_from_permit_id": row["converted_from_permit_id"],
        "license_number": row["license_number"],
        "status": row["status"],
        "issued_at": clock.fmt(row["issued_at"]),
        "expires_at": clock.fmt(row["expires_at"]),
    })


def ledger_entry(row):
    """FeeLedgerEntry carries only id and created_at — no updated_at, no version."""
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "memo": row["memo"],
        "created_at": clock.fmt(row["created_at"]),
    }


def evaluator(row):
    return _audit(row, {
        "id": row["id"],
        "full_name": row["full_name"],
        "profession_code": row["profession_code"],
        "status": row["status"],
        "max_concurrent_reviews": row["max_concurrent_reviews"],
        "open_assignment_count": row["open_assignment_count"],
    })


def review_assignment(row):
    return _audit(row, {
        "id": row["id"],
        "evaluator_id": row["evaluator_id"],
        "application_id": row["application_id"],
        "window_start_at": clock.fmt(row["window_start_at"]),
        "window_end_at": clock.fmt(row["window_end_at"]),
        "status": row["status"],
        "closed_at": clock.fmt(row["closed_at"]),
    })
