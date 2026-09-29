"""Route helpers: existence resolution and the declared-field sets used for sort keys."""

from core import check_owner
from errors import ApiError
from store import store

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "FeeSchedule": COMMON + (
        "schedule_code", "status", "effective_from", "counting_window_mode",
        "free_alarm_allowance", "fee_tiers", "occupancy_multipliers",
        "non_ecv_surcharge_pct", "unpermitted_multiplier",
        "suspension_period_aggravation_cents", "per_incident_fee_cap_cents",
        "probation_threshold_count", "suspension_threshold_count",
        "appeal_filing_days", "permit_term_days", "renewal_grace_days",
        "new_installation_grace_days", "permit_issue_fee_cents",
        "permit_renewal_fee_cents", "late_renewal_tiers",
        "unpermitted_operation_penalty_cents", "reinstatement_base_fee_cents",
        "reinstatement_escalation_pct", "admin_fee_pct", "admin_fee_min_cents",
        "admin_fee_max_cents", "invoice_due_days", "late_penalty_pct",
        "delinquency_days", "collections_referral_threshold_cents",
        "delinquent_balance_block_cents", "exempt_cause_codes",
        "company_probation_score_threshold", "company_suspension_score_threshold",
        "superseded_at"),
    "AlarmCompany": COMMON + (
        "legal_name", "license_number", "contact_email", "contact_phone",
        "status", "score_mode", "reporting_compliance_score",
        "monitored_system_count", "dispatch_request_count_lifetime",
        "consecutive_flagged_report_count", "probation_started_at",
        "status_reason", "last_status_action_at"),
    "AlarmSite": COMMON + (
        "address_key", "street_address", "city", "zip_code", "occupancy_class",
        "police_beat", "status", "governing_fee_schedule_id", "response_status",
        "chargeable_count_window", "chargeable_count_rolling_365",
        "chargeable_count_permit_year", "lifetime_assessed_cents",
        "outstanding_balance_cents", "credit_balance_cents",
        "unpermitted_system_count", "lifted_suspension_count",
        "ecv_callable_contact_count", "renewal_block_active"),
    "SiteContact": COMMON + (
        "alarm_site_id", "full_name", "phone_number", "relationship",
        "contact_priority", "is_ecv_callable", "status", "removed_at"),
    "AlarmSystem": COMMON + (
        "alarm_site_id", "monitoring_company_id", "system_type", "zone_count",
        "ecv_enabled", "verified_response_mode", "status", "installed_at",
        "permitted_at", "unpermitted_since", "rejection_reason",
        "decommissioned_at"),
    "AlarmPermit": COMMON + (
        "alarm_system_id", "alarm_site_id", "permit_number", "status",
        "term_start_at", "term_end_at", "grace_through_at",
        "new_installation_grace_through", "renewal_count", "issued_by_user_id",
        "last_renewed_at", "revocation_reason"),
    "DispatchRequest": COMMON + (
        "alarm_system_id", "alarm_site_id", "monitoring_company_id",
        "alarm_type", "verification_method", "call_attempts",
        "distinct_ecv_contact_count", "audio_video_evidence", "guard_on_scene",
        "occurred_at", "status", "ecv_sufficient",
        "system_permitted_at_occurrence", "refusal_reason", "validated_at",
        "validated_by_user_id", "dispatched_at", "idempotency_key"),
    "FalseAlarmIncident": COMMON + (
        "dispatch_request_id", "alarm_site_id", "alarm_system_id", "occurred_at",
        "cause_code", "status", "determination", "exempt_cause_code",
        "determined_at", "determined_by_user_id", "occurrence_index",
        "assessed_fee_cents", "fee_basis", "counted_window_mode", "appeal_count",
        "narrative"),
    "HearingDocket": COMMON + (
        "hearing_officer_user_id", "session_start", "session_end", "location",
        "capacity", "scheduled_appeal_count", "status", "held_at"),
    "Appeal": COMMON + (
        "false_alarm_incident_id", "alarm_site_id", "hearing_docket_id",
        "prior_appeal_id", "filed_by_user_id", "grounds", "narrative",
        "filed_at", "status", "decision", "decided_at", "decided_by_user_id",
        "findings", "rehearing_depth"),
    "SuspensionOrder": COMMON + (
        "alarm_site_id", "triggering_incident_id", "basis", "status",
        "effective_from", "effective_through", "suspension_sequence",
        "reinstatement_fee_cents", "probation_days", "required_conditions",
        "served_at", "reinstatement_requested_at", "technician_inspection_date",
        "ecv_attestation", "lifted_at", "vacated_reason"),
    "PenaltyInvoice": COMMON + (
        "alarm_site_id", "false_alarm_incident_id", "alarm_permit_id",
        "suspension_order_id", "invoice_number", "kind", "line_items",
        "subtotal_cents", "admin_fee_cents", "assessed_cents", "paid_cents",
        "adjusted_cents", "outstanding_cents", "payment_status",
        "collections_stage", "issued_on", "due_on", "late_penalty_cents",
        "days_delinquent", "referral_total_cents", "referral_agency",
        "referred_on"),
    "PaymentRecord": COMMON + (
        "alarm_site_id", "amount_cents", "tendered_on", "method",
        "allocation_mode", "receipt_number", "recorded_by_user_id", "status",
        "allocated_cents", "credited_cents", "voided_at", "void_reason"),
    "PaymentAllocation": ("id", "created_at", "payment_record_id",
                          "penalty_invoice_id", "amount_cents",
                          "sequence_index", "status"),
    "ComplianceReport": COMMON + (
        "monitoring_company_id", "period_start", "period_end",
        "reported_dispatch_count", "reported_cancellation_count",
        "ecv_attempt_count", "system_dispatch_count", "variance_count",
        "variance_pct", "period_accuracy", "period_ecv_rate", "period_score",
        "status", "correction_count", "reviewed_at", "reviewed_by_user_id",
        "variance_notes"),
}

