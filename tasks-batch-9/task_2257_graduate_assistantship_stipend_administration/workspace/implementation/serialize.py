"""Entity serialisers: exact field sets, Decimals rendered as JSON numbers."""
from decimal import Decimal

COMMON = ("id", "created_at", "updated_at", "version")

TERM_FIELDS = COMMON + (
    "term_code", "term_start", "term_end", "tax_calendar_year", "session_type",
    "proration_method", "remission_drop_deadline", "status", "pay_period_count",
    "locked_at", "closed_at",
)

DEPARTMENT_FIELDS = COMMON + ("code", "name", "non_renewal_notice_days")

POLICY_FIELDS = COMMON + (
    "term_id", "assistantship_type", "degree_level", "min_fte_monthly_stipend_cents",
    "insurance_min_effort_pct", "min_insurance_duration_days", "per_credit_tuition_cents",
    "max_remission_cents_per_term", "term_insurance_premium_cents",
    "tuition_tax_exempt_cap_cents",
)

PAY_PERIOD_FIELDS = COMMON + (
    "term_id", "sequence_no", "period_start", "period_end_exclusive", "pay_date",
    "calendar_day_count", "workday_count", "status",
)

STUDENT_FIELDS = COMMON + (
    "student_number", "full_name", "degree_level", "is_international", "visa_type",
    "enrolled_credit_hours", "cumulative_gpa", "external_weekly_hours", "sap_status",
    "effort_cap_pct", "cap_override_by_user_id", "cap_override_justification",
    "total_effort_pct", "assigned_hours_per_week", "tuition_benefit_ytd_cents",
    "taxable_tuition_benefit_ytd_cents",
)

FUNDING_SOURCE_FIELDS = COMMON + (
    "department_id", "source_code", "source_type", "sponsor_code",
    "authorized_amount_cents", "budget_period_start", "budget_period_end",
    "allows_tuition_remission", "grant_effort_cap_pct", "auto_reinstate_threshold_cents",
    "committed_amount_cents", "expended_amount_cents", "available_amount_cents",
    "status", "suspension_reason",
)

APPOINTMENT_FIELDS = COMMON + (
    "student_id", "department_id", "term_id", "renewed_from_appointment_id",
    "assistantship_type", "effort_pct", "start_date", "end_date",
    "monthly_stipend_cents", "supervisor_user_id", "weekly_hours", "duration_days",
    "tuition_remission_pct", "insurance_eligible", "projected_pay_period_count",
    "total_stipend_cents", "tuition_remission_cents", "insurance_subsidy_cents",
    "employee_premium_cents", "net_term_stipend_cents", "lifecycle_status",
    "payroll_status", "renewal_eligible", "submitted_by_user_id",
    "approved_by_user_id", "return_reason", "pay_suspension_reason",
    "termination_reason", "termination_date",
)

ALLOCATION_FIELDS = COMMON + (
    "appointment_id", "funding_source_id", "share_pct", "is_cost_share",
    "plan_sequence", "allocated_stipend_cents", "allocated_remission_cents",
    "disbursed_amount_cents", "status", "release_reason",
)

DISBURSEMENT_FIELDS = COMMON + (
    "appointment_id", "pay_period_id", "proration_method_applied", "covered_units",
    "period_units", "gross_amount_cents", "allocation_split", "status", "paid_at",
    "voided_at", "reversed_at", "reversal_reason",
)

RENEWAL_FIELDS = COMMON + (
    "appointment_id", "renewal_window_open_date", "notice_deadline_date", "decision",
    "sap_certified", "certified_by_user_id", "certified_at", "issued_by_user_id",
    "notice_sent_date", "acknowledged_at", "revision_count", "status",
)

ASSESSMENT_FIELDS = COMMON + (
    "student_id", "term_id", "tax_calendar_year", "variant_applied", "benefit_cents",
    "exempt_cents", "taxable_cents", "imputed_withholding_cents", "status",
    "amendment_reason",
)


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    return value


def _view(row, fields):
    return dict((name, _plain(row.get(name))) for name in fields)


def term(row):
    return _view(row, TERM_FIELDS)


def department(row):
    return _view(row, DEPARTMENT_FIELDS)


def policy(row):
    return _view(row, POLICY_FIELDS)


def pay_period(row):
    return _view(row, PAY_PERIOD_FIELDS)


def student(row):
    return _view(row, STUDENT_FIELDS)


def funding_source(row):
    return _view(row, FUNDING_SOURCE_FIELDS)


def appointment(row):
    return _view(row, APPOINTMENT_FIELDS)


def allocation(row):
    return _view(row, ALLOCATION_FIELDS)


def disbursement(row):
    return _view(row, DISBURSEMENT_FIELDS)


def renewal(row):
    return _view(row, RENEWAL_FIELDS)


def assessment(row):
    return _view(row, ASSESSMENT_FIELDS)
