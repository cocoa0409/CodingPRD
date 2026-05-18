"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entity contract defined in PRD §2.4 and §3. Per PRD §2.4:

Primary persisted entities (Applicant, Application, OfficeAction,
Response, MaintenanceFee, PCTPhase) expose id, created_at, updated_at,
and version. The two append-only ledger entities (FeeTransaction,
AuditEvent) carry only id and created_at — they have no updated_at and
no version. SystemClock is a singleton with only a `now` field; it has
no updated_at and no version.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    EXAMINER = "Examiner"
    USPTO_ADMIN = "USPTOAdmin"


# ---------------------------------------------------------------------------
# Applicant lifecycle status — PRD §3.1
# ---------------------------------------------------------------------------
class ApplicantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Applicant entity-size classification — PRD §3.1
# ---------------------------------------------------------------------------
class EntitySize(str, Enum):
    LARGE = "LARGE"
    SMALL = "SMALL"
    MICRO = "MICRO"


# ---------------------------------------------------------------------------
# Application type — PRD §3.2
# ---------------------------------------------------------------------------
class ApplicationType(str, Enum):
    UTILITY = "UTILITY"
    DESIGN = "DESIGN"
    PROVISIONAL = "PROVISIONAL"


# ---------------------------------------------------------------------------
# Application lifecycle status — PRD §3.2 / §3.3 / §3.4 / §3.5
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    OFFICE_ACTION_PENDING = "OFFICE_ACTION_PENDING"
    ALLOWED = "ALLOWED"
    GRANTED = "GRANTED"
    ABANDONED = "ABANDONED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Continuation type — PRD §3.2
# ---------------------------------------------------------------------------
class ContinuationType(str, Enum):
    NONE = "NONE"
    CONTINUATION = "CONTINUATION"
    CIP = "CIP"


# ---------------------------------------------------------------------------
# OfficeAction action_type — PRD §3.3
# ---------------------------------------------------------------------------
class OfficeActionType(str, Enum):
    NON_FINAL = "NON_FINAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# OfficeAction lifecycle status — PRD §3.3
# ---------------------------------------------------------------------------
class OfficeActionStatus(str, Enum):
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    ABANDONED_BY_DEFAULT = "ABANDONED_BY_DEFAULT"


# ---------------------------------------------------------------------------
# MaintenanceFee stage — PRD §3.4
# ---------------------------------------------------------------------------
class MaintenanceStage(str, Enum):
    STAGE_3_5 = "STAGE_3_5"
    STAGE_7_5 = "STAGE_7_5"
    STAGE_11_5 = "STAGE_11_5"


# ---------------------------------------------------------------------------
# MaintenanceFee lifecycle status — PRD §3.5
# ---------------------------------------------------------------------------
class MaintenanceFeeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    LAPSED = "LAPSED"


# ---------------------------------------------------------------------------
# PCTPhase lifecycle status — PRD §3.6
# ---------------------------------------------------------------------------
class PCTPhaseStatus(str, Enum):
    INTERNATIONAL = "INTERNATIONAL"
    NATIONAL_ENTERED = "NATIONAL_ENTERED"
    LAPSED = "LAPSED"


# ---------------------------------------------------------------------------
# FeeTransaction fee_category — PRD §3.2 / §3.3 / §3.5 / §3.6
# ---------------------------------------------------------------------------
class FeeCategory(str, Enum):
    FILING = "FILING"
    EXCESS_CLAIM = "EXCESS_CLAIM"
    EXAMINATION = "EXAMINATION"
    ISSUE = "ISSUE"
    MAINTENANCE = "MAINTENANCE"
    EXTENSION = "EXTENSION"
    PCT_TRANSMITTAL = "PCT_TRANSMITTAL"
    PCT_NATIONAL = "PCT_NATIONAL"


# ===========================================================================
# Primary persisted entities — PRD §2.4: id, created_at, updated_at, version.
# ===========================================================================
class Applicant(TypedDict, total=False):
    id: str
    name: str
    entity_size: str
    gross_income_cents: Optional[int]
    prior_filings_count: Optional[int]
    status: str
    applicant_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    application_type: str
    title: str
    claim_count: int
    independent_claim_count: int
    status: str
    filed_at: Optional[str]
    granted_at: Optional[str]
    expires_at: Optional[str]
    parent_application_id: Optional[str]
    continuation_type: Optional[str]
    total_fees_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class OfficeAction(TypedDict, total=False):
    id: str
    application_id: str
    action_number: int
    action_type: str
    issued_at: str
    response_deadline_at: str
    extended_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Response(TypedDict, total=False):
    id: str
    office_action_id: str
    application_id: str
    filed_at: str
    months_extension: int
    extension_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceFee(TypedDict, total=False):
    id: str
    application_id: str
    stage: str
    window_open_at: str
    due_at: str
    grace_period_end_at: str
    status: str
    required_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PCTPhase(TypedDict, total=False):
    id: str
    application_id: str
    pct_filed_at: str
    priority_date: str
    national_phase_deadline_at: str
    status: str
    national_entered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only ledger entities — PRD §2.4: id + created_at ONLY.
# These TypedDicts deliberately omit updated_at and version.
# ===========================================================================
class FeeTransaction(TypedDict, total=False):
    id: str
    application_id: str
    fee_category: str
    amount_cents: int
    paid_at: str
    maintenance_fee_id: Optional[str]
    office_action_id: Optional[str]
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    application_id: str
    actor_role: str
    actor_id: str
    action: str
    details: Dict[str, Any]
    created_at: str


# ===========================================================================
# Singleton — PRD §2.4: only `now` field.
# ===========================================================================
class SystemClock(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "ApplicantStatus",
    "EntitySize",
    "ApplicationType",
    "ApplicationStatus",
    "ContinuationType",
    "OfficeActionType",
    "OfficeActionStatus",
    "MaintenanceStage",
    "MaintenanceFeeStatus",
    "PCTPhaseStatus",
    "FeeCategory",
    "Applicant",
    "Application",
    "OfficeAction",
    "Response",
    "MaintenanceFee",
    "PCTPhase",
    "FeeTransaction",
    "AuditEvent",
    "SystemClock",
]
