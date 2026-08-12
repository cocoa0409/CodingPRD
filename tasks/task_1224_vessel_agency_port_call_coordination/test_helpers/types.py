"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the standard system-managed fields (id, created_at,
updated_at, version) described in PRD section "Common Resource Properties".
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    AGENCY_OPS = "AgencyOps"
    AGENCY_FINANCE = "AgencyFinance"
    PORT_AUTHORITY = "PortAuthority"
    PRINCIPAL_REP = "PrincipalRep"
    VENDOR_REP = "VendorRep"
    CREWING_AGENT = "CrewingAgent"
    HUSBANDRY_OFFICER = "HusbandryOfficer"


class PrincipalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PortCallOpsStatus(str, Enum):
    NOMINATED = "NOMINATED"
    PRE_ARRIVAL_FILED = "PRE_ARRIVAL_FILED"
    CLEARED_TO_ENTER = "CLEARED_TO_ENTER"
    ALONGSIDE = "ALONGSIDE"
    SAILED = "SAILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AuthorityType(str, Enum):
    PORT_STATE_CONTROL = "PORT_STATE_CONTROL"
    IMMIGRATION = "IMMIGRATION"
    CUSTOMS = "CUSTOMS"
    HARBOR_MASTER = "HARBOR_MASTER"


class NotificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class BerthWindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class ServiceOrderKind(str, Enum):
    PILOT = "PILOT"
    TUG = "TUG"
    LINEBOAT = "LINEBOAT"
    LAUNCH = "LAUNCH"


class ServiceOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewChangeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DOCS_VERIFIED = "DOCS_VERIFIED"
    VISA_PENDING = "VISA_PENDING"
    VISA_GRANTED = "VISA_GRANTED"
    SHORE_PASS_ISSUED = "SHORE_PASS_ISSUED"
    PASS_EXPIRED = "PASS_EXPIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REPATRIATED = "REPATRIATED"


class CrewDirection(str, Enum):
    ON_SIGNER = "ON_SIGNER"
    OFF_SIGNER = "OFF_SIGNER"


class VendorCategory(str, Enum):
    PROVISIONS = "PROVISIONS"
    BUNKERS = "BUNKERS"
    REPAIRS = "REPAIRS"
    STORES = "STORES"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    MATCHED = "MATCHED"
    CANCELLED = "CANCELLED"


class CargoDocType(str, Enum):
    BILL_OF_LADING = "BILL_OF_LADING"
    CARGO_MANIFEST = "CARGO_MANIFEST"
    DELIVERY_ORDER = "DELIVERY_ORDER"


class CargoDocStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    ON_HOLD = "ON_HOLD"
    RELEASED = "RELEASED"


class TariffComponent(str, Enum):
    PORT_DUES = "PORT_DUES"
    BERTH_HIRE = "BERTH_HIRE"
    PILOTAGE = "PILOTAGE"


class TariffStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class DAStatus(str, Enum):
    PRO_FORMA = "PRO_FORMA"
    SENT_TO_PRINCIPAL = "SENT_TO_PRINCIPAL"
    FUNDED = "FUNDED"
    FINAL = "FINAL"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


class DALineCategory(str, Enum):
    PORT_DUES = "PORT_DUES"
    PILOTAGE = "PILOTAGE"
    TOWAGE = "TOWAGE"
    BERTH_HIRE = "BERTH_HIRE"
    PROVISIONS = "PROVISIONS"
    BUNKERS = "BUNKERS"
    REPAIRS = "REPAIRS"
    STORES = "STORES"
    CREW_COSTS = "CREW_COSTS"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    SUNDRY = "SUNDRY"


class DALineStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUALIZED = "ACTUALIZED"
    DISPUTED = "DISPUTED"


class DALineSourceType(str, Enum):
    TARIFF = "TARIFF"
    SERVICE_ORDER = "SERVICE_ORDER"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    MANUAL = "MANUAL"


class FundingAdvanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class CostDisputeStatus(str, Enum):
    RAISED = "RAISED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    UPHELD = "UPHELD"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class HusbandryCaseType(str, Enum):
    MEDICAL = "MEDICAL"
    REPATRIATION = "REPATRIATION"
    DESERTION = "DESERTION"
    OTHER = "OTHER"


class HusbandrySeverity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class HusbandryCaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_TREATMENT = "IN_TREATMENT"
    CLEARED = "CLEARED"
    REPATRIATED = "REPATRIATED"


class Principal(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    credit_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PortCall(TypedDict, total=False):
    id: str
    principal_id: str
    vessel_name: str
    imo_number: str
    vessel_gt: int
    flag_state: str
    port_code: str
    eta: str
    etd: str
    hazmat_flag: bool
    cargo_description: str
    ops_status: str
    actual_arrival_at: Optional[str]
    actual_sailed_at: Optional[str]
    alongside_days_estimated: int
    alongside_days_actual: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuthorityNotification(TypedDict, total=False):
    id: str
    port_call_id: str
    authority_type: str
    payload_summary: str
    status: str
    authority_reference: Optional[str]
    rejection_reason: Optional[str]
    revision_count: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BerthWindow(TypedDict, total=False):
    id: str
    port_call_id: str
    berth_code: str
    start_at: str
    end_at: str
    status: str
    occupied_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict, total=False):
    id: str
    port_call_id: str
    kind: str
    vendor_id: Optional[str]
    resource_unit: str
    window_start: str
    window_end: str
    quantity: int
    estimated_cents: int
    actual_cents: Optional[int]
    cancellation_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewChange(TypedDict, total=False):
    id: str
    port_call_id: str
    full_name: str
    nationality: str
    passport_no: str
    passport_expiry: str
    direction: str
    requires_visa: bool
    status: str
    visa_reference: Optional[str]
    shore_pass_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    categories: List[str]
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    port_call_id: str
    vendor_id: str
    category: str
    estimated_cents: int
    needed_by: str
    status: str
    invoiced_cents: Optional[int]
    variance_pct: Optional[float]
    da_line_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CargoDocument(TypedDict, total=False):
    id: str
    port_call_id: str
    doc_type: str
    bl_number: str
    consignee_name: str
    freight_paid: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffTier(TypedDict, total=False):
    gt_up_to: Optional[int]
    rate_cents: float


class Tariff(TypedDict, total=False):
    id: str
    port_code: str
    component: str
    effective_from: str
    night_surcharge_pct: float
    hazmat_surcharge_pct: float
    gt_tiers: List[TariffTier]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisbursementAccount(TypedDict, total=False):
    id: str
    port_call_id: str
    status: str
    total_estimated_cents: int
    agency_fee_estimated_cents: int
    advance_required_cents: int
    advances_received_cents: int
    advances_applied_cents: int
    advances_refunded_cents: int
    funding_available_cents: int
    total_final_cents: Optional[int]
    agency_fee_final_cents: Optional[int]
    balance_due_cents: Optional[int]
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DALine(TypedDict, total=False):
    id: str
    da_id: str
    category: str
    description: str
    estimated_cents: int
    actual_cents: Optional[int]
    status: str
    source_type: str
    source_ref: Optional[str]
    tariff_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingAdvance(TypedDict, total=False):
    id: str
    da_id: str
    amount_cents: int
    applied_cents: int
    refunded_cents: int
    status: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class CostDispute(TypedDict, total=False):
    id: str
    da_id: str
    da_line_id: Optional[str]
    principal_id: str
    amount_cents: int
    reason: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HusbandryCase(TypedDict, total=False):
    id: str
    port_call_id: str
    crew_change_id: Optional[str]
    case_type: str
    severity: str
    summary: str
    status: str
    departure_waiver_granted: bool
    created_at: str
    updated_at: str
    version: int
