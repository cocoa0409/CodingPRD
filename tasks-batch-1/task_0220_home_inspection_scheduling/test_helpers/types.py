"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCHEDULER = "Scheduler"
    INSPECTOR = "Inspector"
    CLIENT = "Client"
    AGENT = "Agent"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RoleInDeal(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class InspectionType(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    FOUR_POINT = "FOUR_POINT"
    WIND_MIT = "WIND_MIT"


class OrderKind(str, Enum):
    PRIMARY = "PRIMARY"
    REINSPECTION = "REINSPECTION"


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_DRAFT = "REPORT_DRAFT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AddOnKind(str, Enum):
    RADON = "RADON"
    TERMITE = "TERMITE"
    SEWER = "SEWER"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SeverityBand(str, Enum):
    PASS = "PASS"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DefectSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DefectStatus(str, Enum):
    LOGGED = "LOGGED"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class DeliveryRecipientKind(str, Enum):
    CLIENT = "CLIENT"
    AGENT = "AGENT"


class DeliveryStatus(str, Enum):
    SENT = "SENT"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (Client, Agent)
# ---------------------------------------------------------------------------
class Territory(TypedDict):
    id: str
    name: str
    zip_codes: List[str]
    travel_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    label: str
    base_rate_cents: int
    tier1_max_sqft: int
    tier2_max_sqft: int
    tier1_rate_cents_per_sqft: int
    tier2_rate_cents_per_sqft: int
    tier3_rate_cents_per_sqft: int
    addon_radon_cents: int
    addon_termite_cents: int
    addon_sewer_cents: int
    reinspection_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    territory_id: str
    certifications: List[str]
    daily_capacity_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — no updated_at, no version
class Client(TypedDict):
    id: str
    full_name: str
    email: str
    role_in_deal: str
    created_at: str


# common_fields: false — no updated_at, no version
class Agent(TypedDict):
    id: str
    full_name: str
    email: str
    brokerage: str
    created_at: str


class Property(TypedDict):
    id: str
    address_line: str
    zip_code: str
    square_footage: int
    year_built: int
    created_at: str
    updated_at: str
    version: int


class InspectionOrder(TypedDict):
    id: str
    property_id: str
    client_id: str
    agent_id: str
    fee_schedule_id: str
    inspector_id: Optional[str]
    parent_order_id: Optional[str]
    order_kind: str
    inspection_type: str
    scheduled_start: Optional[str]
    scheduled_date: Optional[str]
    duration_minutes: Optional[int]
    status: str
    quoted_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    amount_paid_cents: int
    amount_refunded_cents: int
    amount_due_cents: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    order_id: str
    kind: str
    price_cents: int
    added_duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    order_id: str
    measured_square_footage: int
    provisional_risk_score: int
    final_risk_score: Optional[int]
    severity_band: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict):
    id: str
    report_id: str
    location: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    order_id: str
    recipient_kind: str
    recipient_email: str
    severity_band_snapshot: str
    status: str
    created_at: str
    updated_at: str
    version: int
