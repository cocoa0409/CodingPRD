"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes mutable resources (ClientCompany, CommissionAgreement,
Declaration, ShipmentDocument, Filing, InspectionCase, Settlement — carry
id/created_at/updated_at/version) from minimal append-only rows
(RejectionRecord, AuditLog, ExternalEvent — carry only id and created_at;
no updated_at, no version).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BROKER_OPS = "BrokerOps"
    DECLARATION_OFFICER = "DeclarationOfficer"
    DOC_REVIEWER = "DocReviewer"
    FILING_OFFICER = "FilingOfficer"
    INSPECTION_OFFICER = "InspectionOfficer"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    CLIENT_USER = "ClientUser"
    SYSTEM_ADMIN = "SystemAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class ClientCompanyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"


class DeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCS_PENDING = "DOCS_PENDING"
    PRE_VALIDATED = "PRE_VALIDATED"
    FILED = "FILED"
    QUERIED = "QUERIED"
    INSPECTING = "INSPECTING"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    AMENDING = "AMENDING"


class DeclaredValueReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"


class RejectionReasonCode(str, Enum):
    HS_MISMATCH = "HS_MISMATCH"
    VALUE_UNDERSTATED = "VALUE_UNDERSTATED"
    MISSING_LICENSE = "MISSING_LICENSE"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    OTHER = "OTHER"


class DocType(str, Enum):
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    BILL_OF_LADING = "BILL_OF_LADING"
    CONTRACT = "CONTRACT"
    IMPORT_LICENSE = "IMPORT_LICENSE"
    INSPECTION_CERT = "INSPECTION_CERT"
    DANGEROUS_GOODS_DECL = "DANGEROUS_GOODS_DECL"


class AuthenticityStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"


class FilingResponseType(str, Enum):
    AWAITING = "AWAITING"
    RELEASE = "RELEASE"
    QUERY = "QUERY"
    INSPECT = "INSPECT"
    REJECT = "REJECT"


class ManifestMatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    RELEASE = "RELEASE"
    DETENTION = "DETENTION"
    PENALTY = "PENALTY"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    ADVANCED = "ADVANCED"
    REIMBURSED = "REIMBURSED"
    VOIDED = "VOIDED"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    CNY = "CNY"
    JPY = "JPY"
    GBP = "GBP"


class Jurisdiction(str, Enum):
    CN = "CN"
    US = "US"
    EU = "EU"
    JP = "JP"
    GB = "GB"


class TradeAgreementCode(str, Enum):
    NONE = "NONE"
    RCEP = "RCEP"
    USMCA = "USMCA"
    EU_GSP = "EU_GSP"
    CPTPP = "CPTPP"


class TerminatedReason(str, Enum):
    CLIENT_REQUEST = "CLIENT_REQUEST"
    BREACH = "BREACH"
    REGULATORY = "REGULATORY"


class ScopeOfService(str, Enum):
    DECLARATION = "DECLARATION"
    INSPECTION = "INSPECTION"
    TARIFF_ADVANCE = "TARIFF_ADVANCE"
    RETURN_SHIP = "RETURN_SHIP"
    AMENDMENT = "AMENDMENT"


class AuditEntityType(str, Enum):
    DECLARATION = "DECLARATION"
    SETTLEMENT = "SETTLEMENT"
    FILING = "FILING"
    INSPECTION_CASE = "INSPECTION_CASE"
    AGREEMENT = "AGREEMENT"


