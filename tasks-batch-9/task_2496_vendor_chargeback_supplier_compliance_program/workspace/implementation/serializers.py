"""Resource serializers. Every money field is an integer number of cents and
every percentage is carried to two decimal places (PRD 2.6)."""

from core import fmt_dt, pct2


def _num(value):
    if value is None:
        return None
    return float(pct2(value))


def vendor_out(record):
    return {
        "id": record["id"],
        "vendor_code": record["vendor_code"],
        "legal_name": record["legal_name"],
        "payment_terms_days": record["payment_terms_days"],
        "status": record["status"],
        "otif_score": _num(record["otif_score"]),
        "open_chargeback_cents": record["open_chargeback_cents"],
        "recovered_lifetime_cents": record["recovered_lifetime_cents"],
        "refund_due_cents": record["refund_due_cents"],
        "open_violation_count": record["open_violation_count"],
        "open_cap_count": record["open_cap_count"],
        "repeat_offender_flag": record["repeat_offender_flag"],
        "exposure_alert_flag": record["exposure_alert_flag"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def guide_out(record):
    return {
        "id": record["id"],
        "guide_code": record["guide_code"],
        "title": record["title"],
        "scope_code": record["scope_code"],
        "effective_from": fmt_dt(record["effective_from"]),
        "effective_until": fmt_dt(record["effective_until"]),
        "supersedes_guide_id": record["supersedes_guide_id"],
        "status": record["status"],
        "requirement_count": record["requirement_count"],
        "published_at": fmt_dt(record["published_at"]),
        "published_by_user_id": record["published_by_user_id"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def requirement_out(record):
    return {
        "id": record["id"],
        "guide_id": record["guide_id"],
        "requirement_code": record["requirement_code"],
        "domain": record["domain"],
        "severity_tier": record["severity_tier"],
        "min_evidence_count": record["min_evidence_count"],
        "fixed_fee_cents": record["fixed_fee_cents"],
        "per_unit_recovery_cents": record["per_unit_recovery_cents"],
        "handling_pct": _num(record["handling_pct"]),
        "min_fee_cents": record["min_fee_cents"],
        "cap_cents": record["cap_cents"],
        "effective_until": fmt_dt(record["effective_until"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def purchase_order_out(record):
    return {
        "id": record["id"],
        "vendor_id": record["vendor_id"],
        "po_number": record["po_number"],
        "ordered_units": record["ordered_units"],
        "unit_cost_cents": record["unit_cost_cents"],
        "ship_window_start": fmt_dt(record["ship_window_start"]),
        "ship_window_end": fmt_dt(record["ship_window_end"]),
        "must_arrive_by": fmt_dt(record["must_arrive_by"]),
        "status": record["status"],
        "received_units": record["received_units"],
        "first_receipt_at": fmt_dt(record["first_receipt_at"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def shipment_out(record):
    return {
        "id": record["id"],
        "po_id": record["po_id"],
        "asn_number": record["asn_number"],
        "shipped_units": record["shipped_units"],
        "carton_count": record["carton_count"],
        "received_units": record["received_units"],
        "arrived_at": fmt_dt(record["arrived_at"]),
        "invoice_value_cents": record["invoice_value_cents"],
        "status": record["status"],
        "open_violation_count": record["open_violation_count"],
        "evidence_capture_count": record["evidence_capture_count"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def violation_out(record):
    return {
        "id": record["id"],
        "shipment_id": record["shipment_id"],
        "requirement_id": record["requirement_id"],
        "affected_units": record["affected_units"],
        "affected_cartons": record["affected_cartons"],
        "narrative": record["narrative"],
        "detected_by_user_id": record["detected_by_user_id"],
        "detected_at": fmt_dt(record["detected_at"]),
        "status": record["status"],
        "evidence_count": record["evidence_count"],
        "void_reason": record["void_reason"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def evidence_out(record):
    return {
        "id": record["id"],
        "violation_id": record["violation_id"],
        "dispute_id": record["dispute_id"],
        "subject_type": record["subject_type"],
        "kind": record["kind"],
        "reference_uri": record["reference_uri"],
        "note": record["note"],
        "captured_by_user_id": record["captured_by_user_id"],
        "captured_at": fmt_dt(record["captured_at"]),
        "created_at": fmt_dt(record["created_at"]),
    }


def chargeback_out(record):
    return {
        "id": record["id"],
        "violation_id": record["violation_id"],
        "vendor_id": record["vendor_id"],
        "requirement_id": record["requirement_id"],
        "assessment_variant": record["assessment_variant"],
        "fixed_fee_cents": record["fixed_fee_cents"],
        "cost_recovery_cents": record["cost_recovery_cents"],
        "gross_assessed_cents": record["gross_assessed_cents"],
        "reversal_cents": record["reversal_cents"],
        "recovered_cents": record["recovered_cents"],
        "outstanding_cents": record["outstanding_cents"],
        "evidence_at_assessment_count": record["evidence_at_assessment_count"],
        "dispute_status": record["dispute_status"],
        "deduction_posted": record["deduction_posted"],
        "settlement_status": record["settlement_status"],
        "assessed_at": fmt_dt(record["assessed_at"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def dispute_out(record):
    return {
        "id": record["id"],
        "chargeback_id": record["chargeback_id"],
        "vendor_id": record["vendor_id"],
        "reason_code": record["reason_code"],
        "claimed_reversal_cents": record["claimed_reversal_cents"],
        "narrative": record["narrative"],
        "status": record["status"],
        "round_count": record["round_count"],
        "reason_ceiling_pct": _num(record["reason_ceiling_pct"]),
        "approved_reversal_cents": record["approved_reversal_cents"],
        "goodwill_cents": record["goodwill_cents"],
        "submitted_at": fmt_dt(record["submitted_at"]),
        "decided_at": fmt_dt(record["decided_at"]),
        "decided_by_user_id": record["decided_by_user_id"],
        "information_request_note": record["information_request_note"],
        "review_note": record["review_note"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def scorecard_out(record):
    return {
        "id": record["id"],
        "vendor_id": record["vendor_id"],
        "period_code": record["period_code"],
        "period_start": fmt_dt(record["period_start"]),
        "period_end": fmt_dt(record["period_end"]),
        "tolerance_early_days": record["tolerance_early_days"],
        "tolerance_late_days": record["tolerance_late_days"],
        "fill_tolerance_pct": _num(record["fill_tolerance_pct"]),
        "measurement_variant": record["measurement_variant"],
        "status": record["status"],
        "measured_po_count": record["measured_po_count"],
        "on_time_count": record["on_time_count"],
        "in_full_count": record["in_full_count"],
        "otif_count": record["otif_count"],
        "on_time_pct": _num(record["on_time_pct"]),
        "fill_rate_pct": _num(record["fill_rate_pct"]),
        "otif_pct": _num(record["otif_pct"]),
        "composite_score": _num(record["composite_score"]),
        "cap_required": record["cap_required"],
        "measured_at": fmt_dt(record["measured_at"]),
        "finalized_at": fmt_dt(record["finalized_at"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def cap_out(record):
    return {
        "id": record["id"],
        "vendor_id": record["vendor_id"],
        "trigger_scorecard_id": record["trigger_scorecard_id"],
        "predecessor_cap_id": record["predecessor_cap_id"],
        "status": record["status"],
        "escalation_level": record["escalation_level"],
        "repeat_count": record["repeat_count"],
        "milestone_text": record["milestone_text"],
        "committed_completion_at": fmt_dt(record["committed_completion_at"]),
        "due_at": fmt_dt(record["due_at"]),
        "buying_decision": record["buying_decision"],
        "submission_round": record["submission_round"],
        "issued_at": fmt_dt(record["issued_at"]),
        "decided_at": fmt_dt(record["decided_at"]),
        "escalated_at": fmt_dt(record["escalated_at"]),
        "closed_at": fmt_dt(record["closed_at"]),
        "review_note": record["review_note"],
        "escalation_note": record["escalation_note"],
        "closure_note": record["closure_note"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def deduction_out(record):
    return {
        "id": record["id"],
        "vendor_id": record["vendor_id"],
        "invoice_reference": record["invoice_reference"],
        "status": record["status"],
        "amount_cents": record["amount_cents"],
        "allocation_count": record["allocation_count"],
        "over_allocated_cents": record["over_allocated_cents"],
        "posted_at": fmt_dt(record["posted_at"]),
        "posted_by_user_id": record["posted_by_user_id"],
        "reversed_at": fmt_dt(record["reversed_at"]),
        "reversal_reason": record["reversal_reason"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }


def allocation_out(record):
    return {
        "id": record["id"],
        "chargeback_id": record["chargeback_id"],
        "deduction_id": record["deduction_id"],
        "source_type": record["source_type"],
        "allocated_cents": record["allocated_cents"],
        "remittance_reference": record["remittance_reference"],
        "effective_status": record["effective_status"],
        "applied_by_user_id": record["applied_by_user_id"],
        "applied_at": fmt_dt(record["applied_at"]),
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }
