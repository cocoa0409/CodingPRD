"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------


class AssetPosture(str, Enum):
    CLEAR = "CLEAR"
    ENCUMBERED = "ENCUMBERED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class OrphanStatus(str, Enum):
    NOT_ORPHAN = "NOT_ORPHAN"
    DILIGENCE_PENDING = "DILIGENCE_PENDING"
    ORPHAN_CERTIFIED = "ORPHAN_CERTIFIED"


class WorkKind(str, Enum):
    MUSICAL_COMPOSITION = "MUSICAL_COMPOSITION"
    SOUND_RECORDING = "SOUND_RECORDING"
    FILM_CLIP = "FILM_CLIP"
    STILL_IMAGE = "STILL_IMAGE"
    LITERARY_EXCERPT = "LITERARY_EXCERPT"


class Media(str, Enum):
    BROADCAST_TV = "BROADCAST_TV"
    STREAMING = "STREAMING"
    THEATRICAL = "THEATRICAL"
    RADIO = "RADIO"
    SOCIAL = "SOCIAL"
    PRINT = "PRINT"


class Territory(str, Enum):
    NA = "NA"
    EMEA = "EMEA"
    LATAM = "LATAM"
    APAC = "APAC"
    WORLD = "WORLD"


class HolderKind(str, Enum):
    PUBLISHER = "PUBLISHER"
    LABEL = "LABEL"
    ESTATE = "ESTATE"
    COLLECTIVE = "COLLECTIVE"
    INDIVIDUAL = "INDIVIDUAL"


class SearchChannel(str, Enum):
    COPYRIGHT_OFFICE = "COPYRIGHT_OFFICE"
    PERFORMING_RIGHTS_ORG = "PERFORMING_RIGHTS_ORG"
    UNION_GUILD = "UNION_GUILD"
    COMMERCIAL_DATABASE = "COMMERCIAL_DATABASE"
    DIRECT_OUTREACH = "DIRECT_OUTREACH"


class DiligenceOutcome(str, Enum):
    HOLDER_FOUND = "HOLDER_FOUND"
    NO_RESULT = "NO_RESULT"
    CONFLICTING_CLAIM = "CONFLICTING_CLAIM"


class ClearanceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    HOLDER_REVIEW = "HOLDER_REVIEW"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    FAIR_USE_ROUTE = "FAIR_USE_ROUTE"
    LICENSED = "LICENSED"
    EXPIRED = "EXPIRED"


class OfferedByRole(str, Enum):
    NEGOTIATOR = "NEGOTIATOR"
    RIGHTS_HOLDER_REP = "RIGHTS_HOLDER_REP"


class RoundOutcome(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LicenseLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class FeeStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class PostingKind(str, Enum):
    POSTED = "POSTED"
    STRUCK = "STRUCK"


class FairUseStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TakedownStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    UPHELD = "UPHELD"
    RETRACTED = "RETRACTED"


class RenewalAlertStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIRED = "FIRED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    REQUESTER = "Requester"
    CLEARANCE_OFFICER = "ClearanceOfficer"
    NEGOTIATOR = "Negotiator"
    FINANCE_PAYER = "FinancePayer"
    INGESTION_AGENT = "IngestionAgent"
    LEGAL_CERTIFIER = "LegalCertifier"
    ASSET_CURATOR = "AssetCurator"
    RIGHTS_HOLDER_REP = "RightsHolderRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------


class Asset(TypedDict, total=False):
    id: str
    title: str
    work_kind: str
    permitted_media: List[str]
    embargo_until: Optional[str]
    rights_holder_id: Optional[str]
    orphan_status: str
    posture: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RightsHolder(TypedDict, total=False):
    id: str
    legal_name: str
    holder_kind: str
    mfn_floor_cents: int
    contact_verified: bool
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (no updated_at, no version)
class RightsDiligenceLog(TypedDict, total=False):
    id: str
    asset_id: str
    search_channel: str
    outcome: str
    notes: str
    created_at: str


class ClearanceRequest(TypedDict, total=False):
    id: str
    asset_id: str
    requester_id: str
    media: str
    territory: str
    use_start_at: str
    use_end_at: str
    requested_units: int
    status: str
    negotiation_round: int
    agreed_fee_cents: Optional[int]
    fair_use_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only
class NegotiationRound(TypedDict, total=False):
    id: str
    clearance_request_id: str
    round_index: int
    offered_fee_cents: int
    offered_by_role: str
    outcome: str
    created_at: str


class License(TypedDict, total=False):
    id: str
    clearance_request_id: str
    asset_id: str
    territory: str
    media: str
    term_start_at: str
    term_end_at: str
    unit_limit: int
    fee_agreed_cents: int
    fee_status: str
    lifecycle: str
    units_reserved: int
    units_consumed_net: int
    units_consumed_gross: int
    renewal_alert_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageReservation(TypedDict, total=False):
    id: str
    license_id: str
    units: int
    status: str
    hold_expires_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only
class UsageEvent(TypedDict, total=False):
    id: str
    license_id: str
    reservation_id: Optional[str]
    units: int
    used_at: str
    posting_kind: str
    created_at: str


# Append-only
class LicensePayment(TypedDict, total=False):
    id: str
    license_id: str
    amount_cents: int
    payer_id: str
    posted_at: str
    created_at: str


class FairUseAssessment(TypedDict, total=False):
    id: str
    asset_id: str
    clearance_request_id: str
    factor_scores: Dict[str, int]
    composite_score: int
    certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TakedownNotice(TypedDict, total=False):
    id: str
    asset_id: str
    claimant_name: str
    received_at: str
    counter_notice_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalAlert(TypedDict, total=False):
    id: str
    license_id: str
    fires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
