"""Domain types: entity TypedDicts, status enums, role enum.

Field names are PRD-exact (§3 narratives and §2.4 common fields). Every entity in
this system carries the full common-field set (id, created_at, updated_at, version)
per §2.4 ("There are no entities in this system that omit updated_at or version").
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (§2.1) ────────────────────────────────────────────────────────
class UserRole(str, Enum):
    FRANCHISOR = "Franchisor"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    FRANCHISEE = "Franchisee"
    FINANCE_CLERK = "FinanceClerk"
    SYSTEM = "System"


# ─── Status enums ────────────────────────────────────────────────────────────
class TerritoryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    RETIRED = "RETIRED"


class FranchiseeStatus(str, Enum):
    APPLICANT = "APPLICANT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    TRANSFERRED = "TRANSFERRED"
    TERMINATED = "TERMINATED"


class UnitOperationalStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class UnitComplianceStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class SalesReportStatus(str, Enum):
    POLLED = "POLLED"
    ACCEPTED = "ACCEPTED"
    AMENDED = "AMENDED"


class SalesReportSource(str, Enum):
    POS_POLL = "POS_POLL"
    MANUAL = "MANUAL"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


class VendorApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class VendorCategory(str, Enum):
    FOOD = "FOOD"
    PACKAGING = "PACKAGING"
    EQUIPMENT = "EQUIPMENT"
    SERVICES = "SERVICES"


class VendorAuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class BrandAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZED = "FINALIZED"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"


class BrandAuditGrade(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class DevelopmentScheduleStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    BEHIND = "BEHIND"
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"


class NationalAccountStatus(str, Enum):
    OPEN = "OPEN"
    DISTRIBUTED = "DISTRIBUTED"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
class Brand(TypedDict):
    id: str
    name: str
    royalty_tier_1_rate: float
    royalty_tier_2_rate: float
    royalty_tier_3_rate: float
    ad_fund_rate: float
    late_fee_monthly_rate: float
    current_period_index: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    brand_id: str
    code: str
    name: str
    protected: bool
    assigned_franchisee_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Franchisee(TypedDict):
    id: str
    brand_id: str
    legal_name: str
    owner_user_id: str
    is_existing_operator: bool
    status: str
    open_compliance_strikes: int
    created_at: str
    updated_at: str
    version: int


class FranchiseAgreement(TypedDict):
    id: str
    brand_id: str
    franchisee_id: str
    fdd_version: str
    term_end_period_index: int
    transfer_fee_rate: float
    successor_agreement_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    brand_id: str
    franchisee_id: str
    territory_id: str
    address: str
    operational_status: str
    compliance_status: str
    latest_audit_score: Optional[float]
    lifetime_net_sales_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict):
    id: str
    brand_id: str
    unit_id: str
    period_index: int
    gross_sales_cents: int
    discounts_cents: int
    net_sales_cents: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    brand_id: str
    unit_id: str
    period_index: int
    net_sales_basis_cents: int
    royalty_cents: int
    ad_fund_cents: int
    late_fee_cents: int
    total_due_cents: int
    amount_paid_cents: int
    due_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    brand_id: str
    name: str
    category: str
    approval_status: str
    created_at: str
    updated_at: str
    version: int


class VendorAuthorization(TypedDict):
    id: str
    brand_id: str
    unit_id: str
    vendor_id: str
    qualifying_purchase_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BrandAudit(TypedDict):
    id: str
    brand_id: str
    unit_id: str
    food_safety_score: Optional[int]
    cleanliness_score: Optional[int]
    service_score: Optional[int]
    brand_compliance_score: Optional[int]
    weighted_score: Optional[float]
    overall_score: Optional[float]
    grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DevelopmentSchedule(TypedDict):
    id: str
    brand_id: str
    franchisee_id: str
    required_units: int
    deadline_period_index: int
    opened_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NationalAccount(TypedDict):
    id: str
    brand_id: str
    vendor_id: str
    name: str
    rebate_pool_cents: int
    min_qualifying_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
