"""Entity serializers: emit declared fields + common fields; compute derived fields."""
import calc

_COMMON = ("id", "created_at", "updated_at", "version")


def _emit(rec, fields):
    out = {k: rec.get(k) for k in fields}
    for k in _COMMON:
        out[k] = rec[k]
    return out


def site(rec):
    return _emit(rec, ["name", "status"])


def provider(rec):
    return _emit(rec, ["full_name", "provider_type", "npi",
                       "credential_expires_on", "dea_expires_on", "status"])


def roster(rec):
    out = _emit(rec, ["site_id", "service_date", "required_primary_slots",
                      "scheduled_day_end_minute", "lifecycle"])
    out["posture"] = calc.derive_posture(rec)
    return out


def case(rec):
    return _emit(rec, ["roster_id", "procedure_code", "physical_status", "emergency_flag",
                       "scheduled_start_minute", "scheduled_end_minute",
                       "actual_start_minute", "actual_end_minute", "status",
                       "cancellation_reason", "cancellation_notice_minutes",
                       "provisional_charge_cents", "final_charge_cents"])


def assignment(rec):
    return _emit(rec, ["case_id", "roster_id", "provider_id", "assignment_role", "status"])


def call_assignment(rec):
    return _emit(rec, ["roster_id", "provider_id", "window_start_minute",
                       "window_end_minute", "status", "released_at_minute"])


def attestation(rec):
    return _emit(rec, ["case_id", "physician_id",
                       "step_preanesthetic_exam", "step_prescribes_plan",
                       "step_participates_key_portions", "step_ensures_qualified_personnel",
                       "step_monitors_course", "step_available_for_emergencies",
                       "step_post_anesthesia_care",
                       "submitted_count", "rejection_reason", "status"])


def claim(rec):
    return _emit(rec, ["case_id", "provider_id", "modifier_code", "units_total",
                       "charge_cents", "status", "denial_reason", "paid_amount_cents",
                       "resubmission_count"])


def fee_schedule(rec):
    return _emit(rec, ["procedure_code", "base_units", "contracted_max_cents", "description"])


def agreement(rec):
    return _emit(rec, ["site_id", "effective_from", "effective_to", "call_stipend_cents",
                       "late_stay_rate_cents_per_minute", "standby_full_cents",
                       "standby_partial_cents"])


def stipend_entry(rec):
    return _emit(rec, ["provider_id", "roster_id", "entry_type", "occurred_date",
                       "amount_cents", "applied_amount_cents", "status"])


def audit(rec):
    out = _emit(rec, ["roster_id", "status"])
    rt, pe, band = calc.compute_scores(rec)
    rec["realtime_score"], rec["period_score"], rec["risk_band"] = rt, pe, band
    out["realtime_score"] = rt
    out["period_score"] = pe
    out["risk_band"] = band
    return out


def finding(rec):
    return _emit(rec, ["audit_id", "case_id", "assignment_id", "finding_type",
                       "severity", "status", "resolution_note"])
