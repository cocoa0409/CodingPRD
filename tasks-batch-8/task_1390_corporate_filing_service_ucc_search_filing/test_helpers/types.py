"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status / vocabulary enums
# ---------------------------------------------------------------------------

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class IndividualNameRule(str, Enum):
    DL_SAFE_HARBOR = "DL_SAFE_HARBOR"
    LEGAL_NAME_ONLY = "LEGAL_NAME_ONLY"


class DebtorType(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    INDIVIDUAL = "INDIVIDUAL"


class RequestKind(str, Enum):
    NEW_UCC1 = "NEW_UCC1"
    AMENDMENT = "AMENDMENT"
    CONTINUATION = "CONTINUATION"
    TERMINATION = "TERMINATION"


class RequestStatus(str, Enum):
    DRAFT_INTAKE = "DRAFT_INTAKE"
    IN_REVIEW = "IN_REVIEW"
    READY = "READY"
    IN_PROCESS = "IN_PROCESS"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    CLIENT_REQUEST = "CLIENT_REQUEST"
    TARGET_LAPSED = "TARGET_LAPSED"
    TARGET_TERMINATED = "TARGET_TERMINATED"


class CollateralClass(str, Enum):
    GENERAL = "GENERAL"
    FIXTURE = "FIXTURE"
    TIMBER_TO_BE_CUT = "TIMBER_TO_BE_CUT"
    AS_EXTRACTED = "AS_EXTRACTED"


class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class FilingOffice(str, Enum):
    STATE = "STATE"
    COUNTY = "COUNTY"


class FilingKind(str, Enum):
    INITIAL = "INITIAL"
    AMENDMENT = "AMENDMENT"
    CONTINUATION = "CONTINUATION"
    TERMINATION = "TERMINATION"


class EffectivenessStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class ReflectionStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    REFLECTED = "REFLECTED"
    DISCREPANCY = "DISCREPANCY"


class AmendmentScope(str, Enum):
    DEBTOR_NAME = "DEBTOR_NAME"
    COLLATERAL = "COLLATERAL"
    SECURED_PARTY = "SECURED_PARTY"


class CollateralChangeOp(str, Enum):
    ADD = "ADD"
    DELETE = "DELETE"
    RESTATE = "RESTATE"


class RejectionReasonCode(str, Enum):
    NAME_MISMATCH = "NAME_MISMATCH"
    FEE_INCORRECT = "FEE_INCORRECT"
    WRONG_OFFICE = "WRONG_OFFICE"
    MISSING_SIGNATURE = "MISSING_SIGNATURE"
    DUPLICATE_FILING = "DUPLICATE_FILING"
    OTHER = "OTHER"


class SearchPurpose(str, Enum):
    PRE_FILING = "PRE_FILING"
    POST_FILING_VERIFICATION = "POST_FILING_VERIFICATION"


class SearchStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    DISCREPANCY = "DISCREPANCY"


class HitKind(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    SIMILAR = "SIMILAR"


class ReportMode(str, Enum):
    AS_OF_NOW = "AS_OF_NOW"
    FORWARD_PROJECTION = "FORWARD_PROJECTION"


class FilingEventType(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CONTINUED = "CONTINUED"
    AMENDED = "AMENDED"
    TERMINATED = "TERMINATED"
    LAPSED = "LAPSED"
    REVIVED = "REVIVED"
    REFLECTED = "REFLECTED"
    DISCREPANCY_FLAGGED = "DISCREPANCY_FLAGGED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_MANAGER = "ClientManager"
    FILING_SPECIALIST = "FilingSpecialist"
    FILING_REVIEWER = "FilingReviewer"
    FILING_OFFICER = "FilingOfficer"
    SEARCH_ANALYST = "SearchAnalyst"


# ---------------------------------------------------------------------------
# Entity TypedDicts — primary resources carry id + created_at + updated_at + version
# ---------------------------------------------------------------------------

class ClientAccount(TypedDict, total=False):
    id: str
    name: str
    status: str
    fees_charged_total_cents: int
    fees_refunded_total_cents: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionProfile(TypedDict, total=False):
    id: str
    state_code: str
    base_fee_cents: int
    per_additional_debtor_fee_cents: int
    county_surcharge_cents: int
    county_filing_collateral_classes: List[str]
    county_names: List[str]
    individual_name_rule: str
    expedited_daily_capacity: int
    created_at: str
    updated_at: str
    version: int


class Debtor(TypedDict, total=False):
    id: str
    client_id: str
    debtor_type: str
    legal_name: str
    jurisdiction_of_formation: Optional[str]
    drivers_license_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecuredParty(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    reference_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilingRequest(TypedDict, total=False):
    id: str
    client_id: str
    kind: str
    debtor_id: str
    secured_party_id: str
    jurisdiction_code: str
    collateral_class: str
    county_name: Optional[str]
    service_level: str
    additional_debtor_count: int
    fee_authorization_cents: int
    target_filing_id: Optional[str]
    supporting_search_id: Optional[str]
    filing_office: Optional[str]
    quoted_fee_cents: Optional[int]
    intake_submitted_by_user_id: Optional[str]
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UCCFiling(TypedDict, total=False):
    id: str
    filing_request_id: str
    filing_kind: str
    root_filing_id: Optional[str]
    supersedes_attempt_id: Optional[str]
    debtor_id: str
    secured_party_id: str
    jurisdiction_code: str
    filing_office: str
    county_name: Optional[str]
    debtor_name_on_filing: str
    collateral_text: Optional[str]
    amendment_scope: Optional[str]
    collateral_change_op: Optional[str]
    secured_amount_cents: int
    charged_fee_cents: Optional[int]
    filing_number: Optional[str]
    submitted_at: Optional[str]
    filed_at: Optional[str]
    rejected_at: Optional[str]
    rejection_reason_code: Optional[str]
    expiration_at: Optional[str]
    effectiveness_status: str
    reflection_status: str
    open_ucc3_request_count: int
    created_at: str
    updated_at: str
    version: int


class LienSearch(TypedDict, total=False):
    id: str
    client_id: str
    purpose: str
    debtor_id: str
    jurisdiction_code: str
    county_name: Optional[str]
    subject_filing_id: Optional[str]
    status: str
    through_date: Optional[str]
    prior_lien_count: Optional[int]
    priority_position_of_subject: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable records: only id + created_at (no updated_at, no version) — PRD §2.5
# ---------------------------------------------------------------------------

class SearchResultHit(TypedDict, total=False):
    id: str
    lien_search_id: str
    found_debtor_name: str
    found_filing_number: str
    found_filed_at: str
    secured_party_name: str
    hit_kind: str
    is_subject_filing: bool
    created_at: str


class PerfectionReport(TypedDict, total=False):
    id: str
    client_id: str
    mode: str
    horizon_days: int
    as_of: str
    active_count: int
    perfected_count: int
    unreflected_count: int
    expiring_within_horizon_count: int
    lapsed_count: int
    terminated_count: int
    projected_lapsed_count: int
    perfected_exposure_cents: int
    unperfected_exposure_cents: int
    projected_lapsed_exposure_cents: int
    created_at: str


class FilingEvent(TypedDict, total=False):
    id: str
    ucc_filing_id: str
    event_type: str
    event_detail: dict
    occurred_at: str
    created_at: str
