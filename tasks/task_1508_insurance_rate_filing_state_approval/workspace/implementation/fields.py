"""Public wire field lists per entity (common fields + scaffold fields)."""

COMMON = ["id", "created_at", "updated_at", "version"]

PRODUCT = COMMON + ["product_code", "name", "current_locked_indication_id"]

STATE_PROFILE = COMMON + [
    "product_id", "state_code", "filing_method", "min_effective_lead_days",
    "objection_response_sla_days", "deemer_days", "max_single_change_pct",
    "renewal_notice_days", "disapproval_window_days", "status",
]

RATE_INDICATION = COMMON + [
    "product_id", "scope_state_code", "variant", "earned_premium_cents",
    "incurred_loss_cents", "paid_loss_cents", "exposure_units", "trend_factor",
    "countrywide_change_pct", "credibility_z", "indicated_change_pct",
    "alternate_change_pct", "status", "prepared_by_user_id",
    "approved_by_user_id", "review_round",
]

RATE_FILING = COMMON + [
    "product_id", "profile_id", "indication_id", "state_code", "filing_type",
    "proposed_change_pct", "proposed_effective_date", "filing_number", "status",
    "submitted_at", "approved_at", "actual_effective_date", "deemer_date",
    "superseded_at_date", "open_objection_count",
]

FILING_COMPONENT = COMMON + ["filing_id", "component_type", "name", "content_ref", "status"]

DEVIATION = COMMON + [
    "filing_id", "deviation_type", "base_reference", "deviation_factor",
    "justification", "status",
]

OBJECTION = COMMON + [
    "filing_id", "question_text", "raised_at", "due_at", "status",
    "reopen_count", "late_breach", "resolved_at",
]

OBJECTION_RESPONSE = COMMON + [
    "objection_id", "response_text", "status", "drafted_by_user_id", "submitted_at",
]

IMPLEMENTATION_WAVE = COMMON + [
    "filing_id", "product_id", "state_code", "wave_start_date", "wave_end_date",
    "cap_pct", "approved_change_pct", "balance_factor", "target_book_delta_cents",
    "final_book_delta_cents", "rated_policy_count", "excluded_late_notice_count",
    "status",
]

RENEWAL_POLICY = COMMON + [
    "product_id", "wave_id", "state_code", "policy_number",
    "current_premium_cents", "class_rel_factor", "renewal_effective_date",
    "baseline_premium_cents", "raw_change_pct", "raw_new_premium_cents",
    "was_capped", "final_premium_cents", "notice_due_date", "notice_sent_at",
    "status", "exclusion_reason",
]

CALENDAR_ENTRY = COMMON + [
    "filing_id", "wave_id", "objection_id", "entry_type", "due_date", "status",
    "resolved_at",
]
