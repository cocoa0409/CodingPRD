"""Domain types: entity TypedDicts, status enums, role enum for the Ambulance EMS Billing API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BILLING_ADMIN = "BillingAdmin"
    DISPATCHER = "Dispatcher"
    CODER = "Coder"
    BILLER = "Biller"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class StaffRole(str, Enum):
    DISPATCHER = "Dispatcher"
    CODER = "Coder"
    BILLER = "Biller"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class PayerType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    AUTO = "AUTO"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class PayerPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Certification(str, Enum):
    EMT = "EMT"
    AEMT = "AEMT"
    PARAMEDIC = "PARAMEDIC"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OriginModifier(str, Enum):
    S = "S"
    H = "H"
    N = "N"
    R = "R"
    E = "E"
    P = "P"
    I = "I"


class DestinationModifier(str, Enum):
    H = "H"
    N = "N"
    R = "R"
    E = "E"
    P = "P"
    I = "I"
    X = "X"


class LevelOfService(str, Enum):
    BLS = "BLS"
    ALS1 = "ALS1"
    ALS2 = "ALS2"
    SCT = "SCT"


class DocumentationStatus(str, Enum):
    IMPORTED = "IMPORTED"
    CODED = "CODED"
    NECESSITY_REVIEW = "NECESSITY_REVIEW"
    DOCUMENTATION_COMPLETE = "DOCUMENTATION_COMPLETE"
    RETURNED = "RETURNED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLING_IN_PROGRESS = "BILLING_IN_PROGRESS"
    BILLED = "BILLED"
    PATIENT_BALANCE = "PATIENT_BALANCE"
    CLOSED = "CLOSED"
    VOID = "VOID"


class ChargeType(str, Enum):
    BASE_RATE = "BASE_RATE"
    MILEAGE = "MILEAGE"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class RemittanceOutcome(str, Enum):
    PAID = "PAID"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    NOT_MEDICALLY_NECESSARY = "NOT_MEDICALLY_NECESSARY"
    MISSING_PCS = "MISSING_PCS"
    NON_COVERED_DESTINATION = "NON_COVERED_DESTINATION"
    COB_PRIMARY_NOT_BILLED = "COB_PRIMARY_NOT_BILLED"
    DUPLICATE = "DUPLICATE"


class PaymentSource(str, Enum):
    PAYER = "PAYER"
    PATIENT = "PATIENT"


class AdjustmentType(str, Enum):
    CHARITY = "CHARITY"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"
    BALANCE_BILLING_CAP = "BALANCE_BILLING_CAP"
    GOODWILL = "GOODWILL"


# ---- Entity TypedDicts (all entities carry common_fields: id/created_at/updated_at/version) ----

class Agency(TypedDict):
    id: str
    name: str
    npi: str
    state_code: str
    base_state_is_no_surprises: bool
    charity_fpl_threshold_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgencyStaff(TypedDict):
    id: str
    agency_id: str
    full_name: str
    role: str
    pcs_signature_authority: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PayerPlan(TypedDict):
    id: str
    name: str
    payer_type: str
    qpa_multiplier: float
    allows_balance_billing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    household_size: int
    annual_household_income_cents: Optional[int]
    coverages: List[dict]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    agency_id: str
    unit_call_sign: str
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    agency_id: str
    full_name: str
    certification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnitAssignment(TypedDict):
    id: str
    transport_id: str
    vehicle_id: str
    crew_member_id: str
    window_start_iso: str
    window_end_iso: str
    created_at: str
    updated_at: str
    version: int


class Transport(TypedDict):
    id: str
    agency_id: str
    patient_id: str
    run_number: str
    dispatch_iso: str
    origin_modifier: str
    destination_modifier: str
    loaded_miles: float
    is_rural_pickup: bool
    level_of_service: Optional[str]
    emergency_indicator: bool
    medical_necessity_met: bool
    pcs_signed: bool
    documentation_status: str
    billing_status: str
    total_billed_cents: int
    total_allowed_cents: int
    total_paid_cents: int
    total_writeoff_cents: int
    patient_responsibility_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    transport_id: str
    charge_type: str
    hcpcs_code: str
    units: float
    billed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    transport_id: str
    payer_plan_id: str
    prior_claim_id: Optional[str]
    sequence_rank: int
    billed_amount_cents: int
    prior_paid_cents: int
    allowed_amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceLine(TypedDict):
    id: str
    claim_id: str
    outcome: str
    reported_allowed_cents: Optional[int]
    paid_cents: int
    denial_reason: Optional[str]
    contractual_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    transport_id: str
    claim_id: Optional[str]
    source: str
    amount_cents: int
    posted_iso: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict):
    id: str
    transport_id: str
    adjustment_type: str
    amount_cents: int
    requested_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
