"""Resource representations."""

from decimal import Decimal

import derive
import store


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def study(rec):
    ledger = derive.study_ledger(rec)
    out = {
        "id": rec["id"],
        "protocol_number": rec["protocol_number"],
        "title": rec["title"],
        "sponsor_name": rec["sponsor_name"],
        "funding_source": rec["funding_source"],
        "ind_ide_status": rec["ind_ide_status"],
        "therapeutic_intent": rec["therapeutic_intent"],
        "registry_number": rec["registry_number"],
        "qct_determination": rec["qct_determination"],
        "qct_basis": rec["qct_basis"],
        "qct_determined_by_user_id": rec["qct_determined_by_user_id"],
        "qct_determined_at": store.iso(rec["qct_determined_at"]),
        "lifecycle_status": rec["lifecycle_status"],
        "budget_status": rec["budget_status"],
        "budget_source_analysis_id": rec["budget_source_analysis_id"],
        "budget_basis": rec["budget_basis"],
        "indirect_rate_pct": _num(rec["indirect_rate_pct"]),
        "effective_indirect_rate_pct": _num(rec["effective_indirect_rate_pct"]),
        "per_patient_subtotal_cents": rec["per_patient_subtotal_cents"],
        "per_patient_budget_cents": rec["per_patient_budget_cents"],
        "invoiceable_subtotal_cents": rec["invoiceable_subtotal_cents"],
        "invoiceable_budget_cents": rec["invoiceable_budget_cents"],
        "budget_built_by_user_id": rec["budget_built_by_user_id"],
        "budget_executed_by_user_id": rec["budget_executed_by_user_id"],
        "billing_hold_posture": derive.billing_hold_posture(rec),
        "open_finding_count": derive.open_finding_count(rec["id"]),
        "rebuild_required_calendar_count": derive.rebuild_required_calendar_count(rec["id"]),
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }
    out.update(ledger)
    return out


