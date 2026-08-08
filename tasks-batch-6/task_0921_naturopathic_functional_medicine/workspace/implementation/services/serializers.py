"""Entity -> JSON projections. Field sets follow SCAFFOLD.yaml `entities`."""

from services.dispensary import last_dose_date, lot_is_expired, product_stock
from services.threads import sla_breached, conversion_eligible

COMMON = ["created_at", "updated_at", "version"]


def _pick(row, names):
    return {name: row.get(name) for name in names}


def practitioner(row):
    return _pick(
        row,
        ["id", "full_name", "credential", "npi", "licensed_state_codes", "is_active"]
        + COMMON,
    )


def patient(row):
    return _pick(
        row,
        [
            "id",
            "full_name",
            "email",
            "state_code",
            "primary_practitioner_id",
            "telehealth_consent",
            "medication_classes",
            "clinical_status",
            "scope_review_status",
            "scope_review_reason",
            "scope_review_opened_by_user_id",
            "intake_booking_score",
            "intake_protocol_score",
            "clinical_write_gate",
            "red_flag_referral_open",
            "cash_charged_total_cents",
            "cash_refunded_total_cents",
        ]
        + COMMON,
    )


def intake_section(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "section_type",
            "payload_summary",
            "status",
            "weight",
            "submitted_at",
            "attested_at",
            "expires_at",
        ]
        + COMMON,
    )


def membership(row):
    data = _pick(
        row,
        [
            "id",
            "patient_id",
            "tier",
            "status",
            "cycle_start_date",
            "cycle_end_date",
            "cycle_index",
            "paused_at",
            "paused_days_total",
            "monthly_fee_cents",
            "dispensary_discount_pct",
            "includes_messaging",
            "visits_granted",
            "visits_consumed",
            "visits_remaining",
            "visits_forfeited",
            "lab_credits_granted",
            "lab_credits_consumed",
            "lab_credits_remaining",
            "lab_credits_forfeited",
            "last_proration_net_charge_cents",
        ]
        + COMMON,
    )
    data["dispensary_discount_pct"] = float(data["dispensary_discount_pct"])
    return data


def lab_order(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "ordering_practitioner_id",
            "panel_code",
            "specimen_type",
            "status",
            "funding_source",
            "price_cents",
            "lab_credit_cost",
            "requested_collection_date",
            "fasting_attested",
            "cycle_day",
            "washout_class",
            "washout_clearance_date",
            "collected_at",
            "has_critical_result",
            "interpretation_summary",
        ]
        + COMMON,
    )


def lab_result(row):
    # Immutable observation: id and created_at only, no updated_at and no version.
    return _pick(
        row,
        [
            "id",
            "lab_order_id",
            "analyte_code",
            "value",
            "unit",
            "standard_low",
            "standard_high",
            "optimal_low",
            "optimal_high",
            "critical_low",
            "critical_high",
            "standard_band",
            "optimal_band",
            "is_critical",
            "created_at",
        ],
    )


def protocol(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "practitioner_id",
            "supersedes_protocol_id",
            "title",
            "version_no",
            "status",
            "symptom_score_baseline",
            "advancement_blocked",
            "interaction_flags",
            "issued_at",
            "activated_at",
        ]
        + COMMON,
    )


def protocol_item(row):
    data = _pick(
        row,
        [
            "id",
            "protocol_id",
            "product_id",
            "dose_amount_mg",
            "frequency_per_day",
            "duration_days",
            "titration_interval_days",
            "status",
            "titration_step_no",
            "last_decision",
            "last_decision_at",
            "next_review_due_at",
            "titration_locked",
            "discontinue_reason",
        ]
        + COMMON,
    )
    dose_date = last_dose_date(row)
    data["last_dose_date"] = dose_date.isoformat() if dose_date else None
    return data


def product(row):
    data = _pick(
        row,
        [
            "id",
            "sku",
            "name",
            "supplement_class",
            "retail_price_cents",
            "practitioner_cost_cents",
            "interacts_with_med_classes",
            "interaction_severity",
        ]
        + COMMON,
    )
    data["stock_on_hand"] = product_stock(row["id"])
    return data


def lot(row):
    data = _pick(
        row,
        [
            "id",
            "product_id",
            "lot_code",
            "quantity_initial",
            "quantity_on_hand",
            "expiry_date",
            "is_quarantined",
        ]
        + COMMON,
    )
    data["is_expired"] = lot_is_expired(row)
    return data


def dispense(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "protocol_item_id",
            "product_lot_id",
            "dispensed_by_practitioner_id",
            "quantity",
            "pricing_variant",
            "unit_price_cents",
            "total_price_cents",
            "status",
            "dispensed_at",
            "professional_sample",
            "reversed_at",
            "reversal_reason",
            "reversal_authorized_by_user_id",
        ]
        + COMMON,
    )


def encounter(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "practitioner_id",
            "source_thread_id",
            "modality",
            "scheduled_start",
            "scheduled_end",
            "scheduling_status",
            "billing_status",
            "duration_minutes",
            "service_code",
            "diagnosis_codes",
            "base_fee_cents",
            "extended_block_count",
            "cash_charged_cents",
            "entitlement_consumed",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]
        + COMMON,
    )


def thread(row):
    data = _pick(
        row,
        [
            "id",
            "patient_id",
            "practitioner_id",
            "subject",
            "status",
            "patient_message_count",
            "clinician_message_count",
            "clinical_minutes_total",
            "opened_at",
            "sla_due_at",
            "first_clinical_reply_at",
        ]
        + COMMON,
    )
    data["sla_breached"] = sla_breached(row)
    data["evisit_conversion_eligible"] = conversion_eligible(row)
    return data


def superbill(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "encounter_id",
            "revision_no",
            "status",
            "diagnosis_codes",
            "service_code",
            "rendering_practitioner_npi",
            "billable_total_cents",
            "non_billable_membership_cents",
            "excluded_supplement_cents",
            "denial_code",
            "denial_reason",
            "appeal_narrative",
            "void_reason",
            "issued_at",
        ]
        + COMMON,
    )


def referral(row):
    return _pick(
        row,
        [
            "id",
            "patient_id",
            "referring_practitioner_id",
            "lab_order_id",
            "referral_type",
            "recipient_name",
            "specialty",
            "reason",
            "status",
            "attempt_no",
            "due_by_date",
            "acknowledged_at",
            "report_summary",
            "report_received_at",
            "closed_at",
            "decline_reason",
        ]
        + COMMON,
    )
