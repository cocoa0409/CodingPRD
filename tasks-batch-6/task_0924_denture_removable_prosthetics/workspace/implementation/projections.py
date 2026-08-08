"""Response projection (PRD 2.4).

Projection is post-commit: the body a mutating call returns is the state of the
resource AFTER the write, with the already-incremented `version` and the
already-refreshed `updated_at`.

Every instant leaves through `iso()` -- the single rendering rule of PRD 2.5.
Nullable fields are always present, rendered as JSON null.  Computed collection
fields are always present as arrays, empty rather than null.
"""
import calc
import domain
from util import iso


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def patient(row):
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "date_of_birth": row["date_of_birth"],
            "phone": row["phone"],
            "write_gate_active": domain.patient_write_gate_active(row),
            "delivered_prosthesis_count": domain.patient_delivered_prosthesis_count(row),
            "last_frequency_anchor_at": iso(
                domain.patient_last_frequency_anchor_at(row)
            ),
        }
    )
    return out


def coverage(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "carrier_name": row["carrier_name"],
            "rank": row["rank"],
            "effective_date": iso(row["effective_date"]),
            "annual_maximum_amount": row["annual_maximum_amount"],
            "coinsurance_major_rate": row["coinsurance_major_rate"],
            "waiting_period_days": row["waiting_period_days"],
            "replacement_frequency_months": row["replacement_frequency_months"],
            "cob_convention": row["cob_convention"],
            "alternate_benefit_enabled": row["alternate_benefit_enabled"],
            "benefit_used_ytd": row["benefit_used_ytd"],
            "benefit_remaining": calc.coverage_benefit_remaining(row),
        }
    )
    return out


def lab(row):
    out = _common(row)
    out.update(
        {
            "lab_name": row["lab_name"],
            "bench_line_count": row["bench_line_count"],
            "standard_turnaround_days": row["standard_turnaround_days"],
            "rush_turnaround_days": row["rush_turnaround_days"],
            "credit_issued_total": row["credit_issued_total"],
            "credit_applied_total": row["credit_applied_total"],
            "credit_available_balance": row["credit_available_balance"],
        }
    )
    return out


def case(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "prosthesis_type": row["prosthesis_type"],
            "case_status": row["case_status"],
            "fee_schedule_total": row["fee_schedule_total"],
            "predetermination_required": row["predetermination_required"],
            "billed_amount": row["billed_amount"],
            "insurance_paid_amount": row["insurance_paid_amount"],
            "prompt_pay_discount_amount": row["prompt_pay_discount_amount"],
            "patient_responsibility_amount": row["patient_responsibility_amount"],
            "fabrication_started_at": iso(row["fabrication_started_at"]),
            "delivered_at": iso(row["delivered_at"]),
        }
    )
    return out


def arch(row):
    out = _common(row)
    out.update(
        {
            "case_id": row["case_id"],
            "arch_position": row["arch_position"],
            "arch_status": row["arch_status"],
            "required_milestones": list(row["required_milestones"]),
            "completed_milestones": domain.arch_completed_milestones(row),
            "next_required_milestone": domain.arch_next_required_milestone(row),
            "retake_count": row["retake_count"],
            "remake_count": domain.arch_remake_count(row),
            "remake_request_count": domain.arch_remake_request_count(row),
            "remake_eligibility": row["remake_eligibility"],
            "fee_schedule_amount": row["fee_schedule_amount"],
            "last_lab_received_at": iso(row["last_lab_received_at"]),
        }
    )
    return out


def impression(row):
    out = _common(row)
    out.update(
        {
            "case_arch_id": row["case_arch_id"],
            "capture_method": row["capture_method"],
            "attempt_number": row["attempt_number"],
            "quality_score": row["quality_score"],
            "quality_status": row["quality_status"],
            "retake_required": row["quality_status"]
            in ("PROVISIONAL_ACCEPTED", "REJECTED"),
            "reviewed_at": iso(row["reviewed_at"]),
            "superseded_by_impression_id": row["superseded_by_impression_id"],
        }
    )
    return out


def tryin(row):
    out = _common(row)
    out.update(
        {
            "case_arch_id": row["case_arch_id"],
            "milestone_kind": row["milestone_kind"],
            "approval_status": row["approval_status"],
            "adjust_count": row["adjust_count"],
            "decided_at": iso(row["decided_at"]),
            "decided_by_user_id": row["decided_by_user_id"],
        }
    )
    return out


def labcase(row):
    out = _common(row)
    out.update(
        {
            "case_arch_id": row["case_arch_id"],
            "dental_lab_id": row["dental_lab_id"],
            "bench_line": row["bench_line"],
            "turnaround_class": row["turnaround_class"],
            "unit_count": row["unit_count"],
            "lab_invoice_amount": row["lab_invoice_amount"],
            "purpose": row["purpose"],
            "lab_status": row["lab_status"],
            "dispatched_at": iso(row["dispatched_at"]),
            "promised_due_at": iso(row["promised_due_at"]),
            "shelf_life_expires_at": iso(row["shelf_life_expires_at"]),
            "rush_fee_amount": row["rush_fee_amount"],
            "received_at": iso(row["received_at"]),
            "resend_count": row["resend_count"],
            "qc_result": row["qc_result"],
            "expired_at": iso(row["expired_at"]),
        }
    )
    return out


