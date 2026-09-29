"""Domain types for the Homeowner Rehabilitation Loan Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    CONTRACTOR = "Contractor"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    REHAB_SPECIALIST = "RehabSpecialist"
    INSPECTOR = "Inspector"
    LOAN_OFFICER = "LoanOfficer"
    PROGRAM_MANAGER = "ProgramManager"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class IncomeCalcMethod(str, Enum):
    PART_5_ANNUAL = "PART_5_ANNUAL"
    IRS_1040_ADJUSTED = "IRS_1040_ADJUSTED"


class EligibilityStatus(str, Enum):
    APPLIED = "APPLIED"
    INCOME_VERIFIED = "INCOME_VERIFIED"
    INELIGIBLE = "INELIGIBLE"


class IncomeCategory(str, Enum):
    EXTREMELY_LOW = "EXTREMELY_LOW"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    OVER_INCOME = "OVER_INCOME"


class WorkflowState(str, Enum):
    INTAKE = "INTAKE"
    OWNERSHIP_VERIFIED = "OWNERSHIP_VERIFIED"
    INSPECTED = "INSPECTED"
    WRITEUP_APPROVED = "WRITEUP_APPROVED"
    BID_OPEN = "BID_OPEN"
    BID_FAILED = "BID_FAILED"
    AWARDED = "AWARDED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    CONSTRUCTION_COMPLETE = "CONSTRUCTION_COMPLETE"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    LEAD_HOLD = "LEAD_HOLD"
    HISTORIC_HOLD = "HISTORIC_HOLD"
    DUAL_HOLD = "DUAL_HOLD"
    CLEARED_WITH_PROTOCOL = "CLEARED_WITH_PROTOCOL"
    ADVERSE_EFFECT_BLOCKED = "ADVERSE_EFFECT_BLOCKED"


class OwnershipVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OccupancyType(str, Enum):
    OWNER_OCCUPIED_SINGLE = "OWNER_OCCUPIED_SINGLE"
    OWNER_OCCUPIED_DUPLEX = "OWNER_OCCUPIED_DUPLEX"


class OwnershipDocType(str, Enum):
    WARRANTY_DEED = "WARRANTY_DEED"
    QUITCLAIM_DEED = "QUITCLAIM_DEED"
    LIFE_ESTATE = "LIFE_ESTATE"
    CONTRACT_FOR_DEED = "CONTRACT_FOR_DEED"


class LeadHazardControlMethod(str, Enum):
    NONE = "NONE"
    INTERIM_CONTROLS = "INTERIM_CONTROLS"
    ABATEMENT = "ABATEMENT"


class ShpoReviewOutcome(str, Enum):
    NO_ADVERSE_EFFECT = "NO_ADVERSE_EFFECT"
    CONDITIONS = "CONDITIONS"
    ADVERSE_EFFECT = "ADVERSE_EFFECT"


class InspectionType(str, Enum):
    INITIAL_STANDARDS = "INITIAL_STANDARDS"
    DRAW = "DRAW"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class WriteUpState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class WorkItemCategory(str, Enum):
    ROOF = "ROOF"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    LEAD_HAZARD_CONTROL = "LEAD_HAZARD_CONTROL"
    ACCESSIBILITY = "ACCESSIBILITY"
    WINDOWS = "WINDOWS"
    STRUCTURAL = "STRUCTURAL"


class PriorityClass(str, Enum):
    HEALTH_SAFETY = "HEALTH_SAFETY"
    CODE = "CODE"
    INCIPIENT = "INCIPIENT"
    GENERAL_PROPERTY_IMPROVEMENT = "GENERAL_PROPERTY_IMPROVEMENT"


class ApprovedListStatus(str, Enum):
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class SolicitationStatus(str, Enum):
    OPEN = "OPEN"
    TABULATED = "TABULATED"
    AWARDED = "AWARDED"
    FAILED = "FAILED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESPONSIVE = "RESPONSIVE"
    NON_RESPONSIVE = "NON_RESPONSIVE"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN_BY_PROGRAM = "WITHDRAWN_BY_PROGRAM"


class NonResponsiveReason(str, Enum):
    OVER_CEILING = "OVER_CEILING"
    UNDER_FLOOR = "UNDER_FLOOR"
    CONTRACTOR_NOT_APPROVED = "CONTRACTOR_NOT_APPROVED"
    NOT_LEAD_CERTIFIED = "NOT_LEAD_CERTIFIED"


class LoanStructureType(str, Enum):
    DEFERRED = "DEFERRED"
    FORGIVABLE = "FORGIVABLE"
    AMORTIZING = "AMORTIZING"


class LoanStatus(str, Enum):
    STRUCTURED = "STRUCTURED"
    LIEN_RECORDED = "LIEN_RECORDED"
    DISBURSING = "DISBURSING"
    FULLY_DISBURSED = "FULLY_DISBURSED"
    SERVICING = "SERVICING"
    RECAPTURED = "RECAPTURED"
    FORGIVEN = "FORGIVEN"


class RecaptureEventType(str, Enum):
    SALE = "SALE"
    TRANSFER = "TRANSFER"
    REFINANCE = "REFINANCE"
    RENTAL_CONVERSION = "RENTAL_CONVERSION"


class DrawStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INSPECTION_PASSED = "INSPECTION_PASSED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class ChangeOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    CONTRACTOR_NOTIFIED = "CONTRACTOR_NOTIFIED"
    REMEDIED = "REMEDIED"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"
    SANCTIONED = "SANCTIONED"


class DefectCategory(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    INCOMPLETE_WORK = "INCOMPLETE_WORK"
    MATERIAL_DEFECT = "MATERIAL_DEFECT"
    WARRANTY_REFUSAL = "WARRANTY_REFUSAL"


class SanctionLevel(str, Enum):
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    REMOVAL = "REMOVAL"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Twelve of the thirteen resource types carry id + created_at + updated_at +
# version (PRD §2.5). The repair-line resource carries only id + created_at.
# ---------------------------------------------------------------------------


class ProgramYear(TypedDict):
    id: str
    fiscal_year: int
    ami_median_income_cents: int
    max_loan_amount_cents: int
    allocation_budget_cents: int
    committed_amount_cents: int
    disbursed_amount_cents: int
    program_income_balance_cents: int
    uncommitted_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    program_year_id: str
    full_name: str
    email: str
    household_size: int
    income_calc_method: str
    wage_income_cents: int
    benefit_income_cents: int
    actual_asset_income_cents: int
    household_assets_cents: int
    dependents_count: int
    elderly_household: bool
    eligibility_status: str
    annual_income_cents: Optional[int]
    income_limit_cents: Optional[int]
    ami_percent: Optional[float]
    income_category: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RehabApplication(TypedDict):
    id: str
    applicant_id: str
    program_year_id: str
    address_line1: str
    city: str
    state_code: str
    year_built: int
    assessed_value_cents: int
    senior_lien_balance_cents: int
    historic_district: bool
    occupancy_type: str
    ownership_doc_type: str
    lead_review_required: bool
    historic_review_required: bool
    workflow_state: str
    compliance_posture: str
    ownership_verification_status: str
    deed_recorded_date: Optional[str]
    lead_hazard_detected: bool
    lead_hazard_control_method: str
    shpo_review_outcome: Optional[str]
    initial_deficiency_count: int
    awarded_contractor_id: Optional[str]
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PropertyInspection(TypedDict):
    id: str
    application_id: str
    draw_request_id: Optional[str]
    inspection_type: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    performed_by_user_id: str
    result: Optional[str]
    deficiency_count: int
    lead_hazard_present: bool
    xrf_reading_mg_cm2: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WorkWriteUp(TypedDict):
    id: str
    application_id: str
    revision_number: int
    revision_reason: Optional[str]
    state: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    work_item_count: int
    base_estimate_cents: int
    contingency_cents: int
    total_estimate_cents: int
    priority_repair_total_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkItem(TypedDict):
    """The repair-line resource carries only id and created_at (PRD §2.5)."""

    id: str
    write_up_id: str
    description: str
    category: str
    priority_class: str
    estimated_cost_cents: int
    is_lead_hazard_reduction: bool
    is_historic_sensitive: bool
    protocol_multiplier: float
    line_total_cents: int
    created_at: str


class Contractor(TypedDict):
    id: str
    legal_name: str
    license_number: str
    insurance_expires_on: str
    lead_safe_certified: bool
    historic_qualified: bool
    approved_list_status: str
    performance_score: int
    open_complaint_count: int
    sanction_count: int
    on_time_completion_count: int
    active_award_count: int
    created_at: str
    updated_at: str
    version: int


class BidSolicitation(TypedDict):
    id: str
    application_id: str
    write_up_id: str
    bid_due_at: str
    min_bids_required: int
    independent_cost_estimate_cents: int
    responsive_ceiling_cents: int
    responsive_floor_cents: int
    status: str
    bid_count: int
    responsive_bid_count: int
    reopen_count: int
    award_bid_id: Optional[str]
    awarded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    solicitation_id: str
    contractor_id: str
    amount_cents: int
    proposed_start_date: str
    proposed_end_date: str
    status: str
    submitted_at: str
    non_responsive_reason: Optional[str]
    rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RehabLoan(TypedDict):
    id: str
    application_id: str
    structure_type: str
    interest_rate_bps: int
    term_months: int
    forgiveness_term_months: int
    awarded_bid_amount_cents: int
    approved_project_cost_cents: int
    lien_recording_fee_cents: int
    principal_cents: int
    monthly_payment_cents: int
    status: str
    lien_position: Optional[int]
    lien_recorded_at: Optional[str]
    forgiveness_start_date: Optional[str]
    contract_earned_cents: int
    disbursed_cents: int
    retainage_held_cents: int
    forgiven_cents: int
    principal_repaid_cents: int
    unforgiven_balance_cents: int
    recapture_event_type: Optional[str]
    recapture_event_date: Optional[str]
    net_proceeds_cents: Optional[int]
    recapture_amount_cents: Optional[int]
    shortfall_forgiven_cents: Optional[int]
    program_income_posted_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict):
    id: str
    loan_id: str
    contractor_id: str
    requested_amount_cents: int
    is_final_draw: bool
    status: str
    approved_amount_cents: Optional[int]
    retainage_cents: Optional[int]
    net_payment_cents: Optional[int]
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    loan_id: str
    amount_delta_cents: int
    justification: str
    affects_lead_hazard_work: bool
    supersedes_change_order_id: Optional[str]
    status: str
    submitted_by_user_id: str
    cumulative_delta_pct: float
    created_at: str
    updated_at: str
    version: int


class ComplaintCase(TypedDict):
    id: str
    contractor_id: str
    application_id: str
    defect_category: str
    description: str
    status: str
    filed_at: str
    warranty_expires_at: Optional[str]
    remedy_deadline_at: Optional[str]
    sanction_level: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
