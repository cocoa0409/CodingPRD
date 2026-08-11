"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONTRACTOR_ADMIN = "ContractorAdmin"
    CONTRACT_MANAGER = "ContractManager"
    FULFILLMENT_COORDINATOR = "FulfillmentCoordinator"
    CREW_LEAD = "CrewLead"
    DISTRICT_BUYER = "DistrictBuyer"
    SERVICE_AGENT = "ServiceAgent"


class BidSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ADDENDUM_ISSUED = "ADDENDUM_ISSUED"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"


class AwardStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"


class PricingMode(str, Enum):
    COOP_TIERED = "COOP_TIERED"
    AWARD_FLAT = "AWARD_FLAT"


class PurchaseOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    IN_FULFILLMENT = "IN_FULFILLMENT"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PurchaseOrderPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"


class POLineStatus(str, Enum):
    PENDING = "PENDING"
    ORDERED = "ORDERED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    BACKORDERED = "BACKORDERED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class ShipmentKind(str, Enum):
    STANDARD = "STANDARD"
    REPLACEMENT = "REPLACEMENT"


class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"


class InstallTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChecklistItem(str, Enum):
    UNCRATED = "UNCRATED"
    DEBRIS_REMOVED = "DEBRIS_REMOVED"
    PLACED = "PLACED"


class DamageReportStatus(str, Enum):
    OPEN = "OPEN"
    REPLACEMENT_ORDERED = "REPLACEMENT_ORDERED"
    RESOLVED = "RESOLVED"
    CLOSED_NO_FAULT = "CLOSED_NO_FAULT"


class DiscoveryPhase(str, Enum):
    DELIVERY = "DELIVERY"
    INSTALL = "INSTALL"


class FaultType(str, Enum):
    TRANSIT = "TRANSIT"
    HANDLING = "HANDLING"
    DEFECT = "DEFECT"


class BackorderNoticeStatus(str, Enum):
    OPEN = "OPEN"
    ETA_UPDATED = "ETA_UPDATED"
    SUPERSEDED = "SUPERSEDED"
    RESOLVED = "RESOLVED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


# All entities carry the standard system-managed fields of PRD §2.4:
# id, created_at, updated_at, version.

class District(TypedDict, total=False):
    id: str
    name: str
    annual_cap_cents: int
    extended_warranty_enrolled: bool
    created_at: str
    updated_at: str
    version: int


class SchoolSite(TypedDict, total=False):
    id: str
    district_id: str
    name: str
    daily_crew_capacity: int
    address: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BidSpec(TypedDict, total=False):
    id: str
    district_id: str
    title: str
    bid_due_date: str
    delivery_window_start: str
    delivery_window_end: str
    spec_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecLine(TypedDict, total=False):
    id: str
    bid_spec_id: str
    manufacturer: str
    model: str
    qty: int
    max_unit_price_cents: int
    description: Optional[str]
    remaining_qty: int
    created_at: str
    updated_at: str
    version: int


class TierRow(TypedDict):
    min_qty: int
    unit_price_cents: int


class CoopPriceAgreement(TypedDict, total=False):
    id: str
    name: str
    contract_year: int
    tier_table: List[TierRow]
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    bid_spec_id: str
    district_id: str
    pricing_mode: str
    coop_agreement_id: Optional[str]
    flat_unit_price_cents: Optional[int]
    install_rate_cents: int
    order_by_date: str
    warranty_years: int
    extended_years: int
    awarded_spec_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    award_id: str
    po_number: str
    fiscal_year: int
    status: str
    posture: str
    open_backorder_count: int
    total_cents: int
    closeout_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class POLine(TypedDict, total=False):
    id: str
    purchase_order_id: str
    spec_line_id: str
    coop_agreement_id: Optional[str]
    ordered_qty: int
    computed_unit_price_cents: int
    line_total_cents: int
    delivered_qty: int
    installed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict, total=False):
    po_line_id: str
    qty: int
    delivered_qty: int
    manufacturer: str
    model: str


class Shipment(TypedDict, total=False):
    id: str
    purchase_order_id: str
    school_site_id: str
    kind: str
    damage_report_id: Optional[str]
    scheduled_date: str
    lines: List[ShipmentLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    name: str
    booked_days: int
    created_at: str
    updated_at: str
    version: int


class InstallTask(TypedDict, total=False):
    id: str
    shipment_id: str
    crew_id: str
    school_site_id: str
    room_label: str
    start_date: str
    end_date: str
    crew_count: int
    crew_days: int
    completed_checklist: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict, total=False):
    id: str
    po_line_id: str
    shipment_id: Optional[str]
    install_task_id: Optional[str]
    damaged_qty: int
    discovered_during: str
    fault_type: str
    reported_date: str
    replacement_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BackorderNotice(TypedDict, total=False):
    id: str
    po_line_id: str
    status: str
    current_eta_date: str
    revision_count: int
    communicated_at: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    po_line_id: str
    parts_cost_cents: int
    description: str
    status: str
    filed_date: str
    coverage_cents: Optional[int]
    appeal_count: int
    denial_reason: Optional[str]
    parts_order_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int
