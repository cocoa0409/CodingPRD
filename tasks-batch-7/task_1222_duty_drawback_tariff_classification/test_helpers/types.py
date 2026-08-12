"""Domain types for the Duty Drawback & Tariff Classification API.

All primary resources carry the standard system-managed field set of PRD 2.5
(`id`, `created_at`, `updated_at`, `version`).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    ANALYST = "Analyst"
    LICENSED_BROKER = "LicensedBroker"
    COMPLIANCE_MANAGER = "ComplianceManager"
    CLIENT_CONTACT = "ClientContact"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClassificationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class RulingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class MatchBandStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    MATCHED = "MATCHED"


class ClaimType(str, Enum):
    DIRECT_IDENTIFICATION = "DIRECT_IDENTIFICATION"
    SUBSTITUTION = "SUBSTITUTION"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    DEFICIENCY_ISSUED = "DEFICIENCY_ISSUED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class MatchMethod(str, Enum):
    DIRECT = "DIRECT"
    SUBSTITUTION = "SUBSTITUTION"


class ClaimLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class MeasureType(str, Enum):
    EXCLUSION = "EXCLUSION"
    SECTION_301 = "SECTION_301"
    AD_CVD = "AD_CVD"
    SAFEGUARD = "SAFEGUARD"


class MeasureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class OpenedReason(str, Enum):
    CF28 = "CF28"
    FOCUSED_ASSESSMENT = "FOCUSED_ASSESSMENT"
    POST_PAYMENT_AUDIT = "POST_PAYMENT_AUDIT"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    RESPONSE_FILED = "RESPONSE_FILED"
    CLOSED_REFUTED = "CLOSED_REFUTED"
    CLOSED_SUSTAINED = "CLOSED_SUSTAINED"


class CulpabilityLevel(str, Enum):
    NONE = "NONE"
    NEGLIGENCE = "NEGLIGENCE"
    GROSS_NEGLIGENCE = "GROSS_NEGLIGENCE"
    FRAUD = "FRAUD"


class DocType(str, Enum):
    ENTRY_DOCS = "ENTRY_DOCS"
    EXPORT_PROOF = "EXPORT_PROOF"
    MATCHING_WORKSHEET = "MATCHING_WORKSHEET"


class RecordStatus(str, Enum):
    RETAINED = "RETAINED"
    ELIGIBLE_FOR_DESTRUCTION = "ELIGIBLE_FOR_DESTRUCTION"
    DESTROYED = "DESTROYED"


class Client(TypedDict, total=False):
    id: str
    name: str
    importer_of_record_number: str
    contingency_fee_bps: int
    engagement_status: str
    lifetime_recovered_cents: int
    projected_fee_accrual_cents: int
    open_audit_count: int
    created_at: str
    updated_at: str
    version: int


class HTSClassification(TypedDict, total=False):
    id: str
    client_id: str
    product_sku: str
    hts_code: str
    country_of_origin: str
    duty_rate_bps: int
    declared_unit_value_cents: int
    first_sale_price_cents: Optional[int]
    bona_fide_sale: bool
    arms_length: bool
    clearly_destined_us: bool
    first_sale_eligible: bool
    appraised_unit_value_cents: int
    supersedes_id: Optional[str]
    status: str
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BindingRuling(TypedDict, total=False):
    id: str
    classification_id: str
    requested_hts_code: str
    status: str
    issued_hts_code: Optional[str]
    issued_duty_rate_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ImportEntry(TypedDict, total=False):
    id: str
    client_id: str
    classification_id: str
    entry_number: str
    entry_date: str
    port_code: str
    line_quantity: int
    entered_value_cents: int
    duty_paid_cents: int
    non_drawbackable_cents: int
    drawback_eligible_duty_cents: int
    matched_quantity: int
    unclaimed_duty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExportShipment(TypedDict, total=False):
    id: str
    client_id: str
    export_date: str
    hts_code: str
    quantity: int
    fob_value_cents: int
    dest_country: str
    substituted_duty_rate_bps: int
    matched_quantity: int
    value_pool_remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawbackClaim(TypedDict, total=False):
    id: str
    client_id: str
    claim_type: str
    period_start: str
    period_end: str
    status: str
    prepared_by_user_id: str
    filed_by_user_id: Optional[str]
    filed_at: Optional[str]
    deficiency_count: int
    estimate_cents: int
    claimed_duty_cents: Optional[int]
    approved_duty_cents: Optional[int]
    paid_duty_cents: Optional[int]
    paid_at: Optional[str]
    filing_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    import_entry_id: str
    export_shipment_id: str
    matched_quantity: int
    match_method: str
    drawback_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TariffMeasure(TypedDict, total=False):
    id: str
    hts_code_prefix: str
    measure_type: str
    surcharge_bps: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    claim_id: str
    client_id: str
    recovered_duty_cents: int
    fee_bps_snapshot: int
    fee_cents: int
    amount_paid_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    client_id: str
    claim_id: Optional[str]
    opened_reason: str
    due_date: str
    status: str
    culpability_level: Optional[str]
    penalty_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceRecord(TypedDict, total=False):
    id: str
    claim_id: str
    doc_type: str
    retention_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