_TABLE_FOR = {
    "FeeSchedule": ("fee_schedules", "ERR_FEE_SCHEDULE_NOT_FOUND"),
    "AlarmCompany": ("alarm_companies", "ERR_ALARM_COMPANY_NOT_FOUND"),
    "AlarmSite": ("alarm_sites", "ERR_ALARM_SITE_NOT_FOUND"),
    "SiteContact": ("site_contacts", "ERR_SITE_CONTACT_NOT_FOUND"),
    "AlarmSystem": ("alarm_systems", "ERR_ALARM_SYSTEM_NOT_FOUND"),
    "AlarmPermit": ("alarm_permits", "ERR_ALARM_PERMIT_NOT_FOUND"),
    "DispatchRequest": ("dispatch_requests", "ERR_DISPATCH_REQUEST_NOT_FOUND"),
    "FalseAlarmIncident": ("false_alarm_incidents",
                           "ERR_FALSE_ALARM_INCIDENT_NOT_FOUND"),
    "HearingDocket": ("hearing_dockets", "ERR_HEARING_DOCKET_NOT_FOUND"),
    "Appeal": ("appeals", "ERR_APPEAL_NOT_FOUND"),
    "SuspensionOrder": ("suspension_orders", "ERR_SUSPENSION_ORDER_NOT_FOUND"),
    "PenaltyInvoice": ("penalty_invoices", "ERR_PENALTY_INVOICE_NOT_FOUND"),
    "PaymentRecord": ("payment_records", "ERR_PAYMENT_RECORD_NOT_FOUND"),
    "PaymentAllocation": ("payment_allocations",
                          "ERR_PAYMENT_ALLOCATION_NOT_FOUND"),
    "ComplianceReport": ("compliance_reports", "ERR_COMPLIANCE_REPORT_NOT_FOUND"),
}


def fields(entity):
    return set(FIELDS[entity])


def resolve(entity, row_id):
    table, error_id = _TABLE_FOR[entity]
    row = getattr(store, table).get(row_id)
    if row is None:
        raise ApiError(error_id, "%s %s does not exist." % (entity, row_id))
    return row


def all_rows(entity):
    table = _TABLE_FOR[entity][0]
    from store import order_key
    return sorted(getattr(store, table).values(), key=order_key)


def own_site(ctx, site_id):
    check_owner(ctx, site_id=site_id)


def own_company(ctx, company_id):
    check_owner(ctx, company_id=company_id)


def scope_reads(ctx, rows, site_field="alarm_site_id",
                company_field="monitoring_company_id"):
    """Entity-backed roles read only their own aggregate."""
    if ctx.role == "AlarmUser" and site_field:
        return [r for r in rows if r.get(site_field) == ctx.user_id]
    if ctx.role == "AlarmCompanyOperator" and company_field:
        return [r for r in rows if r.get(company_field) == ctx.user_id]
    return rows
