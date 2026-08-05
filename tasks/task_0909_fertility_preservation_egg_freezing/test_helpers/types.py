"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PATIENT = "Patient"
    COORDINATOR = "Coordinator"
    PHYSICIAN = "Physician"
    EMBRYOLOGIST = "Embryologist"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProviderRole(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    EMBRYOLOGIST = "EMBRYOLOGIST"


class RoomKind(str, Enum):
    RETRIEVAL_OR = "RETRIEVAL_OR"
    PROCEDURE = "PROCEDURE"


class ConsultationEligibility(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class Protocol(str, Enum):
    ANTAGONIST = "ANTAGONIST"
    LONG_AGONIST = "LONG_AGONIST"
    MINIMAL_STIM = "MINIMAL_STIM"
    NONE = "NONE"


class ConsultationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    MONITORING = "MONITORING"
    SUSPENDED = "SUSPENDED"
    TRIGGERED = "TRIGGERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class SpecimenType(str, Enum):
    VIAL = "VIAL"
    STRAW = "STRAW"


class SpecimenStatus(str, Enum):
    STORED = "STORED"
    RESERVED = "RESERVED"
    THAWED = "THAWED"
    DISCARDED = "DISCARDED"


class SubscriptionStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class BenefitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class DirectiveType(str, Enum):
    CONSENT = "CONSENT"
    DISPOSITION = "DISPOSITION"


class DispositionAction(str, Enum):
    THAW_TO_SELF = "THAW_TO_SELF"
    DONATE_TO_RESEARCH = "DONATE_TO_RESEARCH"
    DISCARD = "DISCARD"
    TRANSFER_TO_PARTNER = "TRANSFER_TO_PARTNER"


class DirectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class TransferType(str, Enum):
    THAW_TO_TRANSFER = "THAW_TO_TRANSFER"
    TRANSFER_OUT = "TRANSFER_OUT"
    RESEARCH_DONATION = "RESEARCH_DONATION"


class AuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTED = "EXECUTED"
    DENIED = "DENIED"


class ServiceType(str, Enum):
    CYCLE = "CYCLE"
    STORAGE = "STORAGE"
    RETRIEVAL = "RETRIEVAL"
    THAW = "THAW"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


# ---- Entity TypedDicts (all entities carry common fields id/created_at/updated_at/version) ----

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    email: str
    employer_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    provider_role: str
    npi: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcedureRoom(TypedDict):
    id: str
    name: str
    room_kind: str
    created_at: str
    updated_at: str
    version: int


class StorageTank(TypedDict):
    id: str
    name: str
    capacity_slots: int
    used_slots: int
    is_full: bool
    created_at: str
    updated_at: str
    version: int


class Consultation(TypedDict):
    id: str
    patient_id: str
    patient_age_years: int
    amh_level: float
    antral_follicle_count: int
    expected_oocyte_yield: int
    eligibility_status: str
    recommended_protocol: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StimulationCycle(TypedDict):
    id: str
    patient_id: str
    consultation_id: str
    protocol_type: str
    monitoring_visit_count: int
    estimated_cost_cents: int
    final_cost_cents: int
    retrieval_room_id: Optional[str]
    retrieval_start: Optional[str]
    retrieval_end: Optional[str]
    oocytes_retrieved: int
    mature_oocyte_count: int
    trigger_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringAppointment(TypedDict):
    id: str
    cycle_id: str
    provider_id: str
    scheduled_start: str
    scheduled_end: str
    visit_status: str
    created_at: str
    updated_at: str
    version: int


class CryoSpecimen(TypedDict):
    id: str
    patient_id: str
    cycle_id: str
    tank_id: str
    specimen_type: str
    oocyte_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageSubscription(TypedDict):
    id: str
    patient_id: str
    specimen_count: int
    annual_fee_cents: int
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    last_paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitCoverage(TypedDict):
    id: str
    patient_id: str
    employer_name: str
    annual_cap_cents: int
    covered_pct: float
    covered_service_types: List[str]
    consumed_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Directive(TypedDict):
    id: str
    patient_id: str
    directive_type: str
    disposition_action: Optional[str]
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ThawTransferAuthorization(TypedDict):
    id: str
    patient_id: str
    specimen_ids: List[str]
    transfer_type: str
    requester_provider_id: str
    authorizer_provider_id: Optional[str]
    consent_directive_id: Optional[str]
    disposition_directive_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    patient_id: str
    service_type: str
    line_items: List[dict]
    subtotal_cents: int
    facility_fee_cents: int
    estimated_coverage_cents: int
    settled_coverage_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
