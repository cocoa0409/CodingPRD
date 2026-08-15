"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class MemberStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MemberType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    IRRIGATION = "IRRIGATION"


class ServiceLocationStatus(str, Enum):
    PENDING_CONSTRUCTION = "PENDING_CONSTRUCTION"
    ENERGIZED = "ENERGIZED"
    DISCONNECTED = "DISCONNECTED"
    REMOVED = "REMOVED"


class RateClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL_GENERAL = "COMMERCIAL_GENERAL"
    COMMERCIAL_DEMAND = "COMMERCIAL_DEMAND"
    IRRIGATION = "IRRIGATION"
    SEASONAL = "SEASONAL"


class RateScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class AllocationMethod(str, Enum):
    PATRONAGE_WEIGHTED = "PATRONAGE_WEIGHTED"
    FLAT_PER_MEMBER = "FLAT_PER_MEMBER"


class RetirementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    BOARD_APPROVED = "BOARD_APPROVED"
    EXECUTING = "EXECUTING"
    SETTLED = "SETTLED"
    ABORTED = "ABORTED"


class RetirementMethod(str, Enum):
    FIFO_OLDEST = "FIFO_OLDEST"
    PRO_RATA_PERCENTAGE = "PRO_RATA_PERCENTAGE"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    CASHED = "CASHED"
    UNCLAIMED = "UNCLAIMED"
    ESCHEATED = "ESCHEATED"


class OutageStatus(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CREW_DISPATCHED = "CREW_DISPATCHED"
    RESTORED = "RESTORED"
    DUPLICATE = "DUPLICATE"
    CANCELLED = "CANCELLED"


class OutageCause(str, Enum):
    WEATHER = "WEATHER"
    EQUIPMENT = "EQUIPMENT"
    VEGETATION = "VEGETATION"
    ANIMAL = "ANIMAL"
    UNKNOWN = "UNKNOWN"


class RowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MEMBER_CONSENTED = "MEMBER_CONSENTED"
    RECORDED = "RECORDED"
    CONTESTED = "CONTESTED"
    CONDEMNATION = "CONDEMNATION"
    RELEASED = "RELEASED"


class DeviceType(str, Enum):
    WATER_HEATER = "WATER_HEATER"
    IRRIGATION_INTERRUPTIBLE = "IRRIGATION_INTERRUPTIBLE"
    AC_CYCLER = "AC_CYCLER"


class DeviceStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    UNENROLLED = "UNENROLLED"


class ServiceOrderType(str, Enum):
    NEW_SERVICE = "NEW_SERVICE"
    UPGRADE = "UPGRADE"
    RELOCATION = "RELOCATION"
    TEMPORARY = "TEMPORARY"


class ServiceOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    ATC_INVOICED = "ATC_INVOICED"
    PAID = "PAID"
    SCHEDULED = "SCHEDULED"
    CONSTRUCTED = "CONSTRUCTED"
    ENERGIZED = "ENERGIZED"
    CANCELLED = "CANCELLED"


class ElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    NOMINATION_OPEN = "NOMINATION_OPEN"
    NOMINATION_CLOSED = "NOMINATION_CLOSED"
    VOTING_OPEN = "VOTING_OPEN"
    VOTING_CLOSED = "VOTING_CLOSED"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class MeterReadingSource(str, Enum):
    AMR = "AMR"
    MANUAL = "MANUAL"
    ESTIMATED = "ESTIMATED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MEMBER_SERVICES_REP = "MemberServicesRep"
    BOARD_DIRECTOR = "BoardDirector"
    BOARD_SECRETARY = "BoardSecretary"
    RATE_ANALYST = "RateAnalyst"
    BILLING_CLERK = "BillingClerk"
    FIELD_OPS_COORDINATOR = "FieldOpsCoordinator"
    DISPATCHER = "Dispatcher"
    LEGAL_COUNSEL = "LegalCounsel"
    MEMBER = "Member"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Cooperative(TypedDict, total=False):
    id: str
    name: str
    fiscal_year_end_month: int
    capital_credits_pool_cents: int
    retirement_methods_allowed: List[str]
    unclaimed_dormancy_years: int
    annual_meeting_quorum_pct: float
    irrigation_season_start_month: int
    irrigation_season_end_month: int
    active_election_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    legal_name: str
    member_type: str
    status: str
    joined_at: Optional[str]
    terminated_at: Optional[str]
    capital_credit_balance_cents: int
    unclaimed_credit_cents: int
    patronage_base_kwh: int
    patronage_base_irrigation_kwh: int
    deposit_cents: int
    district_id: int
    created_at: str
    updated_at: str
    version: int


class ServiceLocation(TypedDict, total=False):
    id: str
    member_id: str
    address: str
    rate_class: str
    status: str
    energized_at: Optional[str]
    seasonal_active: bool
    irrigation_connected_load_kw: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    code: str
    rate_class: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    customer_charge_cents: int
    tiers: List[dict]
    demand_charge_cents_per_kw: int
    irrigation_offseason_discount_pct: float
    load_management_credit_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): id + created_at only — no updated_at, no version.
class MeterReading(TypedDict, total=False):
    id: str
    created_at: str
    service_location_id: str
    reading_at: str
    kwh_register: int
    demand_kw: float
    source: str


class Invoice(TypedDict, total=False):
    id: str
    service_location_id: str
    billing_period_start: str
    billing_period_end: str
    status: str
    kwh_billed: int
    demand_kw_billed: float
    energy_charge_cents: int
    demand_charge_cents: int
    load_management_credit_cents: int
    total_due_cents: int
    variant: str
    created_at: str
    updated_at: str
    version: int


class CapitalCreditAllocation(TypedDict, total=False):
    id: str
    cooperative_id: str
    fiscal_year: int
    status: str
    total_allocated_cents: int
    method: str
    created_at: str
    updated_at: str
    version: int


class CapitalCreditAllocationLine(TypedDict, total=False):
    id: str
    allocation_id: str
    member_id: str
    allocated_cents: int
    weight_kwh_effective: float
    created_at: str
    updated_at: str
    version: int


class CapitalCreditRetirement(TypedDict, total=False):
    id: str
    cooperative_id: str
    status: str
    method: str
    total_retire_cents: int
    pro_rata_pct: Optional[float]
    executed_at: Optional[str]
    total_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class CapitalCreditPayout(TypedDict, total=False):
    id: str
    retirement_id: str
    member_id: str
    payout_cents: int
    status: str
    issued_at: Optional[str]
    claim_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutageReport(TypedDict, total=False):
    id: str
    service_location_id: str
    reported_by_member_id: str
    status: str
    cause: str
    parent_outage_id: Optional[str]
    restored_at: Optional[str]
    notified_member_count: int
    created_at: str
    updated_at: str
    version: int


class RightOfWayAgreement(TypedDict, total=False):
    id: str
    service_location_id: str
    status: str
    easement_width_ft: float
    consented_at: Optional[str]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoadManagementDevice(TypedDict, total=False):
    id: str
    service_location_id: str
    device_type: str
    status: str
    enrolled_at: str
    monthly_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    service_location_id: str
    order_type: str
    status: str
    distance_ft: float
    requires_road_bore: bool
    aid_to_construction_cents: int
    row_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardElection(TypedDict, total=False):
    id: str
    cooperative_id: str
    year: int
    status: str
    seats: List[int]
    voting_opens_at: str
    voting_closes_at: str
    quorum_met: bool
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): id + created_at only.
class Ballot(TypedDict, total=False):
    id: str
    created_at: str
    election_id: str
    member_id: str
    district: int
    candidate_name: str
    cast_at: str
    is_proxy: bool
