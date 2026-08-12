"""Domain types: entity TypedDicts, status enums, role enum.

All twelve resources carry the common field set (id, created_at, updated_at,
version) per the PRD's common-resource-properties rule — no entity is exempt.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCH_OPS = "DispatchOps"
    RADIOLOGIST = "Radiologist"
    CLIENT_HOSPITAL_USER = "ClientHospitalUser"
    QA_REVIEWER = "QaReviewer"


class HospitalStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CredentialingMode(str, Enum):
    BY_PROXY = "BY_PROXY"
    INDEPENDENT = "INDEPENDENT"


class PricingMode(str, Enum):
    MARGINAL = "MARGINAL"
    FLAT_TIER = "FLAT_TIER"


class RadiologistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RoutingPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StudyStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PRELIMINARY_SIGNED = "PRELIMINARY_SIGNED"
    FINAL_SIGNED = "FINAL_SIGNED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class AssignmentPhase(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class ReportType(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    ADDENDUM = "ADDENDUM"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"


class DiscrepancyCaseStatus(str, Enum):
    OPEN = "OPEN"
    PEER_REVIEW = "PEER_REVIEW"
    ESCALATED_QI = "ESCALATED_QI"
    RECONCILED = "RECONCILED"
    NO_ACTION_CLOSED = "NO_ACTION_CLOSED"


class DiscrepancyCaseOrigin(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class CriticalNoticeStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    ESCALATED = "ESCALATED"
    READBACK_CONFIRMED = "READBACK_CONFIRMED"


class CredentialGrantStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    INVOICED = "INVOICED"


class InvoiceStatus(str, Enum):
    CURRENT = "CURRENT"
    VOID = "VOID"


class Modality(str, Enum):
    CT = "CT"
    MR = "MR"
    XR = "XR"
    US = "US"
    NM = "NM"
    MG = "MG"


class BodyPartGroup(str, Enum):
    NEURO = "NEURO"
    BODY = "BODY"
    MSK = "MSK"
    CHEST = "CHEST"
    VASCULAR = "VASCULAR"
    OTHER = "OTHER"


class Priority(str, Enum):
    STAT = "STAT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class Subspecialty(str, Enum):
    NEURORAD = "NEURORAD"
    MSK = "MSK"
    BODY = "BODY"
    CHEST = "CHEST"
    PEDS = "PEDS"
    GENERAL = "GENERAL"


class ClientHospital(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    status: str
    credentialing_mode: str
    pricing_mode: str
    tat_stat_minutes: int
    tat_urgent_minutes: int
    tat_routine_minutes: int
    penalty_per_breach_minute_cents: int
    breach_penalty_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Radiologist(TypedDict, total=False):
    id: str
    full_name: str
    subspecialties: List[str]
    license_states: List[str]
    status: str
    fatigue_cap_rvu: float
    max_concurrent_stat: int
    reserved_rvu: float
    completed_rvu_24h: float
    stat_active_count: int
    pending_critical_count: int
    created_at: str
    updated_at: str
    version: int


class CoverageShift(TypedDict, total=False):
    id: str
    radiologist_id: str
    starts_at: str
    ends_at: str
    modalities: List[str]
    status: str
    after_hours: bool
    created_at: str
    updated_at: str
    version: int


class RoutingPolicy(TypedDict, total=False):
    id: str
    hospital_id: str
    modality: str
    body_part_group: str
    priority: str
    required_subspecialty: str
    prelim_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Study(TypedDict, total=False):
    id: str
    hospital_id: str
    accession_number: str
    modality: str
    body_part_group: str
    priority: str
    patient_ref: str
    state_code: str
    received_at: str
    due_at: str
    status: str
    routing_policy_id: Optional[str]
    assigned_radiologist_id: Optional[str]
    excluded_radiologist_ids: List[str]
    addendum_count: int
    first_final_signed_at: Optional[str]
    tat_breached: bool
    breach_minutes: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    study_id: str
    radiologist_id: str
    phase: str
    reserved_rvu: float
    status: str
    auto_selected: bool
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    assignment_id: str
    study_id: str
    radiologist_id: str
    report_type: str
    findings_text: str
    impression_text: str
    critical_finding: bool
    discrepancy_grade: Optional[int]
    status: str
    signed_at: Optional[str]
    credited_rvu: float
    created_at: str
    updated_at: str
    version: int


class DiscrepancyCase(TypedDict, total=False):
    id: str
    study_id: str
    prelim_report_id: str
    final_report_id: str
    grade: int
    origin: str
    status: str
    reconciliation_note: Optional[str]
    reconciled_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriticalResultNotice(TypedDict, total=False):
    id: str
    report_id: str
    study_id: str
    radiologist_id: str
    status: str
    notified_party_name: Optional[str]
    notified_at: Optional[str]
    readback_confirmed_by: Optional[str]
    readback_at: Optional[str]
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


class CredentialGrant(TypedDict, total=False):
    id: str
    radiologist_id: str
    hospital_id: str
    grant_type: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict, total=False):
    id: str
    hospital_id: str
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict, total=False):
    hour_class: str
    tier_index: int
    units: int
    rate_cents: int
    amount_cents: int


class Invoice(TypedDict, total=False):
    id: str
    billing_period_id: str
    hospital_id: str
    status: str
    pricing_mode_snapshot: str
    billable_study_count: int
    line_items: List[Dict[str, Any]]
    critical_addon_cents: int
    gross_cents: int
    penalty_credits_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
