"""Response shapes and status vocabularies for every resource in the API.

Two common-field families exist, and the split is normative (PRD 2.5):

* Versioned resources carry ``id``, ``created_at``, ``updated_at`` and ``version``.
* Append-only resources carry ``id`` and ``created_at`` only -- no ``updated_at``
  and no ``version``, because no endpoint mutates or deletes one.
"""

from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Common-field bases
# ---------------------------------------------------------------------------


class VersionedRecord(TypedDict):
    """Common fields for a resource that can be mutated."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """Common fields for a resource that is written once and never changed."""

    id: str
    created_at: str


VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")

# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------

CONTACT_STATUSES = ("OPEN", "LOGGED", "CLOSED_NO_COMPLAINT")

COMPLAINT_HANDLING_STATUSES = (
    "INTAKE",
    "TRIAGED",
    "AWAITING_SAMPLE",
    "IN_RESOLUTION",
    "ON_QUALITY_HOLD",
    "RESOLVED",
    "CLOSED",
    "DUPLICATE",
)
COMPLAINT_REGULATORY_STATUSES = (
    "NOT_APPLICABLE",
    "ESCALATED",
    "REPORTABLE",
    "NOT_REPORTABLE",
    "SUBMITTED",
)
PRODUCT_IDENTIFICATION_STATUSES = ("UNRESOLVED", "RESOLVED")

LOT_RELEASE_STATUSES = ("RELEASED", "HOLD", "WITHDRAWN")

SAMPLE_KIT_STATUSES = (
    "REQUESTED",
    "SHIPPED",
    "IN_TRANSIT_INBOUND",
    "RECEIVED",
    "LAB_ACCEPTED",
    "EXPIRED",
    "CANCELLED",
)
CHAIN_INTEGRITY_STATUSES = ("PENDING", "INTACT", "BROKEN")
KIT_DISPOSITIONS = ("PENDING", "USABLE", "UNUSABLE")

REMEDY_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "APPROVED",
    "REJECTED",
    "FULFILLED",
    "VOIDED_AFTER_FULFILLMENT",
    "VOIDED_BY_HOLD",
    "SUPERSEDED",
)
REMEDY_DECISIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")

REGULATORY_REPORT_STATUSES = (
    "OPEN",
    "DETERMINED_REPORTABLE",
    "DETERMINED_NOT_REPORTABLE",
    "SUBMITTED",
    "WITHDRAWN",
)
REPORT_DETERMINATIONS = ("REPORTABLE", "NOT_REPORTABLE")

TREND_SIGNAL_STATUSES = (
    "DETECTED",
    "INVESTIGATION_OPEN",
    "RECALL_EVALUATION",
    "RECALL_INITIATED",
    "DISMISSED",
    "CLOSED_NO_ACTION",
)
DETECTION_SOURCES = ("OPS_RUN", "MANUAL")
INCLUDED_VARIANTS = ("ADJUDICATED", "PROVISIONAL")

TEMPLATE_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")

# ---------------------------------------------------------------------------
# Versioned resources
# ---------------------------------------------------------------------------


class StaffUser(VersionedRecord, total=False):
    staff_code: str
    full_name: str
    role: str
    authority_tier: str
    is_active: bool


class Consumer(VersionedRecord, total=False):
    external_ref: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    postal_code: Optional[str]
    is_vulnerable_flag: bool
    sentiment_index: float
    complaint_count: int
    open_kit_count: int
    goodwill_authorized_cents: int
    goodwill_outstanding_cents: int
    goodwill_paid_cents: int
    goodwill_voided_cents: int


class Plant(VersionedRecord, total=False):
    plant_code: str
    name: str
    region: str
    oversight_posture: str
    open_investigation_count: int
    recall_initiated_count: int


class ProductionLine(VersionedRecord, total=False):
    plant_id: str
    line_code: str
    nominal_units_per_hour: int
    lot_count: int


class Product(VersionedRecord, total=False):
    sku: str
    name: str
    category: str
    unit_retail_price_cents: int
    units_per_case: int
    is_regulated_food: bool


class ProductionLot(VersionedRecord, total=False):
    product_id: str
    production_line_id: str
    batch_code: str
    normalized_batch_code: str
    code_date: str
    units_produced: int
    release_status: str
    linked_complaint_count: int
    provisional_complaint_count: int
    adjudicated_complaint_count: int
    duplicate_complaint_count: int
    goodwill_charged_cents: int


class Contact(VersionedRecord, total=False):
    consumer_id: str
    channel: str
    received_at: str
    raw_message: str
    handle_or_address: Optional[str]
    status: str
    complaint_count: int
    intake_agent_ref: str


class Complaint(VersionedRecord, total=False):
    contact_id: str
    consumer_id: str
    complaint_type: str
    reported_batch_code: Optional[str]
    pack_code_date: Optional[str]
    foreign_object_class: str
    medical_attention_sought: bool
    hospitalization: bool
    vulnerable_consumer: bool
    symptom_codes: List[str]
    units_claimed: int
    product_identification_status: str
    lot_id: Optional[str]
    product_id: Optional[str]
    provisional_severity_score: float
    provisional_severity_band: str
    adjudicated_severity_score: Optional[float]
    adjudicated_severity_band: Optional[str]
    effective_severity_band: str
    handling_status: str
    regulatory_status: str
    pre_hold_handling_status: Optional[str]
    duplicate_of_complaint_id: Optional[str]
    responded_template_id: Optional[str]
    responded_at: Optional[str]
    triaged_by_ref: Optional[str]


class SampleKit(VersionedRecord, total=False):
    complaint_id: str
    consumer_id: str
    kit_code: str
    seal_id_issued: str
    seal_id_returned: Optional[str]
    status: str
    chain_integrity_status: str
    disposition: str
    custody_event_count: int
    shipped_at: Optional[str]
    expected_return_by: Optional[str]
    occupied_from: Optional[str]
    occupied_until: Optional[str]
    received_at: Optional[str]
    transit_hours: Optional[float]


class Remedy(VersionedRecord, total=False):
    complaint_id: str
    consumer_id: str
    remedy_type: str
    requested_value_cents: int
    base_value_cents: int
    uplift_pct: float
    uplift_cents: int
    payout_cents: int
    authority_tier_required: str
    kit_returned_credit_applied: bool
    status: str
    revision_count: int
    authored_by_ref: str
    decided_by_ref: Optional[str]
    fulfilled_at: Optional[str]


class RegulatoryReport(VersionedRecord, total=False):
    complaint_id: str
    report_kind: str
    status: str
    escalated_at: str
    due_at: str
    submitted_at: Optional[str]
    submitted_late: Optional[bool]
    agency_reference: Optional[str]
    determined_by_ref: Optional[str]
    submitted_by_ref: Optional[str]


class TrendSignal(VersionedRecord, total=False):
    scope_level: str
    plant_id: str
    production_line_id: Optional[str]
    lot_id: Optional[str]
    window_start: str
    window_end: str
    weighted_complaint_count: float
    units_in_scope: int
    observed_rate_ppm: float
    threshold_ppm: float
    detection_source: str
    membership_count: int
    status: str
    opened_by_ref: Optional[str]
    recall_reference: Optional[str]


class ResponseTemplate(VersionedRecord, total=False):
    template_code: str
    title: str
    body: str
    applies_to_type: str
    max_band_allowed: str
    requires_supervisor_approval: bool
    status: str
    usage_count: int


# ---------------------------------------------------------------------------
# Append-only resources: id and created_at only
# ---------------------------------------------------------------------------


class CustodyEvent(AppendOnlyRecord, total=False):
    sample_kit_id: str
    sequence_no: int
    event_type: str
    occurred_at: str
    actor_label: str
    seal_id_observed: Optional[str]
    notes: Optional[str]


class SignalMembership(AppendOnlyRecord, total=False):
    trend_signal_id: str
    complaint_id: str
    severity_weight: float
    included_variant: str


# ---------------------------------------------------------------------------
# Computed reads (not stored resources, so no common fields at all)
# ---------------------------------------------------------------------------


class SentimentRead(TypedDict, total=False):
    consumer_id: str
    view: str
    penalty_total: float
    credit_total: float
    sentiment_index: float
    complaint_count_in_window: int


class ComplaintRateRead(TypedDict, total=False):
    production_lot_id: str
    variant: str
    numerator: int
    units_produced: int
    rate_ppm: float
    rate_undefined: bool


class QualityOpsRun(TypedDict, total=False):
    run_at: str
    kits_expired_count: int
    complaints_advanced_count: int
    signals_created_count: int
    signals_refreshed_count: int
    memberships_created_count: int
    plants_reposted_count: int


class ClockRead(TypedDict, total=False):
    current_utc: str
    previous_utc: str


# Which family each resource belongs to, for common-field assertions.
APPEND_ONLY_RESOURCES = ("CustodyEvent", "SignalMembership")
