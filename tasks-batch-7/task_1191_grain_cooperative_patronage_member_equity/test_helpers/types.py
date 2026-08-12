"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COOP_ADMIN = "CoopAdmin"
    COOP_REGISTRAR = "CoopRegistrar"
    COOP_ACCOUNTANT = "CoopAccountant"
    EXTERNAL_AUDITOR = "ExternalAuditor"
    ELEVATOR_OPERATOR = "ElevatorOperator"
    COOP_TREASURER = "CoopTreasurer"
    BOARD_SECRETARY = "BoardSecretary"
    MEMBER = "Member"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    WITHDRAWN = "WITHDRAWN"
    DECEASED = "DECEASED"
    EXPELLED = "EXPELLED"


class MemberClass(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    PARTNERSHIP = "PARTNERSHIP"
    CORPORATION = "CORPORATION"
    LLC = "LLC"
    ESTATE = "ESTATE"


class FiscalYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_PROVISIONAL = "CLOSED_PROVISIONAL"
    UNDER_AUDIT = "UNDER_AUDIT"
    CLOSED_FINAL = "CLOSED_FINAL"
    REOPENED = "REOPENED"


class DeliveryStatus(str, Enum):
    BOOKED = "BOOKED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class Commodity(str, Enum):
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"
    WHEAT = "WHEAT"
    SORGHUM = "SORGHUM"
    SUNFLOWER = "SUNFLOWER"


class AllocationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"
    REVERSED = "REVERSED"


class AllocationVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TierCode(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class EquityClass(str, Enum):
    QUALIFIED = "QUALIFIED"
    NONQUALIFIED = "NONQUALIFIED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    REDEEMED = "REDEEMED"
    REVOKED = "REVOKED"
    ESCHEATED = "ESCHEATED"
    FROZEN = "FROZEN"


class CycleStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ResolutionKind(str, Enum):
    OPEN_REVOLVEMENT = "OPEN_REVOLVEMENT"
    APPROVE_ESTATE = "APPROVE_ESTATE"
    APPROVE_RETIREMENT = "APPROVE_RETIREMENT"
    APPROVE_SPECIAL_REDEMPTION = "APPROVE_SPECIAL_REDEMPTION"
    AMEND_ALLOCATION = "AMEND_ALLOCATION"
    AUTHORIZE_ESCHEAT = "AUTHORIZE_ESCHEAT"


class ResolutionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VOTING = "VOTING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    TABLED = "TABLED"


class RedemptionKind(str, Enum):
    ESTATE = "ESTATE"
    RETIREMENT = "RETIREMENT"
    SPECIAL_HARDSHIP = "SPECIAL_HARDSHIP"
    CYCLE_REDEMPTION = "CYCLE_REDEMPTION"


class RedemptionStatus(str, Enum):
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    APPEALED = "APPEALED"
    CANCELLED = "CANCELLED"


class EstateClaimStatus(str, Enum):
    FILED = "FILED"
    PROBATED = "PROBATED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISTRIBUTED = "DISTRIBUTED"
    LAPSED = "LAPSED"


class LotStatus(str, Enum):
    DORMANT = "DORMANT"
    NOTIFIED = "NOTIFIED"
    ESCHEAT_PENDING = "ESCHEAT_PENDING"
    ESCHEATED = "ESCHEATED"
    RECOVERED = "RECOVERED"


class TaxFormType(str, Enum):
    FORM_1099_PATR = "FORM_1099_PATR"
    FORM_1099_DIV = "FORM_1099_DIV"
    CORRECTED_1099_PATR = "CORRECTED_1099_PATR"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CORRECTED = "CORRECTED"
    VOID = "VOID"


class DistrictStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    RETIRED = "RETIRED"


# All entities carry the common system-managed fields (id, created_at,
# updated_at, version) per PRD §2.5.

class Member(TypedDict, total=False):
    id: str
    patron_ref: str
    legal_name: str
    member_class: str
    status: str
    joined_at: str
    delegate_district_id: str
    is_producer_member: bool
    capital_share_balance_cents: int
    qualified_equity_cents: int
    nonqualified_equity_cents: int
    per_unit_retains_cents: int
    total_patronage_volume_bu: int
    created_at: str
    updated_at: str
    version: int


class DelegateDistrict(TypedDict, total=False):
    id: str
    code: str
    name: str
    max_delegates: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Delegate(TypedDict, total=False):
    id: str
    district_id: str
    member_id: str
    term_start: str
    term_end: str
    is_seated: bool
    created_at: str
    updated_at: str
    version: int


class FiscalYear(TypedDict, total=False):
    id: str
    year_code: str
    start_date: str
    end_date: str
    status: str
    net_margin_cents: int
    patronage_pool_cents: int
    retained_reserve_pct: float
    qualified_payout_pct: float
    closed_at: Optional[str]
    final_audit_locked: bool
    created_at: str
    updated_at: str
    version: int


class GrainDelivery(TypedDict, total=False):
    id: str
    member_id: str
    fiscal_year_id: str
    commodity: str
    gross_bushels: int
    dockage_pct: float
    net_bushels: int
    is_patron_sourced: bool
    booked_at: str
    status: str
    per_unit_retain_cents: int
    created_at: str
    updated_at: str
    version: int


class PatronageAllocation(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    member_id: str
    allocated_volume_bu: int
    pool_share_ratio: float
    qualified_allocation_cents: int
    nonqualified_allocation_cents: int
    cash_paid_cents: int
    qualified_equity_issued_cents: int
    tier_code: str
    status: str
    variant: str
    created_at: str
    updated_at: str
    version: int


class EquityCertificate(TypedDict, total=False):
    id: str
    member_id: str
    fiscal_year_id: str
    allocation_id: str
    equity_class: str
    face_value_cents: int
    outstanding_cents: int
    status: str
    issued_at: str
    redeemable_at: Optional[str]
    revolvement_cycle_id: Optional[str]
    replaces_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevolvementCycle(TypedDict, total=False):
    id: str
    cycle_code: str
    equity_class: str
    target_year_offset: int
    window_start: str
    window_end: str
    status: str
    budget_cap_cents: int
    redeemed_cents: int
    board_resolution_id: str
    created_at: str
    updated_at: str
    version: int


class BoardResolution(TypedDict, total=False):
    id: str
    resolution_code: str
    kind: str
    subject_ref_id: str
    status: str
    votes_for: int
    votes_against: int
    quorum_required: int
    voting_opens_at: str
    voting_closes_at: str
    created_at: str
    updated_at: str
    version: int


class RedemptionRequest(TypedDict, total=False):
    id: str
    member_id: str
    kind: str
    certificate_ids: List[str]
    requested_amount_cents: int
    status: str
    appointment_at: str
    appeal_of_request_id: Optional[str]
    resolution_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstateClaim(TypedDict, total=False):
    id: str
    deceased_member_id: str
    executor_member_id: str
    filed_at: str
    probate_completed_at: Optional[str]
    claim_window_days: int
    status: str
    claim_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class UnclaimedEquityLot(TypedDict, total=False):
    id: str
    certificate_id: str
    last_known_member_id: str
    dormancy_started_at: str
    escheat_eligible_at: str
    dormancy_years: int
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PatronTaxForm(TypedDict, total=False):
    id: str
    member_id: str
    fiscal_year_id: str
    form_type: str
    box_1_patronage_dividends_cents: int
    box_3_per_unit_retains_cents: int
    box_4_federal_withheld_cents: int
    box_5_redemption_cents: int
    is_corrected: bool
    corrects_form_id: Optional[str]
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
