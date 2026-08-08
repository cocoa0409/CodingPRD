"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, List, Optional


# --- Status enums ----------------------------------------------------------

class PlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    RETIRED = "RETIRED"


class DeedStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ISSUED = "ISSUED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    SURRENDERED = "SURRENDERED"


class IntermentOperationalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPENED = "OPENED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISINTERRED = "DISINTERRED"


class IntermentBillingStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DisintermentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"


class MarkerPermitStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    INSTALLED = "INSTALLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    DECOMMISSIONED = "DECOMMISSIONED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    GROUNDS_FOREMAN = "GroundsForeman"
    FINANCE_OFFICER = "FinanceOfficer"
    HEALTH_OFFICER = "HealthOfficer"
    CEMETERY_DIRECTOR = "CemeteryDirector"
    RIGHT_HOLDER = "RightHolder"


# --- Entity TypedDicts -----------------------------------------------------
# Cemetery, Plot, RightHolder, Deed, Interment, DisintermentAuthorization,
# MarkerPermit and Invoice carry id/created_at/updated_at/version (PRD §2.4).
# Decedent, Payment and CareFundEntry carry ONLY id + created_at (PRD §2.4).

class Cemetery(TypedDict):
    id: str
    name: str
    timezone: str
    crew_team_count: int
    perpetual_care_fund_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Plot(TypedDict):
    id: str
    cemetery_id: str
    section_code: str
    row: str
    plot_number: str
    gis_lat: float
    gis_lng: float
    plot_type: str
    interment_capacity: int
    interments_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RightHolder(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Decedent(TypedDict):
    id: str
    full_name: str
    date_of_birth: Optional[str]
    date_of_death: str
    sex: Optional[str]
    death_year: int
    created_at: str
    # append-only immutable record: no updated_at, no version


class Deed(TypedDict):
    id: str
    plot_id: str
    holder_id: str
    purchase_price_cents: int
    sale_type: str
    care_fund_contribution_cents: int
    sale_invoice_id: str
    status: str
    pending_new_holder_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interment(TypedDict):
    id: str
    plot_id: str
    decedent_id: str
    deed_id: str
    interment_type: str
    depth_position: int
    scheduled_date: str
    scheduled_start: str
    scheduled_end: str
    day_type: str
    service_fee_cents: int
    service_invoice_id: str
    operational_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class DisintermentAuthorization(TypedDict):
    id: str
    interment_id: str
    reason: str
    disinterment_type: str
    target_plot_id: Optional[str]
    health_cleared: bool
    nok_consented: bool
    disinterment_invoice_id: str
    settlement_cents: Optional[int]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkerPermit(TypedDict):
    id: str
    plot_id: str
    deed_id: str
    marker_type: str
    foundation_length_in: int
    foundation_width_in: int
    foundation_fee_cents: int
    foundation_invoice_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    label: str
    amount_cents: int
    taxable: bool


class Invoice(TypedDict):
    id: str
    holder_id: str
    subject_type: str
    subject_id: str
    lines: List[InvoiceLine]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    created_at: str
    # append-only event: no updated_at, no version


class CareFundEntry(TypedDict):
    id: str
    cemetery_id: str
    entry_type: str
    amount_cents: int
    source_deed_id: Optional[str]
    note: Optional[str]
    created_at: str
    # append-only ledger event: no updated_at, no version
