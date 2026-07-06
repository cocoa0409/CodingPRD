"""Domain types: entity TypedDicts, status enums, role enum.

All names use the Device Repair Storefront PRD vocabulary.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    SERVICE_ADVISOR = "ServiceAdvisor"
    STORE_MANAGER = "StoreManager"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class RepairTicketStatus(str, Enum):
    INTAKE = "INTAKE"
    DIAGNOSING = "DIAGNOSING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    IN_REPAIR = "IN_REPAIR"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EstimateStatus(str, Enum):
    SENT = "SENT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    FINALIZED = "FINALIZED"


class PartOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    BACKORDERED = "BACKORDERED"
    INSTALLED = "INSTALLED"
    RETURNED = "RETURNED"


class TradeInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFER_MADE = "OFFER_MADE"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class ProtectionPlanClaimStatus(str, Enum):
    FILED = "FILED"
    ROUTED = "ROUTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Value enums (field domains)
# --------------------------------------------------------------------------
class DeviceCategory(str, Enum):
    PHONE = "PHONE"
    LAPTOP = "LAPTOP"
    TABLET = "TABLET"
    WEARABLE = "WEARABLE"


class CertificationLevel(str, Enum):
    STANDARD = "STANDARD"
    MASTER = "MASTER"


class IntakeChannel(str, Enum):
    WALK_IN = "WALK_IN"
    MAIL_IN = "MAIL_IN"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Recommendation(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class WipeMethod(str, Enum):
    CRYPTO_ERASE = "CRYPTO_ERASE"
    FACTORY_RESET = "FACTORY_RESET"
    PHYSICAL_DESTRUCTION = "PHYSICAL_DESTRUCTION"


class WipeResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PlanType(str, Enum):
    ADH = "ADH"
    EXTENDED_WARRANTY = "EXTENDED_WARRANTY"
    ACCESSORY = "ACCESSORY"


class RoutingDestination(str, Enum):
    IN_STORE = "IN_STORE"
    MANUFACTURER = "MANUFACTURER"
    THIRD_PARTY_ADMIN = "THIRD_PARTY_ADMIN"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    store_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    certification_level: str
    created_at: str
    updated_at: str
    version: int


class RepairBay(TypedDict):
    id: str
    bay_name: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    customer_id: str
    category: str
    brand: str
    model: str
    serial_number: str
    market_value_cents: int
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict):
    id: str
    device_id: str
    customer_id: str
    original_ticket_id: Optional[str]
    intake_channel: str
    reported_issue: str
    is_under_warranty: bool
    is_callback: bool
    spend_cap_cents: int
    assigned_technician_id: Optional[str]
    assigned_bay_id: Optional[str]
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    completed_at: Optional[str]
    final_invoice_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    repair_ticket_id: str
    revision_number: int
    labor_hours: float
    labor_cost_cents: int
    parts_cost_cents: int
    diagnostic_fee_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class PartOrder(TypedDict):
    id: str
    repair_ticket_id: str
    part_id: str
    quantity: int
    line_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    device_id: str
    declared_grade: str
    assessed_grade: Optional[str]
    has_accessories: bool
    assessed_cosmetic_defect_count: int
    quoted_payout_cents: int
    final_payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionPlanClaim(TypedDict):
    id: str
    repair_ticket_id: str
    customer_id: str
    plan_type: str
    routing_destination: Optional[str]
    deductible_cents: int
    covered_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable event, ONLY id + created_at (no updated_at, no version)
class DataWipeCertificate(TypedDict):
    id: str
    device_id: str
    trade_in_id: Optional[str]
    method: str
    wipe_result: str
    certificate_number: str
    created_at: str
