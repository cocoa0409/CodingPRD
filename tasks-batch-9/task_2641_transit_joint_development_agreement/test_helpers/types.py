"""TypedDict definitions and enum value sets for the Joint Development Agreement API.

Field names and value sets mirror the PRD's entity descriptions exactly.
Twelve of the thirteen types carry `id`, `created_at`, `updated_at` and
`version`; `MaintenanceCharge` carries only `id` and `created_at`.
"""

from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Enum value sets
# --------------------------------------------------------------------------

ACQUISITION_FUNDING_SOURCES = ["FEDERAL_GRANT", "LOCAL_ONLY", "MIXED"]
SITE_STATUSES = [
    "INVENTORIED",
    "ASSESSED",
    "SOLICITATION_READY",
    "UNDER_AGREEMENT",
    "CONVEYED",
]
READINESS_TIERS = ["READY", "CONDITIONAL", "NOT_READY"]

ASSESSMENT_VARIANTS = ["PRELIMINARY", "CERTIFIED"]
ASSESSMENT_STATUSES = ["DRAFT", "CERTIFIED", "SUPERSEDED"]

DEBARMENT_STATUSES = ["CLEAR", "SUSPENDED", "DEBARRED"]

SOLICITATION_TYPES = ["RFP", "RFQ", "UNSOLICITED_RESPONSE"]
SOLICITATION_STATUSES = ["DRAFT", "ISSUED", "CLOSED", "AWARDED", "CANCELLED"]

PROPOSED_STRUCTURES = ["GROUND_LEASE", "FEE_DISPOSITION"]
PROPOSAL_STATUSES = ["SUBMITTED", "SHORTLISTED", "SELECTED", "REJECTED"]

NEGOTIATION_PERIOD_STATUSES = [
    "ACTIVE",
    "EXTENDED",
    "EXPIRED",
    "TERMINATED",
    "CONVERTED",
]

VALUATION_METHODS = ["INCOME_APPROACH", "SALES_COMPARISON", "COST_APPROACH"]
TRANSFER_BASES = ["FMV_STRICT", "TRANSIT_SUPPORTIVE_BELOW_MARKET"]
VALUATION_STATUSES = ["DRAFT", "CERTIFIED", "SUPERSEDED"]

NEGOTIATION_STATUSES = [
    "DRAFTING",
    "AGENCY_REVIEW",
    "REVISION_REQUESTED",
    "BOARD_APPROVED",
    "EXECUTED",
]
FEDERAL_APPROVAL_STATUSES = [
    "NOT_REQUIRED",
    "NOT_SUBMITTED",
    "SUBMITTED",
    "FTA_APPROVED",
    "FTA_REJECTED",
]

DISPOSITION_DETERMINATIONS = [
    "PENDING",
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "REJECTED",
    "WITHDRAWN",
]

REPLACEMENT_FACILITY_TYPES = [
    "BUS_BAY",
    "PARK_AND_RIDE",
    "RAIL_PLATFORM",
    "OPERATOR_FACILITY",
]
REPLACEMENT_STATUSES = ["PLANNED", "INTERIM_IN_PLACE", "COMPLETE", "DEFICIENT"]

SHARED_FACILITY_TYPES = ["BUS_BAY", "PLAZA", "PARKING_STRUCTURE", "ELEVATOR_BANK"]
MAINTENANCE_RESPONSIBILITIES = ["AGENCY", "DEVELOPER", "SHARED"]

STAGING_WINDOW_STATUSES = [
    "REQUESTED",
    "APPROVED",
    "REJECTED",
    "SUSPENDED",
    "CLOSED",
]

STAGING_DECISIONS = ["APPROVE", "REJECT"]


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------


class AgencySite(TypedDict):
    id: str
    site_code: str
    name: str
    address_line: str
    parcel_area_sqft: int
    acquisition_funding_source: str
    federal_interest_pct: float
    transit_facility_present: bool
    status: str
    readiness_composite_score: Optional[float]
    readiness_tier: Optional[str]
    federal_interest_basis_cents: int
    federal_interest_encumbered_cents: int
    federal_interest_unencumbered_cents: int
    created_at: str
    updated_at: str
    version: int


