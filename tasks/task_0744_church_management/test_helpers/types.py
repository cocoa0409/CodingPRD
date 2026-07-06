"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    FINANCE_ADMIN = "FinanceAdmin"
    COORDINATOR = "Coordinator"
    MEMBER = "Member"
    PLATFORM_ADMIN = "PlatformAdmin"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MemberType(str, Enum):
    ADULT = "ADULT"
    CHILD = "CHILD"


class MembershipStatus(str, Enum):
    VISITOR = "VISITOR"
    REGULAR = "REGULAR"
    MEMBER = "MEMBER"
    DEPARTED = "DEPARTED"


class PledgeCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PledgeFrequency(str, Enum):
    ONE_TIME = "ONE_TIME"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class DonationStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    CARD = "CARD"
    ACH = "ACH"


class StatementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class EventType(str, Enum):
    SERVICE = "SERVICE"
    CLASS = "CLASS"
    MEETING = "MEETING"
    OUTREACH = "OUTREACH"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class FacilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class BookingType(str, Enum):
    EVENT = "EVENT"
    EXTERNAL = "EXTERNAL"


class FacilityBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class VolunteerRoleType(str, Enum):
    USHER = "USHER"
    GREETER = "GREETER"
    CHILDCARE = "CHILDCARE"
    AUDIO_VISUAL = "AUDIO_VISUAL"
    TEACHER = "TEACHER"


class VolunteerAssignmentStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MinistryArea(str, Enum):
    WORSHIP = "WORSHIP"
    STUDY = "STUDY"
    OUTREACH = "OUTREACH"
    CARE = "CARE"
    YOUTH = "YOUTH"


class GroupMembershipRole(str, Enum):
    LEADER = "LEADER"
    CO_LEADER = "CO_LEADER"
    MEMBER = "MEMBER"


class GroupMembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST = "PAST"


class ChildCheckInStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    SECURITY_HOLD = "SECURITY_HOLD"
    CHECKED_OUT = "CHECKED_OUT"


class HoldReason(str, Enum):
    PIN_MISMATCH = "PIN_MISMATCH"
    UNAUTHORIZED_PICKUP = "UNAUTHORIZED_PICKUP"
    STAFF_HOLD = "STAFF_HOLD"


# All 13 business entities carry common fields (id, created_at, updated_at, version)
# per PRD §2.4.


class Household(TypedDict, total=False):
    id: str
    name: str
    address_line1: str
    postal_code: str
    primary_contact_member_id: Optional[str]
    status: str
    archived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    member_type: str
    guardian_member_ids: List[str]
    email: Optional[str]
    phone: Optional[str]
    membership_status: str
    allow_directory_publish: bool
    created_at: str
    updated_at: str
    version: int


class PledgeCampaign(TypedDict, total=False):
    id: str
    name: str
    target_amount_cents: int
    starts_on: str
    ends_on: str
    status: str
    pledged_total_cents: int
    received_total_cents: int
    fulfilled_pledge_count: int
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict, total=False):
    id: str
    campaign_id: str
    member_id: str
    pledged_amount_cents: int
    frequency: str
    first_expected_on: str
    status: str
    received_amount_cents: int
    remaining_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    member_id: str
    campaign_id: Optional[str]
    pledge_id: Optional[str]
    amount_cents: int
    donation_date: str
    payment_method: str
    is_tax_deductible: bool
    status: str
    posted_at: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class YearEndStatement(TypedDict, total=False):
    id: str
    member_id: str
    tax_year: int
    variant: str
    total_deductible_cents: int
    donation_count: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    buffer_minutes: int
    status: str
    upcoming_booked_hours: float
    created_at: str
    updated_at: str
    version: int


class FacilityBooking(TypedDict, total=False):
    id: str
    facility_id: str
    event_id: Optional[str]
    booking_type: str
    starts_at: str
    ends_at: str
    headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict, total=False):
    id: str
    name: str
    event_type: str
    facility_id: Optional[str]
    starts_at: str
    ends_at: str
    expected_attendance: int
    volunteer_slots: int
    status: str
    volunteer_filled_count: int
    attendance_count: int
    coverage_score: float
    created_at: str
    updated_at: str
    version: int


class VolunteerAssignment(TypedDict, total=False):
    id: str
    event_id: str
    member_id: str
    role_type: str
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SmallGroup(TypedDict, total=False):
    id: str
    name: str
    leader_member_id: str
    ministry_area: str
    capacity: int
    status: str
    roster_count: int
    created_at: str
    updated_at: str
    version: int


class GroupMembership(TypedDict, total=False):
    id: str
    group_id: str
    member_id: str
    role: str
    status: str
    joined_on: str
    created_at: str
    updated_at: str
    version: int


class ChildCheckIn(TypedDict, total=False):
    id: str
    child_member_id: str
    event_id: str
    guardian_member_id: str
    pickup_pin: str
    status: str
    checked_in_at: str
    checked_out_at: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
