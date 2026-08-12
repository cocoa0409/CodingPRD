"""Domain types: entity TypedDicts, status enums, role enum.

All enum values and field names are PRD-exact (PRD.md sections 2 and 3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    POD_OPERATOR = "PodOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REGISTRAR = "Registrar"
    GUIDE = "Guide"
    FAMILY = "Family"


class PodStatus(str, Enum):
    DRAFT = "DRAFT"
    FORMING = "FORMING"
    LICENSING_REVIEW = "LICENSING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVING = "DISSOLVING"
    DISSOLVED = "DISSOLVED"


class PodPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class ComplianceFlag(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    VIOLATION = "VIOLATION"


class SiteStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    ARCHIVED = "ARCHIVED"


class ZoningClass(str, Enum):
    RESIDENTIAL_SINGLE = "RESIDENTIAL_SINGLE"
    RESIDENTIAL_MULTI = "RESIDENTIAL_MULTI"
    COMMERCIAL = "COMMERCIAL"
    MIXED_USE = "MIXED_USE"
    RELIGIOUS = "RELIGIOUS"
    AGRICULTURAL = "AGRICULTURAL"


class FamilyStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StudentStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class GradeBand(str, Enum):
    LOWER_EL = "LOWER_EL"
    UPPER_EL = "UPPER_EL"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class SeatStatus(str, Enum):
    RESERVED = "RESERVED"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class CertificationTier(str, Enum):
    APPRENTICE = "APPRENTICE"
    CERTIFIED = "CERTIFIED"
    LEAD = "LEAD"


class GuideStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ConferenceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class SubmissionKind(str, Enum):
    EXEMPTION_CLAIM = "EXEMPTION_CLAIM"
    FULL_LICENSE = "FULL_LICENSE"


class DeterminationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EXEMPT_GRANTED = "EXEMPT_GRANTED"
    LICENSE_REQUIRED = "LICENSE_REQUIRED"
    LICENSE_GRANTED = "LICENSE_GRANTED"
    DENIED = "DENIED"
    RESUBMITTED = "RESUBMITTED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ImmunizationPolicy(str, Enum):
    REQUIRED = "REQUIRED"
    EXEMPTION_ALLOWED = "EXEMPTION_ALLOWED"
    NOT_REQUIRED = "NOT_REQUIRED"


class VerificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class FundingStatus(str, Enum):
    FUNDED = "FUNDED"
    PARTIALLY_DEPLETED = "PARTIALLY_DEPLETED"
    DEPLETED = "DEPLETED"
    FROZEN = "FROZEN"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


class LineItemKind(str, Enum):
    TUITION = "TUITION"
    FEE = "FEE"
    CREDIT = "CREDIT"


class SourceKind(str, Enum):
    FAMILY = "FAMILY"
    VOUCHER = "VOUCHER"
    SCHOLARSHIP = "SCHOLARSHIP"
    REFUND_REVERSAL = "REFUND_REVERSAL"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class ClaimKind(str, Enum):
    WITHDRAWAL = "WITHDRAWAL"
    DISSOLUTION = "DISSOLUTION"
    OVERPAYMENT = "OVERPAYMENT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


# --- Entity TypedDicts -------------------------------------------------------
# Entities other than Payment carry id + created_at + updated_at + version.
# Payment is an immutable ledger entry and carries only id + created_at.


class Pod(TypedDict, total=False):
    id: str
    name: str
    pod_code: str
    academic_year: str
    term_start_date: str
    term_end_date: str
    seat_capacity: int
    enrolled_count: int
    tuition_full_year_cents: int
    min_guides_required: int
    facility_site_id: str
    status: str
    posture: str
    compliance_flag: str
    dissolution_reason: Optional[str]
    dissolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacilitySite(TypedDict, total=False):
    id: str
    site_name: str
    address_line1: str
    jurisdiction_code: str
    zoning_class: str
    max_occupancy: int
    indoor_sqft: int
    site_status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict, total=False):
    id: str
    family_name: str
    primary_contact_email: str
    billing_address_state: str
    family_status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    family_id: str
    legal_first_name: str
    legal_last_name: str
    date_of_birth: str
    grade_band: str
    esa_account_id: Optional[str]
    student_status: str
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict, total=False):
    id: str
    pod_id: str
    student_id: str
    reserved_at: str
    enrolled_on: str
    withdrawn_on: Optional[str]
    seat_status: str
    tuition_basis_cents: int
    prorated_due_cents: int
    paid_cents: int
    refund_due_cents: int
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    certification_tier: str
    fte_weight: float
    guide_status: str
    created_at: str
    updated_at: str
    version: int


class GuideAssignment(TypedDict, total=False):
    id: str
    pod_id: str
    guide_id: str
    window_start_date: str
    window_end_date: str
    weekly_hours: int
    assignment_status: str
    is_primary: bool
    created_at: str
    updated_at: str
    version: int


class CurriculumPlan(TypedDict, total=False):
    id: str
    pod_id: str
    plan_name: str
    grade_bands_covered: List[str]
    multi_age_grouping: bool
    total_instructional_minutes_per_week: int
    plan_status: str
    approved_at: Optional[str]
    approved_safety_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgressConference(TypedDict, total=False):
    id: str
    pod_id: str
    seat_id: str
    curriculum_plan_id: str
    scheduled_start: str
    scheduled_end: str
    conference_status: str
    notes_summary: Optional[str]
    cycle_count: int
    created_at: str
    updated_at: str
    version: int


class LicensingDetermination(TypedDict, total=False):
    id: str
    pod_id: str
    jurisdiction_code: str
    submission_kind: str
    determination_status: str
    decided_at: Optional[str]
    revision_number: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyPolicy(TypedDict, total=False):
    id: str
    pod_id: str
    policy_version: int
    emergency_plan_text: str
    immunization_policy: str
    background_check_required: bool
    drill_cadence_days: int
    policy_status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VoucherAccount(TypedDict, total=False):
    id: str
    student_id: str
    program_code: str
    awarded_annual_cents: int
    disbursable_balance_cents: int
    verification_status: str
    funding_status: str
    accepted_by_pod: bool
    created_at: str
    updated_at: str
    version: int


class TuitionInvoice(TypedDict, total=False):
    id: str
    seat_id: str
    billing_period_start: str
    billing_period_end: str
    line_items: List[dict]
    subtotal_cents: int
    admin_fee_cents: int
    total_cents: int
    paid_cents: int
    invoice_status: str
    due_date: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Immutable ledger entry: only id + created_at plus business fields.
    # NO updated_at, NO version.
    id: str
    invoice_id: str
    seat_id: str
    source_kind: str
    voucher_account_id: Optional[str]
    amount_cents: int
    paid_at: str
    payment_status: str
    created_at: str


class RefundClaim(TypedDict, total=False):
    id: str
    pod_id: str
    seat_id: str
    claim_kind: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    claim_status: str
    reviewed_by_user_id: Optional[str]
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int
