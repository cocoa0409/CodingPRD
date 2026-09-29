"""
Entity shape descriptors for the Ground Lease Administration API.

PRD.md §2.4 gives every persisted resource `id`, `created_at`, `updated_at` and
`version`, with one stated exception: an `AppraisalSubmission` "carries only an
`id` and a `created_at`. It has no `updated_at` and no `version` field at all,
and neither key appears in its response payload."
"""

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# The sole entity declared without the full common-field block (§2.4).
APPRAISAL_SUBMISSION_FIELDS = ("id", "created_at")
ENTITIES_WITHOUT_VERSION = ("AppraisalSubmission",)

LESSEE_INPUT_FIELDS = ("legal_name", "notice_email", "credit_rating_code")

LEASE_INPUT_FIELDS = (
    "lessee_id",
    "premises_code",
    "commencement_date",
    "expiration_date",
    "initial_annual_base_rent_cents",
    "revaluation_interval_years",
    "reval_collar_min_uplift_bps",
    "reval_collar_max_uplift_bps",
    "percentage_rent_rate_bps",
    "percentage_rent_breakpoint_cents",
    "permitted_use_code",
    "total_permitted_gfa_sqft",
    "improvements_value_cents",
    "reversion_land_value_cents",
    "reversion_standard_code",
    "security_deposit_cents",
)

# Server-derived lease fields — a lease creation response must already carry
# them (PRD §3.1 seeding narrative and §2.4 write-response rule).
LEASE_DERIVED_FIELDS = (
    "lease_status",
    "rent_status",
    "current_annual_base_rent_cents",
    "next_revaluation_date",
    "arrears_balance_cents",
    "gfa_allocated_sqft",
    "gfa_unallocated_sqft",
    "deposit_held_cents",
    "deposit_applied_cents",
    "deposit_refunded_cents",
    "percentage_rent_sublease_base_cents",
    "insurance_status",
)

TRANSFER_DERIVED_FIELDS = (
    "status",
    "tier_depth",
    "submitted_late",
    "allocable_base_rent_cents",
    "transfer_fee_gross_cents",
    "admin_charge_cents",
    "late_surcharge_cents",
    "total_transfer_fee_cents",
    "transfer_fee_paid_cents",
)

STATEMENT_DERIVED_FIELDS = (
    "status",
    "base_rent_offset_credit_cents",
    "included_sublease_rent_cents",
    "gross_percentage_rent_cents",
    "amount_due_cents",
)

LOSS_EVENT_ALLOCATION_FIELDS = (
    "allocated_arrears_cents",
    "allocated_mortgagee_cents",
    "allocated_lessee_cents",
    "allocated_lessor_cents",
)

REVERSION_FIELDS = (
    "status",
    "required_standard_code",
    "weighted_score_bps",
    "deficiency_bps",
    "holdback_cents",
)