def prosthesis(row):
    out = _common(row)
    out.update(
        {
            "case_arch_id": row["case_arch_id"],
            "superseded_prosthesis_id": row["superseded_prosthesis_id"],
            "prosthesis_type": row["prosthesis_type"],
            "is_remake": row["is_remake"],
            "delivered_at": iso(row["delivered_at"]),
            "warranty_status": row["warranty_status"],
            "warranty_expires_at": iso(row["warranty_expires_at"]),
            "frequency_anchor_at": iso(row["frequency_anchor_at"]),
            "replacement_eligible_date": iso(row["replacement_eligible_date"]),
            "recall_status": row["recall_status"],
            "recall_due_at": iso(row["recall_due_at"]),
            "recall_cycle_count": row["recall_cycle_count"],
            "adjustments_used": row["adjustments_used"],
            "adjustments_remaining": 4 - row["adjustments_used"],
            "adjustment_window_ends_at": iso(row["adjustment_window_ends_at"]),
            "in_patient_possession": row["in_patient_possession"],
            "mandatory_reline_due_at": iso(row["mandatory_reline_due_at"]),
        }
    )
    return out


def service(row):
    out = _common(row)
    out.update(
        {
            "prosthesis_id": row["prosthesis_id"],
            "lab_case_id": row["lab_case_id"],
            "service_type": row["service_type"],
            "is_emergency_repair": row["is_emergency_repair"],
            "service_status": row["service_status"],
            "charge_basis": row["charge_basis"],
            "charge_amount": row["charge_amount"],
            "completed_at": iso(row["completed_at"]),
            "voided_at": iso(row["voided_at"]),
        }
    )
    return out


def warranty_claim(row):
    out = _common(row)
    out.update(
        {
            "prosthesis_id": row["prosthesis_id"],
            "post_delivery_service_id": row["post_delivery_service_id"],
            "attributed_lab_case_id": row["attributed_lab_case_id"],
            "reported_issue": row["reported_issue"],
            "claim_status": row["claim_status"],
            "fault_verdict": row["fault_verdict"],
            "lab_credit_amount": row["lab_credit_amount"],
            "patient_charge_amount": row["patient_charge_amount"],
            "warranty_consumed": row["warranty_consumed"],
            "adjudicated_at": iso(row["adjudicated_at"]),
        }
    )
    return out


def remake_request(row):
    out = _common(row)
    out.update(
        {
            "case_arch_id": row["case_arch_id"],
            "warranty_claim_id": row["warranty_claim_id"],
            "reason_code": row["reason_code"],
            "requested_by_user_id": row["requested_by_user_id"],
            "approved_by_user_id": row["approved_by_user_id"],
            "authorization_status": row["authorization_status"],
            "attempt_number": row["attempt_number"],
            "charge_basis": row["charge_basis"],
            "decided_at": iso(row["decided_at"]),
        }
    )
    return out


def predetermination(row):
    out = _common(row)
    out.update(
        {
            "case_id": row["case_id"],
            "coverage_id": row["coverage_id"],
            "requested_amount": row["requested_amount"],
            "determination_status": row["determination_status"],
            "alternate_benefit_type": row["alternate_benefit_type"],
            "allowed_amount": row["allowed_amount"],
            "estimated_plan_payment": row["estimated_plan_payment"],
            "estimated_patient_responsibility": row[
                "estimated_patient_responsibility"
            ],
            "determined_at": iso(row["determined_at"]),
            "expires_at": iso(row["expires_at"]),
        }
    )
    return out


def claim(row):
    out = _common(row)
    out.update(
        {
            "case_id": row["case_id"],
            "coverage_id": row["coverage_id"],
            "predetermination_id": row["predetermination_id"],
            "billed_amount": row["billed_amount"],
            "allowed_amount": row["allowed_amount"],
            "adjudication_status": row["adjudication_status"],
            "submission_target": row["submission_target"],
            "primary_paid_amount": row["primary_paid_amount"],
            "secondary_paid_amount": row["secondary_paid_amount"],
            "plan_paid_amount": row["plan_paid_amount"],
            "patient_responsibility_amount": row["patient_responsibility_amount"],
            "cob_convention_applied": row["cob_convention_applied"],
            "submitted_at": iso(row["submitted_at"]),
            "adjudicated_at": iso(row["adjudicated_at"]),
            "reversed_at": iso(row["reversed_at"]),
        }
    )
    return out


def plan(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "case_id": row["case_id"],
            "superseded_by_plan_id": row["superseded_by_plan_id"],
            "principal_amount": row["principal_amount"],
            "installment_count": row["installment_count"],
            "down_payment_amount": row["down_payment_amount"],
            "pay_in_full": row["pay_in_full"],
            "first_due_date": iso(row["first_due_date"]),
            "frequency": row["frequency"],
            "plan_status": row["plan_status"],
            "paid_amount": domain.plan_paid_amount(row),
            "outstanding_amount": domain.plan_outstanding_amount(row),
            "missed_count": domain.plan_missed_count(row),
            "applied_lab_credit_amount": row["applied_lab_credit_amount"],
        }
    )
    return out


def installment(row):
    out = _common(row)
    out.update(
        {
            "payment_plan_id": row["payment_plan_id"],
            "sequence_number": row["sequence_number"],
            "amount": row["amount"],
            "due_date": iso(row["due_date"]),
            "installment_status": row["installment_status"],
            "is_residual_installment": row["is_residual_installment"],
            "paid_at": iso(row["paid_at"]),
        }
    )
    return out
