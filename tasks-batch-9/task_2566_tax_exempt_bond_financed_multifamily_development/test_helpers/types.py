"""The shape of every stored row, and the tables that index the fourteen of them.

The field tuples below are the response contract: what a read of that resource
must expose. They are used by the assertion helpers to prove a row carries the
whole quartet of common properties and every derived figure the PRD names, rather
than only the handful a particular test happens to look at.
"""

from .api_errors import ApiErrorId
from .constants import COMMON_FIELDS

# ─── Entity names, in the declaration order of PRD §3 ──
# That order is load-bearing: when one body carries more than one unresolvable
# foreign key, the earlier entity's 404 is the one returned.

DEVELOPER = "developer"
INVESTOR = "investor"
CAP_POOL = "cap_pool"
PROJECT = "project"
VOLUME_CAP_ALLOCATION = "volume_cap_allocation"
REGULATORY_AGREEMENT = "regulatory_agreement"
BOND_ISSUE = "bond_issue"
DRAW_REQUEST = "draw_request"
UNIT_RESTRICTION = "unit_restriction"
COST_CERTIFICATION = "cost_certification"
CREDIT_ALLOCATION = "credit_allocation"
INVESTOR_DELIVERY = "investor_delivery"
COMPLIANCE_REPORT = "compliance_report"
PHYSICAL_INSPECTION = "physical_inspection"

ALL_ENTITIES = (
    DEVELOPER,
    INVESTOR,
    CAP_POOL,
    PROJECT,
    VOLUME_CAP_ALLOCATION,
    REGULATORY_AGREEMENT,
    BOND_ISSUE,
    DRAW_REQUEST,
    UNIT_RESTRICTION,
    COST_CERTIFICATION,
    CREDIT_ALLOCATION,
    INVESTOR_DELIVERY,
    COMPLIANCE_REPORT,
    PHYSICAL_INSPECTION,
)

# Each entity's own 404, so a probe never has to accept a generic not-found.
NOT_FOUND_BY_ENTITY = {
    DEVELOPER: ApiErrorId.ERR_DEVELOPER_NOT_FOUND,
    INVESTOR: ApiErrorId.ERR_INVESTOR_NOT_FOUND,
    CAP_POOL: ApiErrorId.ERR_CAP_POOL_NOT_FOUND,
    PROJECT: ApiErrorId.ERR_PROJECT_NOT_FOUND,
    VOLUME_CAP_ALLOCATION: ApiErrorId.ERR_ALLOCATION_NOT_FOUND,
    REGULATORY_AGREEMENT: ApiErrorId.ERR_REG_AGREEMENT_NOT_FOUND,
    BOND_ISSUE: ApiErrorId.ERR_BOND_ISSUE_NOT_FOUND,
    DRAW_REQUEST: ApiErrorId.ERR_DRAW_REQUEST_NOT_FOUND,
    UNIT_RESTRICTION: ApiErrorId.ERR_UNIT_RESTRICTION_NOT_FOUND,
    COST_CERTIFICATION: ApiErrorId.ERR_COST_CERT_NOT_FOUND,
    CREDIT_ALLOCATION: ApiErrorId.ERR_CREDIT_ALLOCATION_NOT_FOUND,
    INVESTOR_DELIVERY: ApiErrorId.ERR_DELIVERY_NOT_FOUND,
    COMPLIANCE_REPORT: ApiErrorId.ERR_COMPLIANCE_REPORT_NOT_FOUND,
    PHYSICAL_INSPECTION: ApiErrorId.ERR_INSPECTION_NOT_FOUND,
}

# The single-row reader on the client for each entity.
READER_BY_ENTITY = {
    DEVELOPER: "get_developer",
    INVESTOR: "get_investor",
    CAP_POOL: "get_cap_pool",
    PROJECT: "get_project",
    VOLUME_CAP_ALLOCATION: "get_volume_cap_allocation",
    REGULATORY_AGREEMENT: "get_regulatory_agreement",
    BOND_ISSUE: "get_bond_issue",
    DRAW_REQUEST: "get_draw_request",
    UNIT_RESTRICTION: "get_unit_restriction",
    COST_CERTIFICATION: "get_cost_certification",
    CREDIT_ALLOCATION: "get_credit_allocation",
    INVESTOR_DELIVERY: "get_investor_delivery",
    COMPLIANCE_REPORT: "get_compliance_report",
    PHYSICAL_INSPECTION: "get_physical_inspection",
}

