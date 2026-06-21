"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Annuity Contract Administration PRD. CreditingEvent is an
append-only ledger entry and carries only id + created_at (no updated_at, no
version); every other entity carries the full common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    CREDITING_OFFICER = "CreditingOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status enums ─────────────────────────────────────────────────────────
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ANNUITIZED = "ANNUITIZED"
    SURRENDERED = "SURRENDERED"
    DEATH_CLAIM = "DEATH_CLAIM"
    TERMINATED = "TERMINATED"


class PremiumStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class SubAccountAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIQUIDATED = "LIQUIDATED"


class IndexSegmentStatus(str, Enum):
    OPEN = "OPEN"
    CREDITED = "CREDITED"


class WithdrawalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AnnuitizationStatus(str, Enum):
    ELECTED = "ELECTED"
    ACTIVE_PAYOUT = "ACTIVE_PAYOUT"
    DECLINED = "DECLINED"


class DeathClaimStatus(str, Enum):
    FILED = "FILED"
    VERIFYING = "VERIFYING"
    VALUED = "VALUED"
    FUNDED = "FUNDED"
    DENIED = "DENIED"


class Exchange1035Status(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


# ─── Value enums ──────────────────────────────────────────────────────────
class ContractType(str, Enum):
    FIXED = "FIXED"
    VARIABLE = "VARIABLE"
    INDEXED = "INDEXED"


class DeathBenefitType(str, Enum):
    RETURN_OF_PREMIUM = "RETURN_OF_PREMIUM"
    ACCOUNT_VALUE = "ACCOUNT_VALUE"
    HIGHEST_ANNIVERSARY = "HIGHEST_ANNIVERSARY"


class CreditingKind(str, Enum):
    FIXED_GUARANTEED = "FIXED_GUARANTEED"
    INDEX_SEGMENT = "INDEX_SEGMENT"
    SUBACCOUNT_RETURN = "SUBACCOUNT_RETURN"


class PayoutOption(str, Enum):
    LIFE_ONLY = "LIFE_ONLY"
    PERIOD_CERTAIN = "PERIOD_CERTAIN"
    LIFE_WITH_PERIOD_CERTAIN = "LIFE_WITH_PERIOD_CERTAIN"
    JOINT_LIFE = "JOINT_LIFE"


# ─── Entity TypedDicts (common_fields: true) ──────────────────────────────
class Product(TypedDict):
    id: str
    name: str
    contract_type: str
    fixed_annual_rate_bps: Optional[int]
    free_withdrawal_corridor_bps: int
    mva_enabled: bool
    death_benefit_type: str
    surrender_charge_schedule: List[dict]
    min_initial_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    product_id: str
    owner_name: str
    annuitant_age: int
    issue_date: Optional[str]
    contract_year: int
    accumulation_value_cents: int
    cumulative_premium_cents: int
    highest_anniversary_value_cents: int
    free_withdrawal_used_cents: int
    status: str
    surrender_charge_bps: int
    created_at: str
    updated_at: str
    version: int


class Premium(TypedDict):
    id: str
    contract_id: str
    gross_premium_cents: int
    premium_load_bps: int
    net_premium_cents: int
    is_initial: bool
    source_exchange_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubAccountAllocation(TypedDict):
    id: str
    contract_id: str
    division_name: str
    allocation_bps: int
    unit_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IndexSegment(TypedDict):
    id: str
    contract_id: str
    index_name: str
    term_start_date: str
    term_end_date: str
    segment_premium_cents: int
    cap_bps: int
    floor_bps: int
    participation_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict):
    id: str
    contract_id: str
    requested_amount_cents: int
    is_full_surrender: bool
    free_amount_cents: int
    chargeable_amount_cents: int
    surrender_charge_cents: int
    mva_cents: int
    gross_withdrawal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    contract_id: str
    full_name: str
    relationship: str
    share_bps: int
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Annuitization(TypedDict):
    id: str
    contract_id: str
    payout_option: str
    period_certain_years: Optional[int]
    annuitization_value_cents: int
    monthly_benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathClaim(TypedDict):
    id: str
    contract_id: str
    date_of_death: str
    identity_verified: bool
    benefit_valued: bool
    death_benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Exchange1035(TypedDict):
    id: str
    direction: str
    source_contract_id: Optional[str]
    target_contract_id: Optional[str]
    external_carrier: Optional[str]
    transfer_amount_cents: int
    cost_basis_cents: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger entry (common_fields: false) ──────────────────────
class CreditingEvent(TypedDict):
    id: str
    contract_id: str
    crediting_kind: str
    source_segment_id: Optional[str]
    source_allocation_id: Optional[str]
    raw_index_return_bps: Optional[int]
    credit_period_start: Optional[str]
    credit_period_end: Optional[str]
    credit_cents: int
    posted_period_index: int
    created_at: str
    # NOTE: no updated_at, no version — append-only.
