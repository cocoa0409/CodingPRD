"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SAM_PLATFORM_ADMIN = "SAMPlatformAdmin"
    SAM_MANAGER = "SAMManager"
    IT_ANALYST = "ITAnalyst"
    LEGAL_COUNSEL = "LegalCounsel"
    PROCUREMENT_LEAD = "ProcurementLead"
    VENDOR_AUDITOR = "VendorAuditor"


class LicenseMetric(str, Enum):
    PER_INSTALL = "PER_INSTALL"
    PER_USER = "PER_USER"
    PER_CORE = "PER_CORE"


class CoverageClass(str, Enum):
    PRODUCTION = "PRODUCTION"
    NON_PRODUCTION = "NON_PRODUCTION"
    DISASTER_RECOVERY = "DISASTER_RECOVERY"


class EntitlementSource(str, Enum):
    MANUAL_IMPORT = "MANUAL_IMPORT"
    CONTRACT_EXTRACT = "CONTRACT_EXTRACT"
    AUTO_TRUE_UP = "AUTO_TRUE_UP"


class EntitlementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class Environment(str, Enum):
    PRODUCTION = "PRODUCTION"
    NON_PRODUCTION = "NON_PRODUCTION"


class MeasurementMethod(str, Enum):
    SCAN = "SCAN"
    MANUAL_DECLARATION = "MANUAL_DECLARATION"


class DeploymentStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXCLUDED = "EXCLUDED"


class GapSeverity(str, Enum):
    COMPLIANT = "COMPLIANT"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class PositionBasis(str, Enum):
    SELF_AUDIT = "SELF_AUDIT"
    VENDOR_MEASURED = "VENDOR_MEASURED"
    AGREED = "AGREED"


class AuditCaseStatus(str, Enum):
    NOTICE_RECEIVED = "NOTICE_RECEIVED"
    SCOPE_NEGOTIATION = "SCOPE_NEGOTIATION"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    FINDINGS_REVIEW = "FINDINGS_REVIEW"
    SETTLEMENT_NEGOTIATION = "SETTLEMENT_NEGOTIATION"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    WITHDRAWN = "WITHDRAWN"


class ScopeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    EXCLUDED = "EXCLUDED"


class ProposedBy(str, Enum):
    VENDOR = "VENDOR"
    CUSTOMER = "CUSTOMER"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    PRIVILEGE_REVIEW = "PRIVILEGE_REVIEW"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"


class OfferedBy(str, Enum):
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"


class OfferStatus(str, Enum):
    TENDERED = "TENDERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class RemediationActionType(str, Enum):
    UNINSTALL = "UNINSTALL"
    PURCHASE_TRUE_UP = "PURCHASE_TRUE_UP"


class RemediationStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AlertType(str, Enum):
    OVER_DEPLOYMENT = "OVER_DEPLOYMENT"
    ENTITLEMENT_EXPIRING = "ENTITLEMENT_EXPIRING"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    SUPPRESSED = "SUPPRESSED"
    RESOLVED = "RESOLVED"


class Vendor(TypedDict):
    id: str
    name: str
    vendor_code: str
    default_license_metric: str
    notice_response_deadline_days: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    vendor_id: str
    name: str
    license_metric: str
    unit_list_price_cents: int
    support_rate_pct: float
    mission_critical: bool
    counts_non_production: bool
    created_at: str
    updated_at: str
    version: int


class EntitlementRecord(TypedDict):
    id: str
    product_id: str
    purchase_order_number: str
    quantity: int
    coverage_class: str
    effective_from: str
    effective_to: Optional[str]
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeploymentRecord(TypedDict):
    id: str
    product_id: str
    measured_quantity: int
    environment: str
    measurement_method: str
    measured_on: str
    status: str
    excluded_by_remediation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicensePosition(TypedDict):
    id: str
    product_id: str
    entitled_quantity: int
    deployed_quantity: int
    gap_quantity: int
    gap_severity: str
    self_audit_exposure_cents: int
    vendor_list_exposure_cents: int
    position_basis: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict):
    id: str
    vendor_id: str
    audit_firm_name: str
    notice_received_on: str
    response_deadline_on: str
    status: str
    provisional_case_exposure_cents: int
    worst_case_exposure_cents: int
    settled_amount_cents: Optional[int]
    accepted_future_discount_pct: Optional[float]
    last_tendered_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditScopeItem(TypedDict):
    id: str
    audit_case_id: str
    product_id: str
    proposed_by: str
    inclusion_rationale: str
    dispute_rationale: Optional[str]
    scope_status: str
    vendor_finding_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DataSubmission(TypedDict):
    id: str
    audit_case_id: str
    submission_label: str
    covered_scope_item_ids: List[str]
    contains_privileged: bool
    prepared_by_user_id: str
    status: str
    released_on: Optional[str]
    released_exposure_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict):
    id: str
    audit_case_id: str
    offered_by: str
    tendered_by_user_id: str
    amount_cents: int
    future_license_discount_pct: float
    status: str
    supersedes_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict):
    id: str
    product_id: str
    action_type: str
    quantity: int
    status: str
    generated_entitlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringAlert(TypedDict):
    id: str
    product_id: str
    alert_type: str
    severity: str
    status: str
    triggered_value: float
    threshold_value: float
    suppressed_value: Optional[float]
    created_at: str
    updated_at: str
    version: int
