"""Domain types: entity TypedDicts, status enums, role enum.

Reflects the Prosthetics & Orthotics Practice API contract. Most resources carry the
common system fields (id, created_at, updated_at, version); ComplianceCheck and ClockState
are append-only audit records that carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PHYSICIAN = "Physician"
    PRACTITIONER = "Practitioner"
    BILLING_SPECIALIST = "BillingSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status enums ─────────────────────────────────────────────────────
class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class DeviceOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    AUTH_PENDING = "AUTH_PENDING"
    FABRICATION = "FABRICATION"
    READY_FOR_FITTING = "READY_FOR_FITTING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PriorAuthStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AdjudicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"


class AppealStatus(str, Enum):
    NONE = "NONE"
    APPEALED = "APPEALED"
    APPEAL_UPHELD = "APPEAL_UPHELD"
    APPEAL_OVERTURNED = "APPEAL_OVERTURNED"


class RepairStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    REPAIRED = "REPAIRED"
    REPLACEMENT_AUTHORIZED = "REPLACEMENT_AUTHORIZED"
    CLOSED = "CLOSED"


class PayerType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class DeviceCategory(str, Enum):
    LOWER_LIMB_PROSTHETIC = "LOWER_LIMB_PROSTHETIC"
    UPPER_LIMB_PROSTHETIC = "UPPER_LIMB_PROSTHETIC"
    SPINAL_ORTHOSIS = "SPINAL_ORTHOSIS"
    LOWER_EXTREMITY_ORTHOSIS = "LOWER_EXTREMITY_ORTHOSIS"


class ClaimModifier(str, Enum):
    NONE = "NONE"
    KX = "KX"
    GA = "GA"
    GZ = "GZ"
    RT = "RT"
    LT = "LT"


class MilestoneStep(str, Enum):
    CASTING = "CASTING"
    MODIFICATION = "MODIFICATION"
    ASSEMBLY = "ASSEMBLY"
    QUALITY_CHECK = "QUALITY_CHECK"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    LAPSED = "LAPSED"
    UNACCREDITED = "UNACCREDITED"


# ─── Entity TypedDicts (common_fields: true) ──────────────────────────
class Patient(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    date_of_birth: str
    payer_type: str
    medicare_beneficiary_id: Optional[str]
    functional_k_level: Optional[int]


class Physician(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    npi: str
    pecos_enrolled: bool


class Supplier(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    accreditation_status: str
    accreditation_expiry: Optional[str]
    surety_bond_active: bool


class Prescription(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    patient_id: str
    physician_id: str
    device_category: str
    primary_diagnosis_code: str
    face_to_face_date: str
    status: str


class DeviceOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    prescription_id: str
    supplier_id: str
    fitting_practitioner_id: str
    status: str
    requires_prior_auth: bool
    milestone_progress_pct: int
    delivery_date: Optional[str]
    warranty_expiry: Optional[str]
    allowed_total_cents: int


class PriorAuth(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    device_order_id: str
    status: str
    auth_number: Optional[str]
    submission_round: int
    decision_deadline: Optional[str]


class ClaimLine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    device_order_id: str
    l_code: str
    modifier: str
    billed_units: int
    fee_schedule_cents: int
    adjudication_status: str
    appeal_status: str
    allowed_cents: int


class FabricationMilestone(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    device_order_id: str
    step: str
    weight: int
    completed: bool


class Adjustment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    device_order_id: str
    adjustment_date: Optional[str]
    within_warranty: bool
    billable: bool


class RepairRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    device_order_id: str
    replaces_order_id: Optional[str]
    status: str
    cost_cents: int
    warranty_applies: bool


# ─── Append-only audit records (common_fields: false) ──────────────────
# These carry ONLY id + created_at — no updated_at, no version.
class ComplianceCheck(TypedDict, total=False):
    id: str
    created_at: str
    device_order_id: str
    passed: bool
    failure_reasons: List[str]


class ClockState(TypedDict, total=False):
    id: str
    created_at: str
    current_utc: str
