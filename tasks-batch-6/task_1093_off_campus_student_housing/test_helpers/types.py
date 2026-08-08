"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Every entity carries the common envelope
(id, created_at, updated_at, version) per PRD §2.4 — all thirteen entities are
versioned; none is append-only.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    UNIVERSITY_PARTNER = "UniversityPartner"
    STUDENT = "Student"


class PartnerTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"


class PropertyStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    FULLY_COMMITTED = "FULLY_COMMITTED"
    SUSPENDED = "SUSPENDED"


class OccupancyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_LEASED = "PARTIALLY_LEASED"
    FULLY_LEASED = "FULLY_LEASED"


class CreditScoreBand(str, Enum):
    THIN = "THIN"
    LOW = "LOW"
    FAIR = "FAIR"
    GOOD = "GOOD"
    EXCELLENT = "EXCELLENT"


class SleepSchedule(str, Enum):
    EARLY = "EARLY"
    LATE = "LATE"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RoommateGroupStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    PLACED = "PLACED"


class MembershipStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    PLACED = "PLACED"


class TermType(str, Enum):
    ACADEMIC_YEAR = "ACADEMIC_YEAR"
    PARTIAL_TERM = "PARTIAL_TERM"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_GUARANTOR = "PENDING_GUARANTOR"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIAL = "PARTIAL"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    SETTLED = "SETTLED"


class GuarantorStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class Relationship(str, Enum):
    PARENT = "PARENT"
    GUARDIAN = "GUARDIAN"
    RELATIVE = "RELATIVE"
    EMPLOYER = "EMPLOYER"
    OTHER = "OTHER"


class InstallmentKind(str, Enum):
    RENT = "RENT"
    AMENITY = "AMENITY"
    SUBLET_FEE = "SUBLET_FEE"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LATE = "LATE"
    PAID = "PAID"
    VOID = "VOID"


class SubletStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class AmenityType(str, Enum):
    PARKING = "PARKING"
    STORAGE = "STORAGE"
    GYM = "GYM"
    STUDY_ROOM = "STUDY_ROOM"
    LAUNDRY = "LAUNDRY"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PayoutStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class University(TypedDict):
    id: str
    name: str
    code: str
    partner_tier: str
    partner_discount_bps: int
    verification_required: bool
    academic_year_start_date: str
    academic_year_end_date: str
    partner_admin_user_id: str
    verified_student_count: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    university_id: str
    manager_user_id: str
    name: str
    address_line: str
    distance_to_campus_m: int
    status: str
    unit_count: int
    total_bed_count: int
    available_bed_count: int
    escrow_balance_cents: int
    maintenance_reserve_cents: int
    payout_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    unit_number: str
    floorplan_code: str
    bedroom_count: int
    bathroom_count: int
    bed_labels: List[str]
    base_rent_cents_per_bed_monthly: int
    leased_bed_count: int
    available_bed_count: int
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    university_id: str
    full_name: str
    email: str
    credit_score_band: str
    cleanliness_level: int
    noise_tolerance: int
    sleep_schedule: str
    smoker: bool
    verification_status: str
    verification_submitted_at: Optional[str]
    verification_expires_at: Optional[str]
    verification_decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoommateGroup(TypedDict):
    id: str
    property_id: str
    lead_student_id: str
    name: str
    required_size: int
    status: str
    accepted_member_count: int
    average_match_score: Optional[int]
    lead_anchored_mean_score: Optional[int]
    placed_unit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GroupMembership(TypedDict):
    id: str
    group_id: str
    student_id: str
    sequence_number: int
    status: str
    match_score: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    student_id: str
    unit_id: str
    property_id: str
    roommate_group_id: Optional[str]
    replaces_lease_id: Optional[str]
    bed_label: str
    term_start_date: str
    term_end_date: str
    term_days: int
    term_type: Optional[str]
    monthly_rent_cents: int
    daily_rate_cents: Optional[int]
    quoted_total_cents: int
    total_contract_cents: Optional[int]
    partner_discount_bps: Optional[int]
    partner_discount_cents: Optional[int]
    installment_count: int
    guarantor_required: bool
    lease_status: str
    funding_status: str
    amenity_fee_total_cents: int
    billed_total_cents: int
    paid_cents: int
    signed_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuarantorApplication(TypedDict):
    id: str
    lease_id: str
    guarantor_full_name: str
    guarantor_annual_income_cents: int
    relationship: str
    income_multiple_bps: int
    status: str
    round_count: int
    reviewer_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    lease_id: str
    kind: str
    sequence_number: int
    due_date: str
    amount_cents: int
    status: str
    late_fee_cents: int
    paid_cents: int
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sublet(TypedDict):
    id: str
    lease_id: str
    subtenant_student_id: str
    start_date: str
    end_date: str
    window_days: int
    sublet_rent_cents: int
    sublet_total_cents: int
    platform_fee_cents: Optional[int]
    installment_id: Optional[str]
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Amenity(TypedDict):
    id: str
    property_id: str
    name: str
    amenity_type: str
    capacity: int
    monthly_fee_cents: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class AmenityAssignment(TypedDict):
    id: str
    amenity_id: str
    lease_id: str
    start_date: str
    end_date: str
    window_days: int
    billed_months: int
    total_fee_cents: int
    installment_id: Optional[str]
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    property_id: str
    period_start_date: str
    period_end_date: str
    gross_collected_cents: int
    platform_fee_bps: int
    platform_fee_cents: int
    holdback_cents: int
    subtotal_cents: int
    rebate_cents: int
    net_amount_cents: int
    status: str
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
