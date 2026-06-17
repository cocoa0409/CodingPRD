"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry id, created_at, updated_at, and version
(the PRD states every entity is mutable and version-bearing).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    LICENSE_CLERK = "LicenseClerk"
    EXAMINER = "Examiner"
    KNOWLEDGE_PROCTOR = "KnowledgeProctor"
    ADJUDICATION_OFFICER = "AdjudicationOfficer"


# --- Status enums ---
class LicensingStatus(str, Enum):
    UNLICENSED = "UNLICENSED"
    ELIGIBLE = "ELIGIBLE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class CdlStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    MEDICALLY_DOWNGRADED = "MEDICALLY_DOWNGRADED"


class RealIdStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class KnowledgeTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RoadTestStatus(str, Enum):
    BOOKED = "BOOKED"
    PROCTORED = "PROCTORED"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"


class RoadTestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LicenseStatus(str, Enum):
    ISSUED = "ISSUED"
    RENEWED = "RENEWED"
    VOID = "VOID"


class ViolationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DISMISSED = "DISMISSED"


class SuspensionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SERVED = "SERVED"
    LIFTED_BY_REINSTATEMENT = "LIFTED_BY_REINSTATEMENT"
    LIFTED_BY_DISMISSAL = "LIFTED_BY_DISMISSAL"


class CdlEndorsementStatus(str, Enum):
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class MedicalCardStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class FeePaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"


class FeePaymentPurpose(str, Enum):
    RENEWAL = "RENEWAL"
    REINSTATEMENT = "REINSTATEMENT"
    ROAD_TEST = "ROAD_TEST"
    KNOWLEDGE_TEST = "KNOWLEDGE_TEST"


class LicenseClass(str, Enum):
    D = "D"
    M = "M"
    A = "A"
    B = "B"
    C = "C"


class EndorsementCode(str, Enum):
    H = "H"
    P = "P"
    S = "S"
    N = "N"
    T = "T"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ---
class DriverRecord(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    state_code: str
    licensing_status: str
    cdl_status: str
    point_balance: int
    prior_suspension_count: int
    knowledge_test_passed: bool
    real_id_status: str
    real_id_categories_met: int
    organ_donor: bool
    voter_registration_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class Examiner(TypedDict, total=False):
    id: str
    full_name: str
    certified_classes: List[str]
    opaque_user_id: str
    created_at: str
    updated_at: str
    version: int


class KnowledgeTest(TypedDict, total=False):
    id: str
    driver_record_id: str
    scheduled_period: int
    total_questions: int
    correct_answers: int
    score_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RoadTestAppointment(TypedDict, total=False):
    id: str
    driver_record_id: str
    examiner_id: str
    license_class: str
    slot_start_period: int
    slot_end_period: int
    maneuver_scores: list
    provisional_score: float
    final_score: float
    outcome: str
    scored_by_examiner_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    driver_record_id: str
    road_test_appointment_id: Optional[str]
    license_class: str
    is_real_id: bool
    issued_period: int
    expiry_period: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    driver_record_id: str
    code: str
    points: int
    occurred_period: int
    recorded_by_officer: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Suspension(TypedDict, total=False):
    id: str
    driver_record_id: str
    triggering_violation_id: Optional[str]
    point_balance_at_start: int
    start_period: int
    duration_days: int
    eligible_period: int
    point_balance_at_reinstatement: int
    reinstatement_fee: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CdlEndorsement(TypedDict, total=False):
    id: str
    driver_record_id: str
    endorsement_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalCard(TypedDict, total=False):
    id: str
    driver_record_id: str
    issued_period: int
    valid_through_period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeePayment(TypedDict, total=False):
    id: str
    driver_record_id: str
    purpose: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
