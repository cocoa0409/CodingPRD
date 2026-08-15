"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CASE_MANAGER = "CaseManager"
    HOUSING_COORDINATOR = "HousingCoordinator"
    EMPLOYMENT_SPECIALIST = "EmploymentSpecialist"
    AGENCY_DIRECTOR = "AgencyDirector"
    FEDERAL_OFFICER = "FederalOfficer"


class CaseStatus(str, Enum):
    PRE_ARRIVAL = "PRE_ARRIVAL"
    ARRIVED = "ARRIVED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class CasePosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    OVERDUE = "OVERDUE"


class MemberRelationship(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    OTHER_RELATIVE = "OTHER_RELATIVE"


class HousingUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"


class HousingSetupStatus(str, Enum):
    PREPARING = "PREPARING"
    READY = "READY"
    OCCUPIED = "OCCUPIED"
    VACATED = "VACATED"


class ServiceType(str, Enum):
    HOME_VISIT = "HOME_VISIT"
    HEALTH_SCREENING = "HEALTH_SCREENING"
    SSN_APPLICATION = "SSN_APPLICATION"
    BENEFITS_ENROLLMENT = "BENEFITS_ENROLLMENT"
    SCHOOL_ENROLLMENT = "SCHOOL_ENROLLMENT"
    EMPLOYMENT_PLAN = "EMPLOYMENT_PLAN"
    CULTURAL_ORIENTATION = "CULTURAL_ORIENTATION"


class DueRule(str, Enum):
    DAYS_30 = "DAYS_30"
    DAYS_90 = "DAYS_90"


class BenchmarkStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    WAIVED = "WAIVED"


class BenefitType(str, Enum):
    SSN = "SSN"
    STATE_ID = "STATE_ID"
    CASH_ASSISTANCE = "CASH_ASSISTANCE"
    MEDICAL = "MEDICAL"
    FOOD_ASSISTANCE = "FOOD_ASSISTANCE"


class BenefitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class EmploymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED_TRANSFERRED = "CLOSED_TRANSFERRED"


class DeterminationVariant(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUALIZED = "ANNUALIZED"


class OrientationTopic(str, Enum):
    US_LAWS = "US_LAWS"
    HEALTHCARE_ACCESS = "HEALTHCARE_ACCESS"
    EDUCATION_SYSTEM = "EDUCATION_SYSTEM"
    EMPLOYMENT_RIGHTS = "EMPLOYMENT_RIGHTS"
    HOUSING_SAFETY = "HOUSING_SAFETY"
    BUDGETING = "BUDGETING"


class OrientationSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NoteType(str, Enum):
    GENERAL = "GENERAL"
    SERVICE_DELIVERY = "SERVICE_DELIVERY"
    INCIDENT = "INCIDENT"
    TRANSFER = "TRANSFER"


class AuthorRole(str, Enum):
    CASE_MANAGER = "CASE_MANAGER"
    HOUSING_COORDINATOR = "HOUSING_COORDINATOR"
    EMPLOYMENT_SPECIALIST = "EMPLOYMENT_SPECIALIST"
    AGENCY_DIRECTOR = "AGENCY_DIRECTOR"


class TransferReason(str, Enum):
    SECONDARY_MIGRATION = "SECONDARY_MIGRATION"
    FAMILY_REUNIFICATION = "FAMILY_REUNIFICATION"
    EMPLOYMENT_OPPORTUNITY = "EMPLOYMENT_OPPORTUNITY"


class CaseTransferStatus(str, Enum):
    INITIATED = "INITIATED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class TransferDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FederalReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class Case(TypedDict, total=False):
    id: str
    case_number: str
    agency_affiliate_code: str
    household_size: int
    scheduled_arrival_date: str
    actual_arrival_date: Optional[str]
    airport_pickup_completed: bool
    status: str
    posture: str
    topics_completed: List[str]
    open_transfer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict, total=False):
    id: str
    case_id: str
    full_name: str
    date_of_birth: str
    relationship: str
    work_eligible: bool
    age_at_arrival: Optional[int]
    school_age_at_arrival: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class HousingUnit(TypedDict, total=False):
    id: str
    address: str
    bedrooms: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingSetup(TypedDict, total=False):
    id: str
    case_id: str
    housing_unit_id: str
    occupancy_start: str
    occupancy_end: str
    furnishing_items_completed: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBenchmark(TypedDict, total=False):
    id: str
    case_id: str
    service_type: str
    due_rule: str
    planned_due_date: str
    due_date: str
    fulfilled_on: Optional[str]
    evidence_note_id: Optional[str]
    on_time: Optional[bool]
    status: str
    waived_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitApplication(TypedDict, total=False):
    id: str
    case_id: str
    member_id: str
    benefit_type: str
    status: str
    filed_on: Optional[str]
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmploymentPlan(TypedDict, total=False):
    id: str
    case_id: str
    monthly_income_cents: int
    trailing_3m_income_cents: int
    job_start_date: Optional[str]
    employed_members_count: int
    status: str
    self_sufficient: Optional[bool]
    determination_variant: Optional[str]
    certified_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrientationSession(TypedDict, total=False):
    id: str
    case_id: str
    topic: str
    start_at: str
    end_at: str
    status: str
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseNote(TypedDict, total=False):
    # Append-only documentation (PRD §2.4): id + created_at only;
    # updated_at and version are absent.
    id: str
    case_id: str
    note_type: str
    body: str
    service_date: Optional[str]
    author_role: str
    created_at: str


class CaseTransfer(TypedDict, total=False):
    id: str
    case_id: str
    receiving_affiliate_code: str
    reason: str
    status: str
    initiated_by_user_id: str
    responded_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FederalReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    cases_arrived_count: int
    benchmarks_met_count: int
    benchmarks_met_on_time_count: int
    benchmarks_pending_count: int
    benchmarks_waived_count: int
    per_capita_allocation_cents: int
    status: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
