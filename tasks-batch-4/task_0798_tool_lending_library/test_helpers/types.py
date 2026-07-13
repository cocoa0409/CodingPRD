"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted entity in this API carries the common fields id, created_at,
updated_at, and version (PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Role enum
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    MEMBER = "Member"
    VOLUNTEER = "Volunteer"
    COORDINATOR = "Coordinator"


# --------------------------------------------------------------------------- #
# Status / enum value sets
# --------------------------------------------------------------------------- #
class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"


class VolunteerRoleLevel(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    COORDINATOR = "COORDINATOR"


class ItemCategory(str, Enum):
    TOOL = "TOOL"
    OUTDOOR = "OUTDOOR"
    KITCHEN = "KITCHEN"


class CopyAvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ON_LOAN = "ON_LOAN"


class CopyConditionStatus(str, Enum):
    GOOD = "GOOD"
    NEEDS_MAINTENANCE = "NEEDS_MAINTENANCE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    RETIRED = "RETIRED"


class CopyOrigin(str, Enum):
    PURCHASE = "PURCHASE"
    DONATION = "DONATION"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ReservationSource(str, Enum):
    MEMBER = "MEMBER"
    WAITLIST_PROMOTION = "WAITLIST_PROMOTION"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    LOST = "LOST"


class ReturnCondition(str, Enum):
    GOOD = "GOOD"
    MINOR_DAMAGE = "MINOR_DAMAGE"
    MAJOR_DAMAGE = "MAJOR_DAMAGE"
    LOST = "LOST"


class HoldStatus(str, Enum):
    PENDING = "PENDING"
    PROMOTED = "PROMOTED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"


class FeeType(str, Enum):
    LATE = "LATE"
    DAMAGE = "DAMAGE"
    REPLACEMENT = "REPLACEMENT"


class FeeStatus(str, Enum):
    ACCRUING = "ACCRUING"
    PENDING = "PENDING"
    PAID = "PAID"
    WAIVED = "WAIVED"


class DonationStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DonationCondition(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"


class MaintenanceReason(str, Enum):
    DAMAGE = "DAMAGE"
    ROUTINE = "ROUTINE"
    INSPECTION = "INSPECTION"


class MaintenanceSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class MaintenanceSource(str, Enum):
    MANUAL = "MANUAL"
    DAMAGE_INTAKE = "DAMAGE_INTAKE"


class MaintenanceOutcome(str, Enum):
    RETURN_TO_SERVICE = "RETURN_TO_SERVICE"
    SCRAP = "SCRAP"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4)
# --------------------------------------------------------------------------- #
class Member(TypedDict):
    id: str
    name: str
    email: str
    tier: str
    status: str
    max_active_loans: int
    max_active_holds: int
    balance_limit_cents: int
    membership_expires_at: Optional[str]
    outstanding_balance_cents: int
    total_assessed_cents: int
    total_paid_cents: int
    total_waived_cents: int
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    name: str
    role_level: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    name: str
    category: str
    replacement_value_cents: int
    loan_period_days: int
    daily_late_fee_cents: int
    max_renewals: int
    serviceable_copies_count: int
    available_copies_count: int
    reserved_count: int
    on_loan_count: int
    maintenance_count: int
    waitlist_length: int
    created_at: str
    updated_at: str
    version: int


class ItemCopy(TypedDict):
    id: str
    item_id: str
    asset_tag: str
    acquired_on: str
    origin: str
    availability_status: str
    condition_status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    item_id: str
    copy_id: Optional[str]
    window_start: str
    window_end: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    member_id: str
    copy_id: str
    reservation_id: Optional[str]
    item_id: str
    checked_out_at: str
    due_date: str
    renewals_used: int
    status: str
    return_condition: Optional[str]
    returned_at: Optional[str]
    checked_out_by_volunteer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    member_id: str
    item_id: str
    promoted_reservation_id: Optional[str]
    claim_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fee(TypedDict):
    id: str
    member_id: str
    loan_id: Optional[str]
    fee_type: str
    amount_cents: int
    status: str
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    donor_name: str
    donor_member_id: Optional[str]
    item_id: str
    proposed_condition: str
    created_copy_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict):
    id: str
    copy_id: str
    reason: str
    severity: Optional[str]
    source: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
