"""Domain types for the Employer Health Coverage Reporting API.

Entity TypedDicts, status enums and the role enum, derived from PRD §2 and §3.

Nine resource families carry the full mutable-resource property set
(``id``, ``created_at``, ``updated_at``, ``version``); the remaining seven are
append-only ledger rows that carry only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BENEFITS_ADMIN = "BenefitsAdmin"
    PREPARER = "Preparer"
    FILING_AGENT = "FilingAgent"
    EMPLOYEE_SELF_SERVICE = "EmployeeSelfService"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class FilingSeasonStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class DeterminationState(str, Enum):
    NOT_DETERMINED = "NOT_DETERMINED"
    DETERMINED_ALE = "DETERMINED_ALE"
    DETERMINED_NON_ALE = "DETERMINED_NON_ALE"
    REOPENED = "REOPENED"
    CORRECTION_OPEN = "CORRECTION_OPEN"
    LOCKED = "LOCKED"


class DeterminationBasis(str, Enum):
    AGGREGATED = "AGGREGATED"
    SINGLE_MEMBER = "SINGLE_MEMBER"


class AleReason(str, Enum):
    THRESHOLD_MET = "THRESHOLD_MET"
    SEASONAL_EXCEPTION = "SEASONAL_EXCEPTION"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MeasurementMethod(str, Enum):
    LOOK_BACK = "LOOK_BACK"
    MONTHLY = "MONTHLY"


class CountYear(str, Enum):
    PRIOR_YEAR = "PRIOR_YEAR"
    REPORTING_YEAR = "REPORTING_YEAR"


class CycleType(str, Enum):
    STANDARD = "STANDARD"
    INITIAL = "INITIAL"


class EmploymentType(str, Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    VARIABLE_HOUR = "VARIABLE_HOUR"
    SEASONAL = "SEASONAL"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class EventType(str, Enum):
    LEAVE_START = "LEAVE_START"
    LEAVE_END = "LEAVE_END"
    TRANSFER = "TRANSFER"
    TERMINATION = "TERMINATION"
    REHIRE = "REHIRE"


class LeaveType(str, Enum):
    FMLA = "FMLA"
    USERRA = "USERRA"
    JURY_DUTY = "JURY_DUTY"
    UNPAID_OTHER = "UNPAID_OTHER"


class OfferKind(str, Enum):
    NO_OFFER = "NO_OFFER"
    MEC_NO_MV = "MEC_NO_MV"
    MEC_MV_SELF_ONLY = "MEC_MV_SELF_ONLY"
    MEC_MV_SELF_SPOUSE = "MEC_MV_SELF_SPOUSE"
    MEC_MV_SELF_DEP = "MEC_MV_SELF_DEP"
    MEC_MV_FAMILY = "MEC_MV_FAMILY"
    MEC_MV_FAMILY_CONDITIONAL_SPOUSE = "MEC_MV_FAMILY_CONDITIONAL_SPOUSE"
    COBRA_TERMINATED = "COBRA_TERMINATED"
    RETIREE_COVERAGE = "RETIREE_COVERAGE"


class FormType(str, Enum):
    ORIGINAL = "ORIGINAL"
    CORRECTED = "CORRECTED"


class FurnishingStatus(str, Enum):
    NOT_FURNISHED = "NOT_FURNISHED"
    FURNISHED_PAPER = "FURNISHED_PAPER"
    FURNISHED_ELECTRONIC = "FURNISHED_ELECTRONIC"
    REDELIVERY_REQUIRED = "REDELIVERY_REQUIRED"
    VOIDED = "VOIDED"


class FilingStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    ATTACHED = "ATTACHED"
    PENDING_FILING = "PENDING_FILING"
    FILED_ACCEPTED = "FILED_ACCEPTED"
    FILED_WITH_ERRORS = "FILED_WITH_ERRORS"
    CORRECTION_DRAFTED = "CORRECTION_DRAFTED"
    VOIDED = "VOIDED"


class SafeHarborPreference(str, Enum):
    W2 = "W2"
    RATE_OF_PAY = "RATE_OF_PAY"
    FPL = "FPL"
    NONE = "NONE"


class FtSource(str, Enum):
    LOOK_BACK_STABILITY = "LOOK_BACK_STABILITY"
    MONTHLY_ACTUAL = "MONTHLY_ACTUAL"
    LNAP = "LNAP"
    NOT_EMPLOYED = "NOT_EMPLOYED"


class SpecialSituation(str, Enum):
    NONE = "NONE"
    WAITING_PERIOD = "WAITING_PERIOD"
    INITIAL_MEASUREMENT = "INITIAL_MEASUREMENT"
    LEAVE = "LEAVE"
    TRANSFER = "TRANSFER"
    TERMINATION = "TERMINATION"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryChannel(str, Enum):
    PAPER = "PAPER"
    ELECTRONIC = "ELECTRONIC"


class TransmittalStatus(str, Enum):
    DRAFT = "DRAFT"
    BUILT = "BUILT"
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_ERRORS = "ACCEPTED_WITH_ERRORS"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class TransmissionType(str, Enum):
    ORIGINAL = "ORIGINAL"
    CORRECTION = "CORRECTION"
    REPLACEMENT = "REPLACEMENT"


class RequiredChannel(str, Enum):
    ANY = "ANY"
    ELECTRONIC = "ELECTRONIC"


class AgencyResponseStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_ERRORS = "ACCEPTED_WITH_ERRORS"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"


class ErrorSeverity(str, Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"


class ResolutionStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTED = "CORRECTED"
    ACCEPTED_AS_FILED = "ACCEPTED_AS_FILED"


class ErrorResolution(str, Enum):
    CORRECT_FORM = "CORRECT_FORM"
    ACCEPT_AS_FILED = "ACCEPT_AS_FILED"


class NoticeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    RECOMPUTED = "RECOMPUTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    ABATED_FULL = "ABATED_FULL"
    ABATED_PARTIAL = "ABATED_PARTIAL"
    SUSTAINED = "SUSTAINED"


class NoticeDetermination(str, Enum):
    ABATED_FULL = "ABATED_FULL"
    ABATED_PARTIAL = "ABATED_PARTIAL"
    SUSTAINED = "SUSTAINED"


class EvidenceType(str, Enum):
    MEC_OFFER_PROOF = "MEC_OFFER_PROOF"
    FT_STATUS_DISPUTE = "FT_STATUS_DISPUTE"
    OFFER_PROOF = "OFFER_PROOF"


# ---------------------------------------------------------------------------
# Mutable resource families: id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class FilingSeason(TypedDict):
    id: str
    tax_year: int
    status: str
    furnishing_deadline_date: str
    filing_deadline_date: str
    tier2_cutoff_date: str
    affordability_pct: float
    mainland_fpl_annual_cents: int
    penalty_a_annual_cents: int
    penalty_b_annual_cents: int
    electronic_filing_threshold: int
    open_correction_count: int
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ControlledGroup(TypedDict):
    id: str
    filing_season_id: str
    name: str
    determination_state: str
    determination_basis: Optional[str]
    single_member_id: Optional[str]
    monthly_group_fte: List[int]
    annual_average_fte_raw: Optional[float]
    annual_average_fte: Optional[int]
    ale_reason: Optional[str]
    seasonal_exception_applied: bool
    open_correction_count: int
    determined_at: Optional[str]
    last_determination_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GroupMember(TypedDict):
    id: str
    controlled_group_id: str
    ein: str
    legal_name: str
    ownership_pct: float
    measurement_method: str
    member_status: str
    generated_form_count: int
    unattached_form_count: int
    attached_form_count: int
    reporting_year_ft_months: int
    allocated_exclusion_employees: int
    allocated_penalty_cents: int
    furnishing_penalty_total_cents: int
    open_transmittal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    group_member_id: str
    full_name: str
    ssn_last4: str
    hire_date: str
    employment_type: str
    employment_status: str
    termination_date: Optional[str]
    open_leave_type: Optional[str]
    is_hourly: bool
    hourly_rate_cents: Optional[int]
    monthly_salary_cents: Optional[int]
    w2_box1_wages_cents: int
    measurement_method_override: Optional[str]
    effective_measurement_method: str
    full_time_months: List[int]
    full_time_month_count: int
    ft_source_by_month: List[str]
    measured_average_hours: Optional[float]
    last_recomputed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FurnishingConsent(TypedDict):
    id: str
    employee_id: str
    electronic_address: str
    consent_status: str
    grant_count: int
    granted_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Form1095C(TypedDict):
    id: str
    employee_id: str
    form_type: str
    corrected_from_form_id: Optional[str]
    plan_start_month: int
    safe_harbor_preference: str
    furnishing_status: str
    filing_status: str
    transmittal_id: Optional[str]
    all_12_months_code: Optional[str]
    ft_month_count: int
    offered_month_count: int
    assessable_month_count: int
    line15_total_cents: int
    late_furnishing_penalty_cents: int
    generated_by_user_id: str
    furnished_by_user_id: Optional[str]
    furnished_at: Optional[str]
    correction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transmittal(TypedDict):
    id: str
    group_member_id: str
    transmission_type: str
    authoritative_indicator: bool
    status: str
    cycle_number: int
    form_count: int
    aggregate_return_count: int
    required_channel: str
    monthly_ft_counts: List[int]
    channel: Optional[str]
    receipt_id: Optional[str]
    error_count: int
    open_error_count: int
    built_by_user_id: Optional[str]
    built_at: Optional[str]
    transmitted_by_user_id: Optional[str]
    transmitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransmittalError(TypedDict):
    id: str
    transmittal_id: str
    form_1095c_id: Optional[str]
    error_code: str
    error_field: str
    severity: str
    resolution_status: str
    resolution_note: Optional[str]
    corrected_form_id: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PenaltyNotice(TypedDict):
    id: str
    controlled_group_id: str
    notice_number: str
    notice_date: str
    response_due_date: str
    proposed_amount_cents: int
    asserted_a_months: List[int]
    asserted_b_employee_months: List[dict]
    status: str
    evidence_count: int
    applied_evidence_count: int
    a_month_penalty_cents: Optional[int]
    b_month_penalty_cents: Optional[int]
    recalculated_amount_cents: Optional[int]
    allocated_total_cents: int
    unallocated_amount_cents: int
    abated_amount_cents: Optional[int]
    determination: Optional[str]
    recomputed_at: Optional[str]
    last_evidence_user_id: Optional[str]
    response_submitted_by_user_id: Optional[str]
    response_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledger families: id + created_at ONLY
# ---------------------------------------------------------------------------
class MonthlyHeadcount(TypedDict):
    id: str
    group_member_id: str
    count_year: str
    month: int
    full_time_employee_count: int
    part_time_hours_total: int
    total_employee_count: int
    seasonal_excess_count: int
    member_fte: float
    created_at: str


class MeasurementCycle(TypedDict):
    id: str
    group_member_id: str
    employee_id: Optional[str]
    cycle_type: str
    measurement_start_date: str
    measurement_end_date: str
    admin_period_end_date: str
    stability_start_date: str
    stability_end_date: str
    hours_threshold_monthly: int
    created_at: str


class HoursRecord(TypedDict):
    id: str
    employee_id: str
    measurement_year: int
    month: int
    hours_of_service: int
    paid_leave_hours: int
    special_unpaid_leave_hours: int
    counted_hours: int
    excluded_from_denominator: bool
    created_at: str


class EmploymentEvent(TypedDict):
    id: str
    employee_id: str
    event_type: str
    effective_date: str
    leave_type: Optional[str]
    to_group_member_id: Optional[str]
    note: Optional[str]
    resulting_status: str
    recorded_by_user_id: str
    created_at: str


class CoverageOffer(TypedDict):
    id: str
    employee_id: str
    offer_kind: str
    minimum_value: bool
    lowest_cost_self_only_cents: int
    effective_start_date: str
    effective_end_date: str
    covered_months: List[int]
    offers_spouse: bool
    offers_dependents: bool
    conditional_spouse_offer: bool
    enrolled: bool
    created_at: str


class MonthlyCoverageLine(TypedDict):
    id: str
    form_1095c_id: str
    month: int
    line14_code: str
    line15_amount_cents: Optional[int]
    line16_code: Optional[str]
    full_time_flag: bool
    ft_source: str
    special_situation: str
    safe_harbor_applied: Optional[str]
    affordability_threshold_cents: Optional[int]
    assessable: bool
    created_at: str


class PenaltyEvidence(TypedDict):
    id: str
    penalty_notice_id: str
    evidence_type: str
    month: int
    employee_id: Optional[str]
    document_ref: str
    asserted_line14_code: Optional[str]
    asserted_line16_code: Optional[str]
    applied: bool
    filed_by_user_id: str
    created_at: str


MUTABLE_FAMILIES = (
    "filing_seasons",
    "controlled_groups",
    "group_members",
    "employees",
    "furnishing_consents",
    "forms_1095c",
    "transmittals",
    "transmittal_errors",
    "penalty_notices",
)

APPEND_ONLY_FAMILIES = (
    "monthly_headcounts",
    "measurement_cycles",
    "hours_records",
    "employment_events",
    "coverage_offers",
    "monthly_coverage_lines",
    "penalty_evidence",
)
