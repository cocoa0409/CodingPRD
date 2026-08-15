"""Domain types: entity status enums and the role enum (PRD §2.1, §3).

Every resource carries the common system-managed fields of PRD §2.5:
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELING = "MODELING"
    UNDER_LEGAL_REVIEW = "UNDER_LEGAL_REVIEW"
    PRIVILEGED_FINAL = "PRIVILEGED_FINAL"
    REMEDIATION_OPEN = "REMEDIATION_OPEN"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class GroupStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    ANALYZED = "ANALYZED"


class RunStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class FindingStatus(str, Enum):
    FLAGGED = "FLAGGED"
    TARGETED = "TARGETED"
    MONITORED = "MONITORED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    FULLY_COMMITTED = "FULLY_COMMITTED"
    COMPLETED = "COMPLETED"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    REVERSED = "REVERSED"


class FilingStatus(str, Enum):
    COMPILING = "COMPILING"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    RE_TESTING = "RE_TESTING"
    COMPLETED = "COMPLETED"


class Methodology(str, Enum):
    REGRESSION_OLS = "REGRESSION_OLS"
    COHORT_MEDIAN = "COHORT_MEDIAN"


class AllocationStrategy(str, Enum):
    FULL_CLOSURE = "FULL_CLOSURE"
    PRO_RATA = "PRO_RATA"


class UserRole(str, Enum):
    COMP_ANALYST = "CompAnalyst"
    LEGAL_COUNSEL = "LegalCounsel"
    REMEDIATION_APPROVER = "RemediationApprover"
    PEOPLE_OPS_ADMIN = "PeopleOpsAdmin"
    COMPLIANCE_REPORTER = "ComplianceReporter"
    PLATFORM_ADMIN = "PlatformAdmin"


class PayEquityStudy(TypedDict, total=False):
    id: str
    name: str
    analysis_period_start: str
    analysis_period_end: str
    protected_classes: List[str]
    significance_threshold: float
    actionable_gap_pct: float
    min_group_size: int
    monitor_cadence_days: int
    status: str
    review_rounds: int
    privileged_model_run_ids: List[str]
    snapshot_count: int
    assigned_snapshot_count: int
    unresolved_finding_count: int
    actionable_finding_count: int
    created_at: str
    updated_at: str
    version: int


class EmployeeSnapshot(TypedDict, total=False):
    id: str
    study_id: str
    employee_ref: str
    gender_class: str
    ethnicity_class: str
    age_band: str
    job_family: str
    job_level: int
    location_code: str
    fte_factor: float
    base_salary_cents: int
    bonus_cents: int
    hire_date: str
    comparator_group_id: Optional[str]
    annualized_base_cents: int
    tenure_years: float
    created_at: str
    updated_at: str
    version: int


class ComparatorGroup(TypedDict, total=False):
    id: str
    study_id: str
    name: str
    job_family: str
    min_job_level: int
    max_job_level: int
    location_code: str
    member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ModelRun(TypedDict, total=False):
    id: str
    comparator_group_id: str
    study_id: str
    methodology: str
    run_index: int
    per_class_results: dict
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GapFinding(TypedDict, total=False):
    id: str
    model_run_id: str
    comparator_group_id: str
    study_id: str
    protected_class: str
    class_value: str
    reference_class: str
    adjusted_gap_pct: float
    p_value: float
    affected_headcount: int
    is_actionable: bool
    status: str
    disposition_rationale: Optional[str]
    disposition_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    study_id: str
    total_budget_cents: int
    allocation_strategy: str
    committed_cents: int
    remaining_cents: int
    rejection_count: int
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict, total=False):
    id: str
    plan_id: str
    gap_finding_id: str
    employee_snapshot_id: str
    study_id: str
    proposed_increase_cents: int
    approved_increase_cents: Optional[int]
    effective_date: str
    status: str
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportFiling(TypedDict, total=False):
    id: str
    study_id: str
    report_type: str
    jurisdiction_rule_id: Optional[str]
    reporting_year: int
    due_date: str
    band_rows: Optional[List[dict]]
    total_headcount: Optional[int]
    submitted_at: Optional[str]
    late_submission: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class JurisdictionRule(TypedDict, total=False):
    id: str
    jurisdiction_code: str
    range_disclosure_required: bool
    max_range_spread_pct: Optional[float]
    min_posting_duration_days: int
    pay_data_report_required: bool
    filing_due_month: Optional[int]
    filing_due_day: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransparencyPosting(TypedDict, total=False):
    id: str
    jurisdiction_rule_id: str
    job_posting_ref: str
    title: str
    min_salary_cents: Optional[int]
    max_salary_cents: Optional[int]
    published_at: Optional[str]
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PipelineAnalysis(TypedDict, total=False):
    id: str
    study_id: str
    stage: str
    cohort_period_start: str
    cohort_period_end: str
    records: List[dict]
    pass_rates: dict
    adverse_impact_ratio: Optional[float]
    adverse_impact_flag: bool
    highest_rate_class: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringCycle(TypedDict, total=False):
    id: str
    study_id: str
    window_start: str
    window_end: str
    due_date: str
    cycle_index: int
    retest_result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
