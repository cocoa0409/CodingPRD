"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    GATE_OPERATOR = "GateOperator"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    BILLING_CLERK = "BillingClerk"
    HAULER = "Hauler"


class Material(str, Enum):
    MSW = "MSW"
    CONSTRUCTION_DEBRIS = "CONSTRUCTION_DEBRIS"
    GREEN_WASTE = "GREEN_WASTE"
    CLEAN_WOOD = "CLEAN_WOOD"
    TIRE = "TIRE"
    ASBESTOS = "ASBESTOS"


class GasStatus(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EXCEEDANCE = "EXCEEDANCE"


class AcceptancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class CellStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class HaulerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONSUMED = "CONSUMED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class TicketStatus(str, Enum):
    CREATED = "CREATED"
    WEIGHED = "WEIGHED"
    INSPECTED = "INSPECTED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CARD = "CARD"
    CHECK = "CHECK"


# ---- Entities (common_fields: true carry id/created_at/updated_at/version) ----

class Facility(TypedDict):
    id: str
    name: str
    total_airspace_cubic_yards: float
    consumed_airspace_cubic_yards: float
    remaining_airspace_cubic_yards: float
    latest_methane_ppm: int
    gas_status: str
    acceptance_posture: str
    diversion_rate_provisional: float
    diversion_rate_final: float
    created_at: str
    updated_at: str
    version: int


class Cell(TypedDict):
    id: str
    facility_id: str
    name: str
    capacity_cubic_yards: float
    consumed_cubic_yards: float
    remaining_cubic_yards: float
    fill_sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulerAccount(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Manifest(TypedDict):
    id: str
    hauler_account_id: str
    declared_material: str
    declared_weight_tons: float
    is_special_waste: bool
    special_waste_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialWasteApproval(TypedDict):
    id: str
    manifest_id: str
    waste_type: str
    profile_ref: str
    status: str
    decided_by: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    facility_id: str
    hauler_account_id: str
    manifest_id: Optional[str]
    cell_id: Optional[str]
    invoice_id: Optional[str]
    material: str
    gross_weight_tons: float
    tare_weight_tons: Optional[float]
    net_weight_tons: Optional[float]
    is_diverted: bool
    estimated_fee_cents: int
    tipping_fee_cents: Optional[int]
    posted_airspace_cy: Optional[float]
    inspected_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event, carries ONLY id + created_at
class GasReading(TypedDict):
    id: str
    facility_id: str
    methane_ppm: int
    reading_at: str
    resulting_gas_status: str
    created_at: str


class DisposalWindow(TypedDict):
    id: str
    cell_id: str
    waste_type: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScaleReservation(TypedDict):
    id: str
    facility_id: str
    lane_number: int
    truck_ref: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    hauler_account_id: str
    line_ticket_ids: List[str]
    line_count: int
    tipping_subtotal_cents: int
    total_cents: int
    amount_paid_cents: int
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
    updated_at: str
    version: int
