"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3).

All resources carry the common system-managed properties `id`, `created_at`,
`updated_at`, and `version` (PRD §2.4: "No resource in this system omits
`updated_at` or `version`").
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DegreeType(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRADUATED = "GRADUATED"


class EnrollmentStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"
    W = "W"


class StudentProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class AuditKind(str, Enum):
    STANDARD = "STANDARD"
    WHAT_IF = "WHAT_IF"
    CONDITIONAL = "CONDITIONAL"
    FINAL = "FINAL"


class AuditStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class WaiverKind(str, Enum):
    SUBSTITUTION = "SUBSTITUTION"
    WAIVER = "WAIVER"


class WaiverStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADVISOR_APPROVED = "ADVISOR_APPROVED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLEARED = "CLEARED"
    CONDITIONALLY_CLEARED = "CONDITIONALLY_CLEARED"
    DENIED = "DENIED"
    DEGREE_CONFERRED = "DEGREE_CONFERRED"


class DiplomaStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class HonorsDesignation(str, Enum):
    NONE = "NONE"
    CUM_LAUDE = "CUM_LAUDE"
    MAGNA_CUM_LAUDE = "MAGNA_CUM_LAUDE"
    SUMMA_CUM_LAUDE = "SUMMA_CUM_LAUDE"


class HonorsGpaBasis(str, Enum):
    INSTITUTIONAL = "INSTITUTIONAL"
    CUMULATIVE = "CUMULATIVE"


class UserRole(str, Enum):
    STUDENT = "Student"
    ADVISOR = "Advisor"
    REGISTRAR = "RegistrarStaff"
    SYSADMIN = "SystemAdmin"


class Program(TypedDict, total=False):
    id: str
    program_code: str
    name: str
    degree_type: str
    min_total_credits: float
    min_gpa: float
    catalog_year_start: int
    catalog_year_end: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RequirementGroup(TypedDict, total=False):
    id: str
    program_id: str
    group_code: str
    required_credits: float
    min_grade: str
    eligible_course_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class HonorsPolicy(TypedDict, total=False):
    id: str
    program_id: str
    honors_gpa_basis: str
    cum_threshold: float
    magna_threshold: float
    summa_threshold: float
    effective_first_year: int
    effective_last_year: int
    residency_min_credits: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    credits: float
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    student_number: str
    legal_name: str
    financial_hold: bool
    status: str
    total_earned_credits: float
    institutional_earned_credits: float
    institutional_gpa: float
    cumulative_gpa: float
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_id: str
    course_id: str
    term: str
    is_transfer: bool
    grade: Optional[str]
    status: str
    credits_attempted: float
    credits_earned: float
    grade_points: float
    created_at: str
    updated_at: str
    version: int


class StudentProgram(TypedDict, total=False):
    id: str
    student_id: str
    program_id: str
    catalog_year: int
    status: str
    latest_audit_satisfied: bool
    created_at: str
    updated_at: str
    version: int


class GroupResult(TypedDict, total=False):
    requirement_group_id: str
    group_code: str
    credits_applied: float
    effective_required_credits: float
    satisfied: bool


class DegreeAudit(TypedDict, total=False):
    id: str
    student_program_id: str
    audit_kind: str
    target_program_id: Optional[str]
    catalog_year_used: int
    status: str
    total_credits_applied: float
    in_progress_credits_counted: float
    outstanding_credits: float
    gpa_at_audit: float
    overall_satisfied: bool
    groups_result: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class SubstitutionWaiver(TypedDict, total=False):
    id: str
    student_program_id: str
    requirement_group_id: str
    kind: str
    enrollment_id: Optional[str]
    credit_waiver_amount: Optional[float]
    reason: Optional[str]
    requested_by_role: str
    requested_by_user_id: str
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GraduationApplication(TypedDict, total=False):
    id: str
    student_program_id: str
    expected_term: str
    expected_conferral_date: str
    diploma_name: Optional[str]
    status: str
    decision_reason: Optional[str]
    honors_designation: Optional[str]
    conferred_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Diploma(TypedDict, total=False):
    id: str
    application_id: str
    printed_name: str
    conferral_date: str
    honors_designation: str
    status: str
    reissue_of_diploma_id: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
