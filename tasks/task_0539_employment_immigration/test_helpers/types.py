"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the common system fields id, created_at,
updated_at, and version (PRD §2.4: "All ten primary entities in this system
carry updated_at and version; none of them omit these fields").
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    EMPLOYER_AGENT = "EmployerAgent"
    DOL_ANALYST = "DOLAnalyst"
    USCIS_OFFICER = "USCISOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class PWDStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class PermCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    RECRUITING = "RECRUITING"
    QUIET_PERIOD = "QUIET_PERIOD"
    FILED = "FILED"
    AUDIT = "AUDIT"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"


class RecruitmentStepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class RecruitmentStepType(str, Enum):
    JOB_ORDER = "JOB_ORDER"
    NEWSPAPER_AD = "NEWSPAPER_AD"
    PROFESSIONAL_JOURNAL = "PROFESSIONAL_JOURNAL"
    EMPLOYER_WEBSITE = "EMPLOYER_WEBSITE"
    JOB_FAIR = "JOB_FAIR"


class LCAStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PafStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    DEFICIENT = "DEFICIENT"


class BeneficiaryStatusCode(str, Enum):
    NONE = "NONE"
    H1B_ACTIVE = "H1B_ACTIVE"
    H1B_EXPIRED = "H1B_EXPIRED"


class H1BRegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    WITHDRAWN = "WITHDRAWN"


class H1BPetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RFE_ISSUED = "RFE_ISSUED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RfeStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    RESPONDED = "RESPONDED"


class I140PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class I140Category(str, Enum):
    EB1 = "EB1"
    EB2 = "EB2"
    EB3 = "EB3"


class WageLevel(str, Enum):
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    LEVEL_III = "LEVEL_III"
    LEVEL_IV = "LEVEL_IV"


class WageSource(str, Enum):
    OES = "OES"
    EMPLOYER_SURVEY = "EMPLOYER_SURVEY"


class Employer(TypedDict):
    id: str
    fein: str
    legal_name: str
    employee_count: int
    h1b_dependent: bool
    total_wage_obligation_cents: int
    created_at: str
    updated_at: str
    version: int


class PrevailingWageDetermination(TypedDict):
    id: str
    employer_id: str
    soc_code: str
    job_title: str
    area_code: str
    wage_level: str
    wage_source: str
    oes_wage_cents: int
    survey_wage_cents: Optional[int]
    prevailing_wage_cents: Optional[int]
    validity_start: str
    validity_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PermCase(TypedDict):
    id: str
    employer_id: str
    pwd_id: str
    job_title: str
    offered_wage_cents: int
    recruitment_start: Optional[str]
    recruitment_end: Optional[str]
    quiet_period_end: Optional[str]
    filed_date: Optional[str]
    priority_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecruitmentStep(TypedDict):
    id: str
    perm_case_id: str
    step_type: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LCA(TypedDict):
    id: str
    employer_id: str
    soc_code: str
    worksite_areas: List[str]
    area_wage_map: dict
    offered_wage_cents: int
    prevailing_wage_cents: int
    hours_per_week: int
    required_wage_cents: int
    aggregate_wage_obligation_cents: int
    validity_start: str
    validity_end: str
    has_wage_rate: bool
    has_prevailing_wage_doc: bool
    has_notice_of_filing: bool
    has_actual_wage_memo: bool
    paf_completeness_score: int
    paf_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    full_name: str
    passport_number: str
    current_status_code: str
    status_valid_until: Optional[str]
    priority_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapProgram(TypedDict):
    id: str
    fiscal_year: int
    selection_quota: int
    selected_count: int
    available_seats: int
    lottery_run: bool
    created_at: str
    updated_at: str
    version: int


class H1BRegistration(TypedDict):
    id: str
    employer_id: str
    beneficiary_id: str
    fiscal_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class H1BPetition(TypedDict):
    id: str
    employer_id: str
    lca_id: str
    beneficiary_id: str
    registration_id: str
    worksite_area: str
    employment_start: str
    employment_end: str
    is_amended: bool
    filing_fee_cents: int
    rfe_status: str
    rfe_issued_date: Optional[str]
    rfe_due_date: Optional[str]
    rfe_response_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class I140Petition(TypedDict):
    id: str
    employer_id: str
    perm_case_id: Optional[str]
    beneficiary_id: str
    category: str
    filed_date: Optional[str]
    priority_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
