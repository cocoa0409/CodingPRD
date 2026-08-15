"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    AUDITOR = "Auditor"


class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EntityType(str, Enum):
    CORPORATION = "CORPORATION"
    S_CORPORATION = "S_CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"
    LLC = "LLC"
    SOLE_PROPRIETORSHIP = "SOLE_PROPRIETORSHIP"
    NONPROFIT = "NONPROFIT"
    GOVERNMENTAL = "GOVERNMENTAL"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PlanType(str, Enum):
    K401 = "401K"
    CAFETERIA_125 = "CAFETERIA_125"
    DEPENDENT_CARE_FSA = "DEPENDENT_CARE_FSA"


class PlanVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class CompDefinition(str, Enum):
    W2 = "W2"
    SEC415 = "SEC415"
    SEC3401 = "SEC3401"


class SafeHarborDesign(str, Enum):
    NONE = "NONE"
    BASIC_MATCH = "BASIC_MATCH"
    ENHANCED_MATCH = "ENHANCED_MATCH"
    QNEC_3PCT = "QNEC_3PCT"
    QACA = "QACA"


class EntryFrequency(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


class PlanYearStatus(str, Enum):
    DRAFT = "DRAFT"
    CENSUS_COLLECTING = "CENSUS_COLLECTING"
    CENSUS_LOCKED = "CENSUS_LOCKED"
    TESTING = "TESTING"
    RESULTS_REVIEW = "RESULTS_REVIEW"
    CORRECTING = "CORRECTING"
    FILED = "FILED"
    TERMINATED = "TERMINATED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"


class CoveredStatus(str, Enum):
    BENEFITING = "BENEFITING"
    ELIGIBLE_NOT_BENEFITING = "ELIGIBLE_NOT_BENEFITING"
    EXCLUDABLE = "EXCLUDABLE"
    INELIGIBLE = "INELIGIBLE"


class HceStatus(str, Enum):
    HCE = "HCE"
    NHCE = "NHCE"
    EXCLUDED_FROM_TESTING = "EXCLUDED_FROM_TESTING"


class KeyEmployeeStatus(str, Enum):
    KEY = "KEY"
    NON_KEY = "NON_KEY"
    EXCLUDED_FROM_TESTING = "EXCLUDED_FROM_TESTING"


class CompSource(str, Enum):
    W2 = "W2"
    SEC415 = "SEC415"
    SEC3401 = "SEC3401"


class CompPeriod(str, Enum):
    CURRENT_YEAR = "CURRENT_YEAR"
    PRIOR_YEAR = "PRIOR_YEAR"


class CompRecordSource(str, Enum):
    IMPORTED = "IMPORTED"
    ADMIN_ADJUSTED = "ADMIN_ADJUSTED"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"


class ContributionType(str, Enum):
    ELECTIVE_DEFERRAL = "ELECTIVE_DEFERRAL"
    MATCH = "MATCH"
    QNEC = "QNEC"
    QMAC = "QMAC"
    PROFIT_SHARING = "PROFIT_SHARING"
    CAFETERIA_PRETAX = "CAFETERIA_PRETAX"
    DEPENDENT_CARE_ELECTIVE = "DEPENDENT_CARE_ELECTIVE"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"
    PENDING_DISTRIBUTION = "PENDING_DISTRIBUTION"
    DISTRIBUTED = "DISTRIBUTED"
    RECHARACTERIZED = "RECHARACTERIZED"
    FORFEITED = "FORFEITED"


class RegulatoryLimitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ElectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EFFECTIVE = "EFFECTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    DISTRIBUTED = "DISTRIBUTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    LAPSED = "LAPSED"


class TestScope(str, Enum):
    COVERAGE_410B = "COVERAGE_410B"
    ADP_401K = "ADP_401K"
    ACP_401M = "ACP_401M"
    TOP_HEAVY_416 = "TOP_HEAVY_416"
    CAFETERIA_125 = "CAFETERIA_125"
    DEPENDENT_CARE_129 = "DEPENDENT_CARE_129"
    FULL_SUITE = "FULL_SUITE"


class RunMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TestRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class OverallResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class Metric(str, Enum):
    COVERAGE_RATIO_PCT = "COVERAGE_RATIO_PCT"
    ADP_HCE_PCT = "ADP_HCE_PCT"
    ADP_NHCE_PCT = "ADP_NHCE_PCT"
    ADP_CEILING_PCT = "ADP_CEILING_PCT"
    ACP_HCE_PCT = "ACP_HCE_PCT"
    ACP_NHCE_PCT = "ACP_NHCE_PCT"
    ACP_CEILING_PCT = "ACP_CEILING_PCT"
    TOP_HEAVY_RATIO_PCT = "TOP_HEAVY_RATIO_PCT"
    CAFETERIA_ELIGIBILITY_PCT = "CAFETERIA_ELIGIBILITY_PCT"
    CAFETERIA_UTILIZATION_PCT = "CAFETERIA_UTILIZATION_PCT"
    DEPENDENT_CARE_55PCT_AVG_PCT = "DEPENDENT_CARE_55PCT_AVG_PCT"
    KEY_EMPLOYEE_CONCENTRATION_PCT = "KEY_EMPLOYEE_CONCENTRATION_PCT"


class LineOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CorrectionType(str, Enum):
    CORRECTIVE_DISTRIBUTION = "CORRECTIVE_DISTRIBUTION"
    QNEC_CONTRIBUTION = "QNEC_CONTRIBUTION"
    QMAC_REALLOCATION = "QMAC_REALLOCATION"
    RECHARACTERIZATION = "RECHARACTERIZATION"
    PLAN_AMENDMENT_RETRO = "PLAN_AMENDMENT_RETRO"


class CorrectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class ExciseStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    ACCRUING = "ACCRUING"
    ASSESSED = "ASSESSED"
    PAID = "PAID"


# All entities carry the four common system fields per PRD §2.4
# ("No entity in this system is exempt from the common property set."):
# id, created_at, updated_at, version.


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    entity_type: str
    controlled_group_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    employer_id: str
    plan_name: str
    plan_type: str
    plan_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanVersion(TypedDict, total=False):
    id: str
    plan_id: str
    effective_start: str
    effective_end: Optional[str]
    comp_definition: str
    safe_harbor_design: str
    sh_match_formula: Optional[str]
    entry_frequency: str
    is_amendment: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanYear(TypedDict, total=False):
    id: str
    plan_id: str
    year_label: int
    year_start: str
    year_end: str
    census_lock_version: int
    status: str
    prior_year_py_id: Optional[str]
    adopted_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CensusEmployee(TypedDict, total=False):
    id: str
    plan_year_id: str
    ssn: str
    full_name: str
    date_of_birth: str
    date_of_hire: str
    date_of_termination: Optional[str]
    employment_status: str
    ownership_pct_direct: float
    is_officer: bool
    family_member_of_ssn: Optional[str]
    covered_status: str
    hce_status: str
    key_employee_status: str
    attributed_ownership_pct: float
    created_at: str
    updated_at: str
    version: int


class CompensationRecord(TypedDict, total=False):
    id: str
    census_employee_id: str
    comp_source: str
    amount_cents: int
    period: str
    source: str
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    census_employee_id: str
    contribution_type: str
    amount_cents: int
    contribution_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryLimit(TypedDict, total=False):
    id: str
    year_label: int
    hce_comp_threshold_cents: int
    key_officer_comp_threshold_cents: int
    sec402g_limit_cents: int
    sec415_annual_additions_limit_cents: int
    dependent_care_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SafeHarborElection(TypedDict, total=False):
    id: str
    plan_year_id: str
    design: str
    elected_on: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafeHarborNotice(TypedDict, total=False):
    id: str
    election_id: str
    notice_period_start: str
    notice_period_end: str
    distributed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestRun(TypedDict, total=False):
    id: str
    plan_year_id: str
    test_scope: str
    run_mode: str
    engine_input_hash: str
    status: str
    overall_result: str
    created_at: str
    updated_at: str
    version: int


class TestResultLine(TypedDict, total=False):
    id: str
    test_run_id: str
    metric: str
    value_pct: float
    threshold_pct: float
    outcome: str
    detail: dict
    created_at: str
    updated_at: str
    version: int


class Correction(TypedDict, total=False):
    id: str
    plan_year_id: str
    test_run_id: str
    correction_type: str
    target_census_employee_id: Optional[str]
    amount_cents: int
    gap_period_income_cents: int
    excise_tax_cents: int
    excise_status: str
    status: str
    deadline_date: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
