"""Domain types: entity TypedDicts, status enums, and the role enum.

Every primary resource (PRD §2.4) carries id, created_at, updated_at, and an
integer version. All money is integer cents and all rates are basis points
(PRD §2.7).
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Enums ──────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    FINANCE_OFFICER = "FinanceOfficer"
    ADMISSIONS_DIRECTOR = "AdmissionsDirector"
    CARE_COORDINATOR = "CareCoordinator"
    RESIDENT = "Resident"


class CareLevel(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    ASSISTED = "ASSISTED"
    SKILLED = "SKILLED"


class ContractType(str, Enum):
    TYPE_A = "TYPE_A"
    TYPE_B = "TYPE_B"
    TYPE_C = "TYPE_C"


class RefundPlan(str, Enum):
    DECLINING = "DECLINING"
    FIFTY_REFUNDABLE = "FIFTY_REFUNDABLE"
    NINETY_REFUNDABLE = "NINETY_REFUNDABLE"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"


class ResidencyStatus(str, Enum):
    DEPOSIT_HELD = "DEPOSIT_HELD"
    WAITLISTED = "WAITLISTED"
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    TERMINATED_VOLUNTARY = "TERMINATED_VOLUNTARY"
    TERMINATED_DEATH = "TERMINATED_DEATH"


class SecondPersonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class WaitlistEntryStatus(str, Enum):
    PENDING = "PENDING"
    OFFERED = "OFFERED"
    PLACED = "PLACED"
    WITHDRAWN = "WITHDRAWN"


class CareTransitionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REVERTED = "REVERTED"


class BedReservationStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    DEATH = "DEATH"


class ResolutionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"


# ─── Entity TypedDicts (all entities common_fields: true) ───────────────────

class Community(TypedDict):
    id: str
    name: str
    current_period_index: int
    actuarial_discount_rate_bps: int
    target_funded_ratio_bps: int
    reserve_assets_cents: int
    is_admissions_frozen: bool
    created_at: str
    updated_at: str
    version: int


class ContractPlan(TypedDict):
    id: str
    community_id: str
    name: str
    contract_type: str
    entrance_fee_cents: int
    refund_plan: str
    declining_monthly_bps: int
    declining_nonrefundable_bps: int
    monthly_service_fee_cents: int
    second_person_fee_cents: int
    assisted_monthly_surcharge_cents: int
    skilled_per_diem_cents: int
    typeb_discounted_days: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    community_id: str
    unit_number: str
    care_level: str
    bed_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    community_id: str
    full_name: str
    date_of_birth: str
    priority_score: int
    created_at: str
    updated_at: str
    version: int


class Residency(TypedDict):
    id: str
    community_id: str
    primary_resident_id: str
    contract_plan_id: str
    unit_id: Optional[str]
    care_level: str
    entrance_fee_paid_cents: int
    occupied_months: int
    skilled_days_used: int
    has_second_person: bool
    refund_disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SecondPerson(TypedDict):
    id: str
    residency_id: str
    full_name: str
    date_of_birth: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    community_id: str
    residency_id: str
    target_care_level: str
    priority_score: int
    enqueued_period_index: int
    rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareTransition(TypedDict):
    id: str
    residency_id: str
    from_level: str
    to_level: str
    effective_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BedReservation(TypedDict):
    id: str
    residency_id: str
    unit_id: str
    hold_start_period: int
    hold_expiry_period: int
    occupied_start_period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlyInvoice(TypedDict):
    id: str
    residency_id: str
    period_index: int
    base_service_fee_cents: int
    second_person_fee_cents: int
    care_surcharge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundDisbursement(TypedDict):
    id: str
    residency_id: str
    gross_entrance_fee_cents: int
    refundable_cents: int
    termination_reason: str
    settlement_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResidentCouncil(TypedDict):
    id: str
    community_id: str
    name: str
    quorum_pct_bps: int
    created_at: str
    updated_at: str
    version: int


class CouncilResolution(TypedDict):
    id: str
    council_id: str
    title: str
    yes_votes: int
    no_votes: int
    eligible_voter_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
