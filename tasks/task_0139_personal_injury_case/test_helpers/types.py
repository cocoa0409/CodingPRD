"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §1, §3 (entities) and PRD §3 (state machines).

PRD §2.4 lifecycle fields:
    "Most resources also carry the created_at timestamp (when the row
    was first inserted), the updated_at timestamp (refreshed on every
    mutation), and an integer version that starts at 1 and increments
    by one each time the row is mutated."
    "Two entities are intentionally exceptions to this pattern:
    ContingencyFeeAgreement is immutable after creation and
    SettlementDisbursement is created once and never revised, so both
    carry only id and created_at — they expose neither updated_at nor
    version."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PARALEGAL = "Paralegal"
    ATTORNEY = "Attorney"
    MANAGING_PARTNER = "ManagingPartner"


# ---------------------------------------------------------------------------
# Status enums — PRD §3 state machines
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    RECORDS_PENDING = "RECORDS_PENDING"
    READY_FOR_DEMAND = "READY_FOR_DEMAND"
    DEMAND_SENT = "DEMAND_SENT"
    NEGOTIATING = "NEGOTIATING"
    LITIGATION = "LITIGATION"
    SETTLED = "SETTLED"
    TRIAL_AWARDED = "TRIAL_AWARDED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class IncidentType(str, Enum):
    AUTO = "AUTO"
    SLIP_FALL = "SLIP_FALL"
    MEDICAL_MALPRACTICE = "MEDICAL_MALPRACTICE"
    PRODUCT_LIABILITY = "PRODUCT_LIABILITY"
    PREMISES = "PREMISES"
    DOG_BITE = "DOG_BITE"


class MedicalRecordRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class PainSufferingMethod(str, Enum):
    MULTIPLIER = "MULTIPLIER"
    PER_DIEM = "PER_DIEM"


class LienType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    ERISA = "ERISA"
    HOSPITAL_STATUTORY = "HOSPITAL_STATUTORY"
    PROVIDER_NEGOTIATED = "PROVIDER_NEGOTIATED"
    CHILD_SUPPORT = "CHILD_SUPPORT"
    ATTORNEY_PRIOR_COUNSEL = "ATTORNEY_PRIOR_COUNSEL"


class LienStatus(str, Enum):
    ASSERTED = "ASSERTED"
    NEGOTIATING = "NEGOTIATING"
    REDUCED = "REDUCED"
    RESOLVED = "RESOLVED"
    DISPUTED = "DISPUTED"


class DemandLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class OfferParty(str, Enum):
    DEFENDANT = "DEFENDANT"
    PLAINTIFF = "PLAINTIFF"


class SettlementOfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COUNTERED = "COUNTERED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class CourtEventType(str, Enum):
    COMPLAINT_FILED = "COMPLAINT_FILED"
    ANSWER_DUE = "ANSWER_DUE"
    DISCOVERY_DEADLINE = "DISCOVERY_DEADLINE"
    MEDIATION = "MEDIATION"
    MOTION_HEARING = "MOTION_HEARING"
    TRIAL = "TRIAL"
    JUDGMENT = "JUDGMENT"


class CourtEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CONTINUED = "CONTINUED"
    CANCELED = "CANCELED"


class DisbursementStrategy(str, Enum):
    CHRONOLOGICAL_PRIORITY = "CHRONOLOGICAL_PRIORITY"
    FORWARD_LOOKING_PRORATA = "FORWARD_LOOKING_PRORATA"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true entities carry id + created_at +
# updated_at + version. common_fields: false entities
# (ContingencyFeeAgreement, SettlementDisbursement) omit updated_at /
# version per PRD §2.4.
# ---------------------------------------------------------------------------
class Client(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    is_minor_at_incident: Optional[bool]
    contact_email: str
    state_of_residence: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    client_id: str
    incident_date: str
    incident_type: str
    jurisdiction_state: str
    status: str
    sol_deadline: str
    sol_tolled_days: int
    assigned_attorney_id: Optional[str]
    assigned_paralegal_id: Optional[str]
    gross_settlement_cents: int
    case_costs_cents: int
    filed_in_court: bool
    disbursement_approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicalRecordRequest(TypedDict, total=False):
    id: str
    case_id: str
    provider_name: str
    date_of_service_start: str
    date_of_service_end: str
    status: str
    sent_at: Optional[str]
    received_at: Optional[str]
    billed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Damages(TypedDict, total=False):
    id: str
    case_id: str
    medical_bills_cents: int
    lost_wages_cents: int
    property_damage_cents: int
    pain_suffering_method: str
    multiplier_value: float
    per_diem_rate_cents: int
    per_diem_days: int
    pain_suffering_cents: int
    total_damages_cents: int
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict, total=False):
    id: str
    case_id: str
    lienholder_name: str
    lien_type: str
    face_amount_cents: int
    negotiated_amount_cents: Optional[int]
    status: str
    final_paid_amount_cents: Optional[int]
    priority_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DemandLetter(TypedDict, total=False):
    id: str
    case_id: str
    demanded_amount_cents: int
    snapshot_total_damages_cents: int
    snapshot_damages_version: int
    status: str
    sent_at: Optional[str]
    response_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict, total=False):
    id: str
    case_id: str
    predecessor_offer_id: Optional[str]
    offer_party: str
    amount_cents: int
    status: str
    expires_at: str
    round_number: int
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: ContingencyFeeAgreement — common_fields false (id + created_at
# only, no updated_at / version).
class ContingencyFeeAgreement(TypedDict, total=False):
    id: str
    case_id: str
    pre_suit_rate_bps: int
    post_suit_rate_bps: int
    trial_rate_bps: int
    signed_at: str
    created_at: str


class CourtEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    scheduled_at: str
    duration_minutes: int
    courtroom: Optional[str]
    status: str
    award_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: SettlementDisbursement — common_fields false (id + created_at
# only, no updated_at / version).
class SettlementDisbursement(TypedDict, total=False):
    id: str
    case_id: str
    gross_amount_cents: int
    attorney_fee_cents: int
    case_costs_cents: int
    total_lien_payment_cents: int
    client_net_cents: int
    strategy: str
    approved_by: str
    created_at: str


__all__ = [
    "UserRole",
    "CaseStatus",
    "IncidentType",
    "MedicalRecordRequestStatus",
    "PainSufferingMethod",
    "LienType",
    "LienStatus",
    "DemandLetterStatus",
    "OfferParty",
    "SettlementOfferStatus",
    "CourtEventType",
    "CourtEventStatus",
    "DisbursementStrategy",
    "Client",
    "Case",
    "MedicalRecordRequest",
    "Damages",
    "Lien",
    "DemandLetter",
    "SettlementOffer",
    "ContingencyFeeAgreement",
    "CourtEvent",
    "SettlementDisbursement",
]
