"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    COMPLIANCE_MANAGER = "ComplianceManager"
    TRADE_OPS_SPECIALIST = "TradeOpsSpecialist"
    COMPLIANCE_DIRECTOR = "ComplianceDirector"


class ProductStatus(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    CLASSIFIED = "CLASSIFIED"


class ClassificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class Jurisdiction(str, Enum):
    EAR = "EAR"
    ITAR = "ITAR"


class DeterminationBasis(str, Enum):
    SELF_CLASSIFICATION = "SELF_CLASSIFICATION"
    CCATS = "CCATS"
    CJ_DETERMINATION = "CJ_DETERMINATION"


class PartyType(str, Enum):
    CUSTOMER = "CUSTOMER"
    CONSIGNEE = "CONSIGNEE"
    END_USER = "END_USER"
    FOREIGN_NATIONAL = "FOREIGN_NATIONAL"


class ScreeningPosture(str, Enum):
    UNSCREENED = "UNSCREENED"
    CLEAR = "CLEAR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class ListSource(str, Enum):
    SDN = "SDN"
    DENIED_PERSONS = "DENIED_PERSONS"
    ENTITY_LIST = "ENTITY_LIST"
    EMBARGOED_COUNTRY = "EMBARGOED_COUNTRY"


class EntrySeverity(str, Enum):
    PROHIBITED = "PROHIBITED"
    RESTRICTED = "RESTRICTED"


class ListEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TriggerContext(str, Enum):
    ORDER = "ORDER"
    SHIPMENT = "SHIPMENT"
    MANUAL = "MANUAL"
    LIST_CHANGE = "LIST_CHANGE"


class AlgorithmVariant(str, Enum):
    EXACT = "EXACT"
    FUZZY = "FUZZY"


class ScreeningResultStatus(str, Enum):
    CLEAR = "CLEAR"
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    CONFIRMED_MATCH = "CONFIRMED_MATCH"


class EndUse(str, Enum):
    CIVILIAN = "CIVILIAN"
    MILITARY = "MILITARY"
    DUAL_USE = "DUAL_USE"


class Determination(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    LICENSE_REQUIRED = "LICENSE_REQUIRED"
    PROHIBITED = "PROHIBITED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    HELD = "HELD"
    LICENSED = "LICENSED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class IssuingAuthority(str, Enum):
    BIS = "BIS"
    DDTC = "DDTC"
    OFAC = "OFAC"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    SCREENED = "SCREENED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class SegregationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class TcpStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AccessGrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ViolationSourceType(str, Enum):
    ORDER = "ORDER"
    SHIPMENT = "SHIPMENT"
    ACCESS_GRANT = "ACCESS_GRANT"
    SCREENING = "SCREENING"
    OTHER = "OTHER"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class ViolationStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    DISCLOSED = "DISCLOSED"
    CLOSED = "CLOSED"


class AuditEventType(str, Enum):
    CLASSIFICATION_ACTIVATED = "CLASSIFICATION_ACTIVATED"
    LICENSE_APPROVED = "LICENSE_APPROVED"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    ORDER_RELEASED = "ORDER_RELEASED"
    SHIPMENT_RELEASED = "SHIPMENT_RELEASED"
    SHIPMENT_RETURNED = "SHIPMENT_RETURNED"
    GRANT_ACTIVATED = "GRANT_ACTIVATED"
    GRANT_REVOKED = "GRANT_REVOKED"
    SCREENING_CONFIRMED_MATCH = "SCREENING_CONFIRMED_MATCH"
    VSD_SUBMITTED = "VSD_SUBMITTED"
    VIOLATION_CLOSED = "VIOLATION_CLOSED"


# --- Entity bodies (common_fields: id + created_at + updated_at + version) ---


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    controlled_content_pct: int
    unit_value_cents: int
    active_classification_id: Optional[str]
    classification_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Classification(TypedDict, total=False):
    id: str
    product_id: str
    jurisdiction: str
    classification_code: str
    determination_basis: str
    sequence: int
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict, total=False):
    id: str
    legal_name: str
    country_code: str
    city: str
    party_type: str
    is_foreign_national: bool
    screening_posture: str
    active_grant_count: int
    last_screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningListEntry(TypedDict, total=False):
    id: str
    list_source: str
    match_name: str
    country_code: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningResult(TypedDict, total=False):
    id: str
    party_id: str
    trigger_context: str
    matched_entry_id: Optional[str]
    algorithm_variant: str
    score: float
    threshold_used: Optional[float]
    status: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExportOrder(TypedDict, total=False):
    id: str
    product_id: str
    party_id: str
    destination_country: str
    end_use: str
    quantity: int
    license_id: Optional[str]
    provisional_determination: str
    determination: Optional[str]
    determination_classification_sequence: Optional[int]
    goods_value_cents: int
    surcharge_cents: int
    total_value_cents: int
    accumulated_fees_cents: int
    shipped_quantity: int
    pre_hold_status: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    product_id: str
    issuing_authority: str
    approved_value_cents: int
    approved_quantity: int
    valid_from: str
    valid_until: str
    conditions: List[str]
    license_number: Optional[str]
    remaining_value_cents: int
    remaining_quantity: int
    consumed_value_cents: int
    consumed_quantity: int
    applicant_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    quantity: int
    planned_ship_date: str
    screening_result_id: Optional[str]
    consumed_value_cents: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TechnologyControlPlan(TypedDict, total=False):
    id: str
    name: str
    enclave_id: str
    product_id: str
    segregation_level: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    tcp_id: str
    party_id: str
    start_date: str
    end_date: str
    requested_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    source_type: str
    source_id: str
    severity: str
    description: str
    identified_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    disclosure_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (carries ONLY id + created_at — no updated_at, no version; PRD §2.4)
class AuditRecord(TypedDict, total=False):
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor_role: str
    actor_user_id: str
    detail: str
    retain_until: str
    created_at: str
