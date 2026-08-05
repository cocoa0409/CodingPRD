"""Serialized representations (PRD 2.5).

A resource is always serialized in full: every field the entity owns appears on
every read and on every write that returns it, an unset computed field carrying
a JSON null rather than being omitted.
"""

from store import num, render_date, render_instant

RAW = "raw"
DATE = "date"
N1 = "n1"
N2 = "n2"
N4 = "n4"

SPECS = {
    "provider": [
        ("npi", RAW), ("full_name", RAW), ("provider_type", RAW), ("state_license", RAW),
        ("dme_supplier_number", RAW), ("status", RAW), ("open_efficacy_loop_count", RAW),
    ],
    "payer": [
        ("name", RAW), ("payer_kind", RAW), ("prior_auth_required", RAW),
        ("useful_lifetime_months", RAW), ("coinsurance_pct", RAW), ("appeal_limit", RAW),
        ("residual_ahi_target", RAW), ("pct_reduction_target", RAW),
    ],
    "patient": [
        ("mrn", RAW), ("full_name", RAW), ("date_of_birth", DATE), ("medical_payer_id", RAW),
        ("dental_payer_id", RAW), ("deductible_remaining_cents", RAW), ("epworth_score", RAW),
        ("records_frozen", RAW),
    ],
    "sleep_study": [
        ("patient_id", RAW), ("ordering_physician_id", RAW), ("appliance_id", RAW),
        ("modality", RAW), ("study_purpose", RAW), ("performed_on", DATE),
        ("respiratory_events", RAW), ("recording_minutes", RAW), ("sleep_minutes", RAW),
        ("artifact_pct", RAW), ("attended", RAW), ("severity_index", N1),
        ("severity_band", RAW), ("repeat_count", RAW), ("status", RAW),
    ],
    "referral": [
        ("patient_id", RAW), ("referring_physician_id", RAW), ("treating_dentist_id", RAW),
        ("diagnostic_study_id", RAW), ("cpap_history", RAW), ("cpap_nights_used", RAW),
        ("cpap_documented_on", DATE), ("severity_band_at_referral", RAW),
        ("eligibility_basis", RAW), ("diagnosis_valid_until", DATE), ("loop_status", RAW),
        ("status", RAW),
    ],
    "written_order": [
        ("patient_id", RAW), ("ordering_physician_id", RAW), ("item_hcpcs", RAW),
        ("order_date", DATE), ("f2f_encounter_date", DATE), ("signed_on", DATE),
        ("f2f_age_days", RAW), ("status", RAW),
    ],
    "prior_auth": [
        ("patient_id", RAW), ("payer_id", RAW), ("referral_id", RAW), ("requested_hcpcs", RAW),
        ("submitted_on", DATE), ("decided_on", DATE), ("approval_valid_until", DATE),
        ("denial_reason", RAW), ("appeal_attempts", RAW), ("status", RAW),
    ],
    "lab_order": [
        ("referral_id", RAW), ("lab_provider_id", RAW), ("appliance_kind", RAW),
        ("capture_method", RAW), ("max_protrusive_mm", N2), ("retruded_position_mm", N2),
        ("promised_turnaround_days", RAW), ("submitted_on", DATE), ("promised_ship_date", DATE),
        ("shipped_on", DATE), ("turnaround_on_time", RAW), ("remake_count", RAW), ("status", RAW),
    ],
    "appliance_lot": [
        ("manufacturer", RAW), ("lot_code", RAW), ("material", RAW), ("notice_reference", RAW),
        ("recall_severity", RAW), ("recall_issued_on", DATE), ("affected_device_count", RAW),
        ("remediated_count", RAW), ("pending_remediation_count", RAW), ("retired_count", RAW),
        ("status", RAW),
    ],
    "appliance": [
        ("patient_id", RAW), ("lab_order_id", RAW), ("lot_id", RAW),
        ("replaces_appliance_id", RAW), ("serial_number", RAW), ("has_microrecorder", RAW),
        ("appliance_kind", RAW), ("hcpcs_code", RAW), ("max_protrusive_mm", N2),
        ("delivered_on", DATE), ("written_order_id", RAW), ("pod_signed_on", DATE),
        ("pod_method", RAW), ("warranty_end_date", DATE), ("useful_lifetime_end_date", DATE),
        ("starting_advancement_mm", N2), ("current_advancement_mm", N2),
        ("applied_visit_count", RAW), ("plateau_declared_on", DATE),
        ("next_recall_due_on", DATE), ("recall_cycle_index", RAW), ("lifecycle_status", RAW),
        ("device_hold_status", RAW), ("recall_status", RAW),
    ],
    "titration_visit": [
        ("appliance_id", RAW), ("performed_by_dentist_id", RAW), ("visit_seq", RAW),
        ("scheduled_for", DATE), ("requested_increment_mm", N2), ("side_effect_severity", RAW),
        ("applied_increment_mm", N2), ("applied_on", DATE), ("days_since_prior_applied", RAW),
        ("status", RAW),
    ],
    "adherence_download": [
        ("appliance_id", RAW), ("source", RAW), ("window_start", DATE), ("window_end", DATE),
        ("nights_recorded", RAW), ("nights_at_or_above_min_hours", RAW),
        ("mean_hours_per_worn_night", RAW), ("rate_of_window", N4), ("rate_of_recorded", N4),
        ("compliant", RAW),
    ],
    "efficacy_report": [
        ("patient_id", RAW), ("referral_id", RAW), ("appliance_id", RAW),
        ("efficacy_study_id", RAW), ("baseline_index", N1), ("residual_index", N1),
        ("pct_reduction", N4), ("meets_absolute_target", RAW), ("meets_relative_target", RAW),
        ("outcome", RAW), ("due_by", DATE), ("submitted_on", DATE),
        ("physician_decision_on", DATE), ("dispute_reason", RAW), ("revision_count", RAW),
        ("status", RAW),
    ],
    "claim": [
        ("patient_id", RAW), ("payer_id", RAW), ("appliance_id", RAW), ("prior_auth_id", RAW),
        ("written_order_id", RAW), ("repair_order_id", RAW), ("claim_type", RAW),
        ("hcpcs_code", RAW), ("date_of_service", DATE), ("billed_cents", RAW),
        ("allowed_cents", RAW), ("deductible_applied_cents", RAW), ("coinsurance_cents", RAW),
        ("patient_responsibility_cents", RAW), ("payer_paid_cents", RAW),
        ("adjustment_cents", RAW), ("denial_error_id", RAW), ("appeal_attempts", RAW),
        ("status", RAW),
    ],
    "repair_order": [
        ("appliance_id", RAW), ("loaner_appliance_id", RAW), ("reason", RAW),
        ("reported_on", DATE), ("labor_minutes", RAW), ("returned_on", DATE),
        ("in_warranty", RAW), ("billable", RAW), ("labor_units", RAW),
        ("repair_charge_cents", RAW), ("resets_useful_lifetime", RAW), ("status", RAW),
    ],
    "audit_hold": [
        ("patient_id", RAW), ("payer_id", RAW), ("opened_on", DATE), ("closed_on", DATE),
        ("scope_note", RAW), ("status", RAW),
    ],
}

# AdherenceDownload is an immutable observation: id and created_at only.
NO_COMMON_MUTABLE = ("adherence_download",)


def dump(kind, row):
    out = {"id": row["id"], "created_at": render_instant(row["created_at"])}
    if kind not in NO_COMMON_MUTABLE:
        out["updated_at"] = render_instant(row["updated_at"])
        out["version"] = row["version"]
    for name, mode in SPECS[kind]:
        value = row.get(name)
        if mode == DATE:
            out[name] = render_date(value)
        elif mode == N1:
            out[name] = num(value, 1)
        elif mode == N2:
            out[name] = num(value, 2)
        elif mode == N4:
            out[name] = num(value, 4)
        else:
            out[name] = value
    return out


def dump_all(kind, rows):
    return [dump(kind, row) for row in rows]
