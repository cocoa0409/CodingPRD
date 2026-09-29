"""Domain types for the Audience Measurement Panel Operations API.

Role enum, every status/enumeration the PRD names, and one TypedDict per
entity. Field names are exactly the names the PRD uses; nothing is abbreviated,
renamed or inferred. Every entity in this system carries the same four
system-managed properties described in PRD 2.5, so each TypedDict below starts
from :class:`CommonRecord`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Roles (PRD 2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    PANEL_OPERATIONS_MANAGER = "PanelOperationsManager"
    FIELD_TECHNICIAN = "FieldTechnician"
    METHODOLOGY_STATISTICIAN = "MethodologyStatistician"
    CLIENT_SERVICE_REP = "ClientServiceRep"
    CLIENT_USER = "ClientUser"
    ACCREDITATION_AUDITOR = "AccreditationAuditor"
    GOVERNANCE_DIRECTOR = "GovernanceDirector"


ALL_ROLES = tuple(role.value for role in UserRole)

# The two confidential read surfaces of PRD 2.1 admit only these three roles.
CONFIDENTIAL_READ_ROLES = (
    UserRole.PANEL_OPERATIONS_MANAGER.value,
    UserRole.METHODOLOGY_STATISTICIAN.value,
    UserRole.ACCREDITATION_AUDITOR.value,
)
CLIENT_FACING_ROLES = (
    UserRole.FIELD_TECHNICIAN.value,
    UserRole.CLIENT_SERVICE_REP.value,
    UserRole.CLIENT_USER.value,
    UserRole.GOVERNANCE_DIRECTOR.value,
)


# ── Market (PRD 3.1) ─────────────────────────────────────────────────────

class RecruitmentPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"
    FROZEN = "FROZEN"


class AccreditationStatus(str, Enum):
    UNAUDITED = "UNAUDITED"
    ACCREDITED = "ACCREDITED"
    QUALIFIED = "QUALIFIED"
    DENIED = "DENIED"


# ── Quota cell (PRD 3.1) ─────────────────────────────────────────────────

class AgeBand(str, Enum):
    P18_34 = "P18_34"
    P35_54 = "P35_54"
    P55_PLUS = "P55_PLUS"


class IncomeBand(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class GeoZone(str, Enum):
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class QuotaStatus(str, Enum):
    UNDER_TARGET = "UNDER_TARGET"
    ON_TARGET = "ON_TARGET"
    FILLED = "FILLED"


# ── Household (PRD 3.2) ──────────────────────────────────────────────────

class HouseholdStatus(str, Enum):
    RECRUITED = "RECRUITED"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    ENUM_PENDING = "ENUM_PENDING"
    ACTIVE = "ACTIVE"
    FAULT_HOLD = "FAULT_HOLD"
    NONCOMPLIANT_HOLD = "NONCOMPLIANT_HOLD"
    RETIRED = "RETIRED"


class RecruitmentSource(str, Enum):
    ADDRESS_SAMPLE = "ADDRESS_SAMPLE"
    RDD_PHONE = "RDD_PHONE"
    ONLINE_PANEL_TRANSFER = "ONLINE_PANEL_TRANSFER"


class EnumerationVerdict(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"


# ── Meter (PRD 3.3) ──────────────────────────────────────────────────────

class MeterType(str, Enum):
    TV_TUNER = "TV_TUNER"
    STREAMING_ROUTER = "STREAMING_ROUTER"
    PORTABLE_OOH = "PORTABLE_OOH"


class InstallStatus(str, Enum):
    SHIPPED = "SHIPPED"
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    FAULTED = "FAULTED"


class FaultCode(str, Enum):
    NO_SIGNAL = "NO_SIGNAL"
    POWER_LOSS = "POWER_LOSS"
    TAMPER = "TAMPER"
    CLOCK_DRIFT = "CLOCK_DRIFT"
    MISSING_INTERVALS = "MISSING_INTERVALS"


# ── Tuning interval (PRD 3.6) ────────────────────────────────────────────

class SourceMethodology(str, Enum):
    INHOME_TUNER = "INHOME_TUNER"
    STREAMING_SDK = "STREAMING_SDK"
    PORTABLE_OOH = "PORTABLE_OOH"


class IntervalState(str, Enum):
    RAW = "RAW"
    EDITED = "EDITED"
    ASCRIBED = "ASCRIBED"
    INVALIDATED = "INVALIDATED"


class InvalidationReason(str, Enum):
    OVER_MAX_TUNING = "OVER_MAX_TUNING"
    METER_FAULTED = "METER_FAULTED"
    OUTLIER_HOUSEHOLD = "OUTLIER_HOUSEHOLD"


# ── Universe estimate and edit rule set (PRD 3.5) ────────────────────────

class UniverseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RuleSetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# ── Processing run (PRD 3.6, 3.7) ────────────────────────────────────────

class RunState(str, Enum):
    OPEN = "OPEN"
    EDITED = "EDITED"
    WEIGHTED = "WEIGHTED"
    PENDING_REPIN = "PENDING_REPIN"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class WeightVariant(str, Enum):
    DESIGN = "DESIGN"
    FINAL = "FINAL"


class RepinReason(str, Enum):
    UNIVERSE_SUPERSEDED = "UNIVERSE_SUPERSEDED"
    RULE_SET_SUPERSEDED = "RULE_SET_SUPERSEDED"


class LimitationDisclosure(str, Enum):
    """Disclosure tokens the edit and weighting passes append (PRD 3.6, 3.7)."""

    OUTLIER_HOUSEHOLDS_EXCLUDED = "OUTLIER_HOUSEHOLDS_EXCLUDED"
    ASCRIBED_INTERVALS_PRESENT = "ASCRIBED_INTERVALS_PRESENT"
    CELL_NO_CONTRIBUTORS = "CELL_NO_CONTRIBUTORS"
    WEIGHT_CAP_APPLIED = "WEIGHT_CAP_APPLIED"


# ── Client and deliverable (PRD 3.8) ─────────────────────────────────────

class ClientTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DeliverableKind(str, Enum):
    SCHEDULED_DATASET = "SCHEDULED_DATASET"
    CUSTOM_ANALYSIS = "CUSTOM_ANALYSIS"


class DeliverableState(str, Enum):
    SCHEDULED = "SCHEDULED"
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    HELD = "HELD"


class HoldReason(str, Enum):
    CLIENT_REQUESTED = "CLIENT_REQUESTED"
    DATA_QUALITY_REVIEW = "DATA_QUALITY_REVIEW"
    UPSTREAM_RUN_REPIN = "UPSTREAM_RUN_REPIN"


# ── Governance (PRD 3.9) ─────────────────────────────────────────────────

class ChangeState(str, Enum):
    DRAFT = "DRAFT"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    NOTIFIED = "NOTIFIED"
    EFFECTIVE = "EFFECTIVE"


class ImpactTier(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MATERIAL = "MATERIAL"


class NotificationState(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CANCELLED = "CANCELLED"


class AuditState(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class AuditOutcome(str, Enum):
    ACCREDITED = "ACCREDITED"
    QUALIFIED = "QUALIFIED"
    DENIED = "DENIED"


# ── Entity shapes ────────────────────────────────────────────────────────
#
# PRD 2.5: "Every resource in this system ... carries the same four
# system-managed properties": `id`, `created_at`, `updated_at`, `version`.

class CommonRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Market(CommonRecord, total=False):
    name: str
    market_code: str
    dma_rank: int
    incentive_budget_cents: int
    incentive_budget_committed_cents: int
    incentive_budget_reserved_cents: int
    quota_cell_count: int
    filled_cell_count: int
    under_target_cell_count: int
    open_audit_count: int
    recruitment_posture: str
    posture_changed_at: str
    accreditation_status: str
    publication_blocked: bool
    limitation_disclosures: List[str]


class QuotaCell(CommonRecord, total=False):
    market_id: str
    age_band: str
    income_band: str
    geo_zone: str
    target_households: int
    base_incentive_cents: int
    intab_count: int
    fill_rate: float
    quota_status: str
    incentive_boost_active: bool
    effective_incentive_multiplier: float


class CellPopulation(TypedDict, total=False):
    quota_cell_id: str
    population_households: int
    population_persons: int


class UniverseEstimate(CommonRecord, total=False):
    market_id: str
    vintage_label: str
    effective_from: str
    effective_to: str
    cell_populations: List[CellPopulation]
    total_population_households: int
    total_population_persons: int
    status: str
    published_at: Optional[str]
    superseded_at: Optional[str]


class AccrualPeriod(TypedDict, total=False):
    period_label: str
    accrued_cents: int
    reversed: bool


class Household(CommonRecord, total=False):
    market_id: str
    quota_cell_id: str
    recruitment_source: str
    persons_count: int
    recruited_at: str
    status: str
    roster_persons_count: Optional[int]
    tv_sets_count: Optional[int]
    enumeration_count: int
    enumeration_verdict: str
    last_enumeration_at: Optional[str]
    compliance_rate_rolling_30: float
    incentive_accrued_cents: int
    accrual_periods: List[AccrualPeriod]
    retired_reason: Optional[str]


class Meter(CommonRecord, total=False):
    household_id: str
    meter_type: str
    serial_no: str
    install_status: str
    installed_at: Optional[str]
    health_status: str
    fault_count: int
    last_fault_code: Optional[str]
    missing_minutes_last_scan: Optional[int]


class TuningInterval(CommonRecord, total=False):
    meter_id: str
    household_id: str
    source_methodology: str
    start_iso: str
    end_iso: str
    station_code: str
    tuning_minutes: int
    processing_run_id: Optional[str]
    usable_minutes: int
    state: str
    invalidation_reason: Optional[str]
    ascribed: bool


class EditRuleSet(CommonRecord, total=False):
    label: str
    missing_interval_ascription_minutes: int
    invalid_tuning_max_minutes: int
    outlier_household_minutes_cap: int
    outlier_weight_ratio_cap: float
    fault_missing_minutes_threshold: int
    status: str
    published_at: Optional[str]


class ProcessingRun(CommonRecord, total=False):
    market_id: str
    universe_estimate_id: str
    edit_rule_set_id: str
    window_start_iso: str
    window_end_iso: str
    window_minutes: int
    state: str
    opened_by_user_id: str
    published_by_user_id: Optional[str]
    weight_variant: Optional[str]
    intab_snapshot_count: int
    contributing_household_count: int
    ascribed_interval_count: int
    invalidated_interval_count: int
    outlier_household_count: int
    excluded_cell_count: int
    total_weight_mass: float
    projected_average_audience: Optional[int]
    limitation_disclosures: List[str]
    repin_required_reason: Optional[str]
    superseded_by_run_id: Optional[str]


class HouseholdWeight(CommonRecord, total=False):
    processing_run_id: str
    household_id: str
    weight_variant: str
    base_weight: float
    adjusted_weight: float
    usable_minutes: int
    contribution: float
    run_compliance_rate: float
    capped: bool


class Client(CommonRecord, total=False):
    name: str
    tier: str
    contract_market_ids: List[str]
    status: str
    tier_base_fee_cents: int
    delivery_sla_hours: int
    custom_analysis_quota: int
    custom_analysis_used: int
    held_deliverable_count: int
    delivery_sla_credit_cents: int
    suspended_reason: Optional[str]


class ClientDeliverable(CommonRecord, total=False):
    client_id: str
    processing_run_id: str
    kind: str
    state: str
    held_from_state: Optional[str]
    hold_reason: Optional[str]
    question: Optional[str]
    requested_cell_count: int
    due_at: Optional[str]
    delivered_at: Optional[str]
    revision_count: int
    gross_cents: Optional[int]
    late_penalty_cents: Optional[int]
    discount_cents: Optional[int]
    total_cents: Optional[int]
    days_late: Optional[int]
    findings_summary: Optional[str]


class ClientNotification(CommonRecord, total=False):
    methodology_change_id: str
    client_id: str
    impact_tier: str
    disclosed_delta_pct: float
    state: str
    sent_at: str
    acknowledged_at: Optional[str]


class MethodologyChange(CommonRecord, total=False):
    title: str
    target_edit_rule_set_id: str
    proposed_edit_rule_set_id: str
    supersedes_change_id: Optional[str]
    affected_market_ids: List[str]
    state: str
    created_by_user_id: str
    baseline_processing_run_id: Optional[str]
    baseline_projected_average_audience: Optional[int]
    impact_delta_pct: Optional[float]
    impact_tier: Optional[str]
    notification_lead_hours: Optional[int]
    notification_deadline_at: Optional[str]
    notified_client_count: int
    acknowledged_client_count: int
    revision_count: int
    activated_at: Optional[str]


class AccreditationAudit(CommonRecord, total=False):
    market_id: str
    scope_edit_rule_set_id: str
    auditor_note: str
    state: str
    outcome: Optional[str]
    opened_by_user_id: str
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    limitation_disclosures: List[str]


AnyRecord = Dict[str, Any]
