"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    STUDY_MANAGER = "StudyManager"
    ENGINEER = "Engineer"
    REVIEWER = "Reviewer"
    CPA = "CPA"


class ClientStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPING = "SCOPING"
    ENGINEERING = "ENGINEERING"
    IN_REVIEW = "IN_REVIEW"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AssetComponentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ALLOCATED = "ALLOCATED"
    EXCLUDED = "EXCLUDED"


class QreLineItemStatus(str, Enum):
    DRAFT = "DRAFT"
    QUALIFIED = "QUALIFIED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class AuditSupportCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AmendedReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"


class FeeInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# common_fields: true — id + created_at + updated_at + version
class Client(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    marginal_tax_rate: float
    status: str
    outstanding_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    client_id: str
    address: str
    building_type: str
    purchase_price_cents: int
    land_value_cents: int
    placed_in_service_date: str
    depreciable_basis_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable staff record, ONLY id + created_at
class Engineer(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str


class Study(TypedDict):
    id: str
    client_id: str
    property_id: Optional[str]
    assigned_engineer_id: Optional[str]
    study_type: str
    tax_year: int
    is_look_back: bool
    fee_type: Optional[str]
    fee_fixed_amount_cents: Optional[int]
    fee_percent_bps: Optional[int]
    credit_method: Optional[str]
    fixed_base_pct: Optional[float]
    avg_annual_gross_receipts_cents: Optional[int]
    prior_qre_year1_cents: int
    prior_qre_year2_cents: int
    prior_qre_year3_cents: int
    status: str
    reviewer_engineer_id: Optional[str]
    total_allocated_cost_cents: int
    first_year_depreciation_cents: int
    first_year_depreciation_no_bonus_cents: int
    rd_credit_regular_cents: int
    rd_credit_asc_cents: int
    estimated_tax_benefit_cents: int
    section_481a_cents: int
    created_at: str
    updated_at: str
    version: int


class AssetComponent(TypedDict):
    id: str
    study_id: str
    component_name: str
    asset_class: str
    allocated_cost_cents: int
    recovery_period_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QreLineItem(TypedDict):
    id: str
    study_id: str
    qre_category: str
    gross_amount_cents: int
    qualified_percent: float
    qualified_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    study_id: str
    report_type: str
    revision_count: int
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditSupportCase(TypedDict):
    id: str
    study_id: str
    irs_notice_ref: str
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AmendedReturn(TypedDict):
    id: str
    study_id: str
    amended_tax_year: int
    section_481a_cents: int
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    study_id: str
    amount_cents: int
    fee_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int
