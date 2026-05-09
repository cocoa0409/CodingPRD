"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4: most entities carry id + created_at + updated_at + version.
PaymentRecord, Vote, AccessLog, and AuditEntry are exceptions — they are
write-once / append-only and carry only id + created_at.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Role enum — PRD §2.1: exactly four role names recognized.
# ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    OWNER = "Owner"
    MAINTENANCE_STAFF = "MaintenanceStaff"
    COMMITTEE_CHAIR = "CommitteeChair"


# ──────────────────────────────────────────────────────────
# Status enums — one per entity that has a state machine.
# ──────────────────────────────────────────────────────────

class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    TENANT_OCCUPIED = "TENANT_OCCUPIED"


class VotingStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_DELINQUENT = "INELIGIBLE_DELINQUENT"
    INELIGIBLE_NO_PROPERTY = "INELIGIBLE_NO_PROPERTY"


class ResidentRelationKind(str, Enum):
    FAMILY = "FAMILY"
    TENANT = "TENANT"


class ResidentLifecycleStatus(str, Enum):
    PENDING_MOVE_IN = "PENDING_MOVE_IN"
    RESIDING = "RESIDING"
    MOVED_OUT = "MOVED_OUT"


class WorkOrderCategory(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    STRUCTURAL = "STRUCTURAL"
    LANDSCAPING = "LANDSCAPING"
    SECURITY = "SECURITY"
    OTHER = "OTHER"


class WorkOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FeeBillingRuleKind(str, Enum):
    PER_SQM_MONTHLY = "PER_SQM_MONTHLY"
    FIXED_AMOUNT_MONTHLY = "FIXED_AMOUNT_MONTHLY"


class FeeBillingRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FeeBillStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WAIVED = "WAIVED"


class DunningStage(str, Enum):
    NONE = "NONE"
    REMINDED = "REMINDED"
    ESCALATED = "ESCALATED"
    LEGAL_NOTICE = "LEGAL_NOTICE"


class PaymentChannel(str, Enum):
    WECHAT = "WECHAT"
    ALIPAY = "ALIPAY"
    BANK_TRANSFER = "BANK_TRANSFER"
    CASH = "CASH"


class PaymentReconciliationStatus(str, Enum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class FacilityType(str, Enum):
    CLUBHOUSE = "CLUBHOUSE"
    GYM = "GYM"
    MEETING_ROOM = "MEETING_ROOM"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    DAMAGED = "DAMAGED"


class ProposalVotingMethod(str, Enum):
    PER_HOUSEHOLD = "PER_HOUSEHOLD"
    PER_AREA = "PER_AREA"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    TALLIED_PASSED = "TALLIED_PASSED"
    TALLIED_FAILED = "TALLIED_FAILED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class VoteChoice(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class ParkingSpaceKind(str, Enum):
    FIXED = "FIXED"
    TEMPORARY = "TEMPORARY"
    VISITOR = "VISITOR"


class ParkingSpaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ALLOCATED = "ALLOCATED"
    UNAVAILABLE = "UNAVAILABLE"


class ParkingApplicationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class AccessLogDirection(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class AccessLogClassification(str, Enum):
    BOUND = "BOUND"
    VISITOR_OK = "VISITOR_OK"
    UNAUTHORIZED = "UNAUTHORIZED"


class AuditSubjectKind(str, Enum):
    FEE_BILL = "FEE_BILL"
    FEE_BILLING_RULE = "FEE_BILLING_RULE"
    PROPOSAL = "PROPOSAL"
    VOTE = "VOTE"


# ──────────────────────────────────────────────────────────
# TypedDicts — common-fields entities carry id/created_at/updated_at/version.
# Append-only entities (PaymentRecord, Vote, AccessLog, AuditEntry) carry
# only id + created_at per PRD §2.4.
# ──────────────────────────────────────────────────────────

class Owner(TypedDict, total=False):
    id: str
    full_name: str
    id_card_no: str
    household_register_no: str
    phone: str
    voting_status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    building_no: str
    unit_no: str
    area_sqm: float
    occupancy_status: str
    owner_id: str
    parking_quota: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    property_id: str
    full_name: str
    id_card_no: str
    relation_kind: str
    phone: str
    lifecycle_status: str
    move_in_at: Optional[str]
    move_out_at: Optional[str]
    lease_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    property_id: str
    reporter_owner_id: str
    category: str
    location_tag: str
    photo_urls: List[str]
    status: str
    assigned_staff_id: Optional[str]
    resolved_at: Optional[str]
    confirm_deadline_at: Optional[str]
    satisfaction_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FeeBillingRule(TypedDict, total=False):
    id: str
    rule_code: str
    kind: str
    rate: float
    late_fee_daily_rate: float
    late_fee_cap_pct: float
    rule_status: str
    created_at: str
    updated_at: str
    version: int


class FeeBill(TypedDict, total=False):
    id: str
    property_id: str
    rule_id: str
    period_year: int
    period_month: int
    principal_amount: float
    late_fee_amount: float
    total_due: float
    due_date: str
    status: str
    paid_amount: float
    dunning_stage: str
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at per PRD §2.4.
class PaymentRecord(TypedDict, total=False):
    id: str
    bill_id: str
    channel: str
    external_txn_id: str
    amount: float
    paid_at: str
    reconciliation_status: str
    created_at: str


class Facility(TypedDict, total=False):
    id: str
    facility_type: str
    name: str
    slot_minutes: int
    capacity_per_slot: int
    cancellation_window_hours: int
    damage_deposit: float
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    facility_id: str
    owner_id: str
    slot_start_at: str
    slot_end_at: str
    status: str
    deposit_held: float
    damage_amount: float
    cancellation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    title: str
    voting_method: str
    pass_threshold_pct: float
    voting_starts_at: str
    voting_ends_at: str
    status: str
    eligible_weight_total: float
    yes_weight: float
    no_weight: float
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at per PRD §2.4.
class Vote(TypedDict, total=False):
    id: str
    proposal_id: str
    voter_owner_id: str
    property_id: str
    choice: str
    weight: float
    created_at: str


class ParkingSpace(TypedDict, total=False):
    id: str
    space_no: str
    kind: str
    monthly_fee: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ParkingApplication(TypedDict, total=False):
    id: str
    owner_id: str
    property_id: str
    requested_kind: str
    license_plate: str
    status: str
    allocated_space_id: Optional[str]
    started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at per PRD §2.4.
class AccessLog(TypedDict, total=False):
    id: str
    license_plate: str
    direction: str
    occurred_at: str
    parking_space_id: Optional[str]
    classification: str
    created_at: str


# Append-only — only id + created_at per PRD §2.4.
class AuditEntry(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    before: dict
    after: dict
    created_at: str
