"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMP_ANALYST = "CompAnalyst"
    COMP_MANAGER = "CompManager"
    HR_DIRECTOR = "HRDirector"
    COMP_COMMITTEE_REVIEWER = "CompCommitteeReviewer"
    VENDOR_ADMIN = "VendorAdmin"


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"


class VendorStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CompositeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class AdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PRESENTED = "PRESENTED"


class GeoDifferentialPolicy(str, Enum):
    NATIONAL = "NATIONAL"
    METRO_TIER = "METRO_TIER"
    CUSTOM_GEO_INDEX = "CUSTOM_GEO_INDEX"


class IndustryCut(str, Enum):
    ALL_INDUSTRIES = "ALL_INDUSTRIES"
    HIGH_TECH = "HIGH_TECH"
    FINANCIAL_SERVICES = "FINANCIAL_SERVICES"
    HEALTHCARE = "HEALTHCARE"
    MANUFACTURING = "MANUFACTURING"
    RETAIL = "RETAIL"


class CareerLevel(str, Enum):
    IC1 = "IC1"
    IC2 = "IC2"
    IC3 = "IC3"
    IC4 = "IC4"
    IC5 = "IC5"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"


class MatchConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).

class Organization(TypedDict, total=False):
    id: str
    name: str
    base_currency: str
    fiscal_year_start_month: int
    market_as_of_date: str
    strategy_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketStrategyPolicy(TypedDict, total=False):
    id: str
    org_id: str
    name: str
    target_percentile: int
    geo_differential_policy: str
    industry_cut: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    org_id: str
    full_name: str
    email: str
    job_id: str
    geo_code: str
    base_salary_annual_cents: int
    hire_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    org_id: str
    job_code: str
    title: str
    job_family: str
    career_level: str
    flsa_status: str
    current_market_composite_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyVendor(TypedDict, total=False):
    id: str
    org_id: str
    vendor_name: str
    contract_start_date: str
    contract_end_date: str
    data_use_scope: str
    confidentiality_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    vendor_id: str
    org_id: str
    survey_code: str
    edition_year: int
    data_effective_date: str
    submission_deadline: str
    industry_cut_supported: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyBenchmark(TypedDict, total=False):
    id: str
    survey_id: str
    benchmark_code: str
    benchmark_title: str
    career_level: str
    industry_cut: str
    geo_scope: str
    p25_cents: int
    p50_cents: int
    p75_cents: int
    p90_cents: int
    sample_size: int
    created_at: str
    updated_at: str
    version: int


class SurveySubmission(TypedDict, total=False):
    id: str
    survey_id: str
    submitted_by_employee_id: str
    incumbent_snapshot: List[dict]
    prepared_at: Optional[str]
    submitted_at: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyJobMatch(TypedDict, total=False):
    id: str
    survey_id: str
    job_id: str
    benchmark_id: str
    match_confidence: str
    match_weight_pct: int
    proposed_by_employee_id: str
    reviewer_employee_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketComposite(TypedDict, total=False):
    id: str
    job_id: str
    strategy_policy_id: str
    job_geo_code: str
    blended_p25_cents: int
    blended_p50_cents: int
    blended_p75_cents: int
    blended_p90_cents: int
    geo_differential_bp: Optional[int]
    source_count: int
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketAdjustmentCycle(TypedDict, total=False):
    id: str
    org_id: str
    name: str
    effective_date: str
    budget_cents: int
    allocated_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketAdjustment(TypedDict, total=False):
    id: str
    cycle_id: str
    employee_id: str
    job_id: str
    proposed_amount_cents: int
    proposed_by_employee_id: str
    approved_by_employee_id: Optional[str]
    pre_adjustment_compa_ratio_bp: int
    post_adjustment_compa_ratio_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompensationReport(TypedDict, total=False):
    id: str
    org_id: str
    title: str
    reporting_period_start: str
    reporting_period_end: str
    pinned_strategy_policy_id: str
    snapshot_payload: Optional[dict]
    presented_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# AuditEvent is append-only: only id + created_at (PRD §2.5) — no updated_at,
# no version.
class AuditEvent(TypedDict, total=False):
    id: str
    org_id: str
    actor_employee_id: Optional[str]
    action: str
    target_entity: str
    target_id: str
    payload_hash: str
    created_at: str
