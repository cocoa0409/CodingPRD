"""Resource projections.

Every projection is computed from the live row at the moment the response is
written, so the `version` a mutating request reports is always the
post-increment value (PRD 2.5).
"""
import util

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(row, fields, datetimes=()):
    out = {}
    for name in fields:
        value = row.get(name)
        out[name] = util.fmt_dt(value) if name in datetimes and value is not None else value
    return out


def _with_common(row, out):
    out["id"] = row["id"]
    out["created_at"] = util.fmt_dt(row["created_at"])
    out["updated_at"] = util.fmt_dt(row["updated_at"])
    out["version"] = row["version"]
    return out


def patient(row):
    out = _base(
        row,
        (
            "full_name", "date_of_birth", "email", "sex_at_birth",
            "clinical_hold", "financial_hold", "eligibility_status",
            "cumulative_mg_testosterone", "cumulative_mg_estradiol",
            "last_insertion_at", "last_insertion_hormone_type",
            "open_notification_count",
        ),
        datetimes=("last_insertion_at",),
    )
    return _with_common(row, out)


def provider(row):
    out = _base(row, ("full_name", "provider_type", "npi", "active"))
    return _with_common(row, out)


def protocol(row):
    # A Protocol is immutable: it carries id and created_at only, with neither
    # updated_at nor version (PRD 2.5).
    out = _base(
        row,
        ("hormone_type", "protocol_version", "title", "published_by_provider_id", "effective_at"),
        datetimes=("effective_at",),
    )
    out["id"] = row["id"]
    out["created_at"] = util.fmt_dt(row["created_at"])
    return out


def consent(row):
    out = _base(
        row,
        ("patient_id", "hormone_type", "protocol_version", "consented_max_dose_mg",
         "signed_at", "status"),
        datetimes=("signed_at",),
    )
    return _with_common(row, out)


def consult(row):
    out = _base(
        row,
        ("patient_id", "physician_id", "hormone_type", "prescribed_dose_mg",
         "symptom_score", "indication", "planned_large_count", "planned_small_count",
         "planned_total_mg", "planned_pellet_count"),
    )
    return _with_common(row, out)


def lab_panel(row):
    out = _base(
        row,
        ("patient_id", "ordered_by_provider_id", "acknowledged_by_provider_id",
         "analyte", "value", "unit", "drawn_at", "resulted_at", "is_trough_draw",
         "lab_reference_band", "clinic_optimal_band", "critical_flag", "status"),
        datetimes=("drawn_at", "resulted_at"),
    )
    return _with_common(row, out)


def pellet_lot(row):
    out = _base(
        row,
        ("lot_code", "hormone_type", "strength_mg", "expiry_date", "qty_received",
         "qty_on_hand", "qty_reserved", "qty_consumed", "qty_wasted", "qty_returned",
         "sterility_status", "recall_severity", "recalled_at", "recall_reason"),
        datetimes=("expiry_date", "recalled_at"),
    )
    return _with_common(row, out)


def standing_order(row):
    out = _base(
        row,
        ("physician_id", "scope_hormone_types", "scope_injection_types", "max_dose_mg",
         "valid_from", "valid_until", "status", "suspended_reason"),
        datetimes=("valid_from", "valid_until"),
    )
    out["scope_hormone_types"] = list(row.get("scope_hormone_types") or [])
    out["scope_injection_types"] = list(row.get("scope_injection_types") or [])
    return _with_common(row, out)


def procedure(row):
    out = _base(
        row,
        ("patient_id", "provider_id", "consult_id", "standing_order_id",
         "consent_record_id", "lab_panel_id", "membership_id", "procedure_type",
         "hormone_type", "room_code", "scheduled_start", "scheduled_end",
         "planned_pellet_count", "planned_total_mg", "pellets_allocated",
         "pellets_opened", "pellets_inserted", "pellets_wasted",
         "delivered_total_mg", "status", "recall_status", "charge_cents",
         "cancel_tier", "cancel_fee_cents", "performed_at", "hold_reason"),
        datetimes=("scheduled_start", "scheduled_end", "performed_at"),
    )
    return _with_common(row, out)


def allocation(row):
    out = _base(
        row,
        ("procedure_id", "lot_id", "strength_mg", "quantity", "allocation_rank", "status"),
    )
    return _with_common(row, out)


def membership(row):
    out = _base(
        row,
        ("patient_id", "tier", "monthly_fee_cents", "discount_pct",
         "included_visits_allowance", "included_visits_used", "period_start",
         "period_end", "status", "paused_at", "pause_days_used", "pause_credit_cents"),
        datetimes=("period_start", "period_end", "paused_at"),
    )
    return _with_common(row, out)


def series_pack(row):
    out = _base(
        row,
        ("patient_id", "series_type", "purchased_visits", "remaining_visits",
         "redeemed_visits", "refunded_visits", "forfeited_visits", "price_cents",
         "per_visit_value_cents", "purchased_at", "expires_at", "refunded_cents",
         "status"),
        datetimes=("purchased_at", "expires_at"),
    )
    return _with_common(row, out)


def injection_visit(row):
    out = _base(
        row,
        ("patient_id", "provider_id", "standing_order_id", "series_pack_id",
         "membership_id", "injection_type", "room_code", "scheduled_start",
         "scheduled_end", "payment_source", "charge_cents", "series_debit_cents",
         "administered_at", "status"),
        datetimes=("scheduled_start", "scheduled_end", "administered_at"),
    )
    return _with_common(row, out)


def adverse_event(row):
    out = _base(
        row,
        ("patient_id", "procedure_id", "injection_visit_id", "lot_id",
         "standing_order_id", "reported_by_provider_id", "reviewed_by_provider_id",
         "severity", "source", "narrative", "onset_at", "review_due_at",
         "disposition_note", "status"),
        datetimes=("onset_at", "review_due_at"),
    )
    return _with_common(row, out)


def financing_plan(row):
    out = _base(
        row,
        ("patient_id", "procedure_id", "principal_cents", "down_payment_cents",
         "installment_count", "first_due_date", "paid_installment_cents",
         "outstanding_cents", "waived_cents", "refunded_cents", "late_fee_cents",
         "missed_count", "status"),
        datetimes=("first_due_date",),
    )
    out["schedule"] = [
        {
            "index": e["index"],
            "due_date": util.fmt_dt(e["due_date"]),
            "amount_cents": e["amount_cents"],
            "status": e["status"],
        }
        for e in row.get("schedule", [])
    ]
    return _with_common(row, out)


def notification(row):
    out = _base(
        row,
        ("patient_id", "procedure_id", "lot_id", "notification_type",
         "severity_class", "message", "due_at", "acknowledged_at", "status"),
        datetimes=("due_at", "acknowledged_at"),
    )
    return _with_common(row, out)


BY_TABLE = {
    "Patient": patient,
    "Provider": provider,
    "Protocol": protocol,
    "ConsentRecord": consent,
    "Consult": consult,
    "LabPanel": lab_panel,
    "PelletLot": pellet_lot,
    "StandingOrder": standing_order,
    "Procedure": procedure,
    "PelletAllocation": allocation,
    "Membership": membership,
    "SeriesPack": series_pack,
    "InjectionVisit": injection_visit,
    "AdverseEvent": adverse_event,
    "FinancingPlan": financing_plan,
    "PatientNotification": notification,
}


def dump(row):
    return BY_TABLE[row["_table"]](row)
