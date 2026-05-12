"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes pinned to PRD §2.4 and §3 prose. Entities listed in PRD §2.4
as immutable event records (SwiftMessage, ExpiryAlert, ExternalEvent,
AuditLogEntry, Clock) carry only id and created_at; their TypedDicts MUST
omit updated_at and version because the contract tells the implementer
not to emit those keys.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    BENEFICIARY = "Beneficiary"
    ISSUING_BANK = "IssuingBank"
    ADVISING_BANK = "AdvisingBank"
    CONFIRMING_BANK = "ConfirmingBank"
    NEGOTIATING_BANK = "NegotiatingBank"
    OPERATOR = "Operator"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3 narratives)
# ---------------------------------------------------------------------------
class LcLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ISSUED = "ISSUED"
    ADVISED = "ADVISED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class AmendmentConsentStatus(str, Enum):
    NONE = "NONE"
    PENDING_APPLICANT = "PENDING_APPLICANT"
    PENDING_BENEFICIARY = "PENDING_BENEFICIARY"
    PENDING_CONFIRMING_BANK = "PENDING_CONFIRMING_BANK"
    CONSENTED = "CONSENTED"
    REJECTED = "REJECTED"


class ConfirmationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"


class LcType(str, Enum):
    SIGHT = "SIGHT"
    USANCE = "USANCE"


class AmendmentStatus(str, Enum):
    PENDING = "PENDING"
    CONSENTED = "CONSENTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ConsentDecision(str, Enum):
    PENDING = "PENDING"
    CONSENTED = "CONSENTED"
    REJECTED = "REJECTED"


class PresentationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    EXAMINED_CLEAN = "EXAMINED_CLEAN"
    EXAMINED_DISCREPANT = "EXAMINED_DISCREPANT"
    ACCEPTED_BY_APPLICANT = "ACCEPTED_BY_APPLICANT"
    REFUSED = "REFUSED"
    RETURNED = "RETURNED"
    SETTLED = "SETTLED"


class ExaminationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PRIMARY_DONE = "PRIMARY_DONE"
    CROSS_CHECK_DONE = "CROSS_CHECK_DONE"
    CONFLICT = "CONFLICT"
    FINALIZED = "FINALIZED"


class ReviewOutcome(str, Enum):
    CLEAN = "CLEAN"
    DISCREPANT = "DISCREPANT"


class DiscrepancyCode(str, Enum):
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    LATE_PRESENTATION = "LATE_PRESENTATION"
    LATE_SHIPMENT = "LATE_SHIPMENT"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    DESCRIPTION_MISMATCH = "DESCRIPTION_MISMATCH"
    INCONSISTENT_DOCS = "INCONSISTENT_DOCS"
    EXPIRED_LC = "EXPIRED_LC"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"


class ApplicantAction(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"


class DocumentType(str, Enum):
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    BILL_OF_LADING = "BILL_OF_LADING"
    PACKING_LIST = "PACKING_LIST"
    INSURANCE_POLICY = "INSURANCE_POLICY"
    CERTIFICATE_OF_ORIGIN = "CERTIFICATE_OF_ORIGIN"


class SettlementType(str, Enum):
    SIGHT_PAYMENT = "SIGHT_PAYMENT"
    USANCE_ACCEPTANCE = "USANCE_ACCEPTANCE"
    NEGOTIATION = "NEGOTIATION"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    COMPENSATED = "COMPENSATED"


class ReimbursementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    HONORED = "HONORED"
    DISPUTED = "DISPUTED"
    EXTINGUISHED = "EXTINGUISHED"


class BankRole(str, Enum):
    ISSUING = "ISSUING"
    ADVISING = "ADVISING"
    CONFIRMING = "CONFIRMING"
    NEGOTIATING = "NEGOTIATING"


class PartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SwiftMessageType(str, Enum):
    MT700 = "MT700"
    MT707 = "MT707"
    MT710 = "MT710"


class ExpiryAlertKind(str, Enum):
    T_MINUS_15 = "T_MINUS_15"
    T_MINUS_5 = "T_MINUS_5"
    EXPIRED = "EXPIRED"
    PRESENTATION_PERIOD_LAPSED = "PRESENTATION_PERIOD_LAPSED"


class ExternalEventSource(str, Enum):
    BANKING = "BANKING"
    CUSTOMS = "CUSTOMS"
    LOGISTICS = "LOGISTICS"
    SWIFT = "SWIFT"


class ExternalEventType(str, Enum):
    BANK_PAYMENT_CONFIRMED = "BANK_PAYMENT_CONFIRMED"
    CUSTOMS_DECLARATION_FILED = "CUSTOMS_DECLARATION_FILED"
    SHIPMENT_DEPARTED = "SHIPMENT_DEPARTED"
    SHIPMENT_DELIVERED = "SHIPMENT_DELIVERED"
    SWIFT_ACK = "SWIFT_ACK"
    SWIFT_NAK = "SWIFT_NAK"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4)
