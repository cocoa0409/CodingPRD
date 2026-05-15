"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, most resources carry id/created_at/updated_at/version.
ContactEvent, DailyHealthReport, RiskTierDecision, Dispatch, and
AuditLog are append-only — they carry only id and created_at; no
updated_at, no version on those entities.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HOSPITAL_REPORTER = "HospitalReporter"
    LAB_TECHNICIAN = "LabTechnician"
    CDC_DISPATCHER = "CDCDispatcher"
    CDC_TRACER = "CDCTracer"
    CDC_SUPERVISOR = "CDCSupervisor"
    RISK_EXPERT = "RiskExpert"
    PRESS_OFFICER = "PressOfficer"
    SUPPLY_MANAGER = "SupplyManager"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.*)
# ---------------------------------------------------------------------------
class InstitutionType(str, Enum):
    HOSPITAL = "HOSPITAL"
    LAB = "LAB"
    CDC = "CDC"
    VENUE = "VENUE"
    TRANSIT = "TRANSIT"


class InstitutionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PersonIsolationStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    VIOLATED_TERMINATED = "VIOLATED_TERMINATED"


class CaseType(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    ASYMPTOMATIC = "ASYMPTOMATIC"


class CaseStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_TRACING = "UNDER_TRACING"
    CONFIRMED = "CONFIRMED"
    RECOVERED = "RECOVERED"
    DEDUPLICATED = "DEDUPLICATED"


class ContactEventType(str, Enum):
    TRANSIT = "TRANSIT"
    VENUE = "VENUE"
    COWORKER = "COWORKER"
    HOUSEHOLD = "HOUSEHOLD"


class ContactEventTier(str, Enum):
    CLOSE = "CLOSE"
    SUB_CLOSE = "SUB_CLOSE"


class IngestedFrom(str, Enum):
    HIS = "HIS"
    LIS = "LIS"
    TRANSIT_CODE = "TRANSIT_CODE"
    VENUE_CODE = "VENUE_CODE"
    MANUAL = "MANUAL"


class TracingTaskStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_REVISION = "NEEDS_REVISION"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class SlaSeverity(str, Enum):
    NONE = "NONE"
    SOFT = "SOFT"
    HARD = "HARD"


class IsolationMode(str, Enum):
    CENTRALIZED = "CENTRALIZED"
    HOME = "HOME"
    MEDICAL_OBSERVATION = "MEDICAL_OBSERVATION"


class IsolationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    RELEASED = "RELEASED"
    VIOLATED_TERMINATED = "VIOLATED_TERMINATED"


class IsolationEligibility(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    EXTEND = "EXTEND"
    RELEASE = "RELEASE"


class FacilityStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class TestType(str, Enum):
    PCR = "PCR"
    ANTIGEN = "ANTIGEN"
    ANTIBODY = "ANTIBODY"


class TestResult(str, Enum):
    PENDING = "PENDING"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    INVALID = "INVALID"


class TestOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    FOLLOW_UP = "FOLLOW_UP"
    CLOSED = "CLOSED"
    VOID = "VOID"


class RiskDecisionMode(str, Enum):
    AUTO = "AUTO"
    EXPERT_OVERRIDE = "EXPERT_OVERRIDE"


class RiskDecisionStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class SupplyCategory(str, Enum):
    PPE = "PPE"
    TEST_KIT = "TEST_KIT"
    MEDICATION = "MEDICATION"
    VACCINE = "VACCINE"


class SupplyRequestStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class DispatchStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class BulletinStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"
    ARCHIVED = "ARCHIVED"


class BulletinChannel(str, Enum):
    WEBSITE = "WEBSITE"
    APP = "APP"
    PRESS = "PRESS"


class AuditedEntityType(str, Enum):
    CASE = "Case"
    RISK_TIER_DECISION = "RiskTierDecision"
    ISOLATION = "Isolation"
    TEST_ORDER = "TestOrder"


# ---------------------------------------------------------------------------
# Mutable entities — PRD §2.4 carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class ReportingInstitution(TypedDict):
    id: str
    institution_code: str
    institution_type: str
    district_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Region(TypedDict):
    id: str
    district_code: str
    population: int
    current_risk_tier: str
    provisional_risk_tier: str
    last_tier_decision_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Person(TypedDict):
    id: str
    person_hash: str
    demographics: dict
    district_code: str
    isolation_status: str
    latest_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    person_id: str
    reporting_institution_id: str
    case_type: str
    onset_date: str
    reported_at: str
    report_deadline_at: str
    is_late_report: bool
    symptoms: List[str]
    exposure_history: List[str]
    status: str
    superseded_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TracingTask(TypedDict):
    id: str
    case_id: str
    assigned_cdc_id: str
    status: str
    due_at: str
    dispatched_at: str
    completed_at: Optional[str]
    discovered_contact_count: int
    created_at: str
    updated_at: str
    version: int


class Isolation(TypedDict):
    id: str
    person_id: str
    mode: str
    facility_id: Optional[str]
    start_date: str
    planned_end_date: str
    actual_end_date: Optional[str]
    status: str
    extension_count: int
    daily_reports_received: int
    violations_count: int
    created_at: str
    updated_at: str
    version: int


class IsolationFacility(TypedDict):
    id: str
    facility_code: str
    district_code: str
    capacity: int
    occupied: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestOrder(TypedDict):
    id: str
    person_id: str
    ordering_institution_id: str
    test_type: str
    collected_at: Optional[str]
    result: str
    result_recorded_at: Optional[str]
    status: str
    chain_of_custody: List[dict]
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict):
    id: str
    sku: str
    category: str
    reserve_quantity: int
    allocated_quantity: int
    created_at: str
    updated_at: str
    version: int


class SupplyRequest(TypedDict):
    id: str
    sku: str
    requesting_institution_id: str
    requested_quantity: int
    priority_score: int
    allocated_quantity: int
    dispatched_quantity: int
    consumed_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bulletin(TypedDict):
    id: str
    bulletin_date: str
    total_new_cases: int
    tier_summary: dict
    status: str
    channels: List[str]
    rumor_corrections: List[dict]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4: id + created_at ONLY; NO updated_at, NO version
# ---------------------------------------------------------------------------
class ContactEvent(TypedDict):
    id: str
    source_person_id: str
    target_person_id: str
    event_type: str
    event_time: str
    duration_minutes: int
    distance_meters: float
    tier: str
    ingested_from: str
    created_at: str


class DailyHealthReport(TypedDict):
    id: str
    isolation_id: str
    report_date: str
    temperature_c: float
    symptoms: List[str]
    is_abnormal: bool
    created_at: str


class RiskTierDecision(TypedDict):
    id: str
    region_id: str
    previous_tier: str
    provisional_tier: str
    final_tier: Optional[str]
    mode: str
    expert_reviewer_id: Optional[str]
    published_at: Optional[str]
    status: str
    created_at: str


class Dispatch(TypedDict):
    id: str
    request_id: str
    quantity: int
    dispatched_at: str
    delivered_at: Optional[str]
    status: str
    created_at: str


class AuditLog(TypedDict):
    id: str
    entity_type: str
    entity_id: str
    from_state: str
    to_state: str
    actor_role: str
    actor_id: str
    at: str
    created_at: str


__all__ = [
    "UserRole",
    "InstitutionType",
    "InstitutionStatus",
    "RiskTier",
    "PersonIsolationStatus",
    "CaseType",
    "CaseStatus",
    "ContactEventType",
    "ContactEventTier",
    "IngestedFrom",
    "TracingTaskStatus",
    "SlaSeverity",
    "IsolationMode",
    "IsolationStatus",
    "IsolationEligibility",
    "FacilityStatus",
    "TestType",
    "TestResult",
    "TestOrderStatus",
    "RiskDecisionMode",
    "RiskDecisionStatus",
    "SupplyCategory",
    "SupplyRequestStatus",
    "DispatchStatus",
    "BulletinStatus",
    "BulletinChannel",
    "AuditedEntityType",
    "ReportingInstitution",
    "Region",
    "Person",
    "Case",
    "TracingTask",
    "Isolation",
    "IsolationFacility",
    "TestOrder",
    "SupplyItem",
    "SupplyRequest",
    "Bulletin",
    "ContactEvent",
    "DailyHealthReport",
    "RiskTierDecision",
    "Dispatch",
    "AuditLog",
]
