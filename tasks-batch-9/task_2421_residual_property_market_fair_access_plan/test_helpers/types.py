"""Field inventories for every persisted record in the plan.

These are used by the assertion helpers to check the audit-field contract of
PRD 2.4: most records carry ``id``, ``created_at``, ``updated_at`` and
``version``, while a declination record carries only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List

# A record is a plain JSON object as returned inside the response envelope.
Record = Dict[str, Any]
RecordList = List[Record]

IDENTITY_FIELDS = ("id", "created_at")
MUTATION_FIELDS = ("updated_at", "version")
COMMON_FIELDS = IDENTITY_FIELDS + MUTATION_FIELDS

# PRD 2.4: "The records carrying all four fields are member insurers,
# producers, applicants, catastrophe zones, properties, applications,
# inspections, improvement requirements, rate filings, policies, take-out
# offers, assessment events and assessment allocations."
VERSIONED_ENTITIES = (
    "MemberInsurer",
    "Producer",
    "Applicant",
    "CatastropheZone",
    "Property",
    "Application",
    "Inspection",
    "ImprovementRequirement",
    "RateFiling",
    "Policy",
    "TakeoutOffer",
    "AssessmentEvent",
    "AssessmentAllocation",
)

# PRD 2.4: "A declination record ... carries only id and created_at. Both
# updated_at and version are absent from a declination record entirely."
UNVERSIONED_ENTITIES = ("DeclinationRecord",)

MEMBER_INSURER_FIELDS = (
    "id",
    "name",
    "naic_code",
    "market_share_pct",
    "written_premium_share_pct",
    "status",
    "takeout_credit_count",
    "cumulative_assessed_cents",
    "created_at",
    "updated_at",
    "version",
)

CAT_ZONE_FIELDS = (
    "id",
    "code",
    "peril",
    "exposure_cap_cents",
    "restricted_min_condition_score",
    "aggregate_insured_value_cents",
    "concentration_ratio",
    "status",
    "created_at",
    "updated_at",
    "version",
)

PRODUCER_FIELDS = (
    "id",
    "full_name",
    "license_number",
    "commission_tier",
    "e_and_o_expiry_date",
    "agreement_status",
    "agreement_effective_date",
    "commission_rate_bps",
    "ytd_commission_cents",
    "created_at",
    "updated_at",
    "version",
)

APPLICANT_FIELDS = (
    "id",
    "full_name",
    "email",
    "phone",
    "created_at",
    "updated_at",
    "version",
)

PROPERTY_FIELDS = (
    "id",
    "cat_zone_id",
    "address_line",
    "zip_code",
    "construction_type",
    "roof_age_years",
    "replacement_cost_cents",
    "condition_score",
    "occupancy",
    "created_at",
    "updated_at",
    "version",
)

APPLICATION_FIELDS = (
    "id",
    "property_id",
    "applicant_id",
    "producer_id",
    "requested_dwelling_limit_cents",
    "requested_peril_package",
    "status",
    "declination_count",
    "quoted_annual_premium_cents",
    "voluntary_equivalent_premium_cents",
    "voluntary_market_comparison_pct",
    "quote_rate_filing_id",
    "submitted_at",
    "eligibility_hold_reason",
    "decline_reason",
    "eligibility_reviewer_user_id",
    "approved_to_bind_at",
    "bind_deadline_at",
    "created_at",
    "updated_at",
    "version",
)

DECLINATION_FIELDS = (
    "id",
    "application_id",
    "member_insurer_id",
    "declined_on",
    "reason_code",
    "evidence_reference",
    "verified",
    "created_at",
)

INSPECTION_FIELDS = (
    "id",
    "application_id",
    "scheduled_for",
    "ordered_at",
    "completed_at",
    "inspector_user_id",
    "observed_condition_score",
    "result",
    "open_requirement_count",
    "cleared_major_count",
    "created_at",
    "updated_at",
    "version",
)

IMPROVEMENT_REQUIREMENT_FIELDS = (
    "id",
    "inspection_id",
    "code",
    "severity",
    "status",
    "due_at",
    "evidence_reference",
    "cleared_at",
    "waiver_reason",
    "created_at",
    "updated_at",
    "version",
)

RATE_FILING_FIELDS = (
    "id",
    "cat_zone_id",
    "peril_package",
    "filed_rate_per_1000_cents",
    "voluntary_market_avg_rate_per_1000_cents",
    "differential_pct",
    "effective_date",
    "status",
    "filed_by_user_id",
    "reviewed_by_user_id",
    "review_note",
    "created_at",
    "updated_at",
    "version",
)

POLICY_FIELDS = (
    "id",
    "application_id",
    "property_id",
    "applicant_id",
    "producer_id",
    "rate_filing_id",
    "predecessor_policy_id",
    "dwelling_limit_cents",
    "peril_package",
    "excluded_perils",
    "condition_score_at_bind",
    "exposure_value_cents",
    "effective_date",
    "expiration_date",
    "coverage_status",
    "depopulation_status",
    "base_premium_cents",
    "cat_surcharge_cents",
    "annual_premium_cents",
    "commission_credited_cents",
    "commission_returned_cents",
    "unearned_premium_cents",
    "cancellation_fee_cents",
    "refund_cents",
    "cancel_reason",
    "cancellation_date",
    "created_at",
    "updated_at",
    "version",
)

TAKEOUT_OFFER_FIELDS = (
    "id",
    "policy_id",
    "member_insurer_id",
    "offered_premium_cents",
    "comparable_coverage_flag",
    "election_deadline_at",
    "status",
    "elected_at",
    "withdrawal_reason",
    "credit_units_granted",
    "created_at",
    "updated_at",
    "version",
)

ASSESSMENT_EVENT_FIELDS = (
    "id",
    "cat_zone_id",
    "trigger_loss_cents",
    "reserve_balance_cents_at_trigger",
    "assessable_amount_cents",
    "allocation_basis",
    "status",
    "allocated_total_cents",
    "remainder_cents",
    "allocation_run_count",
    "cancellation_reason",
    "created_at",
    "updated_at",
    "version",
)

ASSESSMENT_ALLOCATION_FIELDS = (
    "id",
    "assessment_event_id",
    "member_insurer_id",
    "basis_weight_pct",
    "gross_share_cents",
    "takeout_credit_applied_cents",
    "net_due_cents",
    "credits_consumed",
    "status",
    "paid_at",
    "created_at",
    "updated_at",
    "version",
)