class AuditEventType(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    FIELD_CHANGE = "FIELD_CHANGE"
    ADVANCE_PAID = "ADVANCE_PAID"
    REIMBURSED = "REIMBURSED"
    AMENDMENT_FILED = "AMENDMENT_FILED"
    VOUCHER_DELIVERED = "VOUCHER_DELIVERED"


class EventSource(str, Enum):
    SINGLE_WINDOW = "SINGLE_WINDOW"
    INSPECTION_QUARANTINE = "INSPECTION_QUARANTINE"
    BANK = "BANK"
    LOGISTICS = "LOGISTICS"


class EventType(str, Enum):
    CUSTOMS_RESPONSE = "CUSTOMS_RESPONSE"
    MANIFEST_DROPPED = "MANIFEST_DROPPED"
    INSPECTION_NOTICE = "INSPECTION_NOTICE"
    BANK_DEBIT_CONFIRMED = "BANK_DEBIT_CONFIRMED"
    RETURN_SHIPMENT_DISPATCHED = "RETURN_SHIPMENT_DISPATCHED"


class TargetEntityType(str, Enum):
    FILING = "FILING"
    DECLARATION = "DECLARATION"
    SETTLEMENT = "SETTLEMENT"
    INSPECTION_CASE = "INSPECTION_CASE"


# ---------------------------------------------------------------------------
# Entity TypedDicts — carry id/created_at/updated_at/version (PRD §2.4)
# ---------------------------------------------------------------------------
class ClientCompany(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    country_code: str
    contact_email: str
    default_settlement_currency: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionAgreement(TypedDict, total=False):
    id: str
    client_id: str
    scope_of_service: List[str]
    fee_schedule: Dict[str, float]
    agreement_currency: str
    valid_from: str
    valid_until: str
    late_interest_daily_rate_bps: int
    status: str
    signed_at: Optional[str]
    signature_token: Optional[str]
    pinned_fee_schedule_version: Optional[int]
    renewed_from_agreement_id: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Declaration(TypedDict, total=False):
    id: str
    agreement_id: str
    jurisdiction_code: str
    shipment_reference: str
    hs_code: str
    country_of_origin: str
    trade_agreement_code: str
    declared_value_amount: float
    declared_currency: str
    fx_rate_to_settlement: Optional[float]
    declared_value_review_status: str
    form_payload: Optional[dict]
    status: str
    rejection_reason_code: Optional[str]
    amendment_count: int
    pinned_agreement_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShipmentDocument(TypedDict, total=False):
    id: str
    declaration_id: str
    doc_type: str
    storage_uri: str
    declared_total_value: Optional[float]
    declared_total_currency: Optional[str]
    authenticity_score: Optional[float]
    authenticity_status: str
    follow_up_requested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict, total=False):
    id: str
    declaration_id: str
    single_window_ref: str
    submitted_at: str
    response_type: str
    response_received_at: Optional[str]
    query_due_at: Optional[str]
    query_response_at: Optional[str]
    manifest_match_status: str
    is_amendment: bool
    created_at: str
    updated_at: str
    version: int


class InspectionCase(TypedDict, total=False):
    id: str
    filing_id: str
    warehouse_code: str
    scheduled_at: str
    sample_required: bool
    sample_provided_at: Optional[str]
    outcome: str
    penalty_amount: float
    post_inspection_doc_uri: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    declaration_id: str
    tariff_amount: float
    vat_amount: float
    consumption_tax_amount: float
    penalty_amount: float
    broker_fee_amount: float
    settlement_currency: str
    advance_paid_amount: float
    advance_paid_at: Optional[str]
    reimbursement_due_at: Optional[str]
    reimbursed_at: Optional[str]
    late_interest_amount: float
    voucher_uri: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable rows — carry only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------
class RejectionRecord(TypedDict, total=False):
    id: str
    declaration_id: str
    rejection_reason_code: str
    archived_at: str
    free_text_note: Optional[str]
    prior_amendment_count: int
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_role: str
    actor_id: str
    payload: Dict[str, Any]
    created_at: str


class ExternalEvent(TypedDict, total=False):
    id: str
    source_system: str
    event_type: str
    target_entity_type: str
    target_entity_id: str
    payload: Dict[str, Any]
    processed_at: str
    created_at: str


__all__ = [
    "UserRole",
    "ClientCompanyStatus",
    "AgreementStatus",
    "DeclarationStatus",
    "DeclaredValueReviewStatus",
    "RejectionReasonCode",
    "DocType",
    "AuthenticityStatus",
    "FilingResponseType",
    "ManifestMatchStatus",
    "InspectionOutcome",
    "SettlementStatus",
    "Currency",
    "Jurisdiction",
    "TradeAgreementCode",
    "TerminatedReason",
    "ScopeOfService",
    "AuditEntityType",
    "AuditEventType",
    "EventSource",
    "EventType",
    "TargetEntityType",
    "ClientCompany",
    "CommissionAgreement",
    "Declaration",
    "ShipmentDocument",
    "Filing",
    "InspectionCase",
    "Settlement",
    "RejectionRecord",
    "AuditLog",
    "ExternalEvent",
]
