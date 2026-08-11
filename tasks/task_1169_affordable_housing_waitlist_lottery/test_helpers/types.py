"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3).

Every resource carries the common system-managed fields of PRD §2.4:
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    HOUSING_DEVELOPER = "HousingDeveloper"
    MARKETING_COORDINATOR = "MarketingCoordinator"
    APPLICATION_CLERK = "ApplicationClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LOTTERY_ADMINISTRATOR = "LotteryAdministrator"
    FUNDING_AGENCY_AUDITOR = "FundingAgencyAuditor"
    APPLICANT = "Applicant"
    ANONYMOUS = "Anonymous"


class BedroomCount(str, Enum):
    STUDIO = "STUDIO"
    ONE_BR = "ONE_BR"
    TWO_BR = "TWO_BR"
    THREE_BR = "THREE_BR"


class AmiTier(str, Enum):
    AMI_30 = "AMI_30"
    AMI_50 = "AMI_50"
    AMI_60 = "AMI_60"
    AMI_80 = "AMI_80"


class AccessibilityFeature(str, Enum):
    NONE = "NONE"
    MOBILITY = "MOBILITY"
    HEARING_VISION = "HEARING_VISION"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    LEASED = "LEASED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOTTERY_COMPLETED = "LOTTERY_COMPLETED"
    LEASING = "LEASING"
    PURGE_SCHEDULED = "PURGE_SCHEDULED"
    PURGED = "PURGED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ProvisionalDetermination(str, Enum):
    PROVISIONALLY_ELIGIBLE = "PROVISIONALLY_ELIGIBLE"
    PROVISIONALLY_OVER_INCOME = "PROVISIONALLY_OVER_INCOME"
    UNASSESSED = "UNASSESSED"


class PreferenceCategory(str, Enum):
    LOCAL_RESIDENT = "LOCAL_RESIDENT"
    VETERAN = "VETERAN"
    ACCESSIBILITY = "ACCESSIBILITY"


class PreferenceClaimStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"


class IncomeCertificationStatus(str, Enum):
    INITIATED = "INITIATED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    DOCS_RECEIVED = "DOCS_RECEIVED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"


class CertDetermination(str, Enum):
    ELIGIBLE = "ELIGIBLE"


class LotteryRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    EXECUTED = "EXECUTED"
    PUBLISHED = "PUBLISHED"
    VOIDED = "VOIDED"


class WaitlistEntryStatus(str, Enum):
    RANKED = "RANKED"
    OFFERED = "OFFERED"
    LEASED = "LEASED"
    REMOVED = "REMOVED"


class RemovalReason(str, Enum):
    MAX_REFUSALS = "MAX_REFUSALS"
    PURGED = "PURGED"
    LOTTERY_VOIDED = "LOTTERY_VOIDED"
    ADMIN_REMOVED = "ADMIN_REMOVED"


class UnitOfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class PurgeRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTICES_SENT = "NOTICES_SENT"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class ComplianceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETURNED = "RETURNED"


class PeriodMode(str, Enum):
    CALENDAR_QUARTER = "CALENDAR_QUARTER"
    ROLLING_90_DAY = "ROLLING_90_DAY"


class MarketingChannel(str, Enum):
    COMMUNITY_MEETING = "COMMUNITY_MEETING"
    LOCAL_NEWSPAPER = "LOCAL_NEWSPAPER"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    HOUSING_AUTHORITY_WEBSITE = "HOUSING_AUTHORITY_WEBSITE"
    MAILERS = "MAILERS"


# --- Entity record shapes (all carry the PRD §2.4 common fields) ---

class Property(TypedDict, total=False):
    id: str
    name: str
    address_line: str
    city: str
    state_code: str
    units_total: int
    units_available_count: int
    units_reserved_count: int
    units_leased_count: int
    units_out_of_service_count: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    property_id: str
    unit_number: str
    bedroom_count: str
    ami_tier: str
    accessibility_feature: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OccupancyStandard(TypedDict, total=False):
    id: str
    property_id: str
    bedroom_count: str
    min_occupants: int
    max_occupants: int
    uniqueness_scope: str
    created_at: str
    updated_at: str
    version: int


class AmiLimit(TypedDict, total=False):
    id: str
    property_id: str
    household_size: int
    ami_tier: str
    annual_limit_cents: int
    uniqueness_scope: str
    created_at: str
    updated_at: str
    version: int


class ApplicationCampaign(TypedDict, total=False):
    id: str
    property_id: str
    name: str
    application_open_at: str
    application_close_at: str
    marketing_channels: List[str]
    marketing_plan_summary: str
    target_ami_tier: str
    status: str
    applications_received_count: int
    waitlist_active_count: int
    entries_leased_count: int
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    campaign_id: str
    household_size: int
    self_reported_annual_income_cents: int
    confirmation_code: str
    provisional_determination: str
    verified_preference_categories: List[str]
    status: str
    verified_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreferenceClaim(TypedDict, total=False):
    id: str
    application_id: str
    category: str
    evidence_ref: str
    status: str
    denial_reason: Optional[str]
    decided_at: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeSource(TypedDict):
    source_type: str
    amount_per_period_cents: int
    periods_per_year: int


class IncomeCertification(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    required_docs: List[str]
    income_sources: List[IncomeSource]
    certified_annual_income_cents: Optional[int]
    ami_percentage_bp: Optional[int]
    determination: Optional[str]
    certified_at: Optional[str]
    certified_by: Optional[str]
    valid_until: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotteryRun(TypedDict, total=False):
    id: str
    campaign_id: str
    seed: str
    status: str
    eligible_application_count: Optional[int]
    entries_generated: Optional[int]
    sealed_by: Optional[str]
    executed_by: Optional[str]
    published_by: Optional[str]
    sealed_at: Optional[str]
    executed_at: Optional[str]
    published_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    lottery_run_id: str
    campaign_id: str
    application_id: str
    base_rank: int
    preference_tier: int
    effective_rank: int
    refusal_count: int
    last_confirmed_at: Optional[str]
    removal_reason: Optional[str]
    removed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UnitOffer(TypedDict, total=False):
    id: str
    campaign_id: str
    entry_id: str
    unit_id: str
    offered_at: str
    response_deadline: str
    responded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurgeRun(TypedDict, total=False):
    id: str
    campaign_id: str
    notice_response_days: int
    status: str
    notice_sent_at: Optional[str]
    response_deadline: Optional[str]
    executed_at: Optional[str]
    entries_removed_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict, total=False):
    id: str
    campaign_id: str
    period_start: str
    period_end: str
    period_mode: str
    applications_received_count: int
    applications_verified_count: int
    preference_claims_decided_count: int
    preference_claims_verified_count: int
    preference_verification_rate_bp: int
    lottery_runs_executed_count: int
    offers_made_count: int
    offers_accepted_count: int
    entries_removed_count: int
    lease_up_rate_bp: int
    status: str
    submitted_by: Optional[str]
    submitted_at: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
