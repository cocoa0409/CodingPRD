"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NetworkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LineOfBusiness(str, Enum):
    COMMERCIAL_HMO = "COMMERCIAL_HMO"
    COMMERCIAL_PPO = "COMMERCIAL_PPO"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    MEDICAID = "MEDICAID"


class BenchmarkStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED = "SIGNED"
    IN_CONFIGURATION = "IN_CONFIGURATION"
    IN_TESTING = "IN_TESTING"
    READY_FOR_GO_LIVE = "READY_FOR_GO_LIVE"
    ACTIVE = "ACTIVE"
    TERMINATION_NOTICE = "TERMINATION_NOTICE"
    TERMINATED = "TERMINATED"


class VersionStatus(str, Enum):
    DRAFT = "DRAFT"
    LOADED = "LOADED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class RateType(str, Enum):
    PERCENT_OF_MEDICARE = "PERCENT_OF_MEDICARE"
    FLAT_RATE = "FLAT_RATE"
    PER_DIEM = "PER_DIEM"
    CASE_RATE = "CASE_RATE"


class BenchmarkLookupMode(str, Enum):
    STRICT = "STRICT"
    PROVISIONAL = "PROVISIONAL"


class EntryStatus(str, Enum):
    STAGED = "STAGED"
    MAPPED = "MAPPED"
    LOCKED = "LOCKED"


class OverrideType(str, Enum):
    FLAT_RATE = "FLAT_RATE"
    PCT_OF_MEDICARE = "PCT_OF_MEDICARE"
    EXCLUDE = "EXCLUDE"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    PRICED = "PRICED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class ClaimOutcome(str, Enum):
    PENDING = "PENDING"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    EXCLUDED = "EXCLUDED"


class SnapshotStatus(str, Enum):
    OPEN = "OPEN"
    ADJUSTED = "ADJUSTED"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    COMPUTED = "COMPUTED"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    RECOVERED = "RECOVERED"
    VOIDED = "VOIDED"


class AdjustmentDirection(str, Enum):
    UNDERPAID = "UNDERPAID"
    OVERPAID = "OVERPAID"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EFFECTIVE = "EFFECTIVE"
    RESCINDED = "RESCINDED"


class ConditionCategory(str, Enum):
    INPATIENT_CONFINEMENT = "INPATIENT_CONFINEMENT"
    PREGNANCY = "PREGNANCY"
    DIALYSIS = "DIALYSIS"
    ONCOLOGY_TREATMENT = "ONCOLOGY_TREATMENT"
    TRANSPLANT_WORKUP = "TRANSPLANT_WORKUP"


class CaseStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NOTIFIED = "NOTIFIED"
    ACTIVE_COVERAGE = "ACTIVE_COVERAGE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CLOSED_RESCINDED = "CLOSED_RESCINDED"


class UserRole(str, Enum):
    PlanAdmin = "PlanAdmin"
    ContractManager = "ContractManager"
    ContractLegal = "ContractLegal"
    ConfigurationAnalyst = "ConfigurationAnalyst"
    PaymentIntegrityAnalyst = "PaymentIntegrityAnalyst"
    ProviderRep = "ProviderRep"


class Provider(TypedDict, total=False):
    id: str
    legal_name: str
    tin: str
    npi: str
    locality_code: str
    provider_status: str
    created_at: str
    updated_at: str
    version: int


class Network(TypedDict, total=False):
    id: str
    name: str
    line_of_business: str
    network_status: str
    created_at: str
    updated_at: str
    version: int


class MedicareBenchmark(TypedDict, total=False):
    id: str
    benchmark_year: int
    locality_code: str
    hcpcs_code: str
    benchmark_amount_cents: int
    benchmark_status: str
    created_at: str
    updated_at: str
    version: int


class RateParityRule(TypedDict, total=False):
    id: str
    line_of_business_a: str
    line_of_business_b: str
    band_bps: int
    rule_status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    provider_id: str
    network_id: str
    base_effective_date: str
    term_months: int
    escalator_bps: int
    escalator_mode: str
    auto_renew: bool
    contract_status: str
    negotiation_round: int
    submitted_by_user_id: Optional[str]
    signed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractVersion(TypedDict, total=False):
    id: str
    contract_id: str
    version_number: int
    effective_date: str
    retro_effective_date: Optional[str]
    version_status: str
    created_at: str
    updated_at: str
    version: int


class FeeScheduleEntry(TypedDict, total=False):
    id: str
    contract_version_id: str
    hcpcs_code: str
    service_category: str
    rate_type: str
    pct_of_medicare_bps: Optional[int]
    flat_rate_cents: Optional[int]
    benchmark_lookup_mode: str
    medicare_benchmark_id: Optional[str]
    resolved_benchmark_cents: Optional[int]
    computed_rate_cents: Optional[int]
    entry_status: str
    created_at: str
    updated_at: str
    version: int


class CarveOut(TypedDict, total=False):
    id: str
    contract_version_id: str
    service_category: str
    override_type: str
    override_flat_cents: Optional[int]
    override_pct_bps: Optional[int]
    start_date: str
    end_date: str
    priority_rank: int
    created_at: str
    updated_at: str
    version: int


class SimulationBatch(TypedDict, total=False):
    id: str
    contract_version_id: str
    label: str
    batch_status: str
    total_claims: int
    matched_claims: int
    mismatched_claims: int
    excluded_claims: int
    pending_claims: int
    total_priced_cents: int
    created_at: str
    updated_at: str
    version: int


class SimulationClaim(TypedDict, total=False):
    id: str
    simulation_batch_id: str
    hcpcs_code: str
    service_category: str
    service_date: str
    billed_cents: int
    los_days: int
    expected_allowed_cents: int
    priced_allowed_cents: Optional[int]
    claim_outcome: str
    created_at: str
    updated_at: str
    version: int


class PaidClaimSnapshot(TypedDict, total=False):
    id: str
    contract_id: str
    claim_number: str
    hcpcs_code: str
    service_category: str
    service_date: str
    billed_cents: int
    paid_cents: int
    snapshot_status: str
    created_at: str
    updated_at: str
    version: int


class RetroAdjustmentRun(TypedDict, total=False):
    id: str
    contract_version_id: str
    run_status: str
    window_start_date: str
    window_end_date: str
    adjustment_count: int
    total_underpaid_cents: int
    total_overpaid_cents: int
    net_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class RetroAdjustment(TypedDict, total=False):
    id: str
    retro_run_id: str
    paid_claim_id: str
    service_date: str
    original_paid_cents: int
    repriced_allowed_cents: int
    delta_cents: int
    direction: str
    adjustment_status: str
    created_at: str
    updated_at: str
    version: int


class TerminationNotice(TypedDict, total=False):
    id: str
    contract_id: str
    notice_date: str
    termination_date: str
    reason: str
    notice_status: str
    created_at: str
    updated_at: str
    version: int


class ContinuityOfCareCase(TypedDict, total=False):
    id: str
    termination_notice_id: str
    member_ref: str
    condition_category: str
    treatment_end_date: str
    coverage_end_date: str
    case_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: NO updated_at, NO version
class AuditEvent(TypedDict, total=False):
    id: str
    contract_id: str
    event_type: str
    actor_role: str
    actor_id: str
    detail: str
    occurred_at: str
    created_at: str
