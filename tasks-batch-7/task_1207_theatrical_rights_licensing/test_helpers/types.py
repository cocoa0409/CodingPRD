"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class TitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class TitleKind(str, Enum):
    PLAY = "PLAY"
    MUSICAL = "MUSICAL"
    MUSICAL_WITH_SCORE = "MUSICAL_WITH_SCORE"


class RoyaltyBasis(str, Enum):
    PER_PERFORMANCE = "PER_PERFORMANCE"
    GROSS_PERCENT = "GROSS_PERCENT"
    HYBRID = "HYBRID"


class RestrictionKind(str, Enum):
    BLACKOUT = "BLACKOUT"
    EXCLUSIVE_RUN = "EXCLUSIVE_RUN"
    PRO_TOUR_OVERLAP = "PRO_TOUR_OVERLAP"


class BlocksClassification(str, Enum):
    AMATEUR = "AMATEUR"
    PROFESSIONAL = "PROFESSIONAL"
    BOTH = "BOTH"


class OrgKind(str, Enum):
    SCHOOL = "SCHOOL"
    COMMUNITY = "COMMUNITY"
    SEMI_PRO = "SEMI_PRO"
    PROFESSIONAL_COMPANY = "PROFESSIONAL_COMPANY"


class OrgStanding(str, Enum):
    GOOD = "GOOD"
    SUSPENDED = "SUSPENDED"


class Classification(str, Enum):
    AMATEUR = "AMATEUR"
    PROFESSIONAL = "PROFESSIONAL"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LicenseStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    BREACHED = "BREACHED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class RoyaltyMode(str, Enum):
    QUOTED = "QUOTED"
    SETTLED = "SETTLED"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    RETURN_IN_TRANSIT = "RETURN_IN_TRANSIT"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    LOST = "LOST"


class DepositStatus(str, Enum):
    HELD = "HELD"
    RETURNED = "RETURNED"
    FORFEITED = "FORFEITED"
    PARTIALLY_FORFEITED = "PARTIALLY_FORFEITED"


class AlterationKind(str, Enum):
    CUT = "CUT"
    GENDER_SWAP = "GENDER_SWAP"
    TEXT_CHANGE = "TEXT_CHANGE"
    STAGING_CHANGE = "STAGING_CHANGE"
    TRANSLATION = "TRANSLATION"


class AlterationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class GrantKind(str, Enum):
    CAST_RECORDING_AUDIO = "CAST_RECORDING_AUDIO"
    STREAMING_VIDEO = "STREAMING_VIDEO"
    ARCHIVAL_VIDEO = "ARCHIVAL_VIDEO"


class DistributionScope(str, Enum):
    CAST_CREW_ONLY = "CAST_CREW_ONLY"
    PAYWALL = "PAYWALL"
    PUBLIC_FREE = "PUBLIC_FREE"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXERCISED = "EXERCISED"
    REVOKED = "REVOKED"


class FineKind(str, Enum):
    OVERDUE_MATERIAL = "OVERDUE_MATERIAL"
    UNAUTHORIZED_ALTERATION = "UNAUTHORIZED_ALTERATION"
    UNAUTHORIZED_RECORDING = "UNAUTHORIZED_RECORDING"
    LOSS = "LOSS"


class FineStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class UserRole(str, Enum):
    RIGHTS_ADMIN = "RightsAdmin"
    LICENSING_OFFICER = "LicensingOfficer"
    APPLICANT = "Applicant"
    MATERIALS_CLERK = "MaterialsClerk"
    FINANCE_OFFICER = "FinanceOfficer"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---


class Title(TypedDict, total=False):
    id: str
    name: str
    author: str
    title_kind: str
    royalty_basis: str
    base_flat_fee_cents: int
    gross_percent_bp: int
    restricted_material: bool
    perusal_fee_cents: int
    rental_deposit_cents: int
    late_fee_per_day_cents: int
    restricted_late_fee_per_day_cents: int
    recording_royalty_flat_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TerritoryRestriction(TypedDict, total=False):
    id: str
    title_id: str
    territory_code: str
    restriction_kind: str
    window_start: str
    window_end: str
    blocks_classification: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Organization(TypedDict, total=False):
    id: str
    legal_name: str
    org_kind: str
    home_territory_code: str
    standing: str
    created_at: str
    updated_at: str
    version: int


class LicenseApplication(TypedDict, total=False):
    id: str
    title_id: str
    organization_id: str
    requested_territory_code: str
    requested_classification: str
    venue_seating_capacity: int
    ticket_top_price_cents: int
    performers_compensated: bool
    admission_charged: bool
    projected_gross_cents: int
    performance_count: int
    first_performance_date: str
    last_performance_date: str
    determined_classification: str
    status: str
    submitted_at: Optional[str]
    review_round: int
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    application_id: str
    title_id: str
    organization_id: str
    territory_code: str
    classification: str
    house_seating_capacity: int
    contracted_performance_count: int
    window_start: str
    window_end: str
    royalty_mode: str
    quoted_royalty_total_cents: int
    settled_royalty_total_cents: Optional[int]
    royalty_balance_cents: int
    license_status: str
    payment_status: str
    amendment_seq: int
    supersedes_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict, total=False):
    id: str
    agreement_id: str
    performance_at: str
    reported_attendance: int
    reported_gross_cents: int
    gross_reported: bool
    royalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialRental(TypedDict, total=False):
    id: str
    agreement_id: str
    scripts_qty: int
    scores_qty: int
    deposit_cents: int
    deposit_status: str
    due_date: str
    returned_at: Optional[str]
    accrued_late_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AlterationRequest(TypedDict, total=False):
    id: str
    agreement_id: str
    alteration_kind: str
    description: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecordingGrant(TypedDict, total=False):
    id: str
    agreement_id: str
    grant_kind: str
    distribution_scope: str
    recording_royalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# RoyaltyPayment: common_fields false (append-only) — only id + created_at
class RoyaltyPayment(TypedDict, total=False):
    id: str
    agreement_id: str
    amount_cents: int
    paid_at: str
    created_at: str


class Fine(TypedDict, total=False):
    id: str
    organization_id: str
    rental_id: Optional[str]
    agreement_id: Optional[str]
    fine_kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# AvailabilitySnapshot: common_fields false — only id + created_at
class AvailabilitySnapshot(TypedDict, total=False):
    id: str
    title_id: str
    territory_code: str
    classification: str
    window_start: str
    window_end: str
    available: bool
    blocking_restriction_ids: List[str]
    blocking_agreement_ids: List[str]
    computed_at: str
    created_at: str
