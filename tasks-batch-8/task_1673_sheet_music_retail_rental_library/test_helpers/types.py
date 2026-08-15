"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    LIBRARY_ADMIN = "LibraryAdmin"
    LIBRARY_CLERK = "LibraryClerk"
    RETURNS_CLERK = "ReturnsClerk"
    BILLING_MANAGER = "BillingManager"
    RIGHTS_ADVISOR = "RightsAdvisor"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class PublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EnsembleTier(str, Enum):
    CHAMBER = "CHAMBER"
    BAND = "BAND"
    ORCHESTRA = "ORCHESTRA"


class LicenseFormat(str, Enum):
    PRINT_ONLY = "PRINT_ONLY"
    DIGITAL_ONLY = "DIGITAL_ONLY"
    PRINT_AND_DIGITAL = "PRINT_AND_DIGITAL"


class RightsClass(str, Enum):
    STANDARD = "STANDARD"
    GRAND_RIGHTS = "GRAND_RIGHTS"
    RESTRICTED = "RESTRICTED"


class WorkStatus(str, Enum):
    CATALOGED = "CATALOGED"
    WITHDRAWN = "WITHDRAWN"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ReturnCondition(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    LOST = "LOST"


class RentalSetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    UNDER_REPAIR = "UNDER_REPAIR"
    RETIRED = "RETIRED"


class AccountKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    SCHOOL = "SCHOOL"
    INSTITUTION = "INSTITUTION"


class CreditTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    PREPAY = "PREPAY"


class Standing(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"
    BARRED = "BARRED"


class PurchaseOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class FulfillmentFormat(str, Enum):
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"


class RentalOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    ON_LOAN = "ON_LOAN"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RentalLineStatus(str, Enum):
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    ON_LOAN = "ON_LOAN"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    LOST = "LOST"
    RELEASED = "RELEASED"


class ConditionReportStatus(str, Enum):
    FILED = "FILED"
    INVOICED = "INVOICED"
    SUPERSEDED = "SUPERSEDED"


class DamageInvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_WAIVED = "RESOLVED_WAIVED"


class PerusalFormat(str, Enum):
    PHYSICAL = "PHYSICAL"
    DIGITAL = "DIGITAL"


class PerusalRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    OVERDUE_PERUSAL = "OVERDUE_PERUSAL"
    RETURNED = "RETURNED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class ConvertedTargetKind(str, Enum):
    NONE = "NONE"
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class SaleRecordStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class VenueKind(str, Enum):
    EDUCATIONAL = "EDUCATIONAL"
    CONCERT = "CONCERT"
    COMPETITION = "COMPETITION"
    RELIGIOUS = "RELIGIOUS"


class Determination(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    LICENSE_REQUIRED = "LICENSE_REQUIRED"
    PROHIBITED = "PROHIBITED"


class RightsCaseStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity records — every resource carries id / created_at / updated_at /
# version (PRD §2.4).
# ---------------------------------------------------------------------------

class Publisher(TypedDict, total=False):
    id: str
    name: str
    rental_discount_pct: float
    allows_digital_perusal: bool
    print_only_rental: bool
    out_of_print: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Work(TypedDict, total=False):
    id: str
    publisher_id: str
    title: str
    catalog_number: str
    ensemble_tier: str
    base_rental_rate_cents: int
    sale_price_cents: int
    license_format: str
    perusal_allowed: bool
    rights_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalSet(TypedDict, total=False):
    id: str
    work_id: str
    set_code: str
    copy_count: int
    available_copy_count: int
    condition_grade: str
    replacement_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    account_name: str
    account_kind: str
    credit_tier: str
    credit_limit_cents: int
    open_exposure_cents: int
    settled_exposure_cents: int
    standing: str
    requires_purchase_order: bool
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    account_id: str
    po_number: str
    authorized_amount_cents: int
    encumbered_cents: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalOrder(TypedDict, total=False):
    id: str
    account_id: str
    rental_set_id: str
    purchase_order_id: Optional[str]
    fulfillment_format: str
    copies_requested: int
    checkout_date: str
    due_date: str
    loan_periods: int
    estimated_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    renewal_count: int
    prepayment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalLine(TypedDict, total=False):
    id: str
    rental_order_id: str
    copy_seq: int
    checkout_condition: str
    return_condition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict, total=False):
    id: str
    rental_line_id: str
    assessor_user_id: str
    observed_grade: str
    findings: Optional[str]
    assessed_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageInvoice(TypedDict, total=False):
    id: str
    rental_line_id: str
    condition_report_id: str
    account_id: str
    amount_cents: int
    issuer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PerusalRequest(TypedDict, total=False):
    id: str
    account_id: str
    work_id: str
    format: str
    ship_date: Optional[str]
    return_due_date: Optional[str]
    hold_start: Optional[str]
    hold_end: Optional[str]
    converted_target_kind: str
    converted_target_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleRecord(TypedDict, total=False):
    id: str
    account_id: str
    work_id: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    balance_due_cents: int
    perusal_request_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RightsAdvisoryCase(TypedDict, total=False):
    id: str
    account_id: str
    work_id: str
    venue_kind: str
    question: str
    determination: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
