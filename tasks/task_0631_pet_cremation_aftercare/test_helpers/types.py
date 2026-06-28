"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource model in the Pet Cremation & Aftercare PRD. Entities that
carry the full audit fields (id, created_at, updated_at, version) are kept apart
from the two deliberately append-only resources (CustodyEvent, CertificateRecord)
which carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    CREMATORY_ADMIN = "CrematoryAdmin"
    CREMATORY_OPERATOR = "CrematoryOperator"
    CLINIC_STAFF = "ClinicStaff"
    PET_OWNER = "PetOwner"


# --- Status enums ---
class CaseCustodyStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    IN_COOLER = "IN_COOLER"
    STAGED = "STAGED"
    CREMATED = "CREMATED"
    READY_FOR_RETURN = "READY_FOR_RETURN"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class CaseBillingStatus(str, Enum):
    NOT_BILLABLE = "NOT_BILLABLE"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class WeightTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    XLARGE = "XLARGE"


class ServiceType(str, Enum):
    PRIVATE = "PRIVATE"
    COMMUNAL = "COMMUNAL"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    OTHER = "OTHER"


class CoolerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FULL = "FULL"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    LOADED = "LOADED"
    FIRING = "FIRING"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"


class TransportLegStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class ReturnRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class KeepsakeStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    CANCELLED = "CANCELLED"


class MemorialAddonStatus(str, Enum):
    BOOKED = "BOOKED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AccountStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class CustodyEventType(str, Enum):
    INTAKE = "INTAKE"
    TRANSPORT_PICKUP = "TRANSPORT_PICKUP"
    RECEIVED_AT_FACILITY = "RECEIVED_AT_FACILITY"
    COOLER_IN = "COOLER_IN"
    COOLER_OUT = "COOLER_OUT"
    STAGED = "STAGED"
    CREMATED = "CREMATED"
    RETURN_TO_OWNER = "RETURN_TO_OWNER"
    DISPOSED_COMMUNAL = "DISPOSED_COMMUNAL"
    CANCELLED = "CANCELLED"


# --- Entities carrying full audit fields (id, created_at, updated_at, version) ---
class Clinic(TypedDict):
    id: str
    name: str
    account_code: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    account_status: str
    created_at: str
    updated_at: str
    version: int


class PetOwner(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Cooler(TypedDict):
    id: str
    label: str
    total_capacity: int
    occupied_count: int
    available_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Retort(TypedDict):
    id: str
    label: str
    max_load_lbs: int
    created_at: str
    updated_at: str
    version: int


class CremationBatch(TypedDict):
    id: str
    retort_id: str
    service_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    member_count: int
    loaded_weight_lbs: int
    communal_firing_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    clinic_id: Optional[str]
    owner_id: str
    batch_id: Optional[str]
    cooler_id: Optional[str]
    pet_name: str
    species: str
    weight_lbs: int
    weight_tier: str
    service_type: str
    expedited: bool
    pickup_kind: str
    bill_to: str
    custody_status: str
    billing_status: str
    cremation_charge_cents: int
    custody_chain_open: bool
    created_at: str
    updated_at: str
    version: int


class TransportLeg(TypedDict):
    id: str
    case_id: str
    origin_kind: str
    origin_label: str
    driver_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class KeepsakeOrder(TypedDict):
    id: str
    case_id: str
    item_type: str
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRoute(TypedDict):
    id: str
    case_id: str
    return_method: str
    destination_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MemorialAddon(TypedDict):
    id: str
    case_id: str
    addon_type: str
    price_cents: int
    viewing_room_code: Optional[str]
    viewing_start: Optional[str]
    viewing_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    case_id: str
    clinic_id: Optional[str]
    bill_to: str
    subtotal_cents: int
    handling_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only resources: id + created_at only (PRD §2.4) ---
class CustodyEvent(TypedDict):
    id: str
    case_id: str
    seq: int
    event_type: str
    custodian: str
    occurred_at: str
    created_at: str


class CertificateRecord(TypedDict):
    id: str
    case_id: str
    certificate_number: str
    pet_name: str
    service_type: str
    cremated_at: str
    status: str
    created_at: str
