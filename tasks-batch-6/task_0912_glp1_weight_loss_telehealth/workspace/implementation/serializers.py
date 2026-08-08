"""Entity -> response payload projections.

Every field listed here traces to SCAFFOLD.yaml section 1.1 plus the four
common fields of PRD 2.5.  Nothing else is exposed.
"""

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "patient": (
        "email", "full_name", "state_code", "height_cm", "weight_kg",
        "comorbidity_codes", "payment_mode", "current_bmi", "eligibility_status",
        "lifetime_charged_cents", "lifetime_credited_cents",
    ),
    "provider": ("full_name", "provider_type", "npi", "licensed_state_codes", "status"),
    "pharmacy": ("name", "dispense_type", "served_state_codes", "status"),
    "supply_lot": (
        "pharmacy_id", "lot_code", "strength_mg", "total_units",
        "window_capacity_units", "available_units", "reserved_units",
        "dispensed_units", "expires_at", "status",
    ),
    "screening": (
        "patient_id", "status", "recorded_weight_kg", "recorded_height_cm",
        "egfr", "a1c_pct", "lab_collected_at", "comorbidity_count",
        "assessed_bmi", "eligibility_band", "decision_reason", "submitted_at",
        "submit_count",
    ),
    "consult": (
        "patient_id", "provider_id", "scheduled_start_at", "scheduled_end_at",
        "status", "outcome_note", "reschedule_count",
    ),
    "prescription": (
        "patient_id", "consult_id", "prescriber_provider_id", "screening_id",
        "supersedes_prescription_id", "drug_family", "units_per_cycle",
        "dose_level", "dose_mg", "clinical_status", "fulfillment_status",
        "active_route_mode", "last_dose_change_at", "severity_index_rolling",
        "severity_index_since_dose_change", "discontinue_reason",
    ),
    "titration_step": (
        "prescription_id", "second_signer_provider_id", "step_number",
        "dose_level", "dose_mg", "status", "earliest_escalation_at",
        "administered_at", "hold_reason",
    ),
    "prior_authorization": (
        "prescription_id", "payer_reference", "status", "appeal_count",
        "decided_at", "denial_reason", "approved_through_at",
    ),
    "pharmacy_order": (
        "prescription_id", "titration_step_id", "pharmacy_id", "supply_lot_id",
        "units_requested", "window_start_at", "window_end_at", "status",
        "dispense_type_at_route", "reserved_at", "shipped_at", "cancel_reason",
    ),
    "subscription": (
        "patient_id", "prescription_id", "anchor_at", "coaching_addon_enabled",
        "status", "coaching_credits_granted", "coaching_credits_reserved",
        "coaching_credits_consumed", "coaching_credits_forfeited",
        "coaching_credits_available", "paused_at", "pause_days_used",
        "cycle_count",
    ),
    "billing_cycle": (
        "subscription_id", "sequence_number", "period_start_at", "period_end_at",
        "status", "charge_basis", "medication_charge_cents",
        "coaching_addon_fee_cents", "dispensing_fee_cents",
        "adherence_credit_cents", "total_due_cents", "settled_amount_cents",
        "proration_credit_cents", "coaching_unused_credit_cents", "invoiced_at",
        "void_reason",
    ),
    "check_in": (
        "patient_id", "prescription_id", "triaged_by_provider_id",
        "nausea_score", "vomiting_score", "dehydration_flag", "severity_score",
        "status", "submitted_at", "triaged_at", "resolved_at",
    ),
    "coaching_session": (
        "subscription_id", "coach_provider_id", "billing_cycle_id",
        "scheduled_start_at", "scheduled_end_at", "status", "completed_at",
    ),
}


def dump(kind, record):
    if record is None:
        return None
    out = {"id": record["id"]}
    for name in FIELDS[kind]:
        out[name] = record.get(name)
    out["created_at"] = record["created_at"]
    out["updated_at"] = record["updated_at"]
    out["version"] = record["version"]
    return out


def dump_many(kind, records):
    return [dump(kind, r) for r in records]
