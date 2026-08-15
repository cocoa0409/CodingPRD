"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.1, 2.4, 3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class DealerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DealerTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CoverageType(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class SalesTargetStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_MET = "CLOSED_MET"
    CLOSED_MISSED = "CLOSED_MISSED"


class UnitSaleStatus(str, Enum):
    REPORTED = "REPORTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class FloorPlanAdvanceStatus(str, Enum):
    OPEN = "OPEN"
    CURTAILED = "CURTAILED"
    PAST_DUE = "PAST_DUE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    AUDIT_FLAGGED = "AUDIT_FLAGGED"
    CHARGED_BACK = "CHARGED_BACK"
    DISPUTED = "DISPUTED"


class PartsReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class CertificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LeadStatus(str, Enum):
    NEW = "NEW"
    ROUTED = "ROUTED"
    DECLINED = "DECLINED"
    ORPHANED = "ORPHANED"
    EXPIRED = "EXPIRED"
    ACCEPTED = "ACCEPTED"


class UserRole(str, Enum):
    OEM_NETWORK_ADMIN = "OemNetworkAdmin"
    OEM_SALES_OPS = "OemSalesOps"
    OEM_AUDITOR = "OemAuditor"
    DEALER_USER = "DealerUser"
    ANY = "Any"


# All ten resource types carry the full four-field system set of PRD section 2.4
# (id, created_at, updated_at, version).


class Dealer(TypedDict, total=False):
    id: str
    name: str
    dealer_code: str
    region: str
    credit_limit_cents: int
    min_stock_value_cents: int
    floorplan_utilization_cents: int
    floorplan_available_cents: int
    default_loss_cents: int
    chargeback_balance_cents: int
    discount_reconciliation_cents: int
    parts_purchases_ytd_cents: int
    purchases_year: Optional[int]
    stock_observed_value_cents: int
    stock_compliant: bool
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DealerAgreement(TypedDict, total=False):
    id: str
    dealer_id: str
    agreement_code: str
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TerritoryAssignment(TypedDict, total=False):
    id: str
    dealer_id: str
    agreement_id: str
    territory_code: str
    coverage_type: str
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesTarget(TypedDict, total=False):
    id: str
    dealer_id: str
    period_year: int
    period_quarter: int
    target_units: int
    achieved_units: int
    final_discount_rate: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class UnitSale(TypedDict, total=False):
    id: str
    dealer_id: str
    unit_serial: str
    sale_date: str
    list_price_cents: int
    provisional_discount_cents: int
    final_discount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FloorPlanAdvance(TypedDict, total=False):
    id: str
    dealer_id: str
    unit_serial: str
    advance_cents: int
    advance_date: str
    paid_curtailments_cents: int
    accrued_interest_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    dealer_id: str
    unit_serial: str
    parts_cost_cents: int
    labor_hours: float
    failure_description: str
    claim_amount_cents: int
    paid_amount_cents: Optional[int]
    paid_at: Optional[str]
    chargeback_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsReturnLine(TypedDict, total=False):
    part_number: str
    quantity: int
    unit_credit_cents: int


class PartsReturn(TypedDict, total=False):
    id: str
    dealer_id: str
    return_year: int
    lines: List[PartsReturnLine]
    restock_pct_applied: float
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    dealer_id: str
    cert_code: str
    earned_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict, total=False):
    id: str
    territory_code: str
    product_line: str
    estimated_value_cents: int
    contact_name: str
    routed_dealer_id: Optional[str]
    routed_assignment_id: Optional[str]
    declined_dealer_ids: List[str]
    routed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Scorecard(TypedDict, total=False):
    period_year: int
    period_quarter: int
    variant: str
    sales_score: float
    service_score: float
    training_score: float
    parts_score: float
    total_score: float
