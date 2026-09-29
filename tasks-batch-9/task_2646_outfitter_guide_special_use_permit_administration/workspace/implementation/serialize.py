"""Resource serializers -- one per entity, field lists straight off the scaffold."""

from decimal import Decimal


def _pub(rec, fields):
    out = {"id": rec["id"]}
    for f in fields:
        v = rec.get(f)
        out[f] = float(v) if isinstance(v, Decimal) else v
    out["created_at"] = rec["created_at"]
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if "version" in rec:
        out["version"] = rec["version"]
    return out


OUTFITTER_FIELDS = [
    "legal_name",
    "ein",
    "contact_email",
    "prequalification_insurance_verified",
    "status",
    "prior_permit_count",
    "active_permit_count",
]

USE_AREA_FIELDS = [
    "area_code",
    "name",
    "total_allocated_service_days",
    "reserved_admin_service_days",
    "season_year",
    "season_open_date",
    "season_close_date",
    "party_size_max",
    "max_clients_per_guide",
    "min_liability_coverage_cents",
    "allocatable_service_days",
    "committed_service_days",
    "pending_service_days",
    "available_service_days",
    "demand_ratio",
    "allocation_posture",
]

NEEDS_ASSESSMENT_FIELDS = [
    "use_area_id",
    "assessment_year",
    "public_need_finding",
    "determined_capacity_service_days",
    "allocated_service_days",
    "unallocated_service_days",
    "prospectus_required",
    "status",
    "published_at",
]

PROSPECTUS_FIELDS = [
    "use_area_id",
    "needs_assessment_id",
    "offered_service_days",
    "submission_deadline_date",
    "min_qualifying_score",
    "responsive_application_count",
    "awarded_application_id",
    "cancellation_reason_code",
    "status",
]

APPLICATION_FIELDS = [
    "outfitter_id",
    "use_area_id",
    "prospectus_id",
    "predecessor_permit_id",
    "application_type",
    "season_year",
    "requested_service_days",
    "proposed_activity_type",
    "narrative",
    "status",
    "routing_decision",
    "hold_expires_at",
    "preliminary_evaluation_score",
    "final_evaluation_score",
    "denial_reason_code",
    "screened_at",
]

PERMIT_FIELDS = [
    "outfitter_id",
    "use_area_id",
    "application_id",
    "predecessor_permit_id",
    "authorized_service_days",
    "term_start_date",
    "term_end_date",
    "fee_schedule_code",
    "indemnification_acknowledged",
    "administrative_status",
    "compliance_status",
    "open_noncompliance_points",
    "insurance_current",
    "bond_current",
    "fee_delinquent",
    "authorized_client_capacity_total",
    "service_days_used_ytd",
    "suspension_count",
    "suspended_until_date",
    "suspension_reason_code",
    "revocation_reason_code",
    "latest_performance_rating",
]

OPERATING_PLAN_FIELDS = [
    "permit_id",
    "plan_year",
    "sanitation_section",
    "campsite_section",
    "stock_section",
    "resource_protection_section",
    "completeness_score",
    "status",
    "revision_round",
    "deficiency_sections",
    "reviewed_by_user_id",
    "approved_by_user_id",
    "rejection_reason_code",
]

GUIDE_FIELDS = [
    "outfitter_id",
    "full_name",
    "qualification_level",
    "first_aid_cert_type",
    "first_aid_expires_on",
    "seasons_experience",
    "base_client_capacity",
    "status",
    "qualified_at",
]

AUTHORIZATION_FIELDS = [
    "guide_id",
    "permit_id",
    "authorized_client_capacity",
    "status",
    "authorized_at",
    "revoked_at",
    "revocation_reason_code",
]

INSURANCE_FIELDS = [
    "permit_id",
    "coverage_type",
    "carrier_name",
    "coverage_amount_cents",
    "effective_date",
    "expiration_date",
    "additional_insured_endorsed",
    "status",
]

BOND_FIELDS = [
    "permit_id",
    "bond_amount_cents",
    "surety_name",
    "effective_date",
    "expiration_date",
    "required_amount_cents",
    "status",
]

USE_REPORT_FIELDS = [
    "permit_id",
    "supersedes_report_id",
    "period_start_date",
    "period_end_date",
    "season_year",
    "service_days_used",
    "client_count",
    "gross_revenue_cents",
    "allowable_deductions_cents",
    "adjusted_gross_revenue_cents",
    "applied_rate_bp",
    "fee_component_cents",
    "status",
    "accepted_at",
]

FEE_ASSESSMENT_FIELDS = [
    "permit_id",
    "season_year",
    "variant_applied",
    "reported_agr_cents",
    "assessed_fee_cents",
    "minimum_fee_applied",
    "paid_to_date_cents",
    "balance_due_cents",
    "credit_balance_cents",
    "status",
    "finalized_at",
]

EVALUATION_FIELDS = [
    "permit_id",
    "evaluation_year",
    "resource_protection_score",
    "client_safety_score",
    "reporting_timeliness_score",
    "fee_compliance_score",
    "raw_score",
    "provisional_band",
    "penalty_points_applied",
    "weighted_score",
    "rating",
    "evaluator_user_id",
]

ACTION_FIELDS = [
    "permit_id",
    "severity",
    "action_type",
    "cited_provision",
    "cure_deadline_date",
    "points",
    "status",
    "issued_by_user_id",
    "appeal_basis",
    "appeal_decided_by_user_id",
    "corrective_summary",
]


def outfitter(r):
    return _pub(r, OUTFITTER_FIELDS)


def use_area(r):
    return _pub(r, USE_AREA_FIELDS)


def needs_assessment(r):
    return _pub(r, NEEDS_ASSESSMENT_FIELDS)


def prospectus(r):
    return _pub(r, PROSPECTUS_FIELDS)


def application(r):
    return _pub(r, APPLICATION_FIELDS)


def permit(r):
    return _pub(r, PERMIT_FIELDS)


def operating_plan(r):
    return _pub(r, OPERATING_PLAN_FIELDS)


def guide(r):
    return _pub(r, GUIDE_FIELDS)


def authorization(r):
    return _pub(r, AUTHORIZATION_FIELDS)


def insurance_certificate(r):
    return _pub(r, INSURANCE_FIELDS)


def bond(r):
    return _pub(r, BOND_FIELDS)


def use_report(r):
    return _pub(r, USE_REPORT_FIELDS)


def fee_assessment(r):
    return _pub(r, FEE_ASSESSMENT_FIELDS)


def evaluation(r):
    return _pub(r, EVALUATION_FIELDS)


def action(r):
    return _pub(r, ACTION_FIELDS)
