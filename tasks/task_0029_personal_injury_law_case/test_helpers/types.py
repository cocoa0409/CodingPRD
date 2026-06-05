"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3.1 (entities), §3.2-§3.9 (state machines), and §2.1 (roles).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ─── Status enums ─────────────────────────────────────────────


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    DEMAND_SENT = "DEMAND_SENT"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    LITIGATION = "LITIGATION"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class Jurisdiction(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    FL = "FL"
    IL = "IL"


class MedicalRecordsRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"


class DamagesCategory(str, Enum):
    MEDICAL_BILLS = "MEDICAL_BILLS"
    LOST_WAGES = "LOST_WAGES"
    PAIN_SUFFERING = "PAIN_SUFFERING"
    FUTURE_MEDICAL = "FUTURE_MEDICAL"
    PROPERTY = "PROPERTY"


class DamagesItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class MedicalLienStatus(str, Enum):
    ASSERTED = "ASSERTED"
    NEGOTIATING = "NEGOTIATING"
    AGREED = "AGREED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class DemandLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    WITHDRAWN = "WITHDRAWN"


class SettlementOfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SettlementParty(str, Enum):
    CARRIER = "CARRIER"
    FIRM = "FIRM"


class CourtEventType(str, Enum):
    FILING = "FILING"
    HEARING = "HEARING"
    TRIAL = "TRIAL"
    MEDIATION = "MEDIATION"


class CourtEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OCCURRED = "OCCURRED"
    CANCELLED = "CANCELLED"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PARALEGAL = "Paralegal"
    ATTORNEY = "Attorney"
    MANAGING_PARTNER = "ManagingPartner"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────
# Per PRD §2.4: every primary entity carries id + created_at + updated_at + version.
# The SystemClock singleton carries only id + created_at (no updated_at, no version).


class Client(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    retainer_signed: bool
    retainer_signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    client_id: str
    accident_date: str
    jurisdiction: str
    status: str
    statute_of_limitations_date: str
    sol_tolled_days: int
    filed_in_court: bool
    included_damages_total_cents: int
    gross_settlement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MedicalProvider(TypedDict, total=False):
    id: str
    name: str
    contact: str
    created_at: str
    updated_at: str
    version: int


class MedicalRecordsRequest(TypedDict, total=False):
    id: str
    case_id: str
    provider_id: str
    status: str
    requested_at: str
    received_at: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamagesItem(TypedDict, total=False):
    id: str
    case_id: str
    category: str
    amount_cents: int
    status: str
    documentation_note: str
    created_at: str
    updated_at: str
    version: int


class MedicalLien(TypedDict, total=False):
    id: str
    case_id: str
    provider_id: str
    asserted_amount_cents: int
    negotiated_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DemandLetter(TypedDict, total=False):
    id: str
    case_id: str
    demand_amount_cents: int
    pain_multiplier: float
    status: str
    drafted_by_user_id: str
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict, total=False):
    id: str
    case_id: str
    offer_amount_cents: int
    by_party: str
    counter_to_offer_id: Optional[str]
    round_number: int
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourtEvent(TypedDict, total=False):
    id: str
    case_id: str
    event_type: str
    scheduled_at: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    case_id: str
    gross_settlement_cents: int
    contingency_fee_cents: int
    total_lien_payout_cents: int
    net_to_client_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# SystemClock — singleton; id + created_at only per PRD §2.4.
class SystemClock(TypedDict, total=False):
    id: str
    current_utc: str
    created_at: str
