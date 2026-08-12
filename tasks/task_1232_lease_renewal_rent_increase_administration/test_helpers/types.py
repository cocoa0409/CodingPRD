"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REGIONAL_DIRECTOR = "RegionalDirector"
    PROPERTY_MANAGER = "PropertyManager"
    LEASING_AGENT = "LeasingAgent"
    RESIDENT = "Resident"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    MTM = "MTM"
    NON_RENEWAL_NOTICED = "NON_RENEWAL_NOTICED"
    ENDED = "ENDED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ConcessionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SERVED = "SERVED"
    CONFIRMED = "CONFIRMED"
    ENFORCED = "ENFORCED"
    RESCINDED = "RESCINDED"


class DocumentStatus(str, Enum):
    GENERATED = "GENERATED"
    RESIDENT_SIGNED = "RESIDENT_SIGNED"
    COUNTERSIGNED = "COUNTERSIGNED"
    VOIDED = "VOIDED"
    RESCINDED = "RESCINDED"


class RateStrategy(str, Enum):
    AGGRESSIVE = "AGGRESSIVE"
    BALANCED = "BALANCED"
    CONSERVATIVE = "CONSERVATIVE"


class ResponseType(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    COUNTER = "COUNTER"


class CauseType(str, Enum):
    LEASE_VIOLATION = "LEASE_VIOLATION"
    REPEATED_LATE_PAYMENT = "REPEATED_LATE_PAYMENT"
    PROPERTY_REPOSITIONING = "PROPERTY_REPOSITIONING"
    OWNER_OCCUPANCY = "OWNER_OCCUPANCY"


# All nine primary resources carry the shared system-managed field set of
# PRD §2.5: id, created_at, updated_at, version.


class RentCapPolicy(TypedDict):
    id: str
    jurisdiction_code: str
    base_cap_bps: int
    cpi_adjustment_bps: int
    hard_ceiling_bps: int
    high_increase_threshold_bps: int
    notice_days_low: int
    notice_days_high: int
    non_renewal_notice_days: int
    effective_cap_bps: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    name: str
    rent_cap_policy_id: str
    min_term_months: int
    max_term_months: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    unit_number: str
    bedrooms: int
    current_market_rent_cents: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    unit_id: str
    resident_id: str
    property_id: str
    term_start_date: str
    term_months: int
    term_end_date: str
    monthly_rent_cents: int
    status: str
    status_before_offer: Optional[str]
    mtm_converted_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict):
    id: str
    lease_id: str
    rate_strategy: str
    offer_round: int
    base_rent_cents: int
    proposed_rent_cents: int
    proposed_increase_bps: int
    cap_bps_snapshot: int
    offered_term_months: int
    notice_days_required: int
    latest_issue_date: Optional[str]
    issued_on_date: Optional[str]
    issued_by_user_id: Optional[str]
    response_deadline_date: Optional[str]
    counter_rent_cents: Optional[int]
    counter_term_months: Optional[int]
    accepted_on_date: Optional[str]
    execution_deadline_date: Optional[str]
    executed_rent_cents: Optional[int]
    supersedes_offer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConcessionApproval(TypedDict):
    id: str
    offer_id: str
    requested_rent_cents: int
    reason: Optional[str]
    concession_bps: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NonRenewalNotice(TypedDict):
    id: str
    lease_id: str
    cause_type: str
    evidence_ref: Optional[str]
    effective_date: str
    served_on_date: Optional[str]
    cure_deadline_date: Optional[str]
    prior_lease_status: Optional[str]
    created_by_user_id: str
    served_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalDocument(TypedDict):
    id: str
    offer_id: str
    lease_id: str
    status: str
    executed_rent_cents: Optional[int]
    countersigned_on_date: Optional[str]
    rescind_deadline_date: Optional[str]
    prior_lease_status: Optional[str]
    prior_monthly_rent_cents: Optional[int]
    prior_term_start_date: Optional[str]
    prior_term_end_date: Optional[str]
    prior_term_months: Optional[int]
    created_at: str
    updated_at: str
    version: int
