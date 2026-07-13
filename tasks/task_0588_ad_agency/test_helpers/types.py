"""Domain types for the Ad Agency Ops API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    CREATIVE_LEAD = "CreativeLead"
    MEDIA_BUYER = "MediaBuyer"
    CLIENT_REVIEWER = "ClientReviewer"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class Industry(str, Enum):
    RETAIL = "RETAIL"
    FINANCE = "FINANCE"
    CPG = "CPG"
    TECH = "TECH"
    AUTO = "AUTO"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class Grade(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    DIRECTOR = "DIRECTOR"


class Channel(str, Enum):
    DISPLAY = "DISPLAY"
    VIDEO = "VIDEO"
    SOCIAL = "SOCIAL"
    OOH = "OOH"
    PRINT = "PRINT"


class RetainerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class SowStatus(str, Enum):
    DRAFT = "DRAFT"
    COUNTERSIGNED = "COUNTERSIGNED"
    EXPIRED = "EXPIRED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_FLIGHT = "IN_FLIGHT"
    ON_HOLD = "ON_HOLD"
    WRAP_UP = "WRAP_UP"
    CLOSED = "CLOSED"


class CampaignObjective(str, Enum):
    AWARENESS = "AWARENESS"
    CONSIDERATION = "CONSIDERATION"
    CONVERSION = "CONVERSION"


class DeliverableStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"


class TimeEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    BILLED = "BILLED"


class VendorCostStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    BILLED = "BILLED"


class VendorType(str, Enum):
    FREELANCER = "FREELANCER"
    PRODUCTION = "PRODUCTION"
    PRINT = "PRINT"
    OTHER = "OTHER"


class MediaPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class InsertionOrderStatus(str, Enum):
    RESERVED = "RESERVED"
    PLACED = "PLACED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BillingMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class InvoicePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


# --------------------------------------------------------------------------
# Entities.  Every one of the thirteen resource types carries the four common
# properties id / created_at / updated_at / version (PRD §2.4).
# --------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    name: str
    industry: str
    billing_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    name: str
    rate_junior_cents_per_hour: int
    rate_senior_cents_per_hour: int
    rate_director_cents_per_hour: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    grade: str
    standard_daily_capacity_minutes: int
    cost_rate_cents_per_hour: int
    created_at: str
    updated_at: str
    version: int


class MediaPlacement(TypedDict):
    id: str
    publisher_name: str
    channel: str
    min_dark_days: int
    created_at: str
    updated_at: str
    version: int


class Retainer(TypedDict):
    id: str
    client_id: str
    period_start: str
    period_end: str
    funded_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SOW(TypedDict):
    id: str
    client_id: str
    rate_card_id: str
    title: str
    labor_cap_cents: int
    markup_pct: float
    effective_start: str
    effective_end: str
    status: str
    pinned_rate_card_version: Optional[int]
    pinned_rate_junior_cents_per_hour: Optional[int]
    pinned_rate_senior_cents_per_hour: Optional[int]
    pinned_rate_director_cents_per_hour: Optional[int]
    consumed_labor_cents: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    client_id: str
    sow_id: str
    name: str
    brief_summary: str
    objective: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    campaign_id: str
    title: str
    current_asset_version: int
    approved_asset_version: Optional[int]
    revision_round: int
    last_feedback: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict):
    id: str
    campaign_id: str
    staff_id: str
    approved_by_staff_id: Optional[str]
    started_at: str
    ended_at: str
    work_date: str
    minutes: int
    billable: bool
    pinned_rate_cents_per_hour: int
    estimated_amount_cents: int
    regular_minutes: int
    overtime_minutes: int
    billable_amount_cents: int
    internal_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorCost(TypedDict):
    id: str
    campaign_id: str
    vendor_name: str
    vendor_type: str
    incurred_on: str
    estimated_amount_cents: int
    actual_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MediaPlan(TypedDict):
    id: str
    campaign_id: str
    approved_budget_cents: int
    allowed_channels: List[str]
    uncommitted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsertionOrder(TypedDict):
    id: str
    media_plan_id: str
    placement_id: str
    flight_start: str
    flight_end: str
    gross_cents: int
    delivered_impressions: int
    delivered_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    campaign_id: str
    retainer_id: str
    billing_mode: str
    period_start: str
    period_end: str
    line_count: int
    labor_cents: int
    vendor_base_cents: int
    vendor_marked_up_cents: int
    media_gross_cents: int
    media_commission_cents: int
    subtotal_cents: int
    discount_pct: float
    discount_cents: int
    admin_fee_cents: int
    total_cents: int
    retainer_applied_cents: int
    cash_due_cents: int
    amount_paid_cents: int
    approval_status: str
    payment_status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
