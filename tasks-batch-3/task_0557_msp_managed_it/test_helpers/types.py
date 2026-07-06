"""Domain types: entity TypedDicts, status enums, role enum (MSP Managed IT).

Per PRD §2.5, `Client`, `Site`, `Technician`, `Contract`, `Asset`, `PatchJob`,
`Ticket`, `Dispatch`, `Quote`, and `ProcurementOrder` are versioned records
carrying id + created_at + updated_at + version. `Invoice` and `SeatAdjustment`
are immutable audit rows and therefore carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFBOARDED = "OFFBOARDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ServiceTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AssetType(str, Enum):
    LAPTOP = "LAPTOP"
    DESKTOP = "DESKTOP"
    PHONE = "PHONE"
    SERVER = "SERVER"


class MonitoringStatus(str, Enum):
    UNMONITORED = "UNMONITORED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PatchJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PatchOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TicketStatus(str, Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class TicketPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class DispatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DispatchMode(str, Enum):
    REMOTE = "REMOTE"
    ONSITE = "ONSITE"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class QuoteType(str, Enum):
    PROJECT = "PROJECT"
    PROCUREMENT = "PROCUREMENT"


class ProcurementOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CANCELLED = "CANCELLED"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SkillLevel(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class UserRole(str, Enum):
    ServiceManager = "ServiceManager"
    Dispatcher = "Dispatcher"
    Technician = "Technician"
    AccountManager = "AccountManager"
    ClientContact = "ClientContact"


# --- Entity TypedDicts (versioned records: PRD §2.5) ---

class Client(TypedDict):
    id: str
    company_name: str
    primary_contact_email: str
    credit_limit_cents: int
    credit_available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    client_id: str
    label: str
    address: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    skill_level: str
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    client_id: str
    service_tier: str
    seat_count: int
    per_seat_rate_cents: int
    backup_addon: bool
    security_addon: bool
    seats_available: int
    period_start: Optional[str]
    period_end: Optional[str]
    period_ticket_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    client_id: str
    site_id: str
    contract_id: Optional[str]
    asset_type: str
    hostname: str
    monitoring_status: str
    patch_compliance_pct: float
    created_at: str
    updated_at: str
    version: int


class PatchJob(TypedDict):
    id: str
    asset_id: str
    window_start: str
    window_end: str
    patch_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    client_id: str
    contract_id: str
    asset_id: Optional[str]
    priority: str
    subject: str
    owner_technician_id: Optional[str]
    first_response_at: Optional[str]
    resolved_at: Optional[str]
    sla_response_due_at: str
    sla_resolve_due_at: str
    sla_response_breached: bool
    sla_resolve_breached: bool
    billable_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    ticket_id: str
    technician_id: str
    mode: str
    scheduled_start: str
    scheduled_end: str
    travel_buffer_minutes: int
    logged_minutes: int
    resolves_ticket: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    client_id: str
    quote_type: str
    title: str
    line_items: List[dict]
    tax_rate: float
    valid_until: str
    subtotal_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcurementOrder(TypedDict):
    id: str
    client_id: str
    quote_id: Optional[str]
    line_items: List[dict]
    tax_rate: float
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Immutable audit rows (PRD §2.5): id + created_at only ---

class Invoice(TypedDict):
    """PRD §2.5: Invoice is an immutable computed snapshot — id + created_at ONLY,
    no updated_at, no version."""
    id: str
    contract_id: str
    variant: str
    period_start: str
    period_end: str
    seat_count_snapshot: int
    total_seat_days: int
    base_seat_charge_cents: int
    volume_discount_cents: int
    addon_charge_cents: int
    overage_charge_cents: int
    total_cents: int
    created_at: str


class SeatAdjustment(TypedDict):
    """PRD §2.5: SeatAdjustment is an immutable seat-change event — id + created_at
    ONLY, no updated_at, no version."""
    id: str
    contract_id: str
    delta: int
    effective_at: str
    reason: Optional[str]
    seat_count_after: int
    created_at: str
