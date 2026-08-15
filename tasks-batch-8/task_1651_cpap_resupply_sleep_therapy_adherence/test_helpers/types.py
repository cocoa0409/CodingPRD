"""Domain types: entity TypedDicts, status enums, role enum.

All nine resources carry the four server-managed properties (id, created_at,
updated_at, version) described in PRD §2.4.
"""
from enum import Enum
from typing import Optional, TypedDict


class PatientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE_THERAPY = "ACTIVE_THERAPY"
    NON_COMPLIANT_HOLD = "NON_COMPLIANT_HOLD"
    DISCONTINUING = "DISCONTINUING"
    DISCONTINUED = "DISCONTINUED"


class EnrollmentStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    SETUP_IN_PROGRESS = "SETUP_IN_PROGRESS"
    ACTIVE = "ACTIVE"
    RETRIEVAL_PENDING = "RETRIEVAL_PENDING"
    RETRIEVED = "RETRIEVED"
    RETURNED_TO_PAYER = "RETURNED_TO_PAYER"
    DECOMMISSIONED = "DECOMMISSIONED"


class AcquisitionType(str, Enum):
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class ComponentType(str, Enum):
    MASK = "MASK"
    CUSHION = "CUSHION"
    FILTER = "FILTER"
    TUBING = "TUBING"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_NON_COMPLIANCE = "SUSPENDED_NON_COMPLIANCE"
    SUSPENDED_DISCONTINUATION = "SUSPENDED_DISCONTINUATION"
    CLOSED = "CLOSED"


class AuthStatus(str, Enum):
    PENDING_CLINICAL_CLEARANCE = "PENDING_CLINICAL_CLEARANCE"
    PENDING_PAYER_AUTH = "PENDING_PAYER_AUTH"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    RETURNED = "RETURNED"


class ReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class ExchangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ExchangeReason(str, Enum):
    FIT_LEAK = "FIT_LEAK"
    SKIN_IRRITATION = "SKIN_IRRITATION"
    WRONG_SIZE = "WRONG_SIZE"
    PRESSURE_INTOLERANCE = "PRESSURE_INTOLERANCE"


class BillingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BILLING = "BILLING"
    PAUSED_NON_COMPLIANCE = "PAUSED_NON_COMPLIANCE"
    CONVERTED_TO_OWNERSHIP = "CONVERTED_TO_OWNERSHIP"
    TERMINATED = "TERMINATED"


class EquipmentStatus(str, Enum):
    WITH_PATIENT = "WITH_PATIENT"
    RETRIEVAL_REQUESTED = "RETRIEVAL_REQUESTED"
    RETRIEVED = "RETRIEVED"
    OWNERSHIP_TRANSFERRED = "OWNERSHIP_TRANSFERRED"


class RetrievalStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    CLOSED_UNRECOVERABLE = "CLOSED_UNRECOVERABLE"


class RetrievalReason(str, Enum):
    THERAPY_DISCONTINUED = "THERAPY_DISCONTINUED"
    PROLONGED_NON_COMPLIANCE = "PROLONGED_NON_COMPLIANCE"
    PAYER_STOPPED_COVERAGE = "PAYER_STOPPED_COVERAGE"
    PATIENT_REQUEST = "PATIENT_REQUEST"


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    RESPIRATORY_THERAPIST = "RespiratoryTherapist"
    BILLING_SPECIALIST = "BillingSpecialist"


class PayerPolicy(TypedDict, total=False):
    id: str
    payer_name: str
    plan_code: str
    compliance_threshold_pct: int
    compliance_min_hours_per_night: float
    compliance_window_days: int
    compliance_min_nights: int
    rental_months_to_own: int
    mask_cadence_days: int
    cushion_cadence_days: int
    filter_cadence_days: int
    tubing_cadence_days: int
    mask_exchange_window_days: int
    max_exchanges_per_window: int
    requires_prior_auth: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    payer_policy_id: str
    prescribing_clinician_npi: str
    patient_status: str
    therapy_started_on: Optional[str]
    adherence_percentage: Optional[float]
    is_compliance_current: bool
    outstanding_balance_cents: int
    current_device_enrollment_id: Optional[str]
    current_rental_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceEnrollment(TypedDict, total=False):
    id: str
    patient_id: str
    device_serial: str
    device_model: str
    acquisition_type: str
    enrollment_status: str
    setup_completed_on: Optional[str]
    last_adherence_download_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentSupplyPlan(TypedDict, total=False):
    id: str
    patient_id: str
    component_type: str
    quantity_per_cycle: int
    last_dispensed_on: Optional[str]
    next_eligible_on: Optional[str]
    reminder_sent_on: Optional[str]
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class ResupplyOrder(TypedDict, total=False):
    id: str
    patient_id: str
    component_supply_plan_id: str
    expected_patient_version: int
    auth_status: str
    fulfillment_status: str
    requested_quantity: int
    unit_allowable_cents: Optional[int]
    patient_responsibility_cents: Optional[int]
    clinical_cleared_by_user_id: Optional[str]
    authorized_by_user_id: Optional[str]
    shipped_on: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdherenceReport(TypedDict, total=False):
    id: str
    patient_id: str
    device_enrollment_id: str
    window_end_on: str
    window_start_on: str
    nights_reported: int
    compliant_nights: int
    adherence_pct_provisional: float
    adherence_pct_final: Optional[float]
    report_status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaskExchange(TypedDict, total=False):
    id: str
    patient_id: str
    device_enrollment_id: str
    original_mask_plan_id: str
    superseded_by_exchange_id: Optional[str]
    reason_code: str
    exchange_status: str
    window_anchor_on: str
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalContract(TypedDict, total=False):
    id: str
    patient_id: str
    device_enrollment_id: str
    payer_policy_id: str
    rental_start_on: str
    rental_months_billed: int
    monthly_rental_cents: int
    billing_status: str
    equipment_status: str
    conversion_eligible_on: str
    created_at: str
    updated_at: str
    version: int


class RetrievalCase(TypedDict, total=False):
    id: str
    patient_id: str
    device_enrollment_id: str
    rental_contract_id: Optional[str]
    reason_code: str
    retrieval_status: str
    due_on: str
    received_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
