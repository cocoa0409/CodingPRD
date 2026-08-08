"""Domain types for the Concierge Pediatrics & Newborn Care API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    PHYSICIAN = "Physician"
    CARE_COORDINATOR = "CareCoordinator"
    BILLING_SPECIALIST = "BillingSpecialist"
    PARENT = "Parent"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class PlanTier(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class MembershipStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class BenefitType(str, Enum):
    LACTATION_CONSULT = "LACTATION_CONSULT"
    SLEEP_CONSULT = "SLEEP_CONSULT"


class GrantStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class CoverageRoute(str, Enum):
    ENTITLEMENT = "ENTITLEMENT"
    OVERAGE = "OVERAGE"


class Modality(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEHEALTH = "TELEHEALTH"


class ConsultBookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MilestoneCode(str, Enum):
    NEWBORN = "NEWBORN"
    M1 = "M1"
    M2 = "M2"
    M4 = "M4"
    M6 = "M6"
    M9 = "M9"
    M12 = "M12"
    M24 = "M24"
    M36 = "M36"
    M48 = "M48"
    M60 = "M60"


class WellVisitStatus(str, Enum):
    DUE = "DUE"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class Punctuality(str, Enum):
    EARLY = "EARLY"
    ON_SCHEDULE = "ON_SCHEDULE"
    DELAYED = "DELAYED"


class VaccineCode(str, Enum):
    HEPB = "HEPB"
    DTAP = "DTAP"


class DoseValidity(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class InvalidReason(str, Enum):
    MIN_AGE_NOT_MET = "MIN_AGE_NOT_MET"
    MIN_INTERVAL_NOT_MET = "MIN_INTERVAL_NOT_MET"
    SERIES_ALREADY_COMPLETE = "SERIES_ALREADY_COMPLETE"
    MANUALLY_INVALIDATED = "MANUALLY_INVALIDATED"


class EncounterType(str, Enum):
    SICK_VISIT = "SICK_VISIT"
    AFTER_HOURS_CONTACT = "AFTER_HOURS_CONTACT"
    ROUTINE_QUESTION = "ROUTINE_QUESTION"
    NEWBORN_WEIGHT_CHECK = "NEWBORN_WEIGHT_CHECK"


class AfterHoursReason(str, Enum):
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"
    WEEKDAY_EVENING = "WEEKDAY_EVENING"
    WEEKDAY_EARLY_MORNING = "WEEKDAY_EARLY_MORNING"


class ClinicalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLINICALLY_COMPLETE = "CLINICALLY_COMPLETE"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    BILLING_PENDING = "BILLING_PENDING"
    BILLING_ROUTED = "BILLING_ROUTED"
    BILLING_CLOSED = "BILLING_CLOSED"
    BILLING_VOID = "BILLING_VOID"


class ServiceCode(str, Enum):
    WELL_VISIT = "WELL_VISIT"
    SICK_VISIT = "SICK_VISIT"
    TELEHEALTH_VISIT = "TELEHEALTH_VISIT"
    AFTER_HOURS_SURCHARGE = "AFTER_HOURS_SURCHARGE"
    LACTATION_CONSULT = "LACTATION_CONSULT"
    SLEEP_CONSULT = "SLEEP_CONSULT"


class ServiceRoute(str, Enum):
    COVERED_BY_MEMBERSHIP = "COVERED_BY_MEMBERSHIP"
    BILLED_TO_INSURANCE = "BILLED_TO_INSURANCE"
    PATIENT_RESPONSIBILITY = "PATIENT_RESPONSIBILITY"


class ServiceLineStatus(str, Enum):
    ROUTED = "ROUTED"
    ADJUDICATED = "ADJUDICATED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"


class FormType(str, Enum):
    SCHOOL = "SCHOOL"
    CAMP = "CAMP"
    SPORTS = "SPORTS"


class FormRequestStatus(str, Enum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    ISSUED = "ISSUED"


class BlockedReason(str, Enum):
    MEMBERSHIP_NOT_ACTIVE = "MEMBERSHIP_NOT_ACTIVE"
    IMMUNIZATION_INCOMPLETE = "IMMUNIZATION_INCOMPLETE"
    WELL_VISIT_STALE = "WELL_VISIT_STALE"


# --------------------------------------------------------------------------
# Entity shapes.  Every resource in this API carries id, created_at,
# updated_at and version (PRD §2.5).
# --------------------------------------------------------------------------
class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_rate_cents: int
    included_lactation_consults: int
    included_sleep_consults: int
    form_sla_hours: int
    after_hours_surcharge_waived: bool
    overage_consult_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict):
    id: str
    full_name: str
    panel_slot_cap: float
    licensed_state_codes: List[str]
    weighted_occupancy: float
    available_panel_weight: float
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    household_name: str
    family_monthly_cap_cents: int
    active_membership_count: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    family_id: str
    carrier_name: str
    deductible_cents: int
    deductible_met_cents: int
    coinsurance_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    family_id: str
    first_name: str
    date_of_birth: str
    age_days: int
    current_slot_weight: float
    immunization_complete_for_age: bool
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    child_id: str
    family_id: str
    plan_id: str
    physician_id: str
    start_date: str
    cancellation_effective_date: Optional[str]
    status: str
    enrollment_sequence: int
    discount_pct: float
    monthly_rate_cents: int
    slot_weight: float
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PanelWaitlistEntry(TypedDict):
    id: str
    physician_id: str
    child_id: str
    requested_plan_id: str
    promoted_membership_id: Optional[str]
    candidate_slot_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EntitlementGrant(TypedDict):
    id: str
    membership_id: str
    benefit_type: str
    membership_year_index: int
    granted_count: int
    booked_count: int
    consumed_count: int
    released_count: int
    overage_count: int
    available_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsultBooking(TypedDict):
    id: str
    membership_id: str
    grant_id: str
    consultant_physician_id: str
    consult_type: str
    scheduled_start: str
    scheduled_end: str
    modality: str
    patient_state_code: str
    coverage_route: str
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WellVisit(TypedDict):
    id: str
    membership_id: str
    child_id: str
    milestone_code: str
    target_date: str
    window_open_date: str
    window_close_date: str
    scheduled_date: Optional[str]
    completed_date: Optional[str]
    punctuality: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImmunizationDose(TypedDict):
    id: str
    child_id: str
    prior_valid_dose_id: Optional[str]
    vaccine_code: str
    administered_date: str
    age_days_at_administration: int
    effective_series_index: int
    interval_days_since_prior: Optional[int]
    manually_invalidated: bool
    invalidation_reason_note: Optional[str]
    invalid_reason: Optional[str]
    validity: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    membership_id: str
    child_id: str
    encounter_type: str
    modality: str
    patient_state_code: str
    started_at: str
    ends_at: str
    after_hours: bool
    after_hours_reason: Optional[str]
    surcharge_cents: int
    clinical_status: str
    billing_status: str
    clinical_note: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict):
    id: str
    membership_id: str
    encounter_id: Optional[str]
    consult_booking_id: Optional[str]
    well_visit_id: Optional[str]
    policy_id: Optional[str]
    service_code: str
    route: str
    billed_amount_cents: int
    allowed_amount_cents: Optional[int]
    write_off_cents: int
    deductible_applied_cents: int
    coinsurance_cents: int
    plan_paid_cents: int
    patient_responsibility_cents: int
    membership_covered_cents: int
    payment_received_cents: int
    submitted_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    membership_id: str
    child_id: str
    enrollment_sequence: int
    base_rate_cents: int
    discount_pct: float
    monthly_rate_cents: int
    covered_days: int
    prorated_cents: int
    cap_adjustment_cents: int
    line_total_cents: int


class Invoice(TypedDict):
    id: str
    family_id: str
    cycle_start_date: str
    cycle_end_date: str
    days_in_cycle: int
    lines: List[Dict[str, Any]]
    subtotal_cents: int
    cap_adjustment_cents: int
    total_cents: int
    issued_date: Optional[str]
    due_date: Optional[str]
    paid_date: Optional[str]
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FormRequest(TypedDict):
    id: str
    membership_id: str
    child_id: str
    form_type: str
    needed_by_date: str
    requested_at: str
    due_at: str
    issued_at: Optional[str]
    sla_met: Optional[bool]
    blocked_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
