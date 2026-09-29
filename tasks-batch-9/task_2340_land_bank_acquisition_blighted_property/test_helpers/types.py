"""
Typed shapes for every entity the County Land Bank Authority API returns.

Three record types are append-only journal rows: adjacency edges, reuse hearings
and eligibility screenings carry only ``id`` and ``created_at`` from the common
system fields - they never carry ``updated_at`` or ``version``, because nothing
in the API ever modifies them once written. Their TypedDicts deliberately omit
those two keys.
"""

from typing import List, Optional, TypedDict

# --- Role names --------------------------------------------------------------
ROLE_INTAKE_OFFICER = "IntakeOfficer"
ROLE_BOARD_CLERK = "BoardClerk"
ROLE_DISPOSITION_OFFICER = "DispositionOfficer"
ROLE_INVENTORY_MANAGER = "InventoryManager"
ROLE_COUNTY_TREASURER = "CountyTreasurer"
ROLE_APPLICANT = "Applicant"

ALL_ROLES = (
    ROLE_INTAKE_OFFICER,
    ROLE_BOARD_CLERK,
    ROLE_DISPOSITION_OFFICER,
    ROLE_INVENTORY_MANAGER,
    ROLE_COUNTY_TREASURER,
    ROLE_APPLICANT,
)

# --- Enumerations ------------------------------------------------------------
STRUCTURE_GRADES = ("A", "B", "C", "D", "F")

CUSTODY_STATUSES = ("PROSPECT", "ACQUIRED", "LISTED", "CONVEYED", "REVERTED")
TITLE_STATUSES = ("CLOUDED", "QUIET_TITLE_FILED", "CLEAR")
ACQUISITION_CHANNELS = ("TAX_FORECLOSURE", "DONATION", "NEGOTIATED_PURCHASE")

FUNDING_SOURCE_TYPES = ("GRANT", "TIF_RECAPTURE", "GENERAL_FUND")
FUNDING_RESTRICTIONS = ("ANY", "ACQUISITION_ONLY", "DEMOLITION_ONLY")
FUNDING_STATUSES = ("ACTIVE", "CONSTRAINED", "EXPIRED")

PACKET_STATUSES = (
    "DUE_DILIGENCE",
    "ON_HOLD_FUNDING",
    "BOARD_APPROVED",
    "CLOSED",
    "DECLINED",
)

TITLE_ACTION_TYPES = ("QUIET_TITLE_SUIT", "TAX_DEED_CONFIRMATION", "LIEN_RELEASE")
TITLE_ACTION_STATUSES = ("FILED", "CLEARED", "DEFECT_REMAINS")

WORK_TYPES = ("SECURE", "MOW", "DEMOLITION")
ORDER_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")

RUN_STATUSES = ("PLANNED", "EXECUTED", "VOID")

APPLICANT_TYPES = ("INDIVIDUAL", "NONPROFIT", "DEVELOPER")
ELIGIBILITY_STATUSES = ("ELIGIBLE", "BARRED")

PROGRAMS = ("SIDE_LOT", "HOMEOWNER_SALE", "DEVELOPER_RFP", "COMMUNITY_USE")
APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "SCREENED",
    "INFO_REQUESTED",
    "SUSPENDED_TITLE",
    "RECOMMENDED",
    "BOARD_APPROVED",
    "BOARD_DENIED",
    "DENIED",
    "AWARDED",
)
SUSPENDED_FROM_STATUSES = ("SUBMITTED", "SCREENED", "RECOMMENDED")

SCREENING_OUTCOMES = ("PASS", "FAIL")

DISCHARGE_MODES = ("STATUTORY", "NEGOTIATED")
AGREEMENT_STATUSES = ("EXECUTED", "CURE_PENDING", "COMPLIED", "REVERTED")


