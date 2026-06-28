"""Domain types: entity TypedDicts, status enums, role enum.

Reflects the Remote Patient Monitoring API contract. Per the PRD (§2.4), most
resources carry id/created_at/updated_at/version; ConsentRecord and VitalsReading
are append-style records carrying ONLY id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles (§2.1 — five roles, opaque identity)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CARE_COORDINATOR = "CareCoordinator"
    CLINICIAN = "Clinician"
    PHYSICIAN = "Physician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PAYER_AGENT = "PayerAgent"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PayerType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    COMMERCIAL = "COMMERCIAL"


class EnrollmentStatus(str, Enum):
    PENDING_CONSENT = "PENDING_CONSENT"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    DISCHARGED = "DISCHARGED"


class MonitoringStatus(str, Enum):
    INACTIVE = "INACTIVE"
    MONITORING = "MONITORING"
    PAUSED = "PAUSED"


class ConsentType(str, Enum):
    RPM = "RPM"
    CCM = "CCM"
    BOTH = "BOTH"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVISED = "REVISED"
    RETIRED = "RETIRED"


class DeviceType(str, Enum):
    BP_CUFF = "BP_CUFF"
    GLUCOMETER = "GLUCOMETER"
    PULSE_OX = "PULSE_OX"
    WEIGHT_SCALE = "WEIGHT_SCALE"


class DeviceStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"


class AlertSeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ReviewTaskPriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class ReviewTaskStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_REVIEW = "IN_REVIEW"
    SIGNED = "SIGNED"
    ESCALATED = "ESCALATED"


class CareActivityType(str, Enum):
    REVIEW = "REVIEW"
    OUTREACH = "OUTREACH"
    CARE_COORDINATION = "CARE_COORDINATION"
    EDUCATION = "EDUCATION"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    CLAIMED = "CLAIMED"
    REOPENED = "REOPENED"


class CptCode(str, Enum):
    CPT_99453 = "CPT_99453"
    CPT_99454 = "CPT_99454"
    CPT_99457 = "CPT_99457"


class LineItemStatus(str, Enum):
    ACCRUED = "ACCRUED"
    VOIDED = "VOIDED"
    FINALIZED = "FINALIZED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class Payer(TypedDict):
    id: str
    name: str
    payer_type: str
    rate_99453_cents: int
    rate_99454_cents: int
    rate_99457_cents: int
    requires_active_consent: bool
    timely_filing_days: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    payer_id: str
    mrn: str
    full_name: str
    enrollment_status: str
    monitoring_status: str
    care_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, ONLY id + created_at
class ConsentRecord(TypedDict):
    id: str
    patient_id: str
    consent_type: str
    effective_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str


class CarePlan(TypedDict):
    id: str
    patient_id: str
    diagnosis_code: str
    goal_text: str
    required_care_minutes: int
    status: str
    superseded_by_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    patient_id: str
    device_type: str
    serial_number: str
    status: str
    activated_at: Optional[str]
    setup_billed: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, ONLY id + created_at
class VitalsReading(TypedDict):
    id: str
    patient_id: str
    device_id: str
    reading_value: float
    secondary_value: Optional[float]
    measured_at: str
    service_date: str
    breach_flag: bool
    created_at: str


class ThresholdAlert(TypedDict):
    id: str
    patient_id: str
    vitals_reading_id: str
    severity: str
    status: str
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewTask(TypedDict):
    id: str
    patient_id: str
    threshold_alert_id: str
    escalated_from_task_id: Optional[str]
    priority: str
    status: str
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CareActivity(TypedDict):
    id: str
    patient_id: str
    billing_period_id: str
    clinician_user_id: str
    activity_type: str
    minutes: int
    performed_at: str
    counted_minutes: int
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    patient_id: str
    period_year: int
    period_month: int
    status: str
    provisional_total_minutes: int
    distinct_device_days: int
    finalized_total_minutes: Optional[int]
    finalized_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BillingLineItem(TypedDict):
    id: str
    billing_period_id: str
    cpt_code: str
    units: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    billing_period_id: str
    payer_id: str
    claimed_cents: int
    reimbursed_cents: int
    status: str
    expected_billing_period_version: int
    created_at: str
    updated_at: str
    version: int
