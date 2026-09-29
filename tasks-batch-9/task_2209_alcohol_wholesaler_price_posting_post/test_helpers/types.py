"""Domain types for the Alcohol Price Posting API: status enums, role enums, entity TypedDicts.

Field names mirror the PRD exactly. `AuditFinding` is immutable and therefore
carries only `id` and `created_at` alongside its payload fields (PRD §2.5).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enums
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    """Values of the `X-User-Role` header recognised by the API (PRD §2.1)."""

    FILING_AGENT = "FilingAgent"
    CERTIFYING_OFFICER = "CertifyingOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class LicenseeUserRole(str, Enum):
    """Stored `user_role` of a LicenseeUser (PRD §3.1)."""

    FILING_AGENT = "FILING_AGENT"
    CERTIFYING_OFFICER = "CERTIFYING_OFFICER"
    DUAL_ROLE = "DUAL_ROLE"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BeverageClass(str, Enum):
    SPIRITS = "SPIRITS"
    WINE = "WINE"
    MALT = "MALT"


class BrandRegistrationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PriceScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    POSTED = "POSTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class PriceScheduleItemStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class QuantityDiscountTierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CombinationSaleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class HoldAmendmentStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class ErrorCorrectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class InvoiceValidationStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    FLAGGED = "FLAGGED"


class InvoiceAuditStatus(str, Enum):
    NOT_AUDITED = "NOT_AUDITED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ASSESSED = "ASSESSED"


class ComplianceAuditStatus(str, Enum):
    OPEN = "OPEN"
    COLLECTED = "COLLECTED"
    ASSESSED = "ASSESSED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class FindingType(str, Enum):
    OFF_POSTED_UNDERCHARGE = "OFF_POSTED_UNDERCHARGE"
    OFF_POSTED_OVERCHARGE = "OFF_POSTED_OVERCHARGE"
    EXCESS_PROMOTIONAL_ALLOWANCE = "EXCESS_PROMOTIONAL_ALLOWANCE"
    EXCESS_DEPLETION_ALLOWANCE = "EXCESS_DEPLETION_ALLOWANCE"
    UNPOSTED_BRAND = "UNPOSTED_BRAND"


class PostedPriceVariant(str, Enum):
    AS_AMENDED = "as_amended"
    AS_CERTIFIED = "as_certified"


class ExposureVariant(str, Enum):
    ASSESSED_EXPOSURE = "assessed_exposure"
    PROVISIONAL_EXPOSURE = "provisional_exposure"


# --------------------------------------------------------------------------
# Entity TypedDicts — records carrying id/created_at/updated_at/version
# --------------------------------------------------------------------------

class StateProgram(TypedDict):
    id: str
    state_code: str
    program_name: str
    posting_deadline_day: int
    hold_window_days: int
    correction_window_days: int
    combo_cooldown_days: int
    quantity_discount_allowed: bool
    combination_sale_allowed: bool
    max_quantity_discount_pct: float
    max_promotional_allowance_pct: float
    depletion_allowance_per_case_cents: int
    late_filing_penalty_cents: int
    repeat_correction_penalty_cents: int
    frivolous_amendment_penalty_cents: int
    off_posted_penalty_rate_pct: float
    max_corrections_per_schedule: int
    created_at: str
    updated_at: str
    version: int


class Wholesaler(TypedDict):
    id: str
    license_number: str
    legal_name: str
    state_program_id: str
    license_status: str
    late_filing_penalty_accrued_cents: int
    correction_penalty_accrued_cents: int
    amendment_penalty_accrued_cents: int
    assessed_penalty_cents: int
    penalty_exposure_cents: int
    late_filing_count: int
    frivolous_amendment_count: int
    off_posted_violation_count: int
    open_audit_count: int
    created_at: str
    updated_at: str
    version: int


class LicenseeUser(TypedDict):
    id: str
    wholesaler_id: str
    full_name: str
    user_role: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict):
    id: str
    wholesaler_id: str
    brand_name: str
    supplier_name: str
    beverage_class: str
    registration_status: str
    registration_effective_from: str
    registration_expires_on: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceSchedule(TypedDict):
    id: str
    wholesaler_id: str
    state_program_id: str
    posting_month: str
    effective_date: str
    status: str
    filed_at: Optional[str]
    filed_by_user_id: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    hold_window_ends_at: Optional[str]
    is_late: bool
    return_reason: Optional[str]
    return_count: int
    correction_count: int
    item_count: int
    superseded_by_schedule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceScheduleItem(TypedDict):
    id: str
    schedule_id: str
    brand_id: str
    size_ml: int
    bottles_per_case: int
    case_price_cents: int
    unit_price_cents: int
    certified_case_price_cents: Optional[int]
    certified_unit_price_cents: Optional[int]
    status: str
    amendment_count: int
    correction_count: int
    supersedes_item_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuantityDiscountTier(TypedDict):
    id: str
    item_id: str
    min_cases: int
    discount_pct: float
    discounted_case_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CombinationSale(TypedDict):
    id: str
    schedule_id: str
    member_item_ids: List[str]
    promo_starts_at: str
    promo_ends_at: str
    combined_case_price_cents: int
    floor_price_cents: int
    min_allowed_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HoldAmendment(TypedDict):
    id: str
    amending_item_id: str
    reference_item_id: str
    new_case_price_cents: int
    new_unit_price_cents: int
    status: str
    prior_case_price_cents: Optional[int]
    prior_unit_price_cents: Optional[int]
    rejection_reason: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ErrorCorrection(TypedDict):
    id: str
    item_id: str
    corrected_case_price_cents: int
    corrected_unit_price_cents: int
    reason: str
    status: str
    prior_case_price_cents: Optional[int]
    prior_unit_price_cents: Optional[int]
    variance_pct: float
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailerInvoice(TypedDict):
    id: str
    wholesaler_id: str
    retailer_license_number: str
    invoice_date: str
    validation_status: str
    audit_status: str
    audit_id: Optional[str]
    line_count: int
    subtotal_cents: int
    surcharge_cents: int
    total_cents: int
    total_allowance_cents: int
    off_posted_line_count: int
    total_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    item_id: str
    cases_quantity: int
    bottles_quantity: int
    case_price_charged_cents: int
    unit_price_charged_cents: int
    promotional_allowance_cents: int
    depletion_allowance_cents: int
    gross_cents: int
    quantity_discount_cents: int
    allowed_promotional_cents: int
    excess_promotional_cents: int
    allowed_depletion_cents: int
    excess_depletion_cents: int
    net_price_cents: int
    posted_gross_cents: int
    variance_cents: int
    finding_variance_cents: int
    is_off_posted: bool
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    wholesaler_id: str
    state_program_id: str
    audit_period_month: str
    status: str
    finding_count: int
    total_variance_cents: int
    base_penalty_cents: int
    tier_multiplier: float
    penalty_assessed_cents: int
    prior_violation_count: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Immutable record — carries ONLY id + created_at plus payload fields
# --------------------------------------------------------------------------

class AuditFinding(TypedDict):
    id: str
    created_at: str
    audit_id: str
    invoice_line_id: str
    finding_type: str
    variance_cents: int
    penalty_component_cents: int


# --------------------------------------------------------------------------
# Computed read payloads
# --------------------------------------------------------------------------

class PostedPriceResolution(TypedDict):
    item_id: str
    variant: str
    as_of: str
    resolved_item_id: Optional[str]
    posted_case_price_cents: Optional[int]
    posted_unit_price_cents: Optional[int]


class PenaltyExposureReport(TypedDict):
    wholesaler_id: str
    variant: str
    accrued_cents: int
    provisional_cents: int
    exposure_cents: int


class PostingRunResult(TypedDict):
    state_program_id: str
    run_at: str
    processed_schedule_count: int
    effective_schedule_ids: List[str]
    superseded_schedule_ids: List[str]


class ClockPosition(TypedDict):
    current_utc: str
