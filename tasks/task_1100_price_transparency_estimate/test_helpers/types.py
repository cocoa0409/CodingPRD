"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API is mutable and carries the common fields
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PATIENT_USER = "PatientUser"
    PROVIDER_STAFF = "ProviderStaff"
    PAYER_ANALYST = "PayerAnalyst"
    ADMIN = "Admin"


class CodeSystem(str, Enum):
    CPT = "CPT"
    HCPCS = "HCPCS"
    DRG = "DRG"


class Setting(str, Enum):
    INPATIENT = "INPATIENT"
    OUTPATIENT = "OUTPATIENT"


class PayerType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"


class Methodology(str, Enum):
    FEE_SCHEDULE = "FEE_SCHEDULE"
    PERCENT_OF_CHARGE = "PERCENT_OF_CHARGE"
    CASE_RATE = "CASE_RATE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class RateType(str, Enum):
    FLAT = "FLAT"
    PERCENT = "PERCENT"


class RoomType(str, Enum):
    EXAM = "EXAM"
    PROCEDURE = "PROCEDURE"
    IMAGING = "IMAGING"


class EstimateType(str, Enum):
    GFE_INSURED = "GFE_INSURED"
    GFE_SELFPAY = "GFE_SELFPAY"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ResponsibilityBasis(str, Enum):
    ESTIMATE = "ESTIMATE"
    FINAL = "FINAL"


class PriorAuthStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CONSUMED = "CONSUMED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"


class Procedure(TypedDict, total=False):
    id: str
    code_system: str
    code: str
    description: str
    setting: str
    is_shoppable: bool
    requires_prior_auth: bool
    gross_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict, total=False):
    id: str
    payer_name: str
    payer_type: str
    methodology: str
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NegotiatedRate(TypedDict, total=False):
    id: str
    contract_id: str
    procedure_id: str
    rate_type: str
    flat_amount_cents: Optional[int]
    percent_of_charge: Optional[float]
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class BenefitPlan(TypedDict, total=False):
    id: str
    payer_name: str
    plan_year: int
    individual_deductible_cents: int
    individual_oop_max_cents: int
    coinsurance_rate: float
    copay_cents: int
    in_network: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    name: str
    member_id: str
    benefit_plan_id: str
    deductible_met_cents: int
    oop_met_cents: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    name: str
    npi: str
    specialty: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    name: str
    room_type: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict, total=False):
    id: str
    patient_id: str
    contract_id: Optional[str]
    estimate_type: str
    status: str
    allowed_amount_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    coinsurance_cents: Optional[int]
    copay_cents: Optional[int]
    patient_responsibility_cents: Optional[int]
    plan_paid_cents: Optional[int]
    responsibility_basis: Optional[str]
    recompute_required: bool
    issued_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstimateLine(TypedDict, total=False):
    id: str
    estimate_id: str
    procedure_id: str
    line_number: int
    allowed_amount_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    coinsurance_cents: Optional[int]
    line_patient_responsibility_cents: Optional[int]
    pinned_rate_id: Optional[str]
    pinned_rate_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict, total=False):
    id: str
    estimate_id: str
    procedure_code: str
    requested_units: int
    status: str
    auth_number: Optional[str]
    approved_units: Optional[int]
    expiration_date: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    patient_id: str
    estimate_id: str
    provider_id: str
    room_id: str
    prior_auth_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    estimate_id: str
    reason: str
    disputed_amount_cents: int
    status: str
    resolution_note: Optional[str]
    adjusted_patient_responsibility_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
