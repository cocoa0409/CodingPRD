"""Domain types: entity TypedDicts, status enums, role enum.

Property & Casualty TPA claims administration domain.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ADJUSTER = "Adjuster"
    CLAIMS_MANAGER = "ClaimsManager"
    FINANCE_OFFICER = "FinanceOfficer"
    SIU_INVESTIGATOR = "SiuInvestigator"
    VENDOR = "Vendor"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSIGNED = "ASSIGNED"
    INVESTIGATING = "INVESTIGATING"
    EVALUATED = "EVALUATED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class SiuStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    CLEARED = "CLEARED"
    CONFIRMED = "CONFIRMED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"
    VOID = "VOID"


class VendorInvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    VOID = "VOID"


class LitigationStatus(str, Enum):
    OPEN = "OPEN"
    IN_SUIT = "IN_SUIT"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"
    JUDGMENT = "JUDGMENT"


class SubrogationStatus(str, Enum):
    OPEN = "OPEN"
    DEMAND_SENT = "DEMAND_SENT"
    NEGOTIATING = "NEGOTIATING"
    RECOVERED = "RECOVERED"
    CLOSED_NO_RECOVERY = "CLOSED_NO_RECOVERY"


class SiuReferralStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    CONFIRMED = "CONFIRMED"


class CoverageType(str, Enum):
    PROPERTY = "PROPERTY"
    AUTO = "AUTO"
    LIABILITY = "LIABILITY"
    WORKERS_COMP = "WORKERS_COMP"


class VendorType(str, Enum):
    INDEPENDENT_ADJUSTER = "INDEPENDENT_ADJUSTER"
    APPRAISER = "APPRAISER"
    CONTRACTOR = "CONTRACTOR"
    DEFENSE_ATTORNEY = "DEFENSE_ATTORNEY"


class AllocationMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    INDEMNITY_FIRST = "INDEMNITY_FIRST"


# ---- Entity TypedDicts (common_fields: true carries id/created_at/updated_at/version) ----

class ClientAccount(TypedDict):
    id: str
    name: str
    account_code: str
    sla_ack_hours: int
    sla_contact_hours: int
    reserve_authority_default_cents: int
    open_case_reserve_total_cents: int
    gross_incurred_total_cents: int
    recovered_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    client_account_id: str
    policy_number: str
    coverage_limit_cents: int
    deductible_cents: int
    per_claim_expense_limit_cents: int
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjuster(TypedDict):
    id: str
    name: str
    email: str
    authority_limit_cents: int
    max_open_claims: int
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    credentialed_coverages: List[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    client_account_id: str
    coverage_type: str
    loss_date: str
    reported_date: str
    claimant_name: str
    description: str
    status: str
    siu_status: str
    assigned_adjuster_id: Optional[str]
    indemnity_reserve_cents: int
    expense_reserve_cents: int
    paid_indemnity_cents: int
    paid_expense_cents: int
    recovered_cents: int
    recovered_indemnity_cents: int
    recovered_expense_cents: int
    gross_incurred_cents: int
    net_incurred_cents: int
    ack_at: Optional[str]
    sla_ack_due: Optional[str]
    sla_ack_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    claim_id: str
    assignee_type: str
    adjuster_id: Optional[str]
    vendor_id: Optional[str]
    scope: str
    inspection_start: str
    inspection_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ReserveChange — append-only event: carries ONLY id + created_at (no updated_at, no version)
class ReserveChange(TypedDict):
    id: str
    claim_id: str
    reserve_type: str
    delta_cents: int
    reason: str
    resulting_indemnity_reserve_cents: int
    resulting_expense_reserve_cents: int
    actor_role: str
    created_at: str


class Payment(TypedDict):
    id: str
    claim_id: str
    payment_type: str
    payee_type: str
    payee_name: str
    amount_cents: int
    status: str
    requires_manager_approval: bool
    approved_by_role: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorInvoice(TypedDict):
    id: str
    claim_id: str
    assignment_id: str
    vendor_id: str
    hours: float
    miles: float
    materials_cents: int
    amount_cents: int
    status: str
    approved_by_role: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LitigationCase(TypedDict):
    id: str
    claim_id: str
    defense_vendor_id: Optional[str]
    venue: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubrogationCase(TypedDict):
    id: str
    claim_id: str
    at_fault_party: str
    demand_cents: int
    recovered_cents: int
    allocation_method: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SiuReferral(TypedDict):
    id: str
    claim_id: str
    reason: str
    place_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BordereauReport(TypedDict):
    id: str
    client_account_id: str
    period_start: str
    period_end: str
    basis: str
    total_claim_count: int
    total_incurred_dollars: int
    total_paid_dollars: int
    total_recovered_dollars: int
    created_at: str
    updated_at: str
    version: int
