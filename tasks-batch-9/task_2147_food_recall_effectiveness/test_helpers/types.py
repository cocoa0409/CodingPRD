"""Domain types for the Food Recall Effectiveness API.

Entity TypedDicts, status enums and the acting-role enum, all named exactly as
the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────


class UserRole(str, Enum):
    FIRM_RECALL_OFFICER = "FirmRecallOfficer"
    RECALL_COORDINATOR = "RecallCoordinator"
    HEALTH_HAZARD_PANEL = "HealthHazardPanel"
    FIELD_INVESTIGATOR = "FieldInvestigator"
    INSURANCE_ADJUSTER = "InsuranceAdjuster"


# ─── Status enums ─────────────────────────────────────


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"
    NOTIFICATION_IN_PROGRESS = "NOTIFICATION_IN_PROGRESS"
    RETRIEVAL_ACCOUNTING = "RETRIEVAL_ACCOUNTING"
    EFFECTIVENESS_REVIEW = "EFFECTIVENESS_REVIEW"
    TERMINATION_REQUESTED = "TERMINATION_REQUESTED"
    TERMINATED = "TERMINATED"


class HazardClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class ComplianceFlag(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"
    DELINQUENT = "DELINQUENT"


class HazardEvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RATIFIED = "RATIFIED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class EvaluationVariant(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    RATIFIED = "RATIFIED"


class ConsigneeType(str, Enum):
    DISTRIBUTOR = "DISTRIBUTOR"
    RETAILER = "RETAILER"
    RESTAURANT = "RESTAURANT"
    INSTITUTION = "INSTITUTION"


class ResponseState(str, Enum):
    AWAITING = "AWAITING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REFUSED = "REFUSED"
    NO_RESPONSE = "NO_RESPONSE"


class DeliveryState(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    UNDELIVERABLE = "UNDELIVERABLE"


class NotificationMethod(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class DistributionRecordStatus(str, Enum):
    DECLARED = "DECLARED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


class RetrievalReceiptStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class PublicWarningStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class WarningType(str, Enum):
    PRESS_RELEASE = "PRESS_RELEASE"
    PUBLIC_WARNING = "PUBLIC_WARNING"
    SOCIAL_MEDIA_ONLY = "SOCIAL_MEDIA_ONLY"


class DispositionOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"


class DispositionMethod(str, Enum):
    DESTROY = "DESTROY"
    REWORK = "REWORK"
    RELABEL = "RELABEL"
    RETURN_TO_FIRM = "RETURN_TO_FIRM"


class StatusReportStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    OVERDUE = "OVERDUE"


class ReportKind(str, Enum):
    PERIODIC = "PERIODIC"
    INTERIM = "INTERIM"
    FINAL_EFFECTIVENESS = "FINAL_EFFECTIVENESS"


class CostCategory(str, Enum):
    NOTIFICATION = "NOTIFICATION"
    LOGISTICS = "LOGISTICS"
    DESTRUCTION = "DESTRUCTION"
    LEGAL = "LEGAL"
    PRODUCT_VALUE = "PRODUCT_VALUE"
    LAB_TESTING = "LAB_TESTING"


class CostEntryStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InsuranceClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DENIED = "DENIED"


class Agency(str, Enum):
    FDA = "FDA"
    USDA = "USDA"


class InitiationType(str, Enum):
    FIRM_INITIATED = "FIRM_INITIATED"
    AGENCY_REQUESTED = "AGENCY_REQUESTED"
    MANDATED = "MANDATED"


class RootCauseCode(str, Enum):
    SUPPLIER_INGREDIENT = "SUPPLIER_INGREDIENT"
    SANITATION = "SANITATION"
    PROCESS_DEVIATION = "PROCESS_DEVIATION"
    LABELING = "LABELING"
    PACKAGING = "PACKAGING"
    CROSS_CONTACT = "CROSS_CONTACT"
    UNKNOWN = "UNKNOWN"


# ─── Entity TypedDicts ────────────────────────────────
# Every resource type in this API carries id, created_at, updated_at and
# version; none of them is an append-only log exempt from the latter two.


class Firm(TypedDict):
    id: str
    name: str
    registration_number: str
    policy_deductible_cents: int
    policy_aggregate_cents: int
    policy_paid_to_date_cents: int
    open_recall_count: int
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    firm_id: str
    product_description: str
    agency: str
    initiation_type: str
    lot_codes: List[str]
    status: str
    hazard_class: Optional[str]
    classified_by_user_id: Optional[str]
    effectiveness_check_level: Optional[str]
    sample_tier_scope: int
    eligible_consignee_count: int
    required_sample_size: int
    responded_count: int
    report_cadence_days: int
    compliance_flag: str
    overdue_report_count: int
    total_shipped_units: int
    accounted_units: int
    units_awaiting_disposition: int
    units_pending_verification: int
    units_disposed_verified: int
    contact_effectiveness_pct: float
    quantity_effectiveness_pct: float
    official_effectiveness_pct: float
    total_loaded_cost_cents: int
    insurable_loaded_cost_cents: int
    root_cause_code: Optional[str]
    capa_summary: Optional[str]
    termination_denied_count: int
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HazardEvaluation(TypedDict):
    id: str
    recall_id: str
    probability_of_adverse_health: str
    severity_tier: int
    exposure_population: int
    vulnerable_population: bool
    evidence_strength: str
    variant: str
    hazard_score: float
    recommended_class: Optional[str]
    status: str
    submitted_by_user_id: Optional[str]
    ratified_by_user_id: Optional[str]
    panel_note: Optional[str]
    return_count: int
    created_at: str
    updated_at: str
    version: int


class Consignee(TypedDict):
    id: str
    recall_id: str
    parent_consignee_id: Optional[str]
    name: str
    consignee_type: str
    tier: int
    in_effectiveness_sample: bool
    escalation_level: int
    last_contact_at: Optional[str]
    response_state: str
    closed_without_response: bool
    created_at: str
    updated_at: str
    version: int


class DistributionRecord(TypedDict):
    id: str
    recall_id: str
    consignee_id: str
    lot_code: str
    quantity_shipped: int
    ship_date: str
    quantity_confirmed: Optional[int]
    effective_quantity: int
    status: str
    reconcile_round: int
    created_at: str
    updated_at: str
    version: int


class ConsigneeNotification(TypedDict):
    id: str
    recall_id: str
    consignee_id: str
    method: str
    attempt_no: int
    sent_at: str
    delivery_state: str
    response_state: str
    delivery_recorded_at: Optional[str]
    response_recorded_at: Optional[str]
    counts_toward_effectiveness: bool
    response_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetrievalReceipt(TypedDict):
    id: str
    recall_id: str
    consignee_id: str
    quantity_returned: int
    quantity_destroyed_onsite: int
    quantity_held_segregated: int
    quantity_unrecoverable: int
    accounted_units: int
    status: str
    verified_by_user_id: Optional[str]
    verification_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicWarning(TypedDict):
    id: str
    recall_id: str
    warning_type: str
    headline: str
    body: str
    drafted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    reject_count: int
    review_note: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispositionOrder(TypedDict):
    id: str
    recall_id: str
    method: str
    quantity: int
    facility_name: str
    proposed_by_user_id: str
    authorized_by_user_id: Optional[str]
    certificate_reference: Optional[str]
    executed_at: Optional[str]
    witness_user_id: Optional[str]
    status: str
    reject_count: int
    verification_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatusReport(TypedDict):
    id: str
    recall_id: str
    period_index: int
    report_kind: str
    period_start: str
    period_end: str
    due_at: str
    status: str
    submitted_at: Optional[str]
    narrative: Optional[str]
    reported_effectiveness_pct: float
    reject_count: int
    adjudication_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostEntry(TypedDict):
    id: str
    recall_id: str
    category: str
    amount_cents: int
    description: str
    insurable: bool
    overhead_rate: float
    line_loaded_cost_cents: int
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudication_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    recall_id: str
    claim_reference: str
    claimed_cents: int
    capped_total_cents: int
    coinsurance_rate: float
    settlement_payable_cents: int
    handling_fee_cents: int
    total_claim_value_cents: int
    paid_cents: int
    status: str
    supplement_round: int
    denial_reason: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
