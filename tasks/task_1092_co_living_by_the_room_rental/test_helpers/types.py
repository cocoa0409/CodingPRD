"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Co-Living By-The-Room Rental PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    HOST = "Host"
    MEMBER = "Member"
    COMMUNITY_MANAGER = "CommunityManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_ADMIN = "FinanceAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class HousePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class RoomOccupancy(str, Enum):
    VACANT = "VACANT"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    NOTICE_PENDING = "NOTICE_PENDING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MemberBand(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    DENIED = "DENIED"
    CONVERTED = "CONVERTED"


class BillingCycle(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class TenancyStatus(str, Enum):
    PENDING_MOVE_IN = "PENDING_MOVE_IN"
    ACTIVE = "ACTIVE"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    MOVED_OUT = "MOVED_OUT"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    SETTLED = "SETTLED"


class NoticeReason(str, Enum):
    MEMBER_INITIATED = "MEMBER_INITIATED"
    NONPAYMENT = "NONPAYMENT"
    COMPLIANCE = "COMPLIANCE"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    PAST_DUE = "PAST_DUE"
    PAID = "PAID"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CASH = "CASH"


class BackgroundResult(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    FAILED = "FAILED"


class RuleCode(str, Enum):
    QUIET_HOURS = "QUIET_HOURS"
    GUEST_POLICY = "GUEST_POLICY"
    CLEANLINESS = "CLEANLINESS"
    SMOKING = "SMOKING"
    UNAUTHORIZED_OCCUPANT = "UNAUTHORIZED_OCCUPANT"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    DISPUTED = "DISPUTED"


class TicketArea(str, Enum):
    ROOM = "ROOM"
    SHARED_KITCHEN = "SHARED_KITCHEN"
    SHARED_BATH = "SHARED_BATH"
    LAUNDRY = "LAUNDRY"
    COMMON_AREA = "COMMON_AREA"


class TicketSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    RESOLVED = "RESOLVED"


class PayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    PROJECTED = "PROJECTED"
    RELEASED = "RELEASED"


class PayoutVariant(str, Enum):
    NONE = "NONE"
    ACCRUAL_PROJECTION = "ACCRUAL_PROJECTION"
    CASH_FINAL = "CASH_FINAL"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Host(TypedDict):
    id: str
    legal_name: str
    payout_account_ref: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class House(TypedDict):
    id: str
    host_id: str
    label: str
    address_line1: str
    city: str
    state_code: str
    monthly_utility_budget_cents: int
    total_room_count: int
    vacant_room_count: int
    reserved_room_count: int
    occupied_room_count: int
    notice_pending_room_count: int
    out_of_service_room_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    house_id: str
    room_number: str
    weekly_rate_cents: int
    monthly_rate_cents: int
    private_bath: bool
    occupancy_state: str
    available_from_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    declared_monthly_income_cents: int
    strike_points: int
    standing_band: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    member_id: str
    room_id: str
    requested_move_in_date: str
    billing_cycle: str
    status: str
    cosigner_monthly_income_cents: Optional[int]
    screening_round: int
    monthly_equivalent_cents: int
    required_income_cents: int
    required_deposit_cents: int
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row, only id + created_at
class ScreeningReport(TypedDict):
    id: str
    application_id: str
    sequence_number: int
    background_result: str
    verified_monthly_income_cents: int
    report_reference: str
    submitted_by_user_id: str
    created_at: str


class Membership(TypedDict):
    id: str
    application_id: str
    member_id: str
    room_id: str
    house_id: str
    billing_cycle: str
    period_days: int
    base_period_rate_cents: int
    deposit_cents: int
    move_in_date: str
    tenancy_status: str
    billing_status: str
    notice_reason: Optional[str]
    scheduled_move_out_date: Optional[str]
    actual_move_out_date: Optional[str]
    effective_end_date: Optional[str]
    provisional_final_charge_cents: Optional[int]
    final_charge_cents: Optional[int]
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    membership_id: str
    period_start: str
    period_end: str
    due_date: str
    occupied_rooms_at_period_start: int
    base_rent_cents: int
    utility_share_cents: int
    subtotal_cents: int
    proration_adjustment_cents: int
    late_fee_cents: int
    total_amount_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row, only id + created_at
class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    applied_at: str
    recorded_by_user_id: str
    created_at: str


class HouseRuleIncident(TypedDict):
    id: str
    house_id: str
    membership_id: str
    rule_code: str
    severity: str
    severity_points: int
    occurred_at: str
    description: str
    status: str
    reported_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    dispute_round: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict):
    id: str
    house_id: str
    room_id: Optional[str]
    affected_membership_id: Optional[str]
    area: str
    severity: str
    description: str
    status: str
    sla_deadline_at: str
    visit_start: Optional[str]
    visit_end: Optional[str]
    resolved_at: Optional[str]
    breach_hours: int
    rent_credit_cents: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    house_id: str
    cycle_start: str
    cycle_end: str
    status: str
    variant_applied: str
    gross_cents: int
    platform_fee_cents: int
    maintenance_credit_cents: int
    reserve_cents: int
    net_payout_cents: int
    projected_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
