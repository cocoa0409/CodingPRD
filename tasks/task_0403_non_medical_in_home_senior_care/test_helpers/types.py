"""Domain types: entity TypedDicts, status enums, role enum.

All resources in this API carry the four common fields id, created_at,
updated_at, and version (PRD section 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    SCHEDULER = "Scheduler"
    CAREGIVER = "Caregiver"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class BackgroundTier(str, Enum):
    PENDING = "PENDING"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    REVOKED = "REVOKED"


class EmploymentStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    DISCHARGED = "DISCHARGED"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CareTaskStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class CareTaskCategory(str, Enum):
    ADL = "ADL"
    IADL = "IADL"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class ContinuityStatus(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    BROKEN = "BROKEN"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class BillingMode(str, Enum):
    HOURLY = "HOURLY"
    LIVE_IN = "LIVE_IN"


class EvvSource(str, Enum):
    TELEPHONY = "TELEPHONY"
    MOBILE = "MOBILE"
    MANUAL = "MANUAL"


class MileageStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineType(str, Enum):
    REGULAR = "REGULAR"
    OVERTIME = "OVERTIME"
    LIVE_IN = "LIVE_IN"
    MILEAGE = "MILEAGE"


class LtcClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Agency(TypedDict):
    id: str
    name: str
    base_hourly_rate: float
    live_in_day_rate: float
    overtime_threshold_hours: float
    overtime_multiplier: float
    mileage_rate: float
    evv_rounding_minutes: int
    travel_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Caregiver(TypedDict):
    id: str
    agency_id: str
    full_name: str
    hire_state_code: str
    background_tier: str
    employment_status: str
    max_weekly_hours: float
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    agency_id: str
    full_name: str
    residence_state_code: str
    requires_live_in: bool
    continuity_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    client_id: str
    title: str
    status: str
    task_count: int
    created_at: str
    updated_at: str
    version: int


class CareTask(TypedDict):
    id: str
    care_plan_id: str
    category: str
    name: str
    requires_companion_errand: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CaregiverMatch(TypedDict):
    id: str
    caregiver_id: str
    client_id: str
    is_primary: bool
    match_status: str
    continuity_status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    caregiver_id: str
    client_id: str
    care_plan_id: str
    billing_mode: str
    scheduled_start: str
    scheduled_end: str
    clock_in_at: Optional[str]
    clock_out_at: Optional[str]
    evv_source: Optional[str]
    evv_log: List[dict]
    billable_minutes: int
    visit_charge: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MileageEntry(TypedDict):
    id: str
    visit_id: str
    miles: float
    purpose: str
    line_charge: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    agency_id: str
    caregiver_id: str
    client_id: str
    period_start: str
    period_end: str
    labor_total: float
    mileage_total: float
    invoice_total: float
    client_responsible_amount: float
    lines: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class LtcClaim(TypedDict):
    id: str
    client_id: str
    invoice_id: str
    insurer_name: str
    policy_number: str
    covered_pct: float
    daily_benefit_max: float
    covered_days: int
    expected_invoice_version: int
    covered_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int
