"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INVENTORY_MANAGER = "InventoryManager"
    SALES_PLANNER = "SalesPlanner"
    SALES_MANAGER = "SalesManager"
    PRODUCTION_COORDINATOR = "ProductionCoordinator"
    FIELD_INSTALLER = "FieldInstaller"
    OPERATIONS_AUDITOR = "OperationsAuditor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_ANALYST = "FinanceAnalyst"


class DisplayType(str, Enum):
    STATIC = "STATIC"
    DIGITAL = "DIGITAL"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class FaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    PERMIT_SUSPENDED = "PERMIT_SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class BookingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class WorkOrderType(str, Enum):
    ILLUMINATION_OUTAGE = "ILLUMINATION_OUTAGE"
    STRUCTURAL_REPAIR = "STRUCTURAL_REPAIR"
    VEGETATION_CLEARANCE = "VEGETATION_CLEARANCE"
    POSTING_DAMAGE = "POSTING_DAMAGE"


class AdvertiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class DeliveryPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    UNDER_DELIVERED = "UNDER_DELIVERED"


class FlightStatus(str, Enum):
    HELD = "HELD"
    BOOKED = "BOOKED"
    ART_CLEARED = "ART_CLEARED"
    LIVE = "LIVE"
    MISSED = "MISSED"
    HOLDOVER = "HOLDOVER"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class ArtworkStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    PRINTED = "PRINTED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ArtworkMaterial(str, Enum):
    VINYL = "VINYL"
    POLYETHYLENE = "POLYETHYLENE"
    DIGITAL_FILE = "DIGITAL_FILE"


class PostingStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class MakeGoodReason(str, Enum):
    MISSED_POSTING = "MISSED_POSTING"
    ILLUMINATION_OUTAGE = "ILLUMINATION_OUTAGE"
    PERMIT_SUSPENSION = "PERMIT_SUSPENSION"
    UNDER_DELIVERY = "UNDER_DELIVERY"


class MakeGoodStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class ImpressionSource(str, Enum):
    TRAFFIC_ESTIMATE = "TRAFFIC_ESTIMATE"
    AUDIENCE_MEASURED = "AUDIENCE_MEASURED"


# All resources carry the standard system-managed fields of PRD section 2.4
# (id, created_at, updated_at, version); there are no append-only resources
# without updated_at/version in this domain.


class RateCard(TypedDict, total=False):
    id: str
    market_code: str
    display_type: str
    base_weekly_cents: int
    illumination_premium_pct: float
    traffic_tier_1_threshold: int
    traffic_tier_1_uplift_pct: float
    traffic_tier_2_threshold: int
    traffic_tier_2_uplift_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Face(TypedDict, total=False):
    id: str
    face_code: str
    structure_code: str
    market_code: str
    display_type: str
    illuminated: bool
    daily_traffic_count: int
    width_inches: int
    height_inches: int
    loop_slots_total: Optional[int]
    status: str
    booking_posture: str
    current_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    face_id: str
    supersedes_permit_id: Optional[str]
    permit_number: str
    jurisdiction: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict, total=False):
    id: str
    face_id: str
    order_type: str
    description: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    status: str
    reopen_count: int
    downtime_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class AdvertiserAccount(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    credit_balance_cents: int
    exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    advertiser_id: str
    name: str
    start_date: str
    end_date: str
    status: str
    billing_status: str
    contracted_cents: int
    discount_pct: float
    net_contracted_cents: int
    cancellation_fees_cents: int
    production_charges_cents: int
    delivery_posture: str
    created_at: str
    updated_at: str
    version: int


class ImpressionEntry(TypedDict, total=False):
    period_start: str
    period_end: str
    source: str
    impressions: int


class Flight(TypedDict, total=False):
    id: str
    campaign_id: str
    face_id: str
    rate_card_id: str
    predecessor_flight_id: Optional[str]
    start_date: str
    end_date: str
    loop_slots: Optional[int]
    held_until: str
    weeks: int
    pinned_weekly_cents: int
    gross_cents: int
    discount_pct: float
    net_cents: int
    pinned_rate_card_version: int
    status: str
    cancellation_fee_cents: int
    missed_days: int
    suspension_started_at: Optional[str]
    suspension_days_accrued: int
    holdover_weeks: int
    holdover_charge_cents: int
    impression_entries: List[ImpressionEntry]
    estimated_impressions: int
    delivered_impressions: int
    delivery_ratio: float
    created_at: str
    updated_at: str
    version: int


class ArtworkOrder(TypedDict, total=False):
    id: str
    flight_id: str
    creative_code: str
    material: str
    width_inches: int
    height_inches: int
    revision_count: int
    production_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PostingRecord(TypedDict, total=False):
    id: str
    flight_id: str
    installer_user_id: str
    posted_on: str
    photo_proof_url: str
    notes: str
    status: str
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MakeGood(TypedDict, total=False):
    id: str
    flight_id: str
    reason: str
    credit_cents: int
    status: str
    proposed_by: str
    created_at: str
    updated_at: str
    version: int
