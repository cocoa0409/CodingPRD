"""Domain types: entity TypedDicts, status enums, role enum.

All fourteen resources carry the standard system-managed fields
(id, created_at, updated_at, version) described in PRD section 2.4.
Nullable event timestamps are typed Optional.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class ProductKind(str, Enum):
    MODULE = "MODULE"
    INVERTER = "INVERTER"
    RACKING = "RACKING"
    BOS = "BOS"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    OBSOLETE = "OBSOLETE"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TariffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class InstallerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LotStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    ON_HAND = "ON_HAND"
    DEPLETED = "DEPLETED"
    STRANDED = "STRANDED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ContainerStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROGRESS_BILLED = "PROGRESS_BILLED"
    PTO_BILLED = "PTO_BILLED"
    PAID_IN_FULL = "PAID_IN_FULL"
    WRITTEN_OFF = "WRITTEN_OFF"


class FulfillmentStatus(str, Enum):
    DESIGN = "DESIGN"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class InvoiceKind(str, Enum):
    PROGRESS = "PROGRESS"
    PTO = "PTO"
    CREDIT_MEMO = "CREDIT_MEMO"
    WRITE_OFF = "WRITE_OFF"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"
    PAST_DUE = "PAST_DUE"


class PaymentRecordStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class RmaStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    CLOSED = "CLOSED"


class PermitStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class UserRole(str, Enum):
    DISTRIBUTION_ADMIN = "DistributionAdmin"
    CHANNEL_MANAGER = "ChannelManager"
    INSTALLER_REP = "InstallerRep"
    CREDIT_OFFICER = "CreditOfficer"


class Product(TypedDict, total=False):
    id: str
    sku: str
    product_kind: str
    manufacturer_name: str
    wattage_w: int
    ac_output_w: int
    dc_input_max_w: int
    technology_generation: int
    hts_code: str
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompatibilityRule(TypedDict, total=False):
    id: str
    module_product_id: str
    inverter_product_id: str
    max_modules_per_inverter: int
    min_modules_per_inverter: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffRate(TypedDict, total=False):
    id: str
    hts_code: str
    duty_rate_bp: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Installer(TypedDict, total=False):
    id: str
    legal_name: str
    license_number: str
    credit_limit_cents: int
    progress_payment_pct_bp: int
    payment_terms_days: int
    credit_exposure_cents: int
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    product_id: str
    lot_code: str
    qty_on_hand: int
    qty_allocated: int
    qty_available: int
    qty_quarantined: int
    unit_cost_cents_provisional: int
    unit_cost_cents_final: Optional[int]
    received_at: Optional[str]
    stranded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    container_number: str
    bol_number: str
    origin_port: str
    eta_utc: str
    actual_arrival_utc: Optional[str]
    freight_cost_cents: int
    insurance_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContainerLine(TypedDict, total=False):
    id: str
    container_id: str
    inventory_lot_id: str
    qty_booked: int
    qty_received: int
    qty_damaged: int
    product_id: str
    declared_unit_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    installer_id: str
    project_name: str
    site_postal_code: str
    system_size_kw_dc: Optional[float]
    module_product_id: str
    inverter_product_id: str
    module_qty: int
    inverter_qty: int
    compatibility_rule_id: Optional[str]
    design_locked_at: Optional[str]
    allocated_value_cents: int
    invoiced_value_cents: int
    paid_value_cents: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    project_id: str
    inventory_lot_id: str
    qty_allocated: int
    unit_cost_cents_at_allocation: int
    expected_lot_version: int
    allocated_at: str
    released_at: Optional[str]
    shipped_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    project_id: str
    installer_id: str
    invoice_kind: str
    amount_cents: int
    balance_due_cents: int
    invoice_date: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    invoice_id: str
    amount_cents: int
    posted_at: str
    reversed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RmaClaim(TypedDict, total=False):
    id: str
    installer_id: str
    product_id: str
    allocation_id: str
    qty_claimed: int
    qty_approved: int
    credit_amount_cents: int
    manufacturer_rma_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitPackage(TypedDict, total=False):
    id: str
    project_id: str
    ahj_code: str
    required_documents: List[str]
    submitted_documents: List[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    container_id: str
    container_line_id: str
    qty_damaged: int
    claimed_amount_cents: int
    filed_at: Optional[str]
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
