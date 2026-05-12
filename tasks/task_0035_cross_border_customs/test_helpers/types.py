"""Domain types: entity TypedDicts, status enums, role enum."""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DECLARANT = "Declarant"
    CUSTOMS_OFFICER = "CustomsOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    IMPORTER = "Importer"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Trade modes / dutiable value methods / tax modes
# ---------------------------------------------------------------------------
class TradeMode(str, Enum):
    B2C_DIRECT_MAIL = "B2C_DIRECT_MAIL"
    BONDED_WAREHOUSE = "BONDED_WAREHOUSE"
    GENERAL_TRADE = "GENERAL_TRADE"


class DutiableValueMethod(str, Enum):
    TRANSACTION_VALUE = "TRANSACTION_VALUE"
    DEDUCTIVE_VALUE = "DEDUCTIVE_VALUE"
    COMPUTED_VALUE = "COMPUTED_VALUE"


class TaxMode(str, Enum):
    STANDARD = "STANDARD"
    PERSONAL_POSTAL = "PERSONAL_POSTAL"


class ClassificationSource(str, Enum):
    AUTO_SUGGESTED = "AUTO_SUGGESTED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    RULE_ENGINE = "RULE_ENGINE"


class OverrideReviewStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaymentChannel(str, Enum):
    BANK_TRANSFER = "BANK_TRANSFER"
    ELECTRONIC_PAYMENT = "ELECTRONIC_PAYMENT"
    GUARANTEE_DEDUCTION = "GUARANTEE_DEDUCTION"


class RefundReason(str, Enum):
    RETURN = "RETURN"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"
    ERRONEOUS_DECLARATION = "ERRONEOUS_DECLARATION"


# ---------------------------------------------------------------------------
# Entity statuses
# ---------------------------------------------------------------------------
class HsCodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class ImporterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DeclarantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    PENDING_DECLARATION = "PENDING_DECLARATION"
    DECLARED = "DECLARED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class DeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    QUERIED = "QUERIED"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    CONDITIONALLY_RELEASED = "CONDITIONALLY_RELEASED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


class QueryStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    RESOLVED = "RESOLVED"


class InspectionAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentNoticeStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    REVERSED = "REVERSED"


class RefundStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class AuditEventType(str, Enum):
    DECLARATION_FIELD_CHANGE = "DECLARATION_FIELD_CHANGE"
    DECLARATION_STATUS_CHANGE = "DECLARATION_STATUS_CHANGE"
    TAX_RECOMPUTED = "TAX_RECOMPUTED"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    REFUND_DECISION = "REFUND_DECISION"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


class AuditSubjectType(str, Enum):
    DECLARATION = "DECLARATION"
    PAYMENT_NOTICE = "PAYMENT_NOTICE"
    REFUND = "REFUND"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields == true  → carry id + created_at + updated_at + version
# common_fields == false → carry only id + created_at
# ---------------------------------------------------------------------------

# common_fields: false  (HsCode, TariffRule, ExchangeRate, DeclarationLine,
# InspectionAppointment, AuditEvent)

class HsCode(TypedDict, total=False):
    id: str
    created_at: str
    code: str
    description: str
    keywords: List[str]
    country_code_map: Dict[str, str]
    tariff_rate_bps: int
    vat_rate_bps: int
    consumption_tax_rate_bps: int
    postal_tax_rate_bps: int
    status: str


class TariffRule(TypedDict, total=False):
    id: str
    created_at: str
    hs_code_id: str
    origin_country: str
    destination_country: str
    tariff_rate_bps: int
    effective_from: str
    effective_to: Optional[str]


class ExchangeRate(TypedDict, total=False):
    id: str
    created_at: str
    from_currency: str
    to_currency: str
    rate_micros: int
    effective_date: str


class DeclarationLine(TypedDict, total=False):
    id: str
    created_at: str
    declaration_id: str
    order_line_index: int
    hs_code_id: str
    classification_source: str
    override_review_status: str
    declared_value_minor: int
    line_dutiable_value_cny_minor: int


class InspectionAppointment(TypedDict, total=False):
    id: str
    created_at: str
    declaration_id: str
    scheduled_at: str
    bay_code: str
    status: str


class AuditEvent(TypedDict, total=False):
    id: str
    created_at: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    event_type: str
    before_value: Dict[str, Any]
    after_value: Dict[str, Any]


# common_fields: true  (Order, Declaration, Query, PaymentNotice, Refund,
# Importer, Declarant)

class Importer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    license_number: str
    status: str


class Declarant(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    agent_code: str
    status: str


class Order(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    external_order_ref: str
    importer_id: str
    declarant_id: str
    trade_mode: str
    origin_country: str
    destination_country: str
    currency: str
    line_items: List[Dict[str, Any]]
    total_value_minor: int
    status: str


class Declaration(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    declarant_id: str
    trade_mode: str
    destination_country: str
    dutiable_value_method: str
    dutiable_value_cny_minor: int
    tariff_amount_cny_minor: int
    vat_amount_cny_minor: int
    consumption_tax_cny_minor: int
    total_tax_cny_minor: int
    tax_mode: str
    exchange_rate_date_used: str
    status: str
    submission_count: int
    query_id: Optional[str]
    rejection_reason: Optional[str]
    release_condition: Optional[str]
    pickup_coordinated_at: Optional[str]


class Query(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    declaration_id: str
    question: str
    required_documents: List[str]
    response_text: Optional[str]
    response_documents: List[Dict[str, str]]
    status: str


class PaymentNotice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    declaration_id: str
    amount_cny_minor: int
    due_at: str
    payment_channel: Optional[str]
    voucher_url: Optional[str]
    status: str
    idempotency_key: Optional[str]


class Refund(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    declaration_id: str
    refund_reason: str
    supporting_documents: List[Dict[str, str]]
    refundable_amount_cny_minor: int
    executed_amount_cny_minor: int
    status: str
    rejection_reason: Optional[str]


__all__ = [
    "UserRole",
    "TradeMode",
    "DutiableValueMethod",
    "TaxMode",
    "ClassificationSource",
    "OverrideReviewStatus",
    "PaymentChannel",
    "RefundReason",
    "HsCodeStatus",
    "ImporterStatus",
    "DeclarantStatus",
    "OrderStatus",
    "DeclarationStatus",
    "QueryStatus",
    "InspectionAppointmentStatus",
    "PaymentNoticeStatus",
    "RefundStatus",
    "AuditEventType",
    "AuditSubjectType",
    "HsCode",
    "TariffRule",
    "ExchangeRate",
    "DeclarationLine",
    "InspectionAppointment",
    "AuditEvent",
    "Importer",
    "Declarant",
    "Order",
    "Declaration",
    "Query",
    "PaymentNotice",
    "Refund",
]
