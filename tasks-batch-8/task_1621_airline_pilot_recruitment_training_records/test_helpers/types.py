"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. CostLedgerEntry is append-only and
carries only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    CHECK_AIRMAN = "CheckAirman"
    CREW_SCHEDULER = "CrewScheduler"
    PILOT = "Pilot"
    SYSTEM_ADMIN = "SystemAdmin"


class ApplicantStatus(str, Enum):
    SCREENING = "SCREENING"
    PRIA_PENDING = "PRIA_PENDING"
    PRIA_VERIFIED = "PRIA_VERIFIED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RecordsRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class RequestType(str, Enum):
    PRIA = "PRIA"
    DRUG_TEST = "DRUG_TEST"
    TRAINING_HISTORY = "TRAINING_HISTORY"


class TrainingClassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    REMEDIATION = "REMEDIATION"
    COMPLETED = "COMPLETED"
    DISQUALIFIED = "DISQUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class TrainingPhase(str, Enum):
    GROUND_SCHOOL = "GROUND_SCHOOL"
    SIMULATOR = "SIMULATOR"
    CHECKRIDE = "CHECKRIDE"
    IOE = "IOE"
    DONE = "DONE"


class EventPhase(str, Enum):
    GROUND_SCHOOL = "GROUND_SCHOOL"
    SIMULATOR = "SIMULATOR"
    CHECKRIDE = "CHECKRIDE"
    IOE = "IOE"


class EventType(str, Enum):
    SESSION = "SESSION"
    MILESTONE = "MILESTONE"


class TrainingEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CheckrideStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    CANCELLED = "CANCELLED"


class RideType(str, Enum):
    ORAL = "ORAL"
    PRACTICAL = "PRACTICAL"
    LINE_CHECK = "LINE_CHECK"


class CurrencyState(str, Enum):
    QUALIFIED = "QUALIFIED"
    CURRENCY_WARNING = "CURRENCY_WARNING"
    LAPSED = "LAPSED"
    REQUALIFYING = "REQUALIFYING"
    EXPIRED = "EXPIRED"


class OperatingState(str, Enum):
    ACTIVE = "ACTIVE"
    GROUNDED = "GROUNDED"


class ActivityType(str, Enum):
    REVENUE = "REVENUE"
    TRAINING = "TRAINING"
    CHECK = "CHECK"


class CertClass(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"
    THIRD = "THIRD"


class MedicalCertificateStatus(str, Enum):
    VALID = "VALID"
    DOWNGRADED = "DOWNGRADED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class BidPeriodStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    FINALIZED = "FINALIZED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DenialReason(str, Enum):
    INSUFFICIENT_SENIORITY = "INSUFFICIENT_SENIORITY"
    INELIGIBLE = "INELIGIBLE"


class InstructorType(str, Enum):
    GROUND = "GROUND"
    SIMULATOR = "SIMULATOR"
    CHECK_AIRMAN = "CHECK_AIRMAN"


class SimulatorSlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class LedgerEntryType(str, Enum):
    GROUND_SCHOOL = "GROUND_SCHOOL"
    SIMULATOR = "SIMULATOR"
    IOE = "IOE"
    CHECKRIDE = "CHECKRIDE"
    RETRAINING = "RETRAINING"
    REVERSAL = "REVERSAL"


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    license_number: str
    total_flight_hours: int
    status: str
    seniority_number: Optional[int]
    current_equipment_id: Optional[str]
    cleared_at: Optional[str]
    ledger_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RecordsRequest(TypedDict):
    id: str
    applicant_id: str
    request_type: str
    status: str
    sent_at: Optional[str]
    due_at: Optional[str]
    response_received_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    code: str
    name: str
    simulator_cost_per_hour_cents: int
    ioe_hours_required: int
    landings_required_90d: int
    created_at: str
    updated_at: str
    version: int


class TrainingClass(TypedDict):
    id: str
    equipment_id: str
    class_date: str
    seat_capacity: int
    base_attrition_rate: float
    status: str
    active_enrollment_count: int
    confirmed_count: int
    max_seats_sellable: int
    projected_completions_aggregate: int
    projected_completions_walk: int
    over_committed: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    applicant_id: str
    training_class_id: str
    status: str
    current_phase: str
    failed_attempts: int
    entered_remediation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingEvent(TypedDict):
    id: str
    enrollment_id: str
    instructor_id: str
    simulator_slot_id: Optional[str]
    phase: str
    event_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    score: Optional[int]
    billed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Checkride(TypedDict):
    id: str
    enrollment_id: str
    check_airman_id: str
    ride_type: str
    status: str
    scheduled_at: str
    completed_at: Optional[str]
    attempt_number: int
    created_at: str
    updated_at: str
    version: int


class Qualification(TypedDict):
    id: str
    applicant_id: str
    equipment_id: str
    currency_state: str
    operating_state: str
    qualified_at: str
    landings_90d: int
    landings_expiring_7d: int
    lapsed_since: Optional[str]
    last_evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlightActivity(TypedDict):
    id: str
    qualification_id: str
    activity_date: str
    landings: int
    hours: float
    activity_type: str
    created_at: str
    updated_at: str
    version: int


class MedicalCertificate(TypedDict):
    id: str
    applicant_id: str
    cert_class: str
    issued_at: str
    pilot_age_at_issue: int
    first_class_valid_through: str
    third_class_valid_through: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BidPeriod(TypedDict):
    id: str
    equipment_id: str
    opens_at: str
    closes_at: str
    seats_available: int
    status: str
    awarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    bid_period_id: str
    applicant_id: str
    preference_rank: int
    status: str
    denial_reason: Optional[str]
    seniority_snapshot: Optional[int]
    awarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    instructor_type: str
    daily_max_sessions: int
    created_at: str
    updated_at: str
    version: int


class SimulatorSlot(TypedDict):
    id: str
    equipment_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CostLedgerEntry(TypedDict):
    # Append-only: carries ONLY id + created_at from the common set;
    # updated_at and version are absent.
    id: str
    applicant_id: str
    enrollment_id: Optional[str]
    entry_type: str
    amount_cents: int
    provisional: bool
    memo: Optional[str]
    created_at: str
