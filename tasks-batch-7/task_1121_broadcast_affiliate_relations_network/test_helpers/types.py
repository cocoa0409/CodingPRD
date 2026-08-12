"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry common_fields (id, created_at, updated_at,
version) per PRD §2.4. Status enums reflect the §3 narratives.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    NETWORK_AFFILIATE_RELATIONS = "NetworkAffiliateRelations"
    STATION_GROUP_OWNER = "StationGroupOwner"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class NetworkPosture(str, Enum):
    NORMAL = "NORMAL"
    SWEEP_LOCKDOWN = "SWEEP_LOCKDOWN"
    DISPUTE_FREEZE = "DISPUTE_FREEZE"


class StationPosture(str, Enum):
    CLEARANCE_OK = "CLEARANCE_OK"
    CLEARANCE_DEFICIENT = "CLEARANCE_DEFICIENT"
    DARK = "DARK"


class LeverageTier(str, Enum):
    SMALL = "SMALL"
    MID = "MID"
    LARGE = "LARGE"
    MAJOR = "MAJOR"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    RENEWAL_NEGOTIATION = "RENEWAL_NEGOTIATION"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class ClearanceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AUDITED = "AUDITED"
    CLEARED = "CLEARED"
    DISPUTED = "DISPUTED"


class PreemptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    COUNTERED = "COUNTERED"
    WITHDRAWN = "WITHDRAWN"


class PreemptionReason(str, Enum):
    BREAKING_NEWS = "BREAKING_NEWS"
    LOCAL_SPORTS = "LOCAL_SPORTS"
    EMERGENCY = "EMERGENCY"
    POLITICAL = "POLITICAL"
    OTHER = "OTHER"


class AvailAllocationStatus(str, Enum):
    CLAIMED = "CLAIMED"
    CONFIRMED = "CONFIRMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RetransSettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    RECONCILED = "RECONCILED"
    VOID = "VOID"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class OutageEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class OutageCause(str, Enum):
    TRANSMITTER_FAILURE = "TRANSMITTER_FAILURE"
    FIBER_CUT = "FIBER_CUT"
    SATELLITE_JAM = "SATELLITE_JAM"
    POWER_LOSS = "POWER_LOSS"
    PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE"


class OutageCreditStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    FORFEITED = "FORFEITED"


class RenewalOfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ProposerRole(str, Enum):
    NETWORK_AFFILIATE_RELATIONS = "NETWORK_AFFILIATE_RELATIONS"
    STATION_GROUP_OWNER = "STATION_GROUP_OWNER"


class ComplianceReportStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    AUDITED = "AUDITED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ComplianceReportKind(str, Enum):
    FCC_302 = "FCC_302"
    CHILDRENS_TELEVISION = "CHILDRENS_TELEVISION"
    EEO = "EEO"
    POLITICAL_FILE = "POLITICAL_FILE"


class ExclusivityClaimStatus(str, Enum):
    FILED = "FILED"
    VALIDATED = "VALIDATED"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry common fields per PRD §2.4)
# ---------------------------------------------------------------------------

class Network(TypedDict, total=False):
    id: str
    call_sign: str
    primary_feed_tz: str
    reverse_comp_standard_pct: float
    retrans_share_standard_pct: float
    current_period_index: int
    posture: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class StationGroup(TypedDict, total=False):
    id: str
    group_name: str
    leverage_tier: str
    aggregate_retrans_cents: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict, total=False):
    id: str
    station_group_id: str
    call_sign: str
    dma_code: str
    network_id: str
    posture: str
    monthly_outage_minutes_current_period: int
    clearance_rate_current_period: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict, total=False):
    id: str
    network_id: str
    dma_code: str
    exclusivity_holder_station_id: Optional[str]
    protection_window_start_utc: str
    protection_window_end_utc: str
    created_at: str
    updated_at: str
    version: int


class AffiliationAgreement(TypedDict, total=False):
    id: str
    station_id: str
    network_id: str
    term_start_utc: str
    term_end_utc: str
    reverse_comp_pct: float
    retrans_share_pct: float
    clearance_obligation_hours: int
    status: str
    renewal_round_count: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    network_id: str
    title: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    avail_minutes_total: int
    avail_minutes_local_allocatable: int
    is_syndicated: bool
    created_at: str
    updated_at: str
    version: int


class ClearanceReport(TypedDict, total=False):
    id: str
    station_id: str
    period_index: int
    cleared_hours: float
    preempted_hours: float
    status: str
    clearance_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PreemptionRequest(TypedDict, total=False):
    id: str
    station_id: str
    program_id: str
    agreement_id: str
    requested_start_utc: str
    requested_end_utc: str
    reason: str
    status: str
    counter_start_utc: Optional[str]
    counter_end_utc: Optional[str]
    counter_round_count: int
    created_at: str
    updated_at: str
    version: int


class AvailAllocation(TypedDict, total=False):
    id: str
    station_id: str
    program_id: str
    period_index: int
    local_minutes_claimed: int
    status: str
    claimed_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class RetransSettlement(TypedDict, total=False):
    id: str
    station_id: str
    agreement_id: str
    period_index: int
    gross_retrans_cents: int
    net_retrans_cents: int
    network_share_cents: int
    variant_used: str
    status: str
    outage_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class OutageEvent(TypedDict, total=False):
    id: str
    station_id: str
    period_index: int
    started_at_utc: str
    ended_at_utc: str
    duration_minutes: int
    cause: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutageCredit(TypedDict, total=False):
    id: str
    station_id: str
    outage_event_id: str
    settlement_id: Optional[str]
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict, total=False):
    id: str
    agreement_id: str
    proposed_by_role: str
    proposed_reverse_comp_pct: float
    proposed_retrans_share_pct: float
    proposed_term_months: int
    round_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict, total=False):
    id: str
    station_id: str
    period_index: int
    report_kind: str
    status: str
    finding_count: int
    created_at: str
    updated_at: str
    version: int


class SyndicationExclusivityClaim(TypedDict, total=False):
    id: str
    territory_id: str
    program_id: str
    claimant_station_id: str
    respondent_station_id: str
    alleged_window_start_utc: str
    alleged_window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int
