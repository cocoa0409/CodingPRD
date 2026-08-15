"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class PropertyPosture(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    RESTRICTED = "RESTRICTED"


class OperationalStatus(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"
    RENOVATION = "RENOVATION"


class PestFlag(str, Enum):
    CLEAR = "CLEAR"
    MONITORING = "MONITORING"
    INFESTED = "INFESTED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class PestType(str, Enum):
    ANTS = "ANTS"
    ROACHES = "ROACHES"
    RODENTS = "RODENTS"
    BED_BUGS = "BED_BUGS"
    TERMITES = "TERMITES"


class InspectionKind(str, Enum):
    ROUTINE = "ROUTINE"
    INITIAL = "INITIAL"
    FOLLOW_UP = "FOLLOW_UP"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED = "CANCELLED"


class Severity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class TreatmentType(str, Enum):
    CHEMICAL = "CHEMICAL"
    HEAT = "HEAT"
    EXCLUSION = "EXCLUSION"
    TRAPPING = "TRAPPING"


class TreatmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PREP_NOTIFIED = "PREP_NOTIFIED"
    PREP_VERIFIED = "PREP_VERIFIED"
    NON_COMPLIANT = "NON_COMPLIANT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BedBugCaseStatus(str, Enum):
    OPEN = "OPEN"
    TREATING = "TREATING"
    MONITORING = "MONITORING"
    CLEARED = "CLEARED"
    REOPENED = "REOPENED"


class DisposalStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ChargebackKind(str, Enum):
    NON_COMPLIANCE_FEE = "NON_COMPLIANCE_FEE"
    REPEAT_INFESTATION = "REPEAT_INFESTATION"
    HEAT_SURCHARGE = "HEAT_SURCHARGE"
    FURNITURE_DISPOSAL = "FURNITURE_DISPOSAL"
    LATE_FEE = "LATE_FEE"


class ChargebackStatus(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"
    BILLED = "BILLED"
    PAID = "PAID"


class Resolution(str, Enum):
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"


class ClaimPacketStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISCARDED = "DISCARDED"


class RiskVariant(str, Enum):
    FORWARD = "FORWARD"
    HISTORICAL = "HISTORICAL"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    TECHNICIAN = "Technician"
    RESIDENT = "Resident"
    BILLING_CLERK = "BillingClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class Property(TypedDict, total=False):
    id: str
    name: str
    address: str
    timezone: str
    posture: str
    open_bed_bug_case_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    property_id: str
    vendor_name: str
    scope_pest_types: List[str]
    visits_per_month: int
    coverage_per_incident_cents: int
    heat_treatment_included: bool
    monthly_budget_cents: int
    spent_cents: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    property_id: str
    unit_number: str
    floor: int
    stack_index: int
    bedrooms: int
    operational_status: str
    pest_flag: str
    no_access_strikes: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    unit_id: str
    start_date: str
    end_date: str
    pest_addendum_signed: bool
    chargeback_clause_version: str
    chargeback_cap_cents: int
    status: str
    outstanding_balance_cents: int
    delinquent: bool
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    unit_id: str
    lease_id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    vendor_name: str
    active: bool
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    unit_id: str
    technician_id: str
    bed_bug_case_id: Optional[str]
    kind: str
    pest_type: str
    scheduled_for: str
    status: str
    completed_at: Optional[str]
    live_sightings: int
    evidence_count: int
    bed_bug_positive: bool
    severity: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Treatment(TypedDict, total=False):
    id: str
    unit_id: str
    technician_id: str
    inspection_id: Optional[str]
    bed_bug_case_id: Optional[str]
    pest_type: str
    treatment_type: str
    window_start: str
    window_end: str
    planned_minutes: int
    vacancy_attested: bool
    status: str
    prep_notified_at: Optional[str]
    prep_acknowledged_at: Optional[str]
    reschedule_count: int
    actual_minutes: int
    created_at: str
    updated_at: str
    version: int


class BedBugCase(TypedDict, total=False):
    id: str
    unit_id: str
    status: str
    consecutive_negative_count: int
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FurnitureDisposal(TypedDict, total=False):
    id: str
    bed_bug_case_id: str
    item_description: str
    quantity: int
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    lease_id: str
    source_treatment_id: Optional[str]
    bed_bug_case_id: Optional[str]
    kind: str
    planned_item_count: int
    note: Optional[str]
    status: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    assessed_at: str
    assessed_by: str
    disputed_at: Optional[str]
    dispute_reason: Optional[str]
    resolved_by: Optional[str]
    resolution: Optional[str]
    billed_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimPacket(TypedDict, total=False):
    id: str
    property_id: str
    claim_reference: str
    references: List[dict]
    pinned_references: List[dict]
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
