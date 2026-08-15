"""Domain types: entity TypedDicts, status enums, role enum.

All enums spell values exactly as the PRD prose spells them. Every entity in
this domain carries the common system-managed fields id / created_at /
updated_at / version (PRD section on common resource properties).
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BUYER_MANAGER = "BuyerManager"
    SOURCING_AGENT = "SourcingAgent"
    FACTORY_REP = "FactoryRep"
    INSPECTOR = "Inspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class FactoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class AuditGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    NONE = "NONE"


class AuditType(str, Enum):
    SCREENING = "SCREENING"
    ONSITE = "ONSITE"


class AuditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DocType(str, Enum):
    SOCIAL_AUDIT = "SOCIAL_AUDIT"
    PRODUCT_TEST = "PRODUCT_TEST"
    LAB_TEST = "LAB_TEST"
    FIRE_SAFETY = "FIRE_SAFETY"


class DocStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ProductCategory(str, Enum):
    APPAREL = "APPAREL"
    ELECTRONICS = "ELECTRONICS"
    TOYS = "TOYS"
    FURNITURE = "FURNITURE"


class CommissionMode(str, Enum):
    FOB = "FOB"
    CIF = "CIF"


class SourcingRequestStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PO_PLACED = "PO_PLACED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SampleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"


class QuotationStatus(str, Enum):
    OPEN = "OPEN"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LastActorRole(str, Enum):
    FACTORY = "FACTORY"
    BUYER = "BUYER"


class POStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProductionStatus(str, Enum):
    PLACED = "PLACED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PRODUCTION_COMPLETE = "PRODUCTION_COMPLETE"


class PsiResult(str, Enum):
    NONE = "NONE"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    HANDED_OVER = "HANDED_OVER"


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InspectionType(str, Enum):
    DUPRO = "DUPRO"
    PSI = "PSI"


class InspectionStatus(str, Enum):
    BOOKED = "BOOKED"
    RESULT_RECORDED = "RESULT_RECORDED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DOCS_HANDED_OVER = "DOCS_HANDED_OVER"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Buyer(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    credit_balance_cents: int
    ytd_gmv_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    name: str
    agency_name: str
    commission_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class Factory(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    monthly_capacity_units: int
    status: str
    compliance_posture: str
    debit_balance_cents: int
    latest_audit_grade: str
    audit_score: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class FactoryAudit(TypedDict, total=False):
    id: str
    factory_id: str
    conducted_by_agent_id: str
    audit_type: str
    quality_system_score: int
    social_compliance_score: int
    production_capability_score: int
    financial_stability_score: int
    critical_findings: int
    score: int
    grade: str
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceDocument(TypedDict, total=False):
    id: str
    factory_id: str
    doc_type: str
    issued_date: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SourcingRequest(TypedDict, total=False):
    id: str
    buyer_id: str
    assigned_agent_id: str
    title: str
    product_category: str
    target_price_cents: int
    quantity: int
    commission_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict, total=False):
    id: str
    sourcing_request_id: str
    revision_count: int
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quotation(TypedDict, total=False):
    id: str
    sourcing_request_id: str
    factory_id: str
    unit_price_cents: int
    moq: int
    lead_time_days: int
    valid_until: str
    round_count: int
    last_actor_role: str
    purchase_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    quotation_id: str
    sourcing_request_id: str
    buyer_id: str
    factory_id: str
    assigned_agent_id: str
    ordered_qty: int
    unit_price_cents: int
    total_cents: int
    delivery_month: str
    freight_cents: int
    insurance_cents: int
    shipped_qty: int
    cancelled_qty: int
    open_qty: int
    milestone_plan_locked: bool
    progress_pct: int
    production_status: str
    latest_psi_result: str
    document_status: str
    ship_blocked: bool
    provisional_commission_cents: int
    final_commission_cents: Optional[int]
    commission_rate_bp: int
    remaining_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionMilestone(TypedDict, total=False):
    id: str
    po_id: str
    name: str
    weight_pct: int
    evidence_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    po_id: str
    inspector_id: str
    inspection_type: str
    scheduled_date: str
    duration_days: int
    lot_size: int
    sample_size: int
    defects_critical: int
    defects_major: int
    defects_minor: int
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    po_id: str
    shipped_qty: int
    vessel_ref: str
    doc_refs: List[Any]
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityClaim(TypedDict, total=False):
    id: str
    po_id: str
    filed_by_buyer_id: str
    items: List[Any]
    base_amount_cents: int
    defective_qty: int
    defect_rate: float
    penalty_cents: int
    total_chargeback_cents: int
    approved_by_agent_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
