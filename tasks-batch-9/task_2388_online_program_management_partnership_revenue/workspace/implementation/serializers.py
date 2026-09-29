"""Explicit output shapes.  Nothing prefixed with ``_`` ever leaves the server."""

PARTNERSHIP_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "university_name", "university_ipeds_id", "partner_org_name",
    "contract_structure", "term_months", "effective_date", "expiry_date",
    "status", "revenue_share_tiers", "fee_schedule_monthly_cents",
    "refund_schedule", "revenue_recognition_method", "exclusivity_cip_codes",
    "bundled_services_exception_claimed", "marketing_budget_cents",
    "marketing_budget_remaining_cents", "unrecouped_marketing_spend_cents",
    "collected_tuition_cents", "recognized_revenue_cents",
    "contract_year_recognized_cents", "remitted_to_partner_cents",
    "holdback_balance_cents", "change_request_count", "executed_date",
    "wind_down_effective_date",
)

PROGRAM_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "partnership_id", "program_name", "cip_code", "delivery_modality",
    "credential_level", "tuition_per_credit_cents", "credits_to_complete",
    "enrollment_cap", "projected_annual_enrollments", "competitor_program_count",
    "regional_wage_premium_pct", "employer_partner_count",
    "prior_year_inquiry_volume", "launch_window_start", "launch_window_end",
    "required_service_domains", "demand_score_screening",
    "demand_score_confirmed", "status", "revision_round",
    "active_enrollment_count", "total_enrollment_count",
    "marketing_spend_net_cents", "blended_cac_cents", "recognized_revenue_cents",
    "launched_at", "teach_out_started_at", "closed_at",
)

COURSE_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "program_id", "prerequisite_course_id", "course_code", "title", "credits",
    "required_for_launch", "content_owner", "ip_license_grant_back",
    "design_cost_cents", "design_status", "faculty_approver_name",
    "revision_round",
)

ASSIGNMENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "program_id", "service_domain", "responsible_party", "sla_response_hours",
    "cost_bearer",
)

COUNSELOR_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "partnership_id", "full_name", "employer", "monthly_base_salary_cents",
    "comp_plan_type", "annual_base_cents", "variable_component_cents",
    "variable_basis", "performance_status", "incentive_eligibility",
    "conversion_rate", "open_pipeline_count", "rated_lead_count",
    "enrolled_lead_count", "sla_breach_count", "clawback_pending_cents",
    "last_review_user_id",
)

LEAD_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "program_id", "counselor_id", "source_channel", "prospect_external_id",
    "status", "hours_to_first_contact", "qualified_at",
    "disqualification_reason",
)

ENROLLMENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "program_id", "lead_id", "student_external_id", "credits_enrolled",
    "credits_completed", "tuition_per_credit_snapshot_cents",
    "tuition_charged_cents", "term_start_date", "term_end_date", "status",
    "collected_cents", "refunded_cents", "recognized_to_date_cents",
    "withdrawal_date", "refund_pct_applied", "days_elapsed_at_withdrawal",
)

# Append-only ledgers: id and created_at only, no updated_at and no version.
TUITION_FIELDS = (
    "id", "created_at",
    "enrollment_id", "entry_type", "amount_cents", "posted_date",
    "reference_note", "generated_by",
)

MARKETING_FIELDS = (
    "id", "created_at",
    "program_id", "entry_type", "channel", "amount_cents", "spend_date",
    "reversal_note",
)

STATEMENT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "partnership_id", "period_start", "period_end", "status",
    "recognition_method_applied", "recognized_revenue_cents",
    "share_gross_cents", "marketing_recoupment_cents", "subtotal_cents",
    "holdback_pct", "holdback_cents", "fee_for_service_cents",
    "net_payable_cents", "line_count", "authored_by_user_id",
    "approved_by_user_id", "resolved_by_user_id", "adjustment_delta_cents",
    "requires_recalculation", "dispute_reason", "remittance_reference",
    "remitted_at",
)

TEACH_OUT_FIELDS = (
    "id", "created_at", "updated_at", "version",
    "program_id", "teach_out_end_date", "student_notification_date",
    "asset_transfer_scope", "status", "affected_enrollment_count",
    "remaining_credit_count", "teach_out_cost_cents", "holdback_applied_cents",
    "partner_obligation_cents", "university_residual_cents",
    "transferred_asset_value_cents", "partner_obligation_note",
    "certified_by_user_id", "certified_at",
)


def _shape(entity, fields):
    return {name: entity.get(name) for name in fields}


def partnership(entity):
    return _shape(entity, PARTNERSHIP_FIELDS)


def program(entity):
    return _shape(entity, PROGRAM_FIELDS)


def course(entity):
    return _shape(entity, COURSE_FIELDS)


def assignment(entity):
    return _shape(entity, ASSIGNMENT_FIELDS)


def counselor(entity):
    return _shape(entity, COUNSELOR_FIELDS)


def lead(entity):
    return _shape(entity, LEAD_FIELDS)


def enrollment(entity):
    return _shape(entity, ENROLLMENT_FIELDS)


def tuition_payment(entity):
    return _shape(entity, TUITION_FIELDS)


def marketing_entry(entity):
    return _shape(entity, MARKETING_FIELDS)


def statement(entity):
    return _shape(entity, STATEMENT_FIELDS)


def teach_out_plan(entity):
    return _shape(entity, TEACH_OUT_FIELDS)


def many(fn, items):
    return [fn(item) for item in items]