class ReadinessAssessment(TypedDict):
    id: str
    site_id: str
    environmental_score: int
    utility_score: int
    access_score: int
    entitlement_score: int
    encumbrance_count: int
    assessment_notes: str
    composite_score: float
    variant_applied: str
    tier: Optional[str]
    status: str
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Developer(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    prequalified: bool
    debarment_status: str
    created_at: str
    updated_at: str
    version: int


class Solicitation(TypedDict):
    id: str
    site_id: str
    solicitation_type: str
    response_deadline: str
    benchmark_value_cents: int
    affordable_housing_min_pct: float
    min_proposals_required: int
    joint_use_required: bool
    status: str
    issued_at: Optional[str]
    responsive_proposal_count: int
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    solicitation_id: str
    developer_id: str
    proposed_structure: str
    proposed_annual_rent_cents: Optional[int]
    proposed_purchase_price_cents: Optional[int]
    affordable_units: int
    total_units: int
    transit_ridership_uplift: int
    design_compliance_score: int
    joint_use_committed: bool
    affordable_pct: float
    evaluation_score: float
    rank: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusiveNegotiationPeriod(TypedDict):
    id: str
    site_id: str
    proposal_id: str
    start_date: str
    end_date: str
    extension_count: int
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValuationDetermination(TypedDict):
    id: str
    site_id: str
    method: str
    appraised_value_cents: int
    transit_supportive_use_pct: float
    affordable_units_pct: float
    transfer_basis: str
    effective_date: str
    transit_supportive_credit_cents: int
    federal_interest_floor_cents: int
    permissible_floor_cents: int
    status: str
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JointDevelopmentAgreement(TypedDict):
    id: str
    site_id: str
    developer_id: str
    proposal_id: str
    valuation_id: str
    structure: str
    term_years: int
    base_rent_cents: Optional[int]
    purchase_price_cents: Optional[int]
    revenue_share_pct: float
    projected_gross_revenue_cents: int
    affordable_units_committed: int
    total_units: int
    site_area_share_pct: float
    joint_use_committed: bool
    capital_credit_cents: int
    annual_revenue_to_agency_cents: int
    consideration_value_cents: int
    negotiation_status: str
    federal_approval_status: str
    submitted_by_user_id: Optional[str]
    board_resolution_number: Optional[str]
    execution_date: Optional[str]
    revision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FederalDispositionRequest(TypedDict):
    id: str
    jda_id: str
    narrative: str
    federal_interest_amount_cents: int
    determination: str
    condition_notes: Optional[str]
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransitFacilityReplacement(TypedDict):
    id: str
    jda_id: str
    facility_type: str
    original_capacity: int
    replacement_capacity: int
    interim_capacity: int
    milestone_date: str
    capacity_deficit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SharedFacility(TypedDict):
    id: str
    site_id: str
    facility_type: str
    total_bay_capacity: int
    maintenance_responsibility: str
    cost_share_pct_developer: float
    available_bay_capacity: int
    created_at: str
    updated_at: str
    version: int


class StagingWindow(TypedDict):
    id: str
    jda_id: str
    shared_facility_id: str
    start_at: str
    end_at: str
    bays_occupied: int
    purpose: str
    status: str
    capacity_released: bool
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceLineItem(TypedDict):
    description: str
    cost_cents: int


class MaintenanceCharge(TypedDict):
    """The one immutable event type: only `id` and `created_at` accompany it."""

    id: str
    shared_facility_id: str
    jda_id: str
    period_start: str
    period_end: str
    line_items: List[MaintenanceLineItem]
    effective_share_applied: float
    total_cost_cents: int
    developer_share_cents: int
    agency_share_cents: int
    created_at: str
