"""Response payload field lists, in declaration order, plus list helpers."""

from envelope import list_response
from store import sort_key

AUDIT = ["created_at", "updated_at", "version"]

LOCATION = [
    "id",
    "name",
    "state_code",
    "state_min_wage_cents",
    "cash_wage_cents",
    "tip_credit_enabled",
    "cc_fee_policy",
    "cc_fee_cap_bps",
    "service_charge_treatment",
    "applicable_min_wage_cents",
    "max_tip_credit_per_hour_cents",
    "pending_pool_cents",
] + AUDIT

JOB_ROLE = [
    "id",
    "code",
    "title",
    "tip_status",
    "is_management",
    "pool_contribution_pct_bps",
    "pool_share_points",
    "side_work_eligible",
] + AUDIT

EMPLOYEE = [
    "id",
    "location_id",
    "full_name",
    "external_payroll_ref",
    "monthly_tip_baseline_cents",
    "separation_date",
    "trailing_pool_receipts_cents",
] + AUDIT

ROLE_ASSIGNMENT = [
    "id",
    "employee_id",
    "job_role_id",
    "effective_from",
    "effective_to",
    "tip_credit_notice_acknowledged_at",
    "is_primary",
    "dual_job",
] + AUDIT

POLICY = [
    "id",
    "location_id",
    "pool_type",
    "contribution_basis",
    "share_basis",
    "cc_fee_pass_through",
    "status",
    "activated_at",
] + AUDIT

PAY_PERIOD = [
    "id",
    "location_id",
    "start_date",
    "end_date",
    "status",
    "compute_variant",
    "computed_by_user_id",
    "approved_by_user_id",
    "total_credited_minutes",
    "total_tip_credit_cents",
    "total_topup_cents",
    "total_correction_cents",
    "gross_receipts_cents",
    "reported_tips_cents",
    "allocation_shortfall_cents",
] + AUDIT

SHIFT = [
    "id",
    "employee_id",
    "location_id",
    "job_role_id",
    "pay_period_id",
    "shift_tip_pool_id",
    "business_date",
    "start_at",
    "end_at",
    "scheduled_minutes",
    "side_work_minutes",
    "max_continuous_side_work_minutes",
    "non_tip_credit_minutes",
    "tip_credit_eligible_minutes",
    "gross_sales_cents",
    "charged_sales_cents",
    "cc_processing_fee_bps",
    "declared_cash_tips_cents",
    "declared_charged_tips_cents",
    "declaration_count",
    "time_status",
    "declaration_status",
    "pool_contribution_cents",
    "retained_tips_cents",
    "shift_tip_credit_cents",
] + AUDIT

SERVICE_CHARGE = [
    "id",
    "location_id",
    "allocated_pool_id",
    "allocated_pay_period_id",
    "business_date",
    "amount_cents",
    "description",
    "treatment_override",
    "treatment",
    "status",
] + AUDIT

POOL = [
    "id",
    "location_id",
    "tip_pool_policy_id",
    "policy_version_pinned",
    "business_date",
    "contribution_status",
    "distribution_status",
    "contributing_shift_count",
    "participant_count",
    "total_contributed_cents",
    "service_charge_tips_cents",
    "cc_fee_deducted_cents",
    "net_pool_cents",
    "total_share_weight",
    "distributed_cents",
    "distributed_at",
    "reversed_at",
] + AUDIT

ALLOCATION = [
    "id",
    "shift_tip_pool_id",
    "employee_id",
    "shift_id",
    "entry_type",
    "share_weight",
    "allocated_cents",
    "remainder_cent_awarded",
    "business_date",
    "created_at",
]

PAY_LINE = [
    "id",
    "pay_period_id",
    "employee_id",
    "variant",
    "status",
    "total_minutes",
    "tip_credit_eligible_minutes",
    "non_tip_credit_minutes",
    "regular_minutes",
    "overtime_minutes",
    "straight_cash_cents",
    "service_charge_wages_cents",
    "regular_rate_cents_per_hour",
    "overtime_premium_cents",
    "minimum_wage_obligation_cents",
    "tips_available_cents",
    "pool_tips_cents",
    "retained_tips_cents",
    "tipped_employee_qualified",
    "tip_credit_cents",
    "topup_cents",
    "total_gross_cents",
    "reported_tips_cents",
    "allocated_tips_cents",
    "correction_applied_cents",
    "pending_correction_cents",
    "open_dispute_count",
] + AUDIT

DISPUTE = [
    "id",
    "pay_line_id",
    "raised_by_employee_id",
    "category",
    "claimed_amount_cents",
    "narrative",
    "status",
    "adjudicated_amount_cents",
    "adjudicated_by_user_id",
    "closed_at",
] + AUDIT

CORRECTION = [
    "id",
    "pay_line_id",
    "dispute_id",
    "supersedes_correction_id",
    "amount_cents",
    "reason_code",
    "status",
    "issued_by_user_id",
    "applied_by_user_id",
    "applied_at",
    "voided_at",
] + AUDIT


def view(record, fields):
    return {name: record.get(name) for name in fields}


def paged(rows, fields, limit, offset):
    """Order by created_at ascending, apply the window, wrap in the envelope."""
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return list_response([view(r, fields) for r in window], limit, offset, total)


def apply_filters(rows, filters):
    out = rows
    for key, value in filters.items():
        out = [r for r in out if r.get(key) == value]
    return out
