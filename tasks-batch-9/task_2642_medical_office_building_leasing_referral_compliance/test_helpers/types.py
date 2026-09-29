"""Domain types for the medical office building leasing and referral-compliance API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PORTFOLIO_ADMIN = "PortfolioAdmin"
    LEASING_AGENT = "LeasingAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PROPERTY_MANAGER = "PropertyManager"
    FACILITIES_ENGINEER = "FacilitiesEngineer"
    TENANT_PORTAL_USER = "TenantPortalUser"


class TenantMixPosture(str, Enum):
    BALANCED = "BALANCED"
    ANCHOR_CONCENTRATED = "ANCHOR_CONCENTRATED"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SuiteClass(str, Enum):
    STANDARD_EXAM = "STANDARD_EXAM"
    IMAGING = "IMAGING"
    PROCEDURE = "PROCEDURE"
    INFUSION = "INFUSION"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"


class TenantAffiliation(str, Enum):
    HEALTH_SYSTEM_ANCHOR = "HEALTH_SYSTEM_ANCHOR"
    HEALTH_SYSTEM_AFFILIATED = "HEALTH_SYSTEM_AFFILIATED"
    INDEPENDENT_PRACTICE = "INDEPENDENT_PRACTICE"


class PrimarySpecialty(str, Enum):
    PRIMARY_CARE = "PRIMARY_CARE"
    CARDIOLOGY = "CARDIOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    RADIOLOGY = "RADIOLOGY"
    ONCOLOGY = "ONCOLOGY"
    OPHTHALMOLOGY = "OPHTHALMOLOGY"
    GASTROENTEROLOGY = "GASTROENTEROLOGY"


class ComplianceWatchStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"


class LeaseType(str, Enum):
    DIRECT = "DIRECT"
    MASTER = "MASTER"
    SUBLEASE = "SUBLEASE"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FMV_REVIEW = "PENDING_FMV_REVIEW"
    FMV_CERTIFIED = "FMV_CERTIFIED"
    SUSPENDED_MIX_REVIEW = "SUSPENDED_MIX_REVIEW"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    HOLDOVER = "HOLDOVER"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class FmvCertificationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    STALE = "STALE"


class TerminationReason(str, Enum):
    EXPIRATION = "EXPIRATION"
    MUTUAL = "MUTUAL"
    DEFAULT = "DEFAULT"


class AppraisalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    EXPIRED = "EXPIRED"


class TIProjectStatus(str, Enum):
    DESIGN = "DESIGN"
    IN_REVIEW = "IN_REVIEW"
    ON_HOLD = "ON_HOLD"
    PERMITTED = "PERMITTED"
    CONSTRUCTION = "CONSTRUCTION"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class TIReviewStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TILineItemCategory(str, Enum):
    SHIELDING = "SHIELDING"
    POWER = "POWER"
    MEDICAL_GAS = "MEDICAL_GAS"
    PLUMBING = "PLUMBING"
    FINISHES = "FINISHES"


class RentInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    WRITTEN_OFF = "WRITTEN_OFF"


class ComplianceCaseType(str, Enum):
    RENT_DELINQUENCY = "RENT_DELINQUENCY"
    FMV_DEVIATION = "FMV_DEVIATION"
    SUBLEASE_DOCUMENTATION = "SUBLEASE_DOCUMENTATION"


class ComplianceCaseStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    CURED = "CURED"
    REPORTED = "REPORTED"


class CaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ScoringVariant(str, Enum):
    ROLLING_12M = "ROLLING_12M"
    STRICT_CUMULATIVE = "STRICT_CUMULATIVE"


class SharedSpaceType(str, Enum):
    WAITING_ROOM = "WAITING_ROOM"
    PROCEDURE_ROOM = "PROCEDURE_ROOM"
    INFUSION_BAY = "INFUSION_BAY"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CancellationSource(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLIANCE_CASCADE = "COMPLIANCE_CASCADE"
    LEASE_TERMINATION = "LEASE_TERMINATION"


class ParkingCategory(str, Enum):
    STAFF = "STAFF"
    PATIENT = "PATIENT"


class ParkingAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AttestationType(str, Enum):
    SIGNED_LEASE = "SIGNED_LEASE"
    MASTER_LEASE_CONSENT = "MASTER_LEASE_CONSENT"
    SPACE_SHARING_SCHEDULE = "SPACE_SHARING_SCHEDULE"


class LeaseComplianceAction(str, Enum):
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"
    REINSTATE = "REINSTATE"


class AppraisalDecisionAction(str, Enum):
    QUALIFY = "QUALIFY"
    DISQUALIFY = "DISQUALIFY"


class TIProjectAction(str, Enum):
    SUBMIT_REVIEWS = "SUBMIT_REVIEWS"
    START_CONSTRUCTION = "START_CONSTRUCTION"
    CANCEL = "CANCEL"


class TIReviewType(str, Enum):
    SHIELDING = "SHIELDING"
    UTILITY = "UTILITY"


class TIReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ComplianceCaseAction(str, Enum):
    REMEDIATION_PLAN = "REMEDIATION_PLAN"
    CURE = "CURE"
    REPORT = "REPORT"


# ---------------------------------------------------------------------------
# Entity shapes. Every entity except TILineItem carries id, created_at,
# updated_at and version; TILineItem carries only id and created_at.
# ---------------------------------------------------------------------------


class Building(TypedDict):
    id: str
    name: str
    total_rentable_sf: int
    market_base_rent_psf_annual: float
    operating_expense_annual_psf: float
    total_parking_stalls: int
    patient_min_reserve_pct: float
    anchor_rentable_sf: int
    independent_rentable_sf: int
    leased_rentable_sf: int
    vacant_rentable_sf: int
    anchor_share_pct: float
    tenant_mix_posture: str
    mix_freeze_override: bool
    staff_allocated_stalls: int
    patient_allocated_stalls: int
    unallocated_stalls: int
    created_at: str
    updated_at: str
    version: int


class Suite(TypedDict):
    id: str
    building_id: str
    suite_number: str
    floor: int
    rentable_sf: int
    suite_class: str
    power_amps_available: int
    medical_gas_available: bool
    shielding_certified: bool
    lead_thickness_mm: Optional[float]
    occupancy_status: str
    last_vacated_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    legal_name: str
    affiliation: str
    primary_specialty: str
    is_physician_owned: bool
    npi: str
    delinquency_event_count: int
    referral_compliance_risk_score: int
    strict_cumulative_risk_score: int
    compliance_watch_status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    building_id: str
    suite_id: str
    tenant_id: str
    master_lease_id: Optional[str]
    lease_type: str
    term_start: str
    term_end: str
    term_months: int
    base_rent_psf_annual: float
    status: str
    fmv_certification_status: str
    certified_fmv_floor_psf: Optional[float]
    certified_fmv_ceiling_psf: Optional[float]
    provisional_base_rent_annual: float
    certified_base_rent_annual: Optional[float]
    effective_base_rent_annual: float
    fmv_variance_annual: Optional[float]
    fmv_variance_pct: Optional[float]
    exclusive_use_specialty: Optional[str]
    radius_restriction_miles: float
    after_hours_authorized: bool
    rent_concession_locked: bool
    revision_round: int
    fmv_submitted_by_user_id: Optional[str]
    signed_lease_on_file: bool
    master_lease_consent_on_file: bool
    space_sharing_schedule_on_file: bool
    holdover_premium_applied: bool
    termination_reason: Optional[str]
    terminated_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    lease_id: str
    appraiser_firm: str
    appraisal_date: str
    opinion_low_psf: float
    opinion_high_psf: float
    opinion_midpoint_psf: float
    independence_attested: bool
    status: str
    expires_on: str
    is_controlling: bool
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TenantImprovementProject(TypedDict):
    id: str
    lease_id: str
    suite_id: str
    target_suite_class: str
    lead_thickness_mm: Optional[float]
    power_amps_requested: int
    medical_gas_requested: bool
    authorized_allowance_total: float
    landlord_share_pct: float
    status: str
    shielding_review_status: str
    utility_review_status: str
    power_amps_drawn: int
    landlord_committed_amount: float
    tenant_committed_amount: float
    allowance_remaining: float
    line_item_count: int
    on_hold_from_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TILineItem(TypedDict):
    """Immutable construction line item: carries only id and created_at."""
    id: str
    ti_project_id: str
    sequence_no: int
    description: str
    category: str
    cost_amount: float
    landlord_share_pct_override: Optional[float]
    effective_share_pct: float
    landlord_share_amount: float
    tenant_share_amount: float
    created_at: str


class RentInvoice(TypedDict):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    due_date: str
    base_rent_amount: float
    cam_amount: float
    parking_fee_gross: float
    pre_waiver_total: float
    parking_waiver_tier_pct: float
    parking_waiver_amount: float
    total_amount: float
    amount_paid: float
    status: str
    paid_on: Optional[str]
    days_past_due: int
    days_past_due_at_flag: Optional[int]
    delinquency_tier_weight: Optional[int]
    write_off_justification: Optional[str]
    written_off_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    tenant_id: str
    case_type: str
    basis: str
    status: str
    severity: str
    scoring_variant: str
    risk_score_at_open: int
    opened_on: str
    opened_by_user_id: str
    reopen_count: int
    remediation_summary: Optional[str]
    remediation_due_on: Optional[str]
    report_reference: Optional[str]
    closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SharedSpace(TypedDict):
    id: str
    building_id: str
    name: str
    space_type: str
    capacity_seats: int
    opens_at: str
    closes_at: str
    created_at: str
    updated_at: str
    version: int


class SharedSpaceBooking(TypedDict):
    id: str
    shared_space_id: str
    lease_id: str
    window_start: str
    window_end: str
    occupant_count: int
    is_after_hours: bool
    status: str
    cancellation_source: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParkingAllocation(TypedDict):
    id: str
    building_id: str
    lease_id: str
    category: str
    stall_count: int
    status: str
    revoked_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
