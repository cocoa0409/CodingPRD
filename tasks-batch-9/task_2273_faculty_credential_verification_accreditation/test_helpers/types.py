"""Enumerations and response shapes declared by the PRD.

Values are transcribed from the PRD's own enumerations; nothing here is
inferred from an implementation.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


class Role(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    REGISTRAR_OFFICER = "RegistrarOfficer"
    CREDENTIAL_ANALYST = "CredentialAnalyst"
    PROGRAM_DEAN = "ProgramDean"
    ACCREDITATION_LIAISON = "AccreditationLiaison"
    ACCREDITOR_REVIEWER = "AccreditorReviewer"
    INSTRUCTOR = "Instructor"


class DegreeLevel(str, Enum):
    NON_DEGREE_GRADUATE = "NON_DEGREE_GRADUATE"
    BACHELORS = "BACHELORS"
    MASTERS = "MASTERS"
    DOCTORATE = "DOCTORATE"


class ProgramDegreeLevel(str, Enum):
    CERTIFICATE = "CERTIFICATE"
    ASSOCIATE = "ASSOCIATE"
    BACHELORS = "BACHELORS"
    MASTERS = "MASTERS"
    DOCTORATE = "DOCTORATE"


class TerminalDegreeLevel(str, Enum):
    MASTERS = "MASTERS"
    DOCTORATE = "DOCTORATE"


class QualificationPolicy(str, Enum):
    DEGREE_FIELD = "DEGREE_FIELD"
    COURSEWORK_18 = "COURSEWORK_18"


class AdequacyBasis(str, Enum):
    HEADCOUNT = "HEADCOUNT"
    CREDIT_HOUR_COVERAGE = "CREDIT_HOUR_COVERAGE"


class AdequacyStatus(str, Enum):
    ADEQUATE = "ADEQUATE"
    AT_RISK = "AT_RISK"
    INSUFFICIENT = "INSUFFICIENT"


class LaunchStatus(str, Enum):
    PLANNING = "PLANNING"
    ADEQUACY_REVIEW = "ADEQUACY_REVIEW"
    ADEQUACY_DENIED = "ADEQUACY_DENIED"
    APPROVED_TO_LAUNCH = "APPROVED_TO_LAUNCH"


class TermStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    CLOSED = "CLOSED"


class EmploymentClass(str, Enum):
    FULL_TIME = "FULL_TIME"
    ADJUNCT = "ADJUNCT"
    CLINICAL = "CLINICAL"
    GRADUATE_ASSISTANT = "GRADUATE_ASSISTANT"


class DossierStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    DEFICIENT = "DEFICIENT"


class AppointmentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    CREDENTIALED_ELIGIBLE = "CREDENTIALED_ELIGIBLE"
    CONTRACTED = "CONTRACTED"
    SEPARATED = "SEPARATED"


class DeficiencyCode(str, Enum):
    NO_CREDENTIAL_ON_FILE = "NO_CREDENTIAL_ON_FILE"
    TRANSCRIPT_NOT_OFFICIAL = "TRANSCRIPT_NOT_OFFICIAL"
    FOREIGN_EVALUATION_INCOMPLETE = "FOREIGN_EVALUATION_INCOMPLETE"
    CREDENTIAL_REPUDIATED = "CREDENTIAL_REPUDIATED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REPUDIATED = "REPUDIATED"


class TranscriptStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    UNOFFICIAL_ONLY = "UNOFFICIAL_ONLY"
    OFFICIAL_RECEIVED = "OFFICIAL_RECEIVED"


class VerificationDecision(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"
    REPUDIATE = "REPUDIATE"


class EvaluationStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class EquivalencyVerdict(str, Enum):
    EQUIVALENT = "EQUIVALENT"
    PARTIAL = "PARTIAL"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"


class CourseLevel(str, Enum):
    LOWER_DIVISION = "LOWER_DIVISION"
    UPPER_DIVISION = "UPPER_DIVISION"
    GRADUATE = "GRADUATE"
    DOCTORAL = "DOCTORAL"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    ONLINE_SYNC = "ONLINE_SYNC"
    ONLINE_ASYNC = "ONLINE_ASYNC"


class MeetingDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class AssignmentRole(str, Enum):
    INSTRUCTOR_OF_RECORD = "INSTRUCTOR_OF_RECORD"
    CO_INSTRUCTOR = "CO_INSTRUCTOR"


class AssignmentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED_QUALIFIED = "VERIFIED_QUALIFIED"
    EXCEPTION_FLAGGED = "EXCEPTION_FLAGGED"
    REMEDIATION_IN_PROGRESS = "REMEDIATION_IN_PROGRESS"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class QualificationBasis(str, Enum):
    TERMINAL_DEGREE = "TERMINAL_DEGREE"
    COURSEWORK_18_HOUR = "COURSEWORK_18_HOUR"
    TESTED_EXPERIENCE = "TESTED_EXPERIENCE"
    NONE = "NONE"


class ExceptionCode(str, Enum):
    NO_OFFICIAL_TRANSCRIPT = "NO_OFFICIAL_TRANSCRIPT"
    FOREIGN_EVALUATION_MISSING = "FOREIGN_EVALUATION_MISSING"
    DEGREE_LEVEL_INSUFFICIENT = "DEGREE_LEVEL_INSUFFICIENT"
    DISCIPLINE_MISALIGNED = "DISCIPLINE_MISALIGNED"
    DOSSIER_DEFICIENT = "DOSSIER_DEFICIENT"


class RemediationAction(str, Enum):
    REASSIGN_PENDING = "REASSIGN_PENDING"
    TESTED_EXPERIENCE_PENDING = "TESTED_EXPERIENCE_PENDING"
    CREDENTIAL_UPDATE_PENDING = "CREDENTIAL_UPDATE_PENDING"


class JustificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CertificationLevel(str, Enum):
    NONE = "NONE"
    PRACTITIONER = "PRACTITIONER"
    ADVANCED = "ADVANCED"
    BOARD_CERTIFIED = "BOARD_CERTIFIED"


class JustificationDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RosterStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class CertificationReadiness(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class BlockingReasonCode(str, Enum):
    EXCEPTIONS_OUTSTANDING = "EXCEPTIONS_OUTSTANDING"
    ADEQUACY_BELOW_MINIMUM = "ADEQUACY_BELOW_MINIMUM"
    DOSSIER_DEFICIENT = "DOSSIER_DEFICIENT"


class ContractStatus(str, Enum):
    ISSUED = "ISSUED"
    COUNTERSIGNED = "COUNTERSIGNED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class PdActivityType(str, Enum):
    CONFERENCE = "CONFERENCE"
    CERTIFICATION = "CERTIFICATION"
    COURSEWORK = "COURSEWORK"
    INDUSTRY_PLACEMENT = "INDUSTRY_PLACEMENT"
    PUBLICATION = "PUBLICATION"


class PdStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ReviewType(str, Enum):
    SUBSTANTIVE_CHANGE = "SUBSTANTIVE_CHANGE"
    COMPREHENSIVE = "COMPREHENSIVE"
    FOCUSED_FOLLOWUP = "FOCUSED_FOLLOWUP"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CLOSED_ACCEPTED = "CLOSED_ACCEPTED"
    CLOSED_SANCTION = "CLOSED_SANCTION"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class LaunchDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --------------------------------------------------------------------------
# Response shapes.  PRD 2.5: every entity carries id / created_at /
# updated_at / version.
# --------------------------------------------------------------------------


class BaseEntity(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
OptStr = Optional[str]

COMMON_ENTITY_FIELDS = ("id", "created_at", "updated_at", "version")