# ---------------------------------------------------------------------------
# Persistent entities — full common fields (PRD §2.4)
class LetterOfCredit(TypedDict, total=False):
    id: str
    lc_number: Optional[str]
    applicant_id: str
    beneficiary_id: str
    issuing_bank_id: str
    advising_bank_id: str
    confirming_bank_id: Optional[str]
    lc_type: str
    usance_tenor_days: Optional[int]
    currency: str
    amount_minor_units: int
    tolerance_pct: float
    drawn_amount_minor_units: int
    available_amount_minor_units: int
    latest_shipment_date: str
    presentation_period_days: int
    expiry_date: str
    confirmation_required: bool
    required_documents: List[str]
    lifecycle_status: str
    amendment_consent_status: str
    confirmation_status: str
    cancelled_reason: Optional[str]
    discrepancy_fee_minor_units: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    name: str
    country_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    name: str
    country_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bank(TypedDict):
    id: str
    bank_role: str
    swift_bic: str
    name: str
    country_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LcAmendment(TypedDict, total=False):
    id: str
    lc_id: str
    amendment_seq: int
    changes: dict
    applicant_consent: str
    beneficiary_consent: str
    confirming_bank_consent: str
    status: str
    rejected_by_role: Optional[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Presentation(TypedDict, total=False):
    id: str
    lc_id: str
    presentation_seq: int
    shipment_date: str
    presented_at: str
    drawing_amount_minor_units: int
    status: str
    refusal_notified_at: Optional[str]
    refusal_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict, total=False):
    id: str
    presentation_id: str
    document_type: str
    issuer: str
    document_date: str
    stated_amount_minor_units: int
    stated_currency: str
    payload: dict
    created_at: str
    updated_at: str
    version: int


class ExaminationReport(TypedDict, total=False):
    id: str
    presentation_id: str
    primary_reviewer_id: str
    secondary_reviewer_id: str
    status: str
    primary_outcome: Optional[str]
    secondary_outcome: Optional[str]
    final_outcome: Optional[str]
    examined_at: Optional[str]
    deadline_at: str
    report_payload: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict, total=False):
    id: str
    examination_report_id: str
    presentation_id: str
    discrepancy_code: str
    description: str
    cited_document_id: Optional[str]
    applicant_action: str
    action_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentSettlement(TypedDict, total=False):
    id: str
    presentation_id: str
    lc_id: str
    settlement_type: str
    principal_minor_units: int
    discrepancy_fee_minor_units: int
    negotiation_advance_minor_units: int
    negotiation_discount_minor_units: int
    beneficiary_proceeds_minor_units: int
    maturity_date: Optional[str]
    accepted_at: Optional[str]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    payment_settlement_id: str
    lc_id: str
    claimed_amount_minor_units: int
    status: str
    honored_amount_minor_units: int
    honored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only / event entities — id + created_at only (PRD §2.4)
class SwiftMessage(TypedDict, total=False):
    id: str
    message_type: str
    subject_type: str
    subject_id: str
    lc_id: str
    sender_bic: str
    receiver_bic: str
    payload: dict
    idempotency_key: str
    created_at: str


class ExpiryAlert(TypedDict, total=False):
    id: str
    lc_id: str
    alert_kind: str
    triggered_at: str
    details: dict
    created_at: str


class ExternalEvent(TypedDict, total=False):
    id: str
    source_system: str
    event_type: str
    lc_id: str
    presentation_id: Optional[str]
    idempotency_key: str
    payload: dict
    processed_at: str
    applied_side_effects: List[str]
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    actor_role: Optional[str]
    actor_id: Optional[str]
    action: str
    subject_type: str
    subject_id: str
    lc_id: str
    before_state: Optional[str]
    after_state: Optional[str]
    payload_digest: str
    created_at: str


class Clock(TypedDict, total=False):
    id: str
    now: str
    created_at: str


__all__ = [
    "UserRole",
    "LcLifecycleStatus",
    "AmendmentConsentStatus",
    "ConfirmationStatus",
    "LcType",
    "AmendmentStatus",
    "ConsentDecision",
    "PresentationStatus",
    "ExaminationStatus",
    "ReviewOutcome",
    "DiscrepancyCode",
    "ApplicantAction",
    "DocumentType",
    "SettlementType",
    "SettlementStatus",
    "ReimbursementStatus",
    "BankRole",
    "PartyStatus",
    "SwiftMessageType",
    "ExpiryAlertKind",
    "ExternalEventSource",
    "ExternalEventType",
    "LetterOfCredit",
    "Applicant",
    "Beneficiary",
    "Bank",
    "LcAmendment",
    "Presentation",
    "Document",
    "ExaminationReport",
    "Discrepancy",
    "PaymentSettlement",
    "ReimbursementClaim",
    "SwiftMessage",
    "ExpiryAlert",
    "ExternalEvent",
    "AuditLogEntry",
    "Clock",
]
