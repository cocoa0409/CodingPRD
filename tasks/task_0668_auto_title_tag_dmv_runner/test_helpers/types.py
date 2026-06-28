"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resources, status dimensions, and roles. The Payment
resource is immutable: it carries only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum value sets ─────────────────────────────────────────

class AccountType(str, Enum):
    RETAIL = "RETAIL"
    FLEET = "FLEET"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FeeScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TransactionType(str, Enum):
    TITLE = "TITLE"
    REGISTRATION = "REGISTRATION"
    TRANSFER = "TRANSFER"
    LIEN = "LIEN"


class LifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DocumentStatus(str, Enum):
    COLLECTING = "COLLECTING"
    VERIFIED = "VERIFIED"
    INCOMPLETE = "INCOMPLETE"


class ChecklistCode(str, Enum):
    TITLE_CERT = "TITLE_CERT"
    BILL_OF_SALE = "BILL_OF_SALE"
    ODOMETER = "ODOMETER"
    ID_PROOF = "ID_PROOF"
    INSURANCE = "INSURANCE"
    LIEN_RELEASE = "LIEN_RELEASE"
    LIEN_INSTRUMENT = "LIEN_INSTRUMENT"
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY"


class DocStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class QuoteVariant(str, Enum):
    ESTIMATE = "ESTIMATE"
    FINAL = "FINAL"


class QuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    SETTLED = "SETTLED"


class SubmissionStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    DMV_REJECTED = "DMV_REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PriorityClass(str, Enum):
    EXPEDITE = "EXPEDITE"
    STANDARD = "STANDARD"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class LegStatus(str, Enum):
    ATTACHED = "ATTACHED"
    FILED = "FILED"
    RESOLVED = "RESOLVED"


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    PERFECTED = "PERFECTED"
    VOIDED = "VOIDED"


class PaymentKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_CLERK = "IntakeClerk"
    FEE_ANALYST = "FeeAnalyst"
    RUNNER_DISPATCHER = "RunnerDispatcher"
    LIEN_OFFICER = "LienOfficer"
    ACCOUNT_HOLDER = "AccountHolder"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Resources that carry the standard server-managed fields include
# id + created_at + updated_at + version. Payment is the exception.

class Account(TypedDict):
    id: str
    account_type: str
    legal_name: str
    state_code: str
    credit_terms: bool
    ytd_completed_count: int
    outstanding_balance_cents: int
    status: str
    credit_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    state_code: str
    title_fee_cents: int
    registration_fee_cents: int
    transfer_fee_cents: int
    lien_recording_fee_cents: int
    use_tax_rate_bps: int
    trade_in_credit_allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    account_id: str
    transaction_type: str
    vin: str
    declared_price_cents: int
    trade_in_allowance_cents: int
    expedite: bool
    lifecycle_status: str
    document_status: str
    rejection_round: int
    active_quote_id: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentItem(TypedDict):
    id: str
    transaction_id: str
    checklist_code: str
    doc_status: str
    file_ref: str
    created_at: str
    updated_at: str
    version: int


class FeeQuote(TypedDict):
    id: str
    transaction_id: str
    variant: str
    schedule_id: str
    tax_cents: int
    state_fees_cents: int
    service_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    transaction_id: str
    submission_status: str
    priority_class: str
    sla_deadline_at: Optional[str]
    leg_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RunnerTrip(TypedDict):
    id: str
    dmv_office_code: str
    trip_status: str
    capacity: int
    window_start_at: str
    window_end_at: str
    assigned_leg_count: int
    created_at: str
    updated_at: str
    version: int


class RunnerLeg(TypedDict):
    id: str
    trip_id: str
    submission_id: str
    leg_status: str
    sequence_index: int
    created_at: str
    updated_at: str
    version: int


class LienPacket(TypedDict):
    id: str
    transaction_id: str
    lender_name: str
    lien_amount_cents: int
    packet_status: str
    perfected_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Payment is immutable: id + created_at only — no updated_at, no version.
class Payment(TypedDict):
    id: str
    account_id: str
    transaction_id: str
    amount_cents: int
    kind: str
    created_at: str
