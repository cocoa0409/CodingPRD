"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the Document Shredding & Records Storage PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ACCOUNT_MANAGER = "AccountManager"
    FIELD_TECHNICIAN = "FieldTechnician"
    PLANT_OPERATOR = "PlantOperator"
    DESTRUCTION_WITNESS = "DestructionWitness"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ServiceAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ContainerStatus(str, Enum):
    PLACED = "PLACED"
    SCHEDULED_FOR_SERVICE = "SCHEDULED_FOR_SERVICE"
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"


class ContainerType(str, Enum):
    CONSOLE = "CONSOLE"
    BIN = "BIN"


class ServiceMode(str, Enum):
    ON_SITE = "ON_SITE"
    OFF_SITE_PICKUP = "OFF_SITE_PICKUP"
    DROP_OFF = "DROP_OFF"


class Cadence(str, Enum):
    SCHEDULED = "SCHEDULED"
    ONE_TIME = "ONE_TIME"


class ServiceOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE_SHREDDED = "ON_SITE_SHREDDED"
    PICKED_UP = "PICKED_UP"
    AT_PLANT = "AT_PLANT"
    DESTROYED = "DESTROYED"
    CANCELLED = "CANCELLED"


class CustodySubjectType(str, Enum):
    CONTAINER = "CONTAINER"
    RETENTION_BOX = "RETENTION_BOX"


class CustodyEventType(str, Enum):
    SEALED = "SEALED"
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED_AT_PLANT = "RECEIVED_AT_PLANT"
    DESTROYED = "DESTROYED"
    RETURNED = "RETURNED"


class DestructionCertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class DestructionInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


class RetentionBoxStatus(str, Enum):
    INGESTED = "INGESTED"
    STORED = "STORED"
    OUT_FOR_RETRIEVAL = "OUT_FOR_RETRIEVAL"
    DESTROYED = "DESTROYED"


class RetrievalPriority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class RetrievalRequestStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"


class ComplianceHoldSubjectType(str, Enum):
    RETENTION_BOX = "RETENTION_BOX"
    SERVICE_ORDER = "SERVICE_ORDER"


class ComplianceHoldReason(str, Enum):
    LITIGATION_HOLD = "LITIGATION_HOLD"
    AUDIT_HOLD = "AUDIT_HOLD"
    REGULATORY_FREEZE = "REGULATORY_FREEZE"


class ComplianceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ComplianceRegime(str, Enum):
    STANDARD = "STANDARD"
    FACTA = "FACTA"
    HIPAA = "HIPAA"


class StorageInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (append-only evidence)
# --------------------------------------------------------------------------
class ServiceAccount(TypedDict):
    id: str
    business_name: str
    compliance_regime: str
    billing_email: str
    current_period_index: int
    storage_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceLocation(TypedDict):
    id: str
    account_id: str
    label: str
    address: str
    secure_area: bool
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    account_id: str
    scheduled_purge_rate_cents_per_kg: int
    onetime_purge_rate_cents_per_kg: int
    onsite_trip_fee_cents: int
    console_swap_fee_cents: int
    storage_rate_cents_per_box_per_period: int
    retrieval_fee_cents: int
    rush_retrieval_multiplier_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    account_id: str
    location_id: str
    container_type: str
    capacity_kg: int
    tare_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    account_id: str
    location_id: str
    service_mode: str
    cadence: str
    container_ids: List[str]
    scheduled_slot_start: str
    scheduled_slot_end: str
    billed_weight_kg: float
    order_charge_cents: int
    assigned_tech_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only immutable evidence (no updated_at, no version)
class WeightTicket(TypedDict):
    id: str
    order_id: str
    gross_weight_kg: float
    tare_total_kg: float
    net_weight_kg: float
    captured_by: str
    created_at: str


# common_fields: false — append-only tamper-evident chain (no updated_at, no version)
class CustodyEvent(TypedDict):
    id: str
    order_id: str
    subject_type: str
    subject_id: str
    event_type: str
    sequence_no: int
    actor_id: str
    created_at: str


class DestructionCertificate(TypedDict):
    id: str
    order_id: str
    account_id: str
    certificate_no: str
    destroyed_weight_kg: float
    witnessed_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DestructionInvoice(TypedDict):
    id: str
    order_id: str
    account_id: str
    certificate_id: str
    line_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionBox(TypedDict):
    id: str
    account_id: str
    location_id: str
    barcode: str
    stored_at_period: int
    free_periods: int
    destroy_after_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrievalRequest(TypedDict):
    id: str
    box_id: str
    account_id: str
    priority: str
    retrieval_charge_cents: int
    delivered_period: int
    requested_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceHold(TypedDict):
    id: str
    account_id: str
    subject_type: str
    subject_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageInvoice(TypedDict):
    id: str
    account_id: str
    period_index: int
    storage_line_cents: int
    retrieval_line_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
