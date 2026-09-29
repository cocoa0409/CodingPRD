"""Domain types for the SFSP Sponsorship & Meal Sites API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD names them.
Entities the PRD describes as carrying only ``id`` and ``created_at`` (the area eligibility
record, the meal count entry and the holding log entry) deliberately omit ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    STATE_AGENCY_REVIEWER = "StateAgencyReviewer"
    SPONSOR_ADMIN = "SponsorAdmin"
    SITE_SUPERVISOR = "SiteSupervisor"
    FIELD_MONITOR = "FieldMonitor"


class SponsorType(str, Enum):
    SCHOOL_FOOD_AUTHORITY = "SCHOOL_FOOD_AUTHORITY"
    GOVERNMENT = "GOVERNMENT"
    NONPROFIT = "NONPROFIT"
    CAMP_OPERATOR = "CAMP_OPERATOR"


class ExperienceStatus(str, Enum):
    NEW = "NEW"
    EXPERIENCED = "EXPERIENCED"


class SponsorApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    TERMINATED = "TERMINATED"


class AreaDataSource(str, Enum):
    SCHOOL_DATA = "SCHOOL_DATA"
    CENSUS_ACS = "CENSUS_ACS"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    WITHDRAWN = "WITHDRAWN"


class AdvanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RECOVERED = "RECOVERED"
    DEMAND_ISSUED = "DEMAND_ISSUED"


class SiteType(str, Enum):
    OPEN = "OPEN"
    RESTRICTED_OPEN = "RESTRICTED_OPEN"
    CLOSED_ENROLLED = "CLOSED_ENROLLED"
    CAMP = "CAMP"
    MIGRANT = "MIGRANT"


class ProductionMode(str, Enum):
    SELF_PREP = "SELF_PREP"
    VENDED = "VENDED"


class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    AM_SNACK = "AM_SNACK"
    LUNCH = "LUNCH"
    PM_SNACK = "PM_SNACK"
    SUPPER = "SUPPER"


class EligibilityBasis(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    AREA_ELIGIBLE = "AREA_ELIGIBLE"
    ENROLLED_DOCUMENTATION = "ENROLLED_DOCUMENTATION"
    CAMP_INDIVIDUAL = "CAMP_INDIVIDUAL"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class SiteApprovalStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"


class SiteOperatingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    OPERATING = "OPERATING"
    CLOSED_FOR_SEASON = "CLOSED_FOR_SEASON"


class ServiceDayStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class FoodSafetyStatus(str, Enum):
    OK = "OK"
    BREACH = "BREACH"


class CountEntryKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    REVERSAL = "REVERSAL"


class TemperatureClass(str, Enum):
    COLD = "COLD"
    HOT = "HOT"


class BreachReason(str, Enum):
    TEMP_OUT_OF_BAND = "TEMP_OUT_OF_BAND"
    HOLDING_TIME_EXCEEDED = "HOLDING_TIME_EXCEEDED"


class VisitType(str, Enum):
    FIRST_WEEK = "FIRST_WEEK"
    FULL_REVIEW = "FULL_REVIEW"
    FOLLOW_UP = "FOLLOW_UP"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    REPORT_FILED = "REPORT_FILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FindingSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ActionOrigin(str, Enum):
    VISIT_FINDING = "VISIT_FINDING"
    COMPLIANCE_FLAG = "COMPLIANCE_FLAG"


class ActionStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EDIT_CHECK_FAILED = "EDIT_CHECK_FAILED"
    VALIDATED = "VALIDATED"
    PAID = "PAID"
    REVISION_OPENED = "REVISION_OPENED"


class RateClass(str, Enum):
    RURAL_OR_SELF_PREP = "RURAL_OR_SELF_PREP"
    OTHER = "OTHER"


class EditCheckStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DisallowReason(str, Enum):
    NONE = "NONE"
    MISSING_MONITORING = "MISSING_MONITORING"
    FOOD_SAFETY_BREACH = "FOOD_SAFETY_BREACH"
    EXCEEDS_PRODUCTION = "EXCEEDS_PRODUCTION"


class VoidReason(str, Enum):
    SITE_DENIED = "SITE_DENIED"
    SITE_SUSPENDED = "SITE_SUSPENDED"
    SEASON_CLOSED = "SEASON_CLOSED"


class SuspensionReason(str, Enum):
    SPONSOR_TERMINATED = "SPONSOR_TERMINATED"


# --- Entities carrying id + created_at + updated_at + version -----------------


class Sponsor(TypedDict):
    id: str
    legal_name: str
    sponsor_type: str
    experience_status: str
    program_year: int
    advance_eligible: bool
    application_status: str
    application_decision_reason: Optional[str]
    approved_at: Optional[str]
    advance_paid_cents: int
    advance_recovered_cents: int
    advance_outstanding_cents: int
    reimbursement_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class SponsorBudget(TypedDict):
    id: str
    sponsor_id: str
    program_year: int
    operating_cost_budget_cents: int
    admin_cost_budget_cents: int
    projected_total_meals: int
    admin_cost_ratio: float
    approved_operating_cost_cents: Optional[int]
    approved_admin_cost_cents: Optional[int]
    status: str
    revision_round: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvancePayment(TypedDict):
    id: str
    sponsor_id: str
    request_month: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    recovered_amount_cents: int
    outstanding_cents: int
    status: str
    disbursed_at: Optional[str]
    demand_issued_at: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    sponsor_id: str
    area_eligibility_record_id: Optional[str]
    name: str
    site_type: str
    production_mode: str
    is_open_air: bool
    is_rural: bool
    approved_meal_types: List[str]
    approved_max_attendance: int
    enrolled_free_reduced_pct: Optional[float]
    operating_start_date: str
    operating_end_date: str
    eligibility_basis: str
    eligibility_pct_used: Optional[float]
    approval_status: str
    operating_status: str
    first_operating_date: Optional[str]
    claim_hold: bool
    compliance_flag_count: int
    voided_day_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MealServiceDay(TypedDict):
    id: str
    site_id: str
    service_date: str
    meal_services: List[dict]
    production_mode: str
    production_counts: Optional[Dict[str, int]]
    food_received_at: Optional[str]
    status: str
    food_safety_status: str
    breach_at: Optional[str]
    counted_first_meals: int
    counted_second_meals: int
    counted_adult_meals: int
    reimbursable_meals: int
    non_reimbursable_meals: int
    discarded_meals: int
    leftover_meals: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringVisit(TypedDict):
    id: str
    site_id: str
    monitor_user_id: str
    visit_type: str
    scheduled_date: str
    window_start: str
    window_end: str
    status: str
    conducted_at: Optional[str]
    findings: Optional[List[dict]]
    highest_severity: str
    due_date: Optional[str]
    is_late: bool
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    site_id: str
    monitoring_visit_id: Optional[str]
    follow_up_of_corrective_action_id: Optional[str]
    origin: str
    finding_code: str
    severity: str
    status: str
    due_date: str
    rejection_count: int
    response_note: Optional[str]
    evidence_ref: Optional[str]
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MealClaim(TypedDict):
    id: str
    sponsor_id: str
    claim_month: str
    status: str
    revision_round: int
    claimed_operating_cost_cents: Optional[int]
    claimed_admin_cost_cents: Optional[int]
    meals_rate_value_cents: int
    preliminary_reimbursement_cents: Optional[int]
    final_reimbursement_cents: Optional[int]
    advance_offset_cents: Optional[int]
    net_payable_cents: Optional[int]
    disallowed_meal_count: int
    blocking_hold_count: int
    edit_check_failure_codes: Optional[List[str]]
    deadline_date: str
    is_late: bool
    submitted_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLineItem(TypedDict):
    id: str
    meal_claim_id: str
    site_id: str
    rate_class: str
    finalized_day_count: int
    claimed_first_meals_by_type: Dict[str, int]
    claimed_second_meals_by_type: Dict[str, int]
    disallowed_counts_by_type: Optional[Dict[str, int]]
    meals_rate_value_cents: int
    disallowed_meal_count: int
    edit_check_status: str
    disallow_reason: str
    hold_flag: bool
    created_at: str
    updated_at: str
    version: int


# --- Append-only rows: id + created_at only, no updated_at and no version -----


class AreaEligibilityRecord(TypedDict):
    id: str
    area_code: str
    data_source: str
    free_reduced_pct: float
    determination_date: str
    valid_through_date: str
    created_at: str


class MealCountEntry(TypedDict):
    id: str
    meal_service_day_id: str
    reversal_of_entry_id: Optional[str]
    meal_type: str
    first_meals: int
    second_meals: int
    adult_meals: int
    entry_kind: str
    reimbursable_first_meals: int
    reimbursable_second_meals: int
    non_reimbursable_meals: int
    recorded_at: str
    recorded_by_user_id: str
    created_at: str


class HoldingLogEntry(TypedDict):
    id: str
    meal_service_day_id: str
    meal_type: str
    temperature_class: str
    temperature_f: float
    measured_at: str
    holding_minutes: int
    breach_flag: bool
    breach_reason: Optional[str]
    recorded_by_user_id: str
    created_at: str
