"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class Species(str, Enum):
    CANINE = "CANINE"
    FELINE = "FELINE"
    EXOTIC = "EXOTIC"


class TriageLevel(str, Enum):
    RED = "RED"
    ORANGE = "ORANGE"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


class Department(str, Enum):
    ER = "ER"
    CARDIOLOGY = "CARDIOLOGY"
    ONCOLOGY = "ONCOLOGY"
    SURGERY = "SURGERY"
    NEUROLOGY = "NEUROLOGY"


class VisitStatus(str, Enum):
    REGISTERED = "REGISTERED"
    TRIAGED = "TRIAGED"
    IN_TREATMENT = "IN_TREATMENT"
    READY_FOR_DISCHARGE = "READY_FOR_DISCHARGE"
    DISCHARGED = "DISCHARGED"
    DECEASED = "DECEASED"
    LWBS = "LWBS"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    CONSUMED = "CONSUMED"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class Ward(str, Enum):
    ICU = "ICU"
    WARD = "WARD"


class HospitalizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class Modality(str, Enum):
    IMAGING_CT = "IMAGING_CT"
    IMAGING_MRI = "IMAGING_MRI"
    SURGERY = "SURGERY"


class ResourceRoom(str, Enum):
    CT_SUITE = "CT_SUITE"
    MRI_SUITE = "MRI_SUITE"
    OR_1 = "OR_1"
    OR_2 = "OR_2"


class ProcedureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"


class PaymentProvider(str, Enum):
    CARECREDIT = "CARECREDIT"
    IN_HOUSE = "IN_HOUSE"


class PaymentPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    TRIAGE_NURSE = "TriageNurse"
    CLINICIAN_DVM = "ClinicianDVM"
    FINANCE_COORDINATOR = "FinanceCoordinator"
    OWNER = "Owner"


# ---- Entity TypedDicts (common_fields: true unless noted) ----

class Patient(TypedDict):
    id: str
    name: str
    species: str
    weight_kg: float
    owner_user_id: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    patient_id: str
    chief_complaint: str
    triage_level: Optional[str]
    department: str
    attending_dvm_id: Optional[str]
    status: str
    authorized_ceiling_cents: int
    charges_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    visit_id: str
    to_department: str
    accepting_dvm_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    visit_id: str
    line_items: list
    low_cents: int
    high_cents: int
    deposit_pct: float
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    visit_id: str
    estimate_id: str
    approved_ceiling_cents: int
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Hospitalization(TypedDict):
    id: str
    visit_id: str
    ward: str
    cage_number: int
    admit_at: str
    planned_discharge_at: str
    released_at: Optional[str]
    nights_accrued: int
    board_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    visit_id: str
    modality: str
    resource_room: str
    start_at: str
    end_at: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    visit_id: str
    charge_lines: list
    subtotal_cents: int
    tax_cents: int
    deposit_applied_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    visit_id: str
    invoice_id: str
    provider: str
    principal_cents: int
    term_months: int
    promo_applied: bool
    financing_fee_cents: int
    installment_cents: int
    final_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ReferringVetReport(TypedDict):
    id: str
    visit_id: str
    referring_dvm_email: str
    summary: str
    procedures_performed: list
    total_billed_cents: int
    created_at: str