# ─── Field sets, entity by entity ─────────────────────

DEVELOPER_FIELDS = COMMON_FIELDS + (
    "name",
    "tax_id",
    "contact_email",
    "status",
    "sanction_reason",
    "active_project_count",
)

INVESTOR_FIELDS = COMMON_FIELDS + (
    "name",
    "tax_id",
    "investor_type",
    "total_credit_accepted_cents",
)

CAP_POOL_FIELDS = COMMON_FIELDS + (
    "program_year",
    "base_cap_cents",
    "carryforward_cents",
    "total_cap_cents",
    "reserved_cents",
    "committed_cents",
    "available_cents",
    "awardable_cents",
    "pool_status",
)

# The six derived pool figures, which are re-solved from scratch on every
# allocation create, decision, revision, return, expiry and release.
POOL_LEDGER_FIELDS = (
    "total_cap_cents",
    "reserved_cents",
    "committed_cents",
    "available_cents",
    "awardable_cents",
    "pool_status",
)

PROJECT_FIELDS = COMMON_FIELDS + (
    "developer_id",
    "name",
    "total_units",
    "total_floor_space_sqft",
    "land_cost_cents",
    "depreciable_basis_cents",
    "aggregate_basis_cents",
    "set_aside_election",
    "development_status",
    "compliance_status",
    "restricted_unit_count",
    "market_unit_count",
    "employee_unit_count",
    "designated_unit_count",
    "unit_fraction_bps",
    "floor_space_fraction_bps",
    "applicable_fraction_bps",
    "set_aside_ratio_bps",
    "set_aside_satisfied",
    "provisional_fifty_percent_ratio_bps",
    "final_fifty_percent_ratio_bps",
    "automatic_credit_triggered",
    "placed_in_service_date",
    "compliance_start_date",
    "compliance_end_date",
    "extended_use_end_date",
    "financing_stalled",
    "volume_cap_deferral_count",
)

# The five counters and the three ratios that are re-derived together on every
# designation and every redesignation.
PROJECT_DERIVED_UNIT_FIELDS = (
    "restricted_unit_count",
    "market_unit_count",
    "employee_unit_count",
    "designated_unit_count",
    "unit_fraction_bps",
    "floor_space_fraction_bps",
    "applicable_fraction_bps",
    "set_aside_ratio_bps",
)

UNIT_RESTRICTION_FIELDS = COMMON_FIELDS + (
    "project_id",
    "unit_number",
    "bedroom_count",
    "floor_space_sqft",
    "designation",
    "ami_percent",
    "utility_allowance_cents",
    "market_rent_cents",
    "imputed_household_size",
    "restricted_rent_cents",
    "status",
)

VOLUME_CAP_ALLOCATION_FIELDS = COMMON_FIELDS + (
    "project_id",
    "cap_pool_id",
    "requested_amount_cents",
    "requested_closing_date",
    "awarded_amount_cents",
    "expiry_date",
    "status",
    "decision_round",
    "denial_reason",
    "return_reason",
    "decided_by_user_id",
)

REGULATORY_AGREEMENT_FIELDS = COMMON_FIELDS + (
    "project_id",
    "set_aside_election",
    "compliance_period_years",
    "extended_use_years",
    "recording_county",
    "instrument_number",
    "recording_date",
    "compliance_period_end_date",
    "extended_use_end_date",
    "amendment_count",
    "amendment_reason",
    "status",
)

BOND_ISSUE_FIELDS = COMMON_FIELDS + (
    "project_id",
    "volume_cap_allocation_id",
    "eligible_cost_cents",
    "capitalized_interest_cents",
    "issuance_allowance_cents",
    "par_amount_cents",
    "bond_yield_bps",
    "investment_yield_bps",
    "negative_arbitrage_allowance_cents",
    "negative_arbitrage_cents",
    "cumulative_funded_cents",
    "undrawn_cents",
    "closing_date",
    "conversion_date",
    "redemption_date",
    "dscr_bps",
    "dscr_basis",
    "min_occupancy_bps",
    "operating_months",
    "status",
)

