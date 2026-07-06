"""Domain types: entity TypedDicts, status enums, role enum.

All field names and statuses follow the SEO & Digital-Marketing Agency PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    RESELLER = "Reseller"
    CLIENT = "Client"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ResellerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    AUDITED = "AUDITED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CHURNED = "CHURNED"


class KeywordTargetStatus(str, Enum):
    PLANNED = "PLANNED"
    TRACKING = "TRACKING"
    DROPPED = "DROPPED"


class RetainerStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SprintStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DeliverableStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DeliverableKind(str, Enum):
    CONTENT = "CONTENT"
    BACKLINK = "BACKLINK"
    TECHNICAL = "TECHNICAL"


class DeliverableComplexity(str, Enum):
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


class AdCampaignLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class AdCampaignBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class AdChannel(str, Enum):
    GOOGLE_ADS = "GOOGLE_ADS"
    META = "META"
    BING = "BING"


class AdSpendDisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class GbpListingStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    OPTIMIZED = "OPTIMIZED"
    SUSPENDED = "SUSPENDED"


class RetainerTier(str, Enum):
    STARTER = "STARTER"
    GROWTH = "GROWTH"
    DOMINATE = "DOMINATE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (SiteAudit, RankSnapshot, Report)
# ---------------------------------------------------------------------------
class Reseller(TypedDict):
    id: str
    brand_name: str
    markup_pct: float
    ppc_management_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    reseller_id: Optional[str]
    company_name: str
    primary_domain: str
    status: str
    health_score: int
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only recorded crawl result
class SiteAudit(TypedDict):
    id: str
    client_id: str
    technical_score: int
    content_score: int
    backlink_score: int
    composite_score: int
    created_at: str


class KeywordTarget(TypedDict):
    id: str
    client_id: str
    phrase: str
    search_volume: int
    difficulty: int
    priority_score: float
    current_rank: int
    best_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — single immutable SERP reading
class RankSnapshot(TypedDict):
    id: str
    keyword_target_id: str
    position: int
    organic_traffic: int
    observed_at: str
    created_at: str


class Retainer(TypedDict):
    id: str
    client_id: str
    tier: str
    monthly_credits: int
    wholesale_price_cents: int
    rollover_cap_pct: float
    credits_granted: int
    credits_committed: int
    credits_consumed: int
    credits_available: int
    billing_price_cents: int
    cycle_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    client_id: str
    retainer_id: str
    term_cycles: int
    auto_renew: bool
    early_termination_fee_cents: int
    cycles_elapsed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sprint(TypedDict):
    id: str
    client_id: str
    retainer_id: str
    name: str
    starts_at: str
    ends_at: str
    capacity_credits: int
    committed_credits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    client_id: str
    retainer_id: str
    sprint_id: str
    kind: str
    complexity: str
    credit_cost: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict):
    id: str
    client_id: str
    retainer_id: str
    channel: str
    budget_cents: int
    spent_cents: int
    management_fee_cents: int
    lifecycle_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class AdSpendDispute(TypedDict):
    id: str
    ad_campaign_id: str
    client_id: str
    disputed_cents: int
    credited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GbpListing(TypedDict):
    id: str
    client_id: str
    location_name: str
    service_area: str
    optimization_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — generated point-in-time summary
class Report(TypedDict):
    id: str
    client_id: str
    period_start: str
    period_end: str
    avg_rank: float
    total_traffic: int
    rank_momentum: float
    created_at: str
