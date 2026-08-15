"""Entity serializers: project internal records to their public field set."""
from db import fmt_iso

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "matter": {
        "fields": (
            "matter_number", "title", "matter_type", "adverse_party", "jurisdiction",
            "filing_date", "status", "exposure_low_cents", "exposure_high_cents",
            "probability_of_loss_pct", "exposure_tier", "reserve_amount_cents",
            "accrued_to_date_cents", "posture", "resolution_type", "resolved_at",
            "owning_counsel_id", "close_checklist_ack",
        ),
        "dt": ("filing_date", "resolved_at"),
        "common": True,
    },
    "staff_user": {
        "fields": ("full_name", "email", "job_family", "is_active"),
        "dt": (),
        "common": True,
    },
    "firm": {
        "fields": (
            "firm_name", "panel_status", "conflict_check_status",
            "blended_rate_cap_cents", "is_active",
        ),
        "dt": (),
        "common": True,
    },
    "engagement": {
        "fields": (
            "matter_id", "firm_id", "role_type", "status", "fee_arrangement",
            "proposed_rate_cents", "contingency_pct", "approved_by_user_id",
            "engagement_letter_executed", "supersedes_engagement_id",
        ),
        "dt": (),
        "common": True,
    },
    "budget": {
        "fields": (
            "matter_id", "fiscal_year", "lifecycle_budget_cents", "fy_budget_cents",
            "status", "submitted_by_user_id", "approved_by_user_id",
            "utilization_pct", "prior_version_id",
        ),
        "dt": (),
        "common": True,
    },
    "accrual": {
        # Append-only ledger row: id and created_at only (PRD 2.4).
        "fields": (
            "matter_id", "engagement_id", "period", "entry_kind", "amount_cents",
            "status", "submitted_at", "reverses_entry_id",
        ),
        "dt": ("submitted_at",),
        "common": False,
    },
    "hold": {
        "fields": (
            "matter_id", "scope_description", "status", "issued_at", "released_at",
            "release_reason",
        ),
        "dt": ("issued_at", "released_at"),
        "common": True,
    },
    "custodian": {
        "fields": (
            "hold_id", "staff_user_id", "status", "noticed_at", "acknowledged_at",
            "escalation_count", "exemption_reason",
        ),
        "dt": ("noticed_at", "acknowledged_at"),
        "common": True,
    },
    "vendor": {
        "fields": (
            "vendor_name", "security_clearance_level", "capacity_gb", "committed_gb",
            "is_active",
        ),
        "dt": (),
        "common": True,
    },
    "work_order": {
        "fields": (
            "matter_id", "vendor_id", "hold_id", "service_type", "status",
            "estimated_gb", "actual_gb", "rate_per_gb_cents", "scheduled_start",
            "scheduled_end", "estimated_cost_cents",
        ),
        "dt": ("scheduled_start", "scheduled_end"),
        "common": True,
    },
    "deadline": {
        "fields": (
            "matter_id", "deadline_type", "title", "due_at", "status",
            "is_jurisdictional", "completed_at", "reminder_days",
        ),
        "dt": ("due_at", "completed_at"),
        "common": True,
    },
    "policy": {
        "fields": (
            "tier", "approver_role", "max_single_amount_cents",
            "dual_approval_required_over_cents", "is_active",
        ),
        "dt": (),
        "common": True,
    },
    "settlement": {
        "fields": (
            "matter_id", "proposed_amount_cents", "settlement_kind", "status",
            "counter_amount_cents", "requested_by_user_id", "approved_by_user_ids",
            "authority_tier_at_submission", "terms_summary", "expires_at",
        ),
        "dt": ("expires_at",),
        "common": True,
    },
    "payment": {
        "fields": (
            "matter_id", "settlement_request_id", "payment_kind", "amount_cents",
            "payee_name", "status", "payment_status", "submitted_by_user_id",
            "approved_by_user_id", "disbursed_at",
        ),
        "dt": ("disbursed_at",),
        "common": True,
    },
}


def serialize(kind, rec):
    spec = FIELDS[kind]
    out = {"id": rec["id"]}
    for field in spec["fields"]:
        value = rec.get(field)
        if field in spec["dt"]:
            out[field] = fmt_iso(value) if value is not None else None
        else:
            out[field] = value
    if spec["common"]:
        out["created_at"] = rec["created_at"]
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    else:
        out["created_at"] = rec["created_at"]
    return out
