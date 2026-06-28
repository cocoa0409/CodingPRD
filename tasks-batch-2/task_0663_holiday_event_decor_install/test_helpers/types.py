"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full id / created_at / updated_at / version
quartet (PRD §2.4: "There are no immutable, version-free resources in this domain").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    FIELD_SUPERVISOR = "FieldSupervisor"
    CLIENT_CONTACT = "ClientContact"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ─────────────────────────────────────────────────────────
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ScheduleStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"


class VisitStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class StorageLotStatus(str, Enum):
    RESERVED = "RESERVED"
    STORED = "STORED"
    RELEASED = "RELEASED"


class DamageReportStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ResolutionPath(str, Enum):
    REPAIR = "REPAIR"
    RESTOCK = "RESTOCK"


class RestockOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"


class RenewalOfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class AccountType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    HOA = "HOA"
    EVENT = "EVENT"


class JobType(str, Enum):
    INSTALL = "INSTALL"
    REFRESH = "REFRESH"
    TAKEDOWN = "TAKEDOWN"


class InventoryCategory(str, Enum):
    TREE = "TREE"
    WREATH = "WREATH"
    GARLAND = "GARLAND"
    LIGHTING = "LIGHTING"


# ─── Entity TypedDicts (all carry the full quartet) ───────────────────────
class Client(TypedDict):
    id: str
    legal_name: str
    account_type: str
    contact_email: str
    site_address: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    client_id: str
    renewed_from_contract_id: Optional[str]
    contract_type: str
    season_year: int
    early_bird_deadline: str
    custom_design_surcharge_cents: int
    install_fee_cents: Optional[int]
    storage_fee_cents: Optional[int]
    early_bird_discount_cents: Optional[int]
    total_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignProposal(TypedDict):
    id: str
    contract_id: str
    theme: str
    is_custom: bool
    total_unit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProposalLineItem(TypedDict):
    id: str
    proposal_id: str
    inventory_item_id: str
    quantity: int
    unit_install_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    sku: str
    category: str
    unit_replacement_cents: int
    on_hand_qty: int
    reorder_threshold: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    crew_name: str
    daily_capacity_minutes: int
    home_base_zip: str
    planned_utilization_pct: int
    actual_utilization_pct: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    contract_id: str
    crew_id: Optional[str]
    job_type: str
    scheduled_date: Optional[str]
    route_total_minutes: Optional[int]
    schedule_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    work_order_id: str
    stop_sequence: int
    leg_distance_km: float
    on_site_minutes: int
    actual_minutes: Optional[int]
    visit_status: str
    created_at: str
    updated_at: str
    version: int


class StorageLot(TypedDict):
    id: str
    contract_id: str
    storage_bay_id: str
    unit_count: int
    stored_from: str
    released_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageBay(TypedDict):
    id: str
    bay_code: str
    capacity_units: int
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict):
    id: str
    work_order_id: str
    inventory_item_id: str
    damaged_qty: int
    resolution_path: Optional[str]
    replacement_cost_cents: Optional[int]
    settlement_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestockOrder(TypedDict):
    id: str
    damage_report_id: Optional[str]
    inventory_item_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict):
    id: str
    contract_id: str
    provisional_price_cents: Optional[int]
    final_price_cents: Optional[int]
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
