"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class CLTProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class HouseholdStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class IncomeCertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EducationCourseStatus(str, Enum):
    OFFERED = "OFFERED"
    RETIRED = "RETIRED"


class UnitOccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    LISTED_FOR_RESALE = "LISTED_FOR_RESALE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    IN_DEFAULT = "IN_DEFAULT"
    FORECLOSED = "FORECLOSED"


class MaintenanceFlag(str, Enum):
    OK = "OK"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    UNSAFE = "UNSAFE"


class GroundLeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    IN_DEFAULT = "IN_DEFAULT"
    CURE_PERIOD = "CURE_PERIOD"
    FORECLOSED = "FORECLOSED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class LeaseFeeStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    LATE = "LATE"
    WAIVED = "WAIVED"
    DEFAULTED = "DEFAULTED"


class DefaultNoticeStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    DISMISSED = "DISMISSED"


class DefaultNoticeKind(str, Enum):
    FEE_ARREARS = "FEE_ARREARS"
    MAINTENANCE = "MAINTENANCE"
    UNAUTHORIZED_REFINANCE = "UNAUTHORIZED_REFINANCE"
    OCCUPANCY_VIOLATION = "OCCUPANCY_VIOLATION"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NEEDS_REPAIR = "NEEDS_REPAIR"


class WaitlistEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MATCHED = "MATCHED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    FULFILLED = "FULFILLED"


class ResaleListingStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RefinanceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    LENDER_REVIEW = "LENDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    RECORDED = "RECORDED"


class ResaleFormulaKind(str, Enum):
    APPRAISAL_BASED = "APPRAISAL_BASED"
    INDEXED = "INDEXED"


class UserRole(str, Enum):
    PlatformAdmin = "PlatformAdmin"
    ProgramAdmin = "ProgramAdmin"
    IntakeSpecialist = "IntakeSpecialist"
    ComplianceOfficer = "ComplianceOfficer"
    LeaseManager = "LeaseManager"
    Inspector = "Inspector"
    Household = "Household"


# ---- Entity TypedDicts ----
# Common-fields-bearing entities (id + created_at + updated_at + version)

class CLTProgram(TypedDict, total=False):
    id: str
    name: str
    ami_table_effective_date: str
    area_median_income_cents: int
    max_eligibility_ami_pct: float
    ground_lease_term_years: int
    ground_lease_base_fee_cents: int
    low_income_fee_reduction_pct: float
    resale_formula_kind: str
    indexed_annual_appreciation_pct: float
    appraisal_seller_share_pct: float
    max_refi_ltv_pct: float
    max_equity_withdrawal_cents: int
    default_cure_window_days: int
    inspection_cycle_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    program_id: str
    legal_name: str
    household_size: int
    annual_gross_income_cents: int
    ami_pct: float
    eligibility_status: str
    eligibility_expires_at: Optional[str]
    education_required: bool
    education_completed_at: Optional[str]
    active_lease_id: Optional[str]
    waitlist_entry_id: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


class IncomeCertification(TypedDict, total=False):
    id: str
    household_id: str
    tax_year: int
    reported_annual_income_cents: int
    verified_annual_income_cents: int
    household_size_at_cert: int
    ami_pct_at_cert: float
    status: str
    rejection_reason: str
    reviewed_by: str
    submitted_by: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationCourse(TypedDict, total=False):
    id: str
    program_id: str
    code: str
    title: str
    credit_hours: int
    is_required: bool
    validity_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    program_id: str
    address: str
    bedrooms: int
    original_subsidy_cents: int
    original_sale_price_cents: int
    current_lease_id: Optional[str]
    occupancy_status: str
    last_inspection_passed_at: Optional[str]
    next_inspection_due_at: Optional[str]
    maintenance_flag: str
    appraisal_value_cents: int
    created_at: str
    updated_at: str
    version: int


class GroundLease(TypedDict, total=False):
    id: str
    unit_id: str
    household_id: str
    start_date: str
    end_date: str
    monthly_fee_cents: int
    subsidy_locked_cents: int
    purchase_price_cents: int
    status: str
    fee_arrears_cents: int
    last_fee_charged_at: Optional[str]
    resale_count: int
    created_at: str
    updated_at: str
    version: int


class DefaultNotice(TypedDict, total=False):
    id: str
    lease_id: str
    notice_kind: str
    issued_at: str
    cure_deadline_at: str
    amount_due_cents: int
    status: str
    issued_by: str
    cured_at: Optional[str]
    cure_evidence: str
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict, total=False):
    id: str
    unit_id: str
    scheduled_for: str
    completed_at: Optional[str]
    inspector_user_id: str
    result: str
    findings: str
    follow_up_due_at: Optional[str]
    linked_notice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    household_id: str
    desired_bedrooms: int
    max_price_cents: int
    priority_score: int
    status: str
    matched_unit_id: Optional[str]
    matched_at: Optional[str]
    match_rank_at_match: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ResaleListing(TypedDict, total=False):
    id: str
    unit_id: str
    seller_lease_id: str
    listed_at: str
    appraisal_at_listing_cents: int
    asking_price_cents: int
    seller_proceeds_cents: int
    subsidy_retained_cents: int
    affordability_preserved: bool
    status: str
    matched_waitlist_entry_id: Optional[str]
    buyer_household_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefinanceRequest(TypedDict, total=False):
    id: str
    lease_id: str
    lender_name: str
    requested_loan_cents: int
    requested_cash_out_cents: int
    appraised_value_cents: int
    computed_ltv: float
    program_max_loan_cents: int
    status: str
    rejection_reason: str
    submitted_by: str
    reviewed_by: str
    created_at: str
    updated_at: str
    version: int


# ---- Append-only entities: ONLY id + created_at, NO updated_at, NO version ----

class EducationCompletion(TypedDict, total=False):
    id: str
    household_id: str
    course_id: str
    completed_at: str
    expires_at: str
    recorded_by: str
    score_pct: float
    created_at: str


class LeaseFee(TypedDict, total=False):
    id: str
    lease_id: str
    period_year: int
    period_month: int
    amount_cents: int
    due_date: str
    status: str
    paid_at: Optional[str]
    paid_amount_cents: int
    created_at: str