DRAW_REQUEST_FIELDS = COMMON_FIELDS + (
    "bond_issue_id",
    "draw_number",
    "period_start",
    "period_end",
    "requested_amount_cents",
    "approved_amount_cents",
    "funding_date",
    "negative_arbitrage_accrual_cents",
    "rejection_reason",
    "void_reason",
    "status",
)

COST_CERTIFICATION_FIELDS = COMMON_FIELDS + (
    "project_id",
    "certified_land_cost_cents",
    "certified_depreciable_basis_cents",
    "certified_eligible_basis_cents",
    "certified_aggregate_basis_cents",
    "preparer_name",
    "submission_round",
    "deficiency_notes",
    "reviewed_by_user_id",
    "accepted_at",
    "status",
)

CREDIT_ALLOCATION_FIELDS = COMMON_FIELDS + (
    "project_id",
    "cost_certification_id",
    "qualified_basis_cents",
    "applicable_fraction_bps",
    "credit_percentage_bps",
    "annual_credit_cents",
    "total_credit_cents",
    "delivered_credit_cents",
    "undelivered_credit_cents",
    "recapture_amount_cents",
    "placed_in_service_date",
    "form_8609_number",
    "issued_by_user_id",
    "status",
)

INVESTOR_DELIVERY_FIELDS = COMMON_FIELDS + (
    "credit_allocation_id",
    "investor_id",
    "requested_credit_cents",
    "delivered_credit_cents",
    "capital_contribution_cents",
    "price_per_credit_dollar_bps",
    "accepted_at",
    "rescind_reason",
    "status",
)

COMPLIANCE_REPORT_FIELDS = COMMON_FIELDS + (
    "project_id",
    "reporting_year",
    "restricted_units_occupied",
    "total_units_occupied",
    "average_ami_percent",
    "achieved_set_aside_bps",
    "shortfall_bps",
    "finding_notes",
    "reviewed_by_user_id",
    "status",
)

PHYSICAL_INSPECTION_FIELDS = COMMON_FIELDS + (
    "project_id",
    "window_start",
    "window_end",
    "inspector_name",
    "completed_date",
    "score",
    "deficiency_count",
    "next_inspection_due_date",
    "status",
)

FIELDS_BY_ENTITY = {
    DEVELOPER: DEVELOPER_FIELDS,
    INVESTOR: INVESTOR_FIELDS,
    CAP_POOL: CAP_POOL_FIELDS,
    PROJECT: PROJECT_FIELDS,
    VOLUME_CAP_ALLOCATION: VOLUME_CAP_ALLOCATION_FIELDS,
    REGULATORY_AGREEMENT: REGULATORY_AGREEMENT_FIELDS,
    BOND_ISSUE: BOND_ISSUE_FIELDS,
    DRAW_REQUEST: DRAW_REQUEST_FIELDS,
    UNIT_RESTRICTION: UNIT_RESTRICTION_FIELDS,
    COST_CERTIFICATION: COST_CERTIFICATION_FIELDS,
    CREDIT_ALLOCATION: CREDIT_ALLOCATION_FIELDS,
    INVESTOR_DELIVERY: INVESTOR_DELIVERY_FIELDS,
    COMPLIANCE_REPORT: COMPLIANCE_REPORT_FIELDS,
    PHYSICAL_INSPECTION: PHYSICAL_INSPECTION_FIELDS,
}

# ─── Terminal states, for the no-replay rule ──────────

TERMINAL_STATES = {
    DEVELOPER: ("DEBARRED",),
    PROJECT: ("WITHDRAWN",),
    VOLUME_CAP_ALLOCATION: ("EXPIRED", "RELEASED"),
    REGULATORY_AGREEMENT: ("RELEASED",),
    BOND_ISSUE: ("CONVERTED", "MANDATORY_REDEEMED"),
    DRAW_REQUEST: ("REJECTED", "VOIDED"),
    COST_CERTIFICATION: ("ACCEPTED",),
    CREDIT_ALLOCATION: ("RECAPTURED",),
    INVESTOR_DELIVERY: ("RESCINDED",),
    COMPLIANCE_REPORT: ("CLEARED", "NONCOMPLIANCE_FOUND"),
    PHYSICAL_INSPECTION: ("COMPLETED",),
}
