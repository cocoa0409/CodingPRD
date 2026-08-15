"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class HouseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PLACED = "PLACED"
    DOWNTIME = "DOWNTIME"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class FlockStatus(str, Enum):
    PLANNED = "PLANNED"
    PLACED = "PLACED"
    GROWING = "GROWING"
    CATCH_SCHEDULED = "CATCH_SCHEDULED"
    HARVESTED = "HARVESTED"
    SETTLED = "SETTLED"
    CONDEMNED_LOSS = "CONDEMNED_LOSS"


class PlacementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class FeedType(str, Enum):
    STARTER = "STARTER"
    GROWER = "GROWER"
    FINISHER = "FINISHER"
    WITHDRAWAL = "WITHDRAWAL"


class CatchScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SettlementGroupStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class LoanStatus(str, Enum):
    ISSUED = "ISSUED"
    REPAID = "REPAID"
    CLOSED = "CLOSED"


class LoanPurpose(str, Enum):
    CAPITAL_UPGRADE = "CAPITAL_UPGRADE"
    OPERATING = "OPERATING"


class UserRole(str, Enum):
    INTEGRATOR_ADMIN = "IntegratorAdmin"
    GROWER = "Grower"
    SERVICE_TECH = "ServiceTech"
    LIVEHAUL_SCHEDULER = "LivehaulScheduler"
    SETTLEMENT_ANALYST = "SettlementAnalyst"


# All resources carry the full common-field set (PRD §2.4):
# id, created_at, updated_at, version.

class Grower(TypedDict, total=False):
    id: str
    grower_code: str
    full_name: str
    status: str
    performance_rating: Optional[float]
    loan_outstanding_cents: int
    house_count: int
    created_at: str
    updated_at: str
    version: int


class GrowerContract(TypedDict, total=False):
    id: str
    grower_id: str
    contract_no: str
    base_pay_cents_per_lb: int
    committed_house_count: int
    term_start_date: str
    term_end_date: str
    status: str
    upgrade_required: bool
    created_at: str
    updated_at: str
    version: int


class House(TypedDict, total=False):
    id: str
    grower_id: str
    house_no: str
    capacity_birds: int
    house_status: str
    downtime_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Flock(TypedDict, total=False):
    id: str
    house_id: str
    contract_id: str
    settlement_group_id: str
    flock_no: str
    placed_head: int
    placed_date: Optional[str]
    status: str
    feed_delivered_lbs: int
    mortality_head: int
    condemnation_head: int
    live_weight_lbs: int
    adj_fcr: Optional[float]
    livability_pct: Optional[float]
    condemnation_pct: float
    performance_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ChickPlacement(TypedDict, total=False):
    id: str
    flock_id: str
    scheduled_date: str
    head_count: int
    status: str
    confirmed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedDelivery(TypedDict, total=False):
    id: str
    flock_id: str
    delivered_date: str
    feed_lbs: int
    feed_type: str
    ticket_no: str
    created_at: str
    updated_at: str
    version: int


class MortalityReport(TypedDict, total=False):
    id: str
    flock_id: str
    report_date: str
    dead_head: int
    condemned_head: int
    created_at: str
    updated_at: str
    version: int


class CatchSchedule(TypedDict, total=False):
    id: str
    flock_id: str
    crew_id: str
    catch_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CatchCrew(TypedDict, total=False):
    id: str
    crew_code: str
    max_catches_per_day: int
    created_at: str
    updated_at: str
    version: int


class WeightTicket(TypedDict, total=False):
    id: str
    flock_id: str
    ticket_no: str
    weighed_at: str
    live_weight_lbs: int
    created_at: str
    updated_at: str
    version: int


class BiosecurityAudit(TypedDict, total=False):
    id: str
    house_id: str
    audit_date: str
    result: str
    quarantine_days: int
    created_at: str
    updated_at: str
    version: int


class SettlementGroup(TypedDict, total=False):
    id: str
    group_code: str
    week_ending_date: str
    status: str
    group_avg_fcr: Optional[float]
    group_avg_livability_pct: Optional[float]
    group_avg_condemnation_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    flock_id: str
    variant: str
    rank_position: int
    base_amount_cents: int
    fcr_bonus_cents: int
    condemnation_deduction_cents: int
    loan_repayment_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrowerLoan(TypedDict, total=False):
    id: str
    grower_id: str
    principal_cents: int
    recovery_pct: int
    outstanding_cents: int
    status: str
    purpose: str
    created_at: str
    updated_at: str
    version: int
