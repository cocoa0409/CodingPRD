"""Domain types for the WOC Consult Service API: status enums and entity shapes.

Every name here is taken verbatim from the PRD's field and enum vocabulary.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """PRD §2.1 — the five role names, spelled exactly this way."""

    WOC_NURSE = "WocNurse"
    UNIT_CHARGE = "UnitCharge"
    WOC_PROGRAM_DIRECTOR = "WocProgramDirector"
    MATERIALS_COORDINATOR = "MaterialsCoordinator"
    SYSTEM_OPERATOR = "SystemOperator"


class SurveyPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PatientStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class CertificationStatus(str, Enum):
    TRAINEE = "TRAINEE"
    CANDIDATE = "CANDIDATE"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"


class ConsultStatus(str, Enum):
    REQUESTED = "REQUESTED"
    TRIAGED = "TRIAGED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    ASSIGNED = "ASSIGNED"
    ASSESSED = "ASSESSED"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ConsultType(str, Enum):
    WOUND = "WOUND"
    OSTOMY = "OSTOMY"
    INCONTINENCE = "INCONTINENCE"


class ReportedStage(str, Enum):
    NONE = "NONE"
    MUCOSAL = "MUCOSAL"
    STAGE_1 = "STAGE_1"
    STAGE_2 = "STAGE_2"
    STAGE_3 = "STAGE_3"
    STAGE_4 = "STAGE_4"
    DTI = "DTI"
    UNSTAGEABLE = "UNSTAGEABLE"


class ObservedStage(str, Enum):
    MUCOSAL = "MUCOSAL"
    STAGE_1 = "STAGE_1"
    STAGE_2 = "STAGE_2"
    STAGE_3 = "STAGE_3"
    STAGE_4 = "STAGE_4"
    DTI = "DTI"
    UNSTAGEABLE = "UNSTAGEABLE"


class AcuityVariant(str, Enum):
    INTAKE_PROVISIONAL = "INTAKE_PROVISIONAL"
    ASSESSED_FINAL = "ASSESSED_FINAL"


class PriorityBand(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AnatomicLocation(str, Enum):
    SACRUM = "SACRUM"
    HEEL_LEFT = "HEEL_LEFT"
    HEEL_RIGHT = "HEEL_RIGHT"
    ISCHIUM = "ISCHIUM"
    TROCHANTER = "TROCHANTER"
    OTHER = "OTHER"


class ValidationStatus(str, Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    VALIDATED = "VALIDATED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class PoaDetermination(str, Enum):
    POA = "POA"
    HAPI = "HAPI"
    INDETERMINATE = "INDETERMINATE"


class CaseClassification(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    POA = "POA"
    HAPI = "HAPI"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    CLASSIFIED_POA = "CLASSIFIED_POA"
    CLASSIFIED_HAPI = "CLASSIFIED_HAPI"
    RCA_REQUIRED = "RCA_REQUIRED"
    RCA_IN_PROGRESS = "RCA_IN_PROGRESS"
    RCA_COMPLETE = "RCA_COMPLETE"
    CLOSED = "CLOSED"
    RECLASSIFIED = "RECLASSIFIED"


class RootCauseCategory(str, Enum):
    REPOSITIONING = "REPOSITIONING"
    SUPPORT_SURFACE = "SUPPORT_SURFACE"
    NUTRITION = "NUTRITION"
    DEVICE = "DEVICE"
    MOISTURE = "MOISTURE"
    DOCUMENTATION = "DOCUMENTATION"


class RoundType(str, Enum):
    PREVALENCE = "PREVALENCE"
    INCIDENCE = "INCIDENCE"


class SurveyRoundStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class ObservationClassification(str, Enum):
    NONE = "NONE"
    POA = "POA"
    HAPI = "HAPI"


class SurfaceClass(str, Enum):
    FOAM_OVERLAY = "FOAM_OVERLAY"
    ALTERNATING_PRESSURE = "ALTERNATING_PRESSURE"
    LOW_AIR_LOSS = "LOW_AIR_LOSS"
    BARIATRIC_BED = "BARIATRIC_BED"


class SurfaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    CLEANING = "CLEANING"
    RETIRED = "RETIRED"


class FulfillmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    DENIED = "DENIED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ENCUMBERED = "ENCUMBERED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    RECONCILED = "RECONCILED"


class ProductCategory(str, Enum):
    FOAM = "FOAM"
    HYDROCOLLOID = "HYDROCOLLOID"
    ALGINATE = "ALGINATE"
    SILVER_ANTIMICROBIAL = "SILVER_ANTIMICROBIAL"
    OSTOMY_BARRIER = "OSTOMY_BARRIER"
    SKIN_PROTECTANT = "SKIN_PROTECTANT"


class FormularyTier(str, Enum):
    PREFERRED = "PREFERRED"
    RESTRICTED = "RESTRICTED"
    NON_FORMULARY = "NON_FORMULARY"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProtocolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TEACH_BACK_PASSED = "TEACH_BACK_PASSED"
    SUPPLIES_TRANSITIONED = "SUPPLIES_TRANSITIONED"
    FOLLOWUP_SCHEDULED = "FOLLOWUP_SCHEDULED"
    CLOSED_INCOMPLETE = "CLOSED_INCOMPLETE"


class SupplyTransitionStatus(str, Enum):
    PENDING = "PENDING"
    TRANSITIONED = "TRANSITIONED"


# --- Entity shapes -----------------------------------------------------------
# Resources carrying id + created_at + updated_at + version.


class Unit(TypedDict):
    id: str
    unit_code: str
    name: str
    bed_count: int
    rental_budget_cap_cents: int
    rental_encumbered_cents: int
    rental_committed_cents: int
    rental_released_cents: int
    rental_available_cents: int
    open_hapi_rca_count: int
    disputed_staging_count: int
    survey_posture: str
    last_prevalence_rate: Optional[float]
    last_incidence_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    unit_id: str
    admitted_at: str
    discharged_at: Optional[str]
    status: str
    comorbidity_count: int
    device_related_risk: bool
    ostomy_present: bool
    poa_skin_assessment_documented: bool
    pending_outpatient_followup_count: int
    created_at: str
    updated_at: str
    version: int


class WocNurse(TypedDict):
    id: str
    full_name: str
    home_unit_id: str
    certification_status: str
    ce_credits: int
    competency_signoff_count: int
    last_competency_signoff_at: Optional[str]
    mentored_consult_count: int
    certification_eligibility_score: Optional[float]
    cert_expires_at: Optional[str]
    active_consult_load: int
    max_consult_load: int
    created_at: str
    updated_at: str
    version: int


class ConsultRequest(TypedDict):
    id: str
    patient_id: str
    requesting_unit_id: str
    assigned_nurse_id: Optional[str]
    consult_type: str
    reported_stage: str
    clinical_note: str
    status: str
    acuity_score: Optional[float]
    acuity_variant: Optional[str]
    priority_band: Optional[str]
    sla_due_at: Optional[str]
    revision_count: int
    protocol_hold: bool
    triaged_at: Optional[str]
    escalation_count: int
    closing_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SkinAssessment(TypedDict):
    id: str
    consult_request_id: str
    patient_id: str
    staged_by_nurse_id: str
    anatomic_location: str
    observed_stage: str
    measured_area_cm2: float
    observed_at: str
    present_on_admission_claimed: bool
    poa_determination: Optional[str]
    validation_status: str
    confirmed_stage: Optional[str]
    validated_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    restage_count: int
    created_at: str
    updated_at: str
    version: int


class PressureInjuryCase(TypedDict):
    id: str
    patient_id: str
    unit_id: str
    skin_assessment_id: str
    predecessor_case_id: Optional[str]
    classification: str
    status: str
    rca_lead_nurse_id: Optional[str]
    rca_due_at: Optional[str]
    root_cause_category: Optional[str]
    contributing_factors: List[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyRound(TypedDict):
    id: str
    round_type: str
    window_start: str
    window_end: str
    participating_unit_ids: List[str]
    status: str
    observation_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyObservation(TypedDict):
    """PRD §2.4 — the immutable audit record: only id and created_at.

    It has neither updated_at nor version, and no operation mutates one after
    it is filed.
    """

    id: str
    survey_round_id: str
    unit_id: str
    patient_id: str
    observer_nurse_id: str
    observed_at: str
    injury_present: bool
    observed_stage: Optional[str]
    classification: str
    onset_at: Optional[str]
    at_risk: bool
    created_at: str


class SupportSurface(TypedDict):
    id: str
    asset_tag: str
    surface_class: str
    daily_rate_cents: int
    vendor_name: str
    status: str
    occupied_until: Optional[str]
    available_from: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportSurfaceOrder(TypedDict):
    id: str
    patient_id: str
    unit_id: str
    support_surface_id: str
    consult_request_id: Optional[str]
    rental_start: str
    rental_end: str
    authorized_days: int
    billable_days: int
    projected_cost_cents: int
    vendor_service_fee_cents: int
    authorized_cost_cents: int
    actual_return_at: Optional[str]
    actual_cost_cents: Optional[int]
    fulfillment_status: str
    billing_status: str
    requires_director_override: bool
    posture_hold_applied_at: Optional[str]
    delivered_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormularyProduct(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_cost_cents: int
    formulary_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DressingProtocol(TypedDict):
    id: str
    consult_request_id: str
    formulary_product_id: str
    change_frequency_hours: int
    units_per_change: int
    justification: Optional[str]
    changes_per_week: int
    weekly_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OstomyEducationPlan(TypedDict):
    id: str
    consult_request_id: str
    patient_id: str
    sessions_completed: int
    teach_back_score: Optional[int]
    supply_transition_status: str
    followup_appointment_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