def analysis(rec):
    out = {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "supersedes_analysis_id": rec["supersedes_analysis_id"],
        "revision_number": rec["revision_number"],
        "status": rec["status"],
        "prepared_by_user_id": rec["prepared_by_user_id"],
        "returned_by_user_id": rec["returned_by_user_id"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "return_reason": rec["return_reason"],
        "return_count": rec["return_count"],
        "approved_at": store.iso(rec["approved_at"]),
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }
    out.update(derive.analysis_counters(rec["id"]))
    return out


def coverage_item(rec):
    return {
        "id": rec["id"],
        "coverage_analysis_id": rec["coverage_analysis_id"],
        "item_code": rec["item_code"],
        "description": rec["description"],
        "classification": rec["classification"],
        "medicare_coverage_basis": rec["medicare_coverage_basis"],
        "billable_to": rec["billable_to"],
        "budget_category": rec["budget_category"],
        "charge_master_unit_cents": rec["charge_master_unit_cents"],
        "negotiated_unit_cents": rec["negotiated_unit_cents"],
        "units_per_occurrence": rec["units_per_occurrence"],
        "expected_occurrences": rec["expected_occurrences"],
        "created_at": store.iso(rec["created_at"]),
    }


def calendar(rec):
    out = {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "source_analysis_id": rec["source_analysis_id"],
        "build_generation": rec["build_generation"],
        "status": rec["status"],
        "published_at": store.iso(rec["published_at"]),
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }
    out.update(derive.calendar_counters(rec))
    return out


def calendar_visit(rec):
    return {
        "id": rec["id"],
        "study_calendar_id": rec["study_calendar_id"],
        "visit_name": rec["visit_name"],
        "sequence_index": rec["sequence_index"],
        "target_day_offset": rec["target_day_offset"],
        "window_before_days": rec["window_before_days"],
        "window_after_days": rec["window_after_days"],
        "window_start_day": rec["window_start_day"],
        "window_end_day": rec["window_end_day"],
        "expected_charge_total_cents": derive.visit_expected_total(rec["id"]),
        "created_at": store.iso(rec["created_at"]),
    }


def route(rec):
    return {
        "id": rec["id"],
        "calendar_visit_id": rec["calendar_visit_id"],
        "coverage_item_id": rec["coverage_item_id"],
        "occurrences": rec["occurrences"],
        "routing_target": rec["routing_target"],
        "expected_amount_cents": rec["expected_amount_cents"],
        "created_at": store.iso(rec["created_at"]),
    }


def subject(rec):
    visit_ids = _visit_ids_of_subject(rec["id"])
    charge_count = sum(
        1 for c in store.charges.values()
        if c["subject_visit_id"] is not None and c["subject_visit_id"] in visit_ids
    )
    return {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "subject_number": rec["subject_number"],
        "consented_calendar_id": rec["consented_calendar_id"],
        "consented_calendar_generation": rec["consented_calendar_generation"],
        "consent_date": rec["consent_date"],
        "status": rec["status"],
        "charge_count": charge_count,
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }


def _visit_ids_of_subject(subject_id):
    return {v["id"] for v in store.subject_visits.values()
            if v["study_subject_id"] == subject_id}


def subject_visit(rec):
    generated = sum(1 for c in store.charges.values()
                    if c["subject_visit_id"] == rec["id"]
                    and c["source"] == "VISIT_CASCADE")
    return {
        "id": rec["id"],
        "study_subject_id": rec["study_subject_id"],
        "calendar_visit_id": rec["calendar_visit_id"],
        "actual_service_date": rec["actual_service_date"],
        "day_offset_actual": rec["day_offset_actual"],
        "calendar_generation_at_schedule": rec["calendar_generation_at_schedule"],
        "status": rec["status"],
        "generated_charge_count": generated,
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }


def charge(rec):
    return {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "subject_visit_id": rec["subject_visit_id"],
        "coverage_item_id": rec["coverage_item_id"],
        "sponsor_invoice_id": rec["sponsor_invoice_id"],
        "replaces_charge_id": rec["replaces_charge_id"],
        "charge_code": rec["charge_code"],
        "service_date": rec["service_date"],
        "amount_cents": rec["amount_cents"],
        "source": rec["source"],
        "routing_state": rec["routing_state"],
        "billing_state": rec["billing_state"],
        "suggested_routing_target": rec["suggested_routing_target"],
        "expected_routing_target": derive.expected_routing_target(rec),
        "improper_flag": derive.improper_flag(rec),
        "hold_reason": rec["hold_reason"],
        "hold_applied_at": store.iso(rec["hold_applied_at"]),
        "unbilled_since": store.iso(rec["unbilled_since"]),
        "aging_days": rec["aging_days"],
        "aging_bucket": rec["aging_bucket"],
        "posted_by_user_id": rec["posted_by_user_id"],
        "reviewed_by_user_id": rec["reviewed_by_user_id"],
        "reviewed_at": store.iso(rec["reviewed_at"]),
        "override_justification": rec["override_justification"],
        "refunded_amount_cents": rec["refunded_amount_cents"],
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }


def invoice(rec):
    return {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "sequence_number": rec["sequence_number"],
        "invoice_number": rec["invoice_number"],
        "period_end_date": rec["period_end_date"],
        "status": rec["status"],
        "line_count": rec["line_count"],
        "subtotal_cents": rec["subtotal_cents"],
        "indirect_cents": rec["indirect_cents"],
        "gross_total_cents": rec["gross_total_cents"],
        "volume_credit_cents": rec["volume_credit_cents"],
        "net_total_cents": rec["net_total_cents"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "short_paid": rec["short_paid"],
        "submitted_at": store.iso(rec["submitted_at"]),
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }


def finding(rec):
    return {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "charge_id": rec["charge_id"],
        "finding_type": rec["finding_type"],
        "claimed_amount_cents": rec["claimed_amount_cents"],
        "status": rec["status"],
        "response_narrative": rec["response_narrative"],
        "opened_by_user_id": rec["opened_by_user_id"],
        "responded_by_user_id": rec["responded_by_user_id"],
        "refund_amount_cents": rec["refund_amount_cents"],
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }


def amendment(rec):
    return {
        "id": rec["id"],
        "study_id": rec["study_id"],
        "amendment_number": rec["amendment_number"],
        "scope": rec["scope"],
        "effective_date": rec["effective_date"],
        "status": rec["status"],
        "reanalysis_required": rec["reanalysis_required"],
        "calendar_rebuild_required": rec["calendar_rebuild_required"],
        "created_at": store.iso(rec["created_at"]),
        "updated_at": store.iso(rec["updated_at"]),
        "version": rec["version"],
    }
