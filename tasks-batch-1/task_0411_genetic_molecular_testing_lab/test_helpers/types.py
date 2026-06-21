"""Domain types: entity TypedDicts, status enums, role enum.

All fields and state values use the exact names from the PRD (Genetic & Molecular
Testing Lab). Entities that are NOT common-fields (the singleton LabClock) omit
updated_at/version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    LAB_DIRECTOR = "LabDirector"
    LAB_INTAKE = "LabIntake"
    ACCESSIONING_TECH = "AccessioningTech"
    MOLECULAR_TECHNOLOGIST = "MolecularTechnologist"
    BILLING_SPECIALIST = "BillingSpecialist"
    GENETIC_COUNSELOR = "GeneticCounselor"


# --------------------------------------------------------------------------- #
# Status enums (PRD §2.9 State Enumerations)
# --------------------------------------------------------------------------- #
class GeneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PanelStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PanelGeneStatus(str, Enum):
    INCLUDED = "INCLUDED"
    REMOVED = "REMOVED"


class PipelineStatus(str, Enum):
    ORDERED = "ORDERED"
    REQUISITIONED = "REQUISITIONED"
    ACCESSIONED = "ACCESSIONED"
    SEQUENCING = "SEQUENCING"
    CLASSIFIED = "CLASSIFIED"
    SIGNED_OUT = "SIGNED_OUT"
    CANCELLED = "CANCELLED"


class FinancialStatus(str, Enum):
    PENDING = "PENDING"
    AUTH_REQUESTED = "AUTH_REQUESTED"
    AUTH_APPROVED = "AUTH_APPROVED"
    AUTH_DENIED = "AUTH_DENIED"
    PATIENT_PAY = "PATIENT_PAY"
    SETTLED = "SETTLED"


class BillingStatus(str, Enum):
    OPEN = "OPEN"
    AUTH_REQUESTED = "AUTH_REQUESTED"
    AUTH_APPROVED = "AUTH_APPROVED"
    AUTH_DENIED = "AUTH_DENIED"
    PATIENT_PAY = "PATIENT_PAY"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class RequisitionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VOID = "VOID"


class ConsentStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class SpecimenStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCESSIONED = "ACCESSIONED"
    QNS_REJECTED = "QNS_REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    SALIVA = "SALIVA"
    TISSUE = "TISSUE"


class Classification(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    BENIGN = "BENIGN"
    LIKELY_BENIGN = "LIKELY_BENIGN"
    VUS = "VUS"
    LIKELY_PATHOGENIC = "LIKELY_PATHOGENIC"
    PATHOGENIC = "PATHOGENIC"
    RECLASSIFIED = "RECLASSIFIED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED_OUT = "SIGNED_OUT"
    AMENDED = "AMENDED"


class SequencerStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class SequencerRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    ABORTED = "ABORTED"


class CounselorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InsurancePayer(str, Enum):
    MEDICARE = "MEDICARE"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class ReferralReason(str, Enum):
    PATHOGENIC_RESULT = "PATHOGENIC_RESULT"
    VUS_FOLLOWUP = "VUS_FOLLOWUP"
    INCIDENTAL_FINDING = "INCIDENTAL_FINDING"
    PATIENT_REQUEST = "PATIENT_REQUEST"


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# --------------------------------------------------------------------------- #
# LabClock — singleton, NOT common-fields: only current_utc (no id/version per PRD).
class LabClock(TypedDict):
    current_utc: str


# common_fields: true — id + created_at + updated_at + version
class Gene(TypedDict):
    id: str
    symbol: str
    is_acmg_reportable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Panel(TypedDict):
    id: str
    name: str
    list_price_cents: int
    requires_consent: bool
    gene_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelGene(TypedDict):
    id: str
    panel_id: str
    gene_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    npi: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class TestOrder(TypedDict):
    id: str
    patient_mrn: str
    patient_dob: str
    panel_id: str
    ordering_provider_id: str
    pipeline_status: str
    financial_status: str
    list_price_cents: int
    estimated_patient_responsibility_cents: Optional[int]
    final_patient_responsibility_cents: Optional[int]
    report_required_consent: bool
    has_reportable_incidental: bool
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict):
    id: str
    test_order_id: str
    clinical_indication: str
    insurance_payer: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consent(TypedDict):
    id: str
    test_order_id: str
    incidental_findings_opt_in: bool
    signed_by_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    test_order_id: str
    specimen_type: str
    collected_at: str
    received_at: Optional[str]
    quantity_ng: float
    status: str
    superseded_by_specimen_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Variant(TypedDict):
    id: str
    test_order_id: str
    gene_id: str
    hgvs: str
    is_incidental: bool
    classification: str
    classified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    test_order_id: str
    reportable_variant_ids: List[str]
    incidental_disclosed: bool
    signed_out_by_user_id: Optional[str]
    amends_report_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Billing(TypedDict):
    id: str
    test_order_id: str
    allowed_amount_cents: Optional[int]
    coinsurance_collected_cents: int
    writeoff_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sequencer(TypedDict):
    id: str
    instrument_name: str
    turnaround_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SequencerRun(TypedDict):
    id: str
    sequencer_id: str
    test_order_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GeneticCounselorProfile(TypedDict):
    id: str
    counselor_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CounselorReferral(TypedDict):
    id: str
    test_order_id: str
    counselor_id: str
    triggering_variant_id: Optional[str]
    reason: str
    slot_start: Optional[str]
    slot_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
