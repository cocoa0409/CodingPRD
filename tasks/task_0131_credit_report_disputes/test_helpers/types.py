"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3 entity definitions and §5 error catalog. Entities
that carry the standard four system-managed fields per PRD §2.5
(`id`, `created_at`, `updated_at`, `version`) are modeled with all
four; append-only audit records called out in PRD §2.5
(`FurnisherInquiry`, `ResultNotice`, `HardInquiry`) intentionally
carry only `id` and `created_at`.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    CONSUMER = "Consumer"
    BUREAU_OPERATOR = "BureauOperator"
    FURNISHER = "Furnisher"
    CFPB_OPERATOR = "CFPBOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ===========================================================================
# Enumerations on entity status / branching fields — PRD §3
# ===========================================================================
class Bureau(str, Enum):
    EQUIFAX = "EQUIFAX"
    EXPERIAN = "EXPERIAN"
    TRANSUNION = "TRANSUNION"


class CreditReportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CreditReportPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    LATE_30 = "LATE_30"
    LATE_60 = "LATE_60"
    LATE_90 = "LATE_90"
    CHARGE_OFF = "CHARGE_OFF"
    COLLECTION = "COLLECTION"
    DELETED = "DELETED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"


class FurnisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DisputeChannel(str, Enum):
    ONLINE = "ONLINE"
    MAIL = "MAIL"


class DisputeRequestedAction(str, Enum):
    CORRECT_BALANCE = "CORRECT_BALANCE"
    CORRECT_STATUS = "CORRECT_STATUS"
    DELETE_ITEM = "DELETE_ITEM"
    CORRECT_DOFD = "CORRECT_DOFD"


class DisputeInvestigationOutcome(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    DISMISSED_FRIVOLOUS = "DISMISSED_FRIVOLOUS"


class DisputeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESULTS_PENDING = "RESULTS_PENDING"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    CLOSED_UPDATED = "CLOSED_UPDATED"
    CLOSED_DELETED = "CLOSED_DELETED"
    CLOSED_DISMISSED = "CLOSED_DISMISSED"
    ESCALATED = "ESCALATED"


class FurnisherInquiryResponse(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    NO_RESPONSE = "NO_RESPONSE"


class ResultNoticeOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    DISMISSED_FRIVOLOUS = "DISMISSED_FRIVOLOUS"


class ResultNoticeDeliveryChannel(str, Enum):
    ONLINE = "ONLINE"
    MAIL = "MAIL"


class RegulatoryAgency(str, Enum):
    CFPB = "CFPB"


class RegulatoryComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class CreditFreezeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class CreditLockStatus(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"


class HardInquiryOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    BLOCKED_FREEZE = "BLOCKED_FREEZE"
    BLOCKED_LOCK = "BLOCKED_LOCK"


# ===========================================================================
# Entity TypedDicts — PRD §2.5 common-fields rule applied
# ===========================================================================

# --- Common-fields entities (id + created_at + updated_at + version) -------

class Consumer(TypedDict):
    id: str
    full_name: str
    ssn_last4: str
    email: str
    free_reports_remaining: int
    freeze_pin: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Furnisher(TypedDict):
    id: str
    legal_name: str
    ecoa_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditReport(TypedDict):
    id: str
    consumer_id: str
    bureau: str
    fico_score: int
    posture: str
    last_pulled_day: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TradelineItem(TypedDict):
    id: str
    credit_report_id: str
    furnisher_id: str
    account_ref: str
    original_dofd_day: int
    balance_cents: int
    payment_status: str
    reported_dofd_day: int
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    consumer_id: str
    credit_report_id: str
    tradeline_item_id: str
    channel: str
    supporting_documents: List[Any]
    requested_action: str
    requested_payload: Any
    submitted_day: int
    deadline_day: int
    additional_info_accepted: bool
    investigation_outcome: str
    result_notice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryComplaint(TypedDict):
    id: str
    consumer_id: str
    dispute_id: str
    parent_complaint_id: Optional[str]
    agency: str
    narrative: str
    filed_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditFreeze(TypedDict):
    id: str
    consumer_id: str
    bureau: str
    placed_day: int
    lifted_day: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditLock(TypedDict):
    id: str
    consumer_id: str
    bureau: str
    locked_at_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities — PRD §2.5: ONLY id + created_at ----------------
# PRD §2.5 explicitly names FurnisherInquiry, ResultNotice, HardInquiry
# as append-only records that carry only id and created_at. Their
# TypedDicts intentionally omit updated_at and version.

class FurnisherInquiry(TypedDict):
    id: str
    created_at: str
    dispute_id: str
    furnisher_id: str
    forwarded_day: int
    reverification_deadline_day: int
    response: str
    response_day: Optional[int]
    response_payload: Any


class ResultNotice(TypedDict):
    id: str
    created_at: str
    dispute_id: str
    issued_day: int
    delivery_channel: str
    outcome: str
    free_report_granted: bool
    summary: str


class HardInquiry(TypedDict):
    id: str
    created_at: str
    credit_report_id: str
    requesting_furnisher_id: str
    inquiry_day: int
    outcome: str


__all__ = [
    # Roles
    "UserRole",
    # Enums
    "Bureau",
    "CreditReportStatus",
    "CreditReportPosture",
    "PaymentStatus",
    "VerificationStatus",
    "FurnisherStatus",
    "DisputeChannel",
    "DisputeRequestedAction",
    "DisputeInvestigationOutcome",
    "DisputeStatus",
    "FurnisherInquiryResponse",
    "ResultNoticeOutcome",
    "ResultNoticeDeliveryChannel",
    "RegulatoryAgency",
    "RegulatoryComplaintStatus",
    "CreditFreezeStatus",
    "CreditLockStatus",
    "HardInquiryOutcome",
    # Entities
    "Consumer",
    "Furnisher",
    "CreditReport",
    "TradelineItem",
    "Dispute",
    "RegulatoryComplaint",
    "CreditFreeze",
    "CreditLock",
    "FurnisherInquiry",
    "ResultNotice",
    "HardInquiry",
]
