"""Domain types for the Public Library API.

Status enums and entity TypedDicts derived from PRD §3 (workflows) and PRD §2.4
(common resource properties).

All entities carry common fields (id, created_at, updated_at, version) EXCEPT
AuditLog, which is append-only per PRD §2.4: AuditLog rows carry only id and
created_at — no updated_at and no version.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─────────────────────────────────────────────────────────────
# Roles (PRD §2.1)
# ─────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    READER = "Reader"
    LIBRARIAN = "Librarian"
    FINE_OFFICER = "FineOfficer"
    ILL_COORDINATOR = "ILLCoordinator"
    ADMIN = "Admin"


# ─────────────────────────────────────────────────────────────
# BookTitle / Copy enums (PRD §3.1)
# ─────────────────────────────────────────────────────────────


class BookTitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ClassificationScheme(str, Enum):
    DEWEY = "DEWEY"
    CLC = "CLC"


class SubjectCategory(str, Enum):
    GENERAL = "GENERAL"
    REFERENCE = "REFERENCE"
    CHILDREN = "CHILDREN"
    RARE = "RARE"


class AcquisitionSource(str, Enum):
    PURCHASE = "PURCHASE"
    DONATION = "DONATION"
    EXCHANGE = "EXCHANGE"
    ILL_PURCHASE = "ILL_PURCHASE"


class CopyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LOAN = "ON_LOAN"
    RESERVED = "RESERVED"
    IN_TRANSIT_ILL = "IN_TRANSIT_ILL"
    WEEDED = "WEEDED"


class WeedingReason(str, Enum):
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    OBSOLETE = "OBSOLETE"
    LOW_CIRCULATION = "LOW_CIRCULATION"


# ─────────────────────────────────────────────────────────────
# Reader / Card enums (PRD §3.2)
# ─────────────────────────────────────────────────────────────


class ReaderStatus(str, Enum):
    NORMAL = "NORMAL"
    OVERDUE = "OVERDUE"
    BLACKLISTED = "BLACKLISTED"


class CardType(str, Enum):
    REGULAR = "REGULAR"
    STUDENT = "STUDENT"
    SENIOR = "SENIOR"
    TEMPORARY = "TEMPORARY"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    REISSUED = "REISSUED"
    EXPIRED = "EXPIRED"


# ─────────────────────────────────────────────────────────────
# Loan / Reservation enums (PRD §3.3-§3.5)
# ─────────────────────────────────────────────────────────────


class LoanStatus(str, Enum):
    BORROWED = "BORROWED"
    RENEWED = "RENEWED"
    RECALL_PENDING = "RECALL_PENDING"
    RETURNED = "RETURNED"
    OVERDUE_CLOSED = "OVERDUE_CLOSED"


class LoanChannel(str, Enum):
    COUNTER = "COUNTER"
    KIOSK = "KIOSK"


class ReservationChannel(str, Enum):
    ONLINE = "ONLINE"
    ON_SITE = "ON_SITE"


class ReservationStatus(str, Enum):
    QUEUED = "QUEUED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


# ─────────────────────────────────────────────────────────────
# Fine enums (PRD §3.6)
# ─────────────────────────────────────────────────────────────


class FineSettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


class WaiverReason(str, Enum):
    SYSTEM_FAULT = "SYSTEM_FAULT"
    HOLIDAY = "HOLIDAY"
    HARDSHIP = "HARDSHIP"


# ─────────────────────────────────────────────────────────────
# ILL enums (PRD §3.7)
# ─────────────────────────────────────────────────────────────


class PartnerLibraryCode(str, Enum):
    PL_A = "PL_A"
    PL_B = "PL_B"
    PL_C = "PL_C"


class ILLRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_PARTNER = "AT_PARTNER"
    RETURNED_TRANSIT = "RETURNED_TRANSIT"
    SETTLED = "SETTLED"


# ─────────────────────────────────────────────────────────────
# AcquisitionSuggestion enums (PRD §3.8)
# ─────────────────────────────────────────────────────────────


class SuggestionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACQUIRED = "ACQUIRED"
    DECLINED = "DECLINED"
    DEFERRED = "DEFERRED"


class SuggestionDecision(str, Enum):
    ACQUIRE = "ACQUIRE"
    DECLINE = "DECLINE"
    DEFER = "DEFER"


# ─────────────────────────────────────────────────────────────
# AuditLog enums (PRD §2.8)
# ─────────────────────────────────────────────────────────────


class AuditEventType(str, Enum):
    LOAN_CREATED = "LOAN_CREATED"
    LOAN_RENEWED = "LOAN_RENEWED"
    LOAN_RECALLED = "LOAN_RECALLED"
    LOAN_RETURNED = "LOAN_RETURNED"
    FINE_ACCRUED = "FINE_ACCRUED"
    FINE_WAIVED = "FINE_WAIVED"
    FINE_PAID = "FINE_PAID"
    RESERVATION_CREATED = "RESERVATION_CREATED"
    RESERVATION_FULFILLED = "RESERVATION_FULFILLED"


class InboundEventType(str, Enum):
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    ILL_AVAILABILITY = "ILL_AVAILABILITY"
    ILL_DELIVERED = "ILL_DELIVERED"
    ILL_RETURN_INITIATED = "ILL_RETURN_INITIATED"


# ─────────────────────────────────────────────────────────────
# Entity TypedDicts
# ─────────────────────────────────────────────────────────────


class BookTitle(TypedDict, total=False):
    id: str
    marc_control_number: str
    isbn: str
    title: str
    author: str
    publisher: str
    publication_year: int
    classification_scheme: str
    classification_code: str
    subject_category: str
    acquisition_source: str
    total_copies: int
    available_copies: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Copy(TypedDict, total=False):
    id: str
    book_title_id: str
    barcode: str
    location_code: str
    acquisition_source: str
    acquired_at: str
    weeding_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reader(TypedDict, total=False):
    id: str
    national_id_hash: str
    full_name: str
    identity_verified: bool
    identity_verified_at: Optional[str]
    status: str
    active_loan_count: int
    unpaid_fine_cents: int
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict, total=False):
    id: str
    reader_id: str
    card_number: str
    card_type: str
    max_loans: int
    loan_duration_days: int
    max_renewals: int
    valid_from: str
    valid_until: str
    status: str
    replaced_by_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    copy_id: str
    card_id: str
    reader_id: str
    borrowed_at: str
    due_at: str
    returned_at: Optional[str]
    renewals_used: int
    is_recalled: bool
    recall_due_at: Optional[str]
    channel: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    book_title_id: str
    card_id: str
    reader_id: str
    channel: str
    queue_position: int
    held_copy_id: Optional[str]
    hold_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict, total=False):
    id: str
    loan_id: str
    reader_id: str
    subject_category: str
    daily_rate_cents: int
    fine_cap_cents: int
    accrued_cents: int
    waived_cents: int
    paid_cents: int
    outstanding_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class ILLRequest(TypedDict, total=False):
    id: str
    reader_id: str
    card_id: str
    partner_library_code: str
    target_marc_control_number: str
    agreed_loan_days: Optional[int]
    shipping_cost_cents: int
    handling_fee_cents: int
    settlement_total_cents: int
    in_transit_from: Optional[str]
    in_transit_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AcquisitionSuggestion(TypedDict, total=False):
    id: str
    reader_id: str
    card_id: str
    suggested_isbn: str
    suggested_title: str
    rationale: str
    review_notes: Optional[str]
    decision_book_title_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# AuditLog is append-only per PRD §2.4 — carries only id and created_at.
# No updated_at, no version field.
class AuditLog(TypedDict, total=False):
    id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: Optional[str]
    payload: dict
    occurred_at: str
    created_at: str
