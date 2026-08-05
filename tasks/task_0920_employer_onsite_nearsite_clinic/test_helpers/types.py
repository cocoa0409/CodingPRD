"""Domain types: status enums, role enum and entity TypedDicts.

Every persisted resource in this API carries id, created_at, updated_at and
version (PRD 2.4), so every entity TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------- roles ----
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CLINIC_MANAGER = "ClinicManager"
    CLINICIAN = "Clinician"
    CARE_NAVIGATOR = "CareNavigator"
    EMPLOYER_BENEFITS_ADMIN = "EmployerBenefitsAdmin"
    PARTICIPANT = "Participant"
    PAYROLL_PROCESSOR = "PayrollProcessor"


# ------------------------------------------------------------- statuses ----
class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SiteType(str, Enum):
    ON_SITE = "ON_SITE"
    NEAR_SITE = "NEAR_SITE"


class FeeModel(str, Enum):
    PER_VISIT = "PER_VISIT"
    FTE_HOUR = "FTE_HOUR"


class VendorContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRUED_UP = "TRUED_UP"


class ProviderFunction(str, Enum):
    CLINICIAN = "CLINICIAN"
    NAVIGATOR = "NAVIGATOR"


class CredentialStatus(str, Enum):
    CREDENTIALED = "CREDENTIALED"
    LAPSED = "LAPSED"
    DEACTIVATED = "DEACTIVATED"


class CoverageRole(str, Enum):
    PRIMARY_CARE = "PRIMARY_CARE"
    OCC_HEALTH = "OCC_HEALTH"
    WELLNESS = "WELLNESS"
    NAVIGATION = "NAVIGATION"


class EligibilityTier(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    SPOUSE = "SPOUSE"
    DEPENDENT = "DEPENDENT"
    RETIREE = "RETIREE"


class CoverageStatus(str, Enum):
    FUTURE = "FUTURE"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class AuthorizationStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    WITHDRAWN = "WITHDRAWN"


class AuthorizationDecision(str, Enum):
    GRANT = "GRANT"
    REVOKE = "REVOKE"


class VisitType(str, Enum):
    PRIMARY_CARE = "PRIMARY_CARE"
    OCC_HEALTH = "OCC_HEALTH"
    WELLNESS = "WELLNESS"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    CONSUMED = "CONSUMED"


class CancellationReason(str, Enum):
    PARTICIPANT_REQUEST = "PARTICIPANT_REQUEST"
    CLINIC_REQUEST = "CLINIC_REQUEST"
    NO_SHOW = "NO_SHOW"
    ENROLLMENT_TERMINATED = "ENROLLMENT_TERMINATED"


class EncounterStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    AMENDED = "AMENDED"
    LOCKED = "LOCKED"


class DisclosureStatus(str, Enum):
    WALLED = "WALLED"
    RELEASE_PENDING = "RELEASE_PENDING"
    FITNESS_RELEASED = "FITNESS_RELEASED"
    PARTICIPATION_RELEASED = "PARTICIPATION_RELEASED"
    NOT_DISCLOSABLE = "NOT_DISCLOSABLE"
    SUPPRESSED = "SUPPRESSED"


class FitnessConclusion(str, Enum):
    FIT_FOR_DUTY = "FIT_FOR_DUTY"
    FIT_WITH_RESTRICTIONS = "FIT_WITH_RESTRICTIONS"
    NOT_FIT = "NOT_FIT"


class ChargeableParty(str, Enum):
    HEALTH_PLAN = "HEALTH_PLAN"
    EMPLOYER_DIRECT = "EMPLOYER_DIRECT"
    WELLNESS_BUDGET = "WELLNESS_BUDGET"


class AssessmentSourceType(str, Enum):
    CLINIC_MEASURED = "CLINIC_MEASURED"
    SELF_ATTESTED = "SELF_ATTESTED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class OutcomeCreditStatus(str, Enum):
    MET_DIRECT = "MET_DIRECT"
    PENDING_ALTERNATIVE = "PENDING_ALTERNATIVE"
    CREDITED_VIA_RAS = "CREDITED_VIA_RAS"


class SteerageTier(str, Enum):
    CENTER_OF_EXCELLENCE = "CENTER_OF_EXCELLENCE"
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ReferralUrgency(str, Enum):
    EMERGENT = "EMERGENT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    REDIRECTED = "REDIRECTED"
    ESCALATED = "ESCALATED"
    CLOSED_LOOP = "CLOSED_LOOP"


class AlternativeType(str, Enum):
    COACHING_PROGRAM = "COACHING_PROGRAM"
    EDUCATION_MODULE = "EDUCATION_MODULE"
    PHYSICIAN_ALTERNATIVE = "PHYSICIAN_ALTERNATIVE"


class AlternativeStandardStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"


class AwardType(str, Enum):
    OUTCOME_BASED = "OUTCOME_BASED"
    PARTICIPATORY = "PARTICIPATORY"
    TOBACCO_CESSATION = "TOBACCO_CESSATION"


class AwardStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPORTED = "EXPORTED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    FORFEITED = "FORFEITED"


class ReportingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    RESTATING = "RESTATING"
    CLOSED = "CLOSED"


# -------------------------------------------------------------- entities ---
class Employer(TypedDict):
    id: str
    legal_name: str
    employer_code: str
    annual_total_cost_of_coverage_cents: int
    tobacco_program_enabled: bool
    wellness_budget_cents: int
    wellness_budget_committed_cents: int
    wellness_budget_remaining_cents: int
    program_cost_to_date_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    host_employer_id: Optional[str]
    site_name: str
    site_type: str
    open_time_utc: str
    close_time_utc: str
    operating_weekdays: List[int]
    closure_dates: List[str]
    daily_slot_capacity: int
    slots_held_count: int
    slots_consumed_count: int
    slots_no_show_count: int
    slots_released_count: int
    slots_requested_total: int
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict):
    id: str
    site_id: str
    employer_id: str
    vendor_name: str
    fee_model: str
    per_visit_fee_cents: int
    fte_hourly_rate_cents: int
    minimum_guarantee_cents: int
    quota_visits_total: int
    quota_visits_consumed: int
    quota_visits_released: int
    quota_visits_requested_total: int
    quota_visits_remaining: int
    billable_visit_count: int
    staffed_hours: float
    gross_fee_cents: int
    true_up_amount_cents: int
    contract_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    site_id: str
    full_name: str
    provider_function: str
    license_expiry_date: str
    credential_status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class StaffingShift(TypedDict):
    id: str
    site_id: str
    provider_id: str
    shift_start: str
    shift_end: str
    staffed_hours: float
    coverage_role: str
    created_at: str
    updated_at: str
    version: int


class EligibilityRecord(TypedDict):
    id: str
    employer_id: str
    subscriber_external_id: str
    member_external_id: str
    tier: str
    effective_date: str
    termination_date: Optional[str]
    retro_terminated: bool
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    employer_id: str
    eligibility_record_id: str
    display_name: str
    tier: str
    enrolled_on: str
    enrollment_status: str
    authorization_status: str
    termination_effective_date: Optional[str]
    authorization_revoked_at: Optional[str]
    completed_visit_count: int
    incentive_awarded_cents: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    participant_id: str
    site_id: str
    provider_id: str
    quota_contract_id: Optional[str]
    visit_type: str
    scheduled_start: str
    scheduled_end: str
    service_date: str
    status: str
    reschedule_count: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    appointment_id: str
    participant_id: str
    provider_id: str
    site_id: str
    visit_type: str
    service_date: str
    encounter_status: str
    disclosure_status: str
    fitness_conclusion: Optional[str]
    chargeable_party: Optional[str]
    consumes_benefit_entitlement: Optional[bool]
    amendment_count: int
    clinical_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthAssessment(TypedDict):
    id: str
    participant_id: str
    visit_id: Optional[str]
    source_type: str
    measurement_date: str
    systolic_mmhg: Optional[int]
    diastolic_mmhg: Optional[int]
    bmi: Optional[float]
    a1c_pct: Optional[float]
    ldl_mg_dl: Optional[int]
    cotinine_ng_ml: Optional[float]
    self_reported_tobacco: Optional[bool]
    risk_points_raw: int
    risk_points_total: int
    risk_band: str
    outcome_standard_met: bool
    outcome_credit_status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    participant_id: str
    visit_id: str
    redirected_from_referral_id: Optional[str]
    specialty: str
    steerage_tier: str
    urgency: str
    sla_due_at: str
    status: str
    raised_by_provider_id: str
    authorized_by_provider_id: Optional[str]
    escalated_at: Optional[str]
    loop_closed_at: Optional[str]
    consult_note_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlternativeStandard(TypedDict):
    id: str
    participant_id: str
    health_assessment_id: str
    requested_reason: str
    alternative_type: Optional[str]
    assigned_at: Optional[str]
    due_date: Optional[str]
    reassignment_count: int
    status: str
    credit_granted: bool
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict):
    id: str
    participant_id: str
    employer_id: str
    reporting_period_id: str
    health_assessment_id: Optional[str]
    award_type: str
    award_amount_cents: int
    retroactive: bool
    status: str
    approved_by_user_id: Optional[str]
    exported_by_user_id: Optional[str]
    payroll_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportingPeriod(TypedDict):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    status: str
    restatement_count: int
    finalized_at: Optional[str]
    incentive_awarded_cents: int
    incentive_pending_cents: int
    incentive_paid_cents: int
    incentive_reversed_cents: int
    incentive_forfeited_cents: int
    created_at: str
    updated_at: str
    version: int
