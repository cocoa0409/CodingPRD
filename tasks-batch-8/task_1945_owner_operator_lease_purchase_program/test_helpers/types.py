"""Domain types: entity TypedDicts, status enums, role enum.

All ten primary resources carry the standard system-managed properties
(id, created_at, updated_at, version) described in PRD section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    LEASE_ADMIN = "LeaseAdmin"
    SETTLEMENT_CLERK = "SettlementClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    MAINTENANCE_COORDINATOR = "MaintenanceCoordinator"
    DRIVER = "Driver"


class ClassificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    IN_RETURN = "IN_RETURN"
    RETURNED = "RETURNED"
    SOLD = "SOLD"


class LeaseStatus(str, Enum):
    APPLICATION = "APPLICATION"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class EscrowStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    FULL = "FULL"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    CLOSED = "CLOSED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class LaneStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class WorkOrderCategory(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    REPAIR = "REPAIR"
    RECALL = "RECALL"


class BilledTo(str, Enum):
    CARRIER = "CARRIER"
    OPERATOR = "OPERATOR"
    WARRANTY = "WARRANTY"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DocType(str, Enum):
    W9 = "W9"
    OPERATING_AUTHORITY = "OPERATING_AUTHORITY"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"
    MEDICAL_CARD = "MEDICAL_CARD"


class DocStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class QuoteKind(str, Enum):
    SCHEDULED = "SCHEDULED"
    EARLY = "EARLY"


class QuoteStatus(str, Enum):
    GENERATED = "GENERATED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class OwnerOperator(TypedDict, total=False):
    id: str
    legal_name: str
    cdl_number: str
    classification_status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict, total=False):
    id: str
    vin: str
    year: int
    make: str
    model: str
    odometer_current: int
    powertrain_warranty_expires_on: str
    powertrain_warranty_mileage_limit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict, total=False):
    id: str
    owner_operator_id: str
    truck_id: str
    start_date: str
    term_weeks: int
    weekly_payment_cents: int
    escrow_weekly_contribution_cents: int
    escrow_cap_cents: int
    buyout_base_price_cents: int
    min_revenue_guarantee_weekly_cents: int
    status: str
    missed_payment_count: int
    arrears_cents: int
    total_payments_applied_cents: int
    escrow_satisfied: bool
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict, total=False):
    id: str
    lease_id: str
    balance_cents: int
    total_credited_cents: int
    total_refunded_cents: int
    total_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict, total=False):
    id: str
    lease_id: str
    week_start_date: str
    gross_revenue_cents: int
    fuel_gallons: float
    fuel_price_cents_per_gallon: int
    insurance_weekly_cents: int
    miles_driven: int
    load_declined_flag: bool
    fuel_deduction_cents: int
    maintenance_deduction_cents: int
    guarantee_top_up_cents: int
    escrow_contribution_cents: int
    lease_payment_applied_cents: int
    payment_short_flag: bool
    net_pay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LaneAssignment(TypedDict, total=False):
    id: str
    lease_id: str
    origin: str
    destination: str
    weekly_commitment_cents: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict, total=False):
    id: str
    bay_code: str
    location: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict, total=False):
    id: str
    lease_id: str
    service_bay_id: str
    category: str
    description: str
    scheduled_start: str
    scheduled_end: str
    estimated_cost_cents: int
    actual_cost_cents: int
    odometer_at_service: int
    completed_at: str
    billed_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceDocument(TypedDict, total=False):
    id: str
    owner_operator_id: str
    doc_type: str
    expires_on: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuyoutQuote(TypedDict, total=False):
    id: str
    lease_id: str
    quote_kind: str
    quoted_price_cents: int
    escrow_credit_cents: int
    arrears_carried_cents: int
    amount_due_cents: int
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int
