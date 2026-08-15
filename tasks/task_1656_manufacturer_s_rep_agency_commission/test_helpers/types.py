"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class PrincipalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTICE_PENDING = "NOTICE_PENDING"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class RateScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMMISSION_HOLD = "COMMISSION_HOLD"


class RegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class FulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class CommissionStatus(str, Enum):
    ATTRIBUTED = "ATTRIBUTED"
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class SplitRole(str, Enum):
    REGISTERED = "REGISTERED"
    SPECIFY = "SPECIFY"
    SHIP_TO = "SHIP_TO"
    HOUSE = "HOUSE"
    OVERRIDE = "OVERRIDE"


class RmaStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class EntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    CHARGEBACK = "CHARGEBACK"
    ADJUSTMENT = "ADJUSTMENT"
    STATEMENT_PAYMENT = "STATEMENT_PAYMENT"
    DRAW_RECOVERY = "DRAW_RECOVERY"
    SAMPLE_CHARGE = "SAMPLE_CHARGE"


class StatementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_RECONCILIATION = "IN_RECONCILIATION"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class LineDisposition(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    AMOUNT_VARIANCE = "AMOUNT_VARIANCE"
    UNMATCHED_ORDER = "UNMATCHED_ORDER"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    VARIANCE_ACCEPTED = "VARIANCE_ACCEPTED"


class SampleUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    CHECKED_OUT = "CHECKED_OUT"
    CONVERTED = "CONVERTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class CheckoutStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"
    CONVERTED = "CONVERTED"
    CHARGED = "CHARGED"


class ReturnCondition(str, Enum):
    SELLABLE = "SELLABLE"
    DAMAGED = "DAMAGED"


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    REP = "Rep"
    PRINCIPAL_OPS = "PrincipalOps"
    AUDITOR = "Auditor"


class OrderLine(TypedDict, total=False):
    line_id: str
    family_code: str
    quantity: int
    unit_price_cents: int
    spec_territory_code: Optional[str]
    ship_to_territory_code: Optional[str]
    shipped_qty: int
    returned_qty: int
    applied_rate_bp: Optional[int]
    commission_cents: Optional[int]
    protected_registration_id: Optional[str]


class Principal(TypedDict, total=False):
    id: str
    name: str
    annual_quota_cents: int
    notice_period_days: int
    status: str
    termination_notice_issued_at: Optional[str]
    termination_effective_at: Optional[str]
    credited_ytd_sales_cents: int
    ytd_year: int
    created_at: str
    updated_at: str
    version: int


class TerritoryAgreement(TypedDict, total=False):
    id: str
    principal_id: str
    territory_codes: List[str]
    exclusive: bool
    specify_share_bp: int
    registered_protection_share_bp: int
    effective_start: str
    effective_end: Optional[str]
    tail_period_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    principal_id: str
    family_rates: List[dict]
    attainment_tiers: List[dict]
    registration_bonus_bp: int
    status: str
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class Rep(TypedDict, total=False):
    id: str
    display_name: str
    territory_codes: List[str]
    status: str
    commission_balance_cents: int
    outstanding_draw_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    spec_territory_code: str
    ship_to_territory_code: str
    created_at: str
    updated_at: str
    version: int


class ProjectRegistration(TypedDict, total=False):
    id: str
    principal_id: str
    customer_id: str
    rep_id: str
    family_code: str
    project_name: str
    submitted_at: str
    protection_start: Optional[str]
    protection_end: Optional[str]
    renewals_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    principal_id: str
    external_order_ref: str
    placed_at: str
    lines: List[OrderLine]
    fulfillment_status: str
    commission_status: str
    shipped_at: Optional[str]
    invoiced_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderSplit(TypedDict, total=False):
    id: str
    order_id: str
    line_id: str
    rep_id: Optional[str]
    role: str
    share_bp: int
    is_override: bool
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    order_id: str
    principal_id: str
    lines: List[dict]
    status: str
    provisional_chargeback_cents: Optional[int]
    final_chargeback_cents: Optional[int]
    requested_at: str
    approved_at: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict, total=False):
    # Append-only ledger row (PRD §2.4): carries ONLY id + created_at —
    # updated_at and version are absent by contract.
    id: str
    rep_id: str
    principal_id: str
    order_id: Optional[str]
    statement_id: Optional[str]
    type: str
    amount_cents: int
    ref_line_id: Optional[str]
    business_date: str
    note: Optional[str]
    created_at: str


class StatementLine(TypedDict, total=False):
    line_id: str
    external_order_ref: str
    amount_cents: int
    disposition: str


class CommissionStatement(TypedDict, total=False):
    id: str
    principal_id: str
    period_label: str
    lines: List[StatementLine]
    stated_total_cents: int
    expected_total_cents: Optional[int]
    expected_cash_basis_cents: Optional[int]
    variance_cents: Optional[int]
    status: str
    reconciled_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SampleUnit(TypedDict, total=False):
    id: str
    principal_id: str
    serial_number: str
    family_code: str
    value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SampleCheckout(TypedDict, total=False):
    id: str
    sample_unit_id: str
    rep_id: str
    checked_out_at: str
    due_at: str
    returned_at: Optional[str]
    condition_on_return: Optional[str]
    charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
