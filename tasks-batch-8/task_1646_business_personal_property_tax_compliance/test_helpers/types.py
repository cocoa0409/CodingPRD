"""Domain types: entity shapes, status enums, and role enum for the BPP tax compliance API."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    TAX_ANALYST = "TaxAnalyst"
    SENIOR_MANAGER = "SeniorManager"
    ASSESSOR_CLERK = "AssessorClerk"
    CLIENT = "Client"


class AssetLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPOSED = "DISPOSED"


class AssetClassificationStatus(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    CLASSIFIED = "CLASSIFIED"
    OVERRIDDEN = "OVERRIDDEN"


class TaxableClassification(str, Enum):
    TAXABLE = "TAXABLE"
    NON_TAXABLE = "NON_TAXABLE"
    EXEMPT_FLAGGED = "EXEMPT_FLAGGED"


class DisposalStatus(str, Enum):
    RECORDED = "RECORDED"
    RECONCILED = "RECONCILED"
    REVERSED = "REVERSED"


class RenditionStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AMENDMENT_OPEN = "AMENDMENT_OPEN"
    ACCEPTED = "ACCEPTED"


class ExtensionStatus(str, Enum):
    GRANTED = "GRANTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class NoticeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    PROTESTED = "PROTESTED"
    FINALIZED = "FINALIZED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    DECIDED = "DECIDED"
    ACCEPTED = "ACCEPTED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class AppealDecision(str, Enum):
    GRANTED_REDUCTION = "GRANTED_REDUCTION"
    DENIED = "DENIED"


class BillValidationStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    DISCREPANCY = "DISCREPANCY"


class BillPaymentStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LATE = "LATE"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ExemptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class AbatementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECERTIFICATION_DUE = "RECERTIFICATION_DUE"
    TERMINATED = "TERMINATED"


class ForecastStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ForecastVariant(str, Enum):
    NOTICE_BASED = "NOTICE_BASED"
    RENDERED_CONSERVATIVE = "RENDERED_CONSERVATIVE"


class AssetCategory(str, Enum):
    MACHINERY = "MACHINERY"
    FURNITURE = "FURNITURE"
    COMPUTER = "COMPUTER"
    VEHICLE = "VEHICLE"
    INVENTORY = "INVENTORY"
    LEASEHOLD_IMPROVEMENT = "LEASEHOLD_IMPROVEMENT"


class DepreciationConvention(str, Enum):
    FULL_YEAR = "FULL_YEAR"
    HALF_YEAR = "HALF_YEAR"


class PenaltyBase(str, Enum):
    VALUE_BASE = "VALUE_BASE"
    TAX_BASE = "TAX_BASE"


class ClientAccount(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    forecast_sequence: int
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    display_name: str
    operator_role: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    county_name: str
    state_code: str
    base_deadline_mmdd: str
    max_extension_days: int
    late_penalty_pct_per_month: int
    max_late_penalty_pct: int
    penalty_base: str
    tax_rate: float
    offered_exemption_types: List[str]
    max_exemption_pct: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionClassRule(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    category: str
    is_taxable: bool
    depreciation_convention: str
    percent_good_vector: List[int]
    percent_good_floor_pct: int
    de_minimis_line_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    client_id: str
    jurisdiction_id: str
    asset_tag: str
    category: str
    acquisition_cost_cents: int
    acquisition_date: str
    in_service_date: str
    lifecycle_status: str
    classification_status: str
    taxable_classification: Optional[str]
    disposed_date: Optional[str]
    disposal_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DisposalRecord(TypedDict, total=False):
    id: str
    asset_id: str
    disposal_date: str
    disposal_proceeds_cents: int
    disposal_status: str
    created_at: str
    updated_at: str
    version: int


class RenditionLine(TypedDict, total=False):
    line_no: int
    asset_id: str
    category: str
    acquisition_cost_cents: int
    age_years: int
    percent_good_applied: int
    assessed_value_cents: int
    taxable_classification: Optional[str]
    included: bool
    exclusion_reason: Optional[str]


class Rendition(TypedDict, total=False):
    id: str
    client_id: str
    jurisdiction_id: str
    tax_year: int
    rendition_status: str
    lines: List[RenditionLine]
    total_assessed_value_cents: int
    deadline_date: Optional[str]
    is_late_filing: bool
    late_days: int
    late_penalty_months: int
    late_penalty_cents: int
    filed_at: Optional[str]
    filed_by_operator_id: Optional[str]
    amendment_opened_by_operator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilingExtension(TypedDict, total=False):
    id: str
    rendition_id: str
    requested_extend_to_date: str
    granted_days: Optional[int]
    extension_status: str
    created_at: str
    updated_at: str
    version: int


class AssessmentNotice(TypedDict, total=False):
    id: str
    rendition_id: str
    notice_value_cents: int
    received_date: str
    protest_deadline_date: str
    notice_status: str
    final_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    notice_id: str
    claimed_value_cents: int
    grounds: str
    appeal_status: str
    hearing_date: Optional[str]
    decision: Optional[str]
    decided_value_cents: Optional[int]
    board_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    installment_no: int
    due_date: str
    amount_cents: int
    installment_status: str
    paid_date: Optional[str]


class TaxBill(TypedDict, total=False):
    id: str
    notice_id: str
    billed_amount_cents: int
    tax_rate: float
    due_date: str
    validated_amount_cents: Optional[int]
    variance_cents: Optional[int]
    validation_status: str
    payment_status: str
    installments: List[Installment]
    unscheduled_amount_cents: Optional[int]
    created_by_operator_id: str
    validated_by_operator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionApplication(TypedDict, total=False):
    id: str
    asset_id: str
    exemption_type: str
    exemption_pct: int
    effective_date: str
    expiration_date: str
    application_status: str
    suspended_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbatementAgreement(TypedDict, total=False):
    id: str
    asset_id: str
    first_tax_year: int
    last_tax_year: int
    abatement_pct: int
    agreement_status: str
    last_recertified_year: int
    created_at: str
    updated_at: str
    version: int


class AccrualForecast(TypedDict, total=False):
    id: str
    client_id: str
    tax_year: int
    variant: str
    as_of_date: str
    forecasted_liability_cents: int
    component_count: int
    forecast_status: str
    needs_regeneration: bool
    published_by_operator_id: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record: carries only id + created_at (no updated_at, no version).
class AuditEvent(TypedDict, total=False):
    id: str
    client_id: str
    event_type: str
    message: str
    actor_id: str
    created_at: str