# --- Entities carrying the full common field set -----------------------------
class Property(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    parcel_id: str
    address: str
    situs_ward: int
    lot_area_sqft: int
    assessed_value_cents: int
    structure_present: bool
    structure_condition_grade: str
    vacancy_months: int
    nuisance_complaint_count: int
    open_code_violation_count: int
    delinquent_tax_balance_cents: int
    pre_acquisition_delinquency_cents: int
    custody_status: str
    title_status: str
    acquisition_channel: Optional[str]
    acquired_at: Optional[str]
    acquisition_cost_cents: int
    intake_blight_score: Optional[float]
    current_blight_score: float
    secured: bool
    last_mow_at: Optional[str]
    demolished_at: Optional[str]
    owner_of_record_applicant_id: Optional[str]
    listed_at: Optional[str]


class FundingSource(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    source_type: str
    authorized_cents: int
    restriction: str
    expires_on: str
    committed_cents: int
    disbursed_cents: int
    available_cents: int
    reserve_floor_cents: int
    open_run_count: int
    status: str
    recaptured_cents: int


class AcquisitionPacket(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    funding_source_id: str
    channel: str
    offer_price_cents: int
    title_search_fee_cents: int
    foreclosure_case_no: Optional[str]
    donor_name: Optional[str]
    status: str
    committed_cents: int
    initiated_by_user_id: str
    closed_by_user_id: Optional[str]
    resolution_no: Optional[str]
    deed_reference: Optional[str]
    declined_reason: Optional[str]
    hold_reason: Optional[str]


class TitleAction(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    action_type: str
    round_no: int
    filed_at: str
    defect_count: int
    status: str
    adjudicated_at: Optional[str]


class Contractor(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    license_expires_on: str
    max_concurrent_crews: int
    specialties: List[str]
    debarred: bool


class MaintenanceOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    contractor_id: Optional[str]
    funding_source_id: str
    demolition_run_id: Optional[str]
    work_type: str
    window_start: str
    window_end: str
    openings_count: Optional[int]
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    completed_at: Optional[str]
    cancelled_reason: Optional[str]


class DemolitionRun(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    funding_source_id: str
    run_sequence: int
    budget_cents: int
    situs_ward_filter: Optional[int]
    provisional_cap_cents: int
    selected_property_ids: List[str]
    skipped_property_ids: List[str]
    properties_selected_count: int
    skipped_property_count: int
    committed_subtotal_cents: int
    admin_fee_cents: int
    total_committed_cents: int
    dropped_property_ids: List[str]
    orders_created_count: int
    status: str
    executed_at: Optional[str]


class Applicant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    applicant_type: str
    contact_email: str
    nonprofit_registration_no: Optional[str]
    reverter_count: int
    last_reverter_at: Optional[str]
    good_standing_count: int
    delinquent_tax_total_cents: int
    open_code_violation_total: int
    recent_reverter_count: int
    conveyed_property_count: int
    eligibility_status: str


class DispositionApplication(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    applicant_id: str
    program: str
    proposed_use: str
    offer_price_cents: int
    quoted_price_cents: int
    status: str
    revision_round: int
    submitted_at: Optional[str]
    screening_count: int
    suspended_from_status: Optional[str]
    recommended_by_user_id: Optional[str]
    recommendation_memo: Optional[str]
    decided_by_user_id: Optional[str]
    board_decision_at: Optional[str]
    denial_reason: Optional[str]


class DevelopmentAgreement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    application_id: str
    property_id: str
    performance_deadline: str
    cure_deadline: Optional[str]
    milestone_count: int
    milestones_completed: int
    reverter_clause_active: bool
    abatement_years: int
    discharge_mode: str
    projected_improved_value_cents: int
    sale_price_cents: int
    discharged_tax_cents: int
    abatement_annual_cents: int
    abatement_total_cents: int
    status: str
    executed_at: str
    complied_at: Optional[str]
    reverted_at: Optional[str]


# --- Append-only journal rows: id and created_at only ------------------------
class ParcelAdjacency(TypedDict):
    id: str
    created_at: str
    property_id: str
    adjacent_property_id: str
    shared_boundary_feet: float
    recorded_by_user_id: str


class ReuseHearing(TypedDict):
    id: str
    created_at: str
    property_id: str
    hearing_at: str
    comment_count: int
    support_count: int
    support_ratio: float
    summary: str


class EligibilityScreening(TypedDict):
    id: str
    created_at: str
    application_id: str
    sequence_no: int
    screened_by_user_id: str
    screened_at: str
    delinquent_tax_total_cents: int
    open_code_violation_total: int
    recent_reverter_count: int
    disqualifiers: List[str]
    eligibility_score: float
    outcome: str


# --- Computed read shapes ----------------------------------------------------
class PriceQuote(TypedDict):
    program: str
    quoted_price_cents: int
    tier_applied: str
    marginal_area_sqft: int
    assessed_cap_cents: int
    discount_applied: bool


class ComplianceSweepResult(TypedDict):
    swept_at: str
    funding_expired_count: int
    cure_pending_count: int
    reverted_count: int
    waived_count: int
    restored_inventory_sqft: int


class InventorySummary(TypedDict):
    inventory_property_count: int
    inventory_area_sqft: int
    conveyed_area_sqft: int
    cure_pending_count: int
    total_authorized_cents: int
    total_committed_cents: int
    total_disbursed_cents: int
    total_available_cents: int


# Entities whose rows are append-only journal records: they never expose
# updated_at or version.
APPEND_ONLY_ENTITIES = ("ParcelAdjacency", "ReuseHearing", "EligibilityScreening")
