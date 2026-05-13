"""Domain types: entity TypedDicts, status enums, role enum, event-type enum
for the IP Management API (PRD §1, §3).

Entities with common fields (id, created_at, updated_at, version) per PRD §2.4:
  BusinessUnit, Agent, IPRight, JurisdictionFiling, ApplicationOfficeAction,
  AnnualFeeSchedule, Contract, RoyaltySchedule, ProtectionCase.

Entities WITHOUT updated_at/version (only id + created_at) per PRD §2.4:
  ContractTemplate, Evidence, Cost, AuditEntry.
"""

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ────────────────────── Roles (PRD §2.1) ──────────────────────


class UserRole(str, Enum):
    Admin = "Admin"
    IPManager = "IPManager"
    FinanceManager = "FinanceManager"
    Counsel = "Counsel"
    InternalAgent = "InternalAgent"
    ExternalAgent = "ExternalAgent"


# ────────────────────── Status enums (PRD §3 + §1) ────────────


class BusinessUnitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AgentKind(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class IPType(str, Enum):
    PATENT = "PATENT"
    TRADEMARK = "TRADEMARK"
    COPYRIGHT = "COPYRIGHT"


class HandlingMode(str, Enum):
    AGENCY = "AGENCY"
    SELF = "SELF"


class IPRightStatus(str, Enum):
    DRAFT = "DRAFT"
    MATERIALS_READY = "MATERIALS_READY"
    FILED = "FILED"
    OFFICE_ACTION = "OFFICE_ACTION"
    REGISTERED = "REGISTERED"
    ABANDONED = "ABANDONED"
    TRANSFERRED = "TRANSFERRED"


class JurisdictionFilingStatus(str, Enum):
    FILED = "FILED"
    OFFICE_ACTION = "OFFICE_ACTION"
    REGISTERED = "REGISTERED"
    ABANDONED = "ABANDONED"


class ApplicationOfficeActionStatus(str, Enum):
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    CLOSED_GRANTED = "CLOSED_GRANTED"
    CLOSED_ABANDONED = "CLOSED_ABANDONED"


class AnnualFeeStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    LATE = "LATE"
    ABANDONED = "ABANDONED"


class ContractType(str, Enum):
    TRANSFER = "TRANSFER"
    EXCLUSIVE_LICENSE = "EXCLUSIVE_LICENSE"
    NON_EXCLUSIVE_LICENSE = "NON_EXCLUSIVE_LICENSE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNING = "SIGNING"
    SIGNED = "SIGNED"
    FILED = "FILED"
    AMENDED = "AMENDED"
    TERMINATED = "TERMINATED"


class RoyaltyScheduleStatus(str, Enum):
    FORECAST = "FORECAST"
    SETTLED = "SETTLED"


class ProtectionCaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ProtectionRoute(str, Enum):
    NONE = "NONE"
    DEMAND_LETTER = "DEMAND_LETTER"
    LITIGATION = "LITIGATION"
    MEDIATION = "MEDIATION"
    ARBITRATION = "ARBITRATION"


class ProtectionOutcome(str, Enum):
    WON = "WON"
    LOST = "LOST"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"


class EvidenceKind(str, Enum):
    WITNESS = "WITNESS"
    DOCUMENT = "DOCUMENT"
    SAMPLE = "SAMPLE"
    DIGITAL = "DIGITAL"


class CostCategory(str, Enum):
    APPLICATION = "APPLICATION"
    ANNUAL_FEE = "ANNUAL_FEE"
    LITIGATION = "LITIGATION"
    AGENT_FEE = "AGENT_FEE"


class AuditEventType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    CONTRACT_RECORD = "CONTRACT_RECORD"
    PAYMENT_SETTLED = "PAYMENT_SETTLED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


# ────────────────────── Entity TypedDicts ──────────────────────
# Per PRD §2.4 — entities with common fields carry id, created_at, updated_at,
# version; the four append-only-ish entities (ContractTemplate, Evidence, Cost,
# AuditEntry) carry ONLY id + created_at.


class BusinessUnit(TypedDict, total=False):
    id: str
    code: str
    name: str
    annual_budget_cents: int
    actual_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    kind: str
    full_name: str
    qualification_number: str
    qualification_verified: bool
    jurisdictions: List[str]
    hourly_rate_cents: int
    active_case_count: int
    pending_action_count: int
    upcoming_deadline_count: int
    workload_score: float
    performance_rating: float
    status: str
    created_at: str
    updated_at: str
    version: int


class IPRight(TypedDict, total=False):
    id: str
    ip_type: str
    title: str
    handling_mode: str
    assigned_agent_id: Optional[str]
    business_unit_id: str
    status: str
    primary_jurisdiction: str
    certificate_archive_url: Optional[str]
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionFiling(TypedDict, total=False):
    id: str
    ip_right_id: str
    jurisdiction: str
    filing_number: str
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ApplicationOfficeAction(TypedDict, total=False):
    id: str
    ip_right_id: str
    jurisdiction_filing_id: str
    assigned_agent_id: str
    response_due_at: str
    responded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualFeeSchedule(TypedDict, total=False):
    id: str
    ip_right_id: str
    jurisdiction: str
    fee_year: int
    base_fee_cents: int
    due_date: str
    grace_end_date: str
    paid_at: Optional[str]
    total_paid_cents: int
    surcharge_cents: int
    auto_pay_authorized: bool
    assigned_agent_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractParty(TypedDict, total=False):
    party_id: str
    role: str
    signature_required: bool
    signed_at: Optional[str]


class Contract(TypedDict, total=False):
    id: str
    ip_right_id: str
    template_id: str
    contract_type: str
    parties: List[ContractParty]
    royalty_rate: Optional[float]
    min_guarantee_cents: Optional[int]
    filed_with_authority: bool
    status: str
    business_unit_id: str
    created_at: str
    updated_at: str
    version: int


# ── ContractTemplate: common_fields == false (PRD §2.4) ─────────
class ContractTemplate(TypedDict, total=False):
    id: str
    code: str
    contract_type: str
    body: str
    created_at: str


class RoyaltySchedule(TypedDict, total=False):
    id: str
    contract_id: str
    period_index: int
    period_start: str
    period_end: str
    forecast_revenue_cents: int
    actual_revenue_cents: int
    provisional_royalty_cents: int
    final_royalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionDistributed(TypedDict, total=False):
    legal_paid: int
    agent_paid: int
    punitive_paid: int
    rights_holder_paid: int


class ProtectionCase(TypedDict, total=False):
    id: str
    ip_right_id: str
    assigned_agent_id: str
    business_unit_id: str
    route: str
    status: str
    outcome: Optional[str]
    recovered_amount_cents: int
    legal_fees_cents: int
    agent_fees_cents: int
    punitive_cap_cents: int
    distributed: Optional[ProtectionDistributed]
    rights_holder_currency: str
    created_at: str
    updated_at: str
    version: int


# ── Evidence: common_fields == false (PRD §2.4) ─────────────────
class Evidence(TypedDict, total=False):
    id: str
    protection_case_id: str
    kind: str
    collected_at: str
    storage_uri: str
    chain_of_custody_hash: Optional[str]
    created_at: str


class CostAllocation(TypedDict, total=False):
    business_unit_id: str
    percent_bps: int
    allocated_cents: int


# ── Cost: common_fields == false (PRD §2.4) ─────────────────────
class Cost(TypedDict, total=False):
    id: str
    category: str
    ip_right_id: Optional[str]
    protection_case_id: Optional[str]
    agent_id: Optional[str]
    currency: str
    amount_native_cents: int
    fx_rate_to_usd: float
    amount_usd_cents: int
    allocations: List[CostAllocation]
    allocation_rules: List[Any]
    booked_at: str
    created_at: str


# ── AuditEntry: common_fields == false (PRD §2.4) ───────────────
class AuditEntry(TypedDict, total=False):
    id: str
    subject_entity: str
    subject_id: str
    actor_role: str
    actor_id: str
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload: Any
    created_at: str
