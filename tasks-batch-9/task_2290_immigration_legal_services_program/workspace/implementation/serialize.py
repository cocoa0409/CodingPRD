"""Entity -> JSON projections. Field names come from SCAFFOLD entities."""

import calc
import store

_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(row, names):
    out = {}
    for name in _COMMON:
        out[name] = row.get(name)
    for name in names:
        out[name] = store.num(row.get(name))
    return out


CLIENT_FIELDS = (
    "full_name", "preferred_language_code", "country_of_birth_code", "a_number",
    "date_of_birth", "household_size", "annual_household_income_cents",
    "fpl_percent", "confidentiality_consent_scope", "interpreter_required",
    "open_matter_count", "status",
)

CYCLE_FIELDS = (
    "cycle_label", "period_start_date", "period_end_date", "total_case_slots",
    "reserved_detained_slots", "general_slots_consumed", "detained_slots_consumed",
    "available_slot_count", "waitlisted_count", "utilization_ratio",
    "capacity_posture", "posture_override_until_utc", "checkpoint_epoch",
    "last_checkpoint_utc",
)

FACILITY_FIELDS = (
    "name", "jurisdiction_code", "visit_lead_time_hours", "max_daily_visit_slots",
    "expedited_filing_days", "access_credential_required", "status",
)

RECOGNITION_FIELDS = (
    "recognition_number", "effective_date", "expiry_date", "authorized_forums",
    "status", "conditional_reason_code", "suspended_accreditation_count",
    "lapsed_at_utc",
)

REPRESENTATIVE_FIELDS = (
    "full_name", "rep_type", "bar_number", "languages", "max_case_load",
    "max_supervisees", "weekly_capacity_hours", "active_case_load",
    "supervisee_count", "supervision_required", "authorization_status",
    "facility_access_credential_expires_on", "status",
)

ACCREDITATION_FIELDS = (
    "representative_id", "recognition_id", "approved_by_representative_id",
    "accreditation_type", "requested_forums", "authorized_forums", "status",
    "effective_date", "expiry_date", "renewal_round", "decision_reason_code",
)

SCREENING_FIELDS = (
    "client_id", "cycle_id", "screener_representative_id",
    "decided_by_representative_id", "facility_id", "case_type", "detained",
    "statutory_deadline_date", "one_year_bar_applies", "prior_removal_order",
    "unaccompanied_minor", "legal_eligibility_verdict", "urgency_score",
    "urgency_tier", "urgency_variant_applied", "urgency_anchor_date", "status",
    "decision_reason_code", "referral_partner_code", "waitlist_rank",
    "waitlist_expires_at_utc", "screened_at_utc", "decided_at_utc",
)

MATTER_FIELDS = (
    "client_id", "intake_id", "cycle_id", "principal_matter_id", "facility_id",
    "case_type", "forum", "detained", "representation_status", "filing_status",
    "slot_pool_consumed", "statutory_deadline_date", "expedited_deadline_date",
    "effective_filing_deadline_date", "readiness_index_weighted",
    "readiness_ready_strict", "evidence_blocking_count", "readiness_gate_applied",
    "interpretation_cost_cents", "direct_hours_logged", "supervision_hours_logged",
    "coverage_gap_flag", "outcome", "outcome_recorded_at_utc", "closed_at_utc",
)

ASSIGNMENT_FIELDS = (
    "matter_id", "representative_id", "supervision_link_id", "role_on_case",
    "status", "supervision_source", "direct_hours_logged",
    "supervision_hours_logged", "assigned_at_utc", "activated_at_utc",
    "released_at_utc", "release_reason_code",
)

EVIDENCE_FIELDS = (
    "matter_id", "item_type", "tier", "weight_points", "source_language_code",
    "requires_translation", "status", "due_date", "received_at_utc",
    "verified_at_utc", "rejection_round", "disposition_reason_code",
)

DECLARATION_FIELDS = (
    "matter_id", "preparer_assignment_id", "reviewer_assignment_id",
    "readback_session_id", "language_code", "word_count", "status",
    "revision_round", "readback_completed", "revision_reason_code",
    "certified_at_utc",
)

SESSION_FIELDS = (
    "matter_id", "interpreter_representative_id", "language_code",
    "interpreter_source", "purpose", "scheduled_start_utc", "scheduled_end_utc",
    "actual_minutes", "billed_minutes", "billable_cents", "status",
    "closure_reason_code",
)

EVENT_FIELDS = (
    "matter_id", "facility_id", "assigned_representative_id",
    "continued_from_event_id", "event_type", "starts_at_utc", "ends_at_utc",
    "location_code", "travel_buffer_minutes", "status", "reschedule_count",
    "coverage_gap_flag", "client_conflict_waived",
)

DECISION_FIELDS = (
    "matter_id", "counseled_by_assignment_id", "readback_session_id",
    "decision_type", "risks_disclosed", "alternatives_disclosed",
    "counseling_language_code", "language_match_verified", "status",
    "acknowledged_at_utc", "superseded_by_decision_id", "revocation_reason_code",
)

REPORT_FIELDS = (
    "cycle_id", "grant_code", "period_start_date", "period_end_date",
    "disclosure_level", "status", "cases_served_count", "outcomes_summary",
    "consent_verified_count", "suppressed_case_count", "base_reimbursable_cents",
    "supervision_surcharge_cents", "total_reimbursable_cents",
    "allocated_line_total_cents", "rounding_remainder_cents", "amendment_round",
    "generated_at_utc", "submitted_at_utc",
)


def client(row):
    return _pick(row, CLIENT_FIELDS)


def cycle(row):
    out = _pick(row, CYCLE_FIELDS)
    out["capacity_posture"] = calc.effective_posture(row)
    return out


def facility(row):
    return _pick(row, FACILITY_FIELDS)


def recognition(row):
    return _pick(row, RECOGNITION_FIELDS)


def representative(row):
    out = _pick(row, REPRESENTATIVE_FIELDS)
    out["supervision_required"] = calc.supervision_required(row)
    out["authorization_status"] = calc.authorization_status(row)
    return out


def accreditation(row):
    return _pick(row, ACCREDITATION_FIELDS)


def screening(row):
    return _pick(row, SCREENING_FIELDS)


def matter(row):
    return _pick(row, MATTER_FIELDS)


def assignment(row):
    return _pick(row, ASSIGNMENT_FIELDS)


def evidence(row):
    return _pick(row, EVIDENCE_FIELDS)


def declaration(row):
    return _pick(row, DECLARATION_FIELDS)


def session(row):
    return _pick(row, SESSION_FIELDS)


def event(row):
    return _pick(row, EVENT_FIELDS)


def decision(row):
    return _pick(row, DECISION_FIELDS)


def report(row):
    return _pick(row, REPORT_FIELDS)
