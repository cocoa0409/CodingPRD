"""TypedDict shapes and enums for the export trade documentation API.

Every shape below mirrors the entity field list declared in the PRD. Entities that
carry the common fields expose ``id``, ``created_at``, ``updated_at`` and
``version``; ``PresentationDocumentLink`` is an append-only junction and carries
only ``id`` and ``created_at``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    EXPORT_OPS_COORDINATOR = "ExportOpsCoordinator"
    TRADE_COMPLIANCE_OFFICER = "TradeComplianceOfficer"
    DOCUMENTARY_CREDIT_REVIEWER = "DocumentaryCreditReviewer"
    FINANCE_COLLECTIONS_OFFICER = "FinanceCollectionsOfficer"
    FOREIGN_BUYER = "ForeignBuyer"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in Role]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CreditRating(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"


class SanctionsTier(str, Enum):
    NONE = "NONE"
    WATCHLIST = "WATCHLIST"
    EMBARGOED = "EMBARGOED"


class Incoterm(str, Enum):
    EXW = "EXW"
    FCA = "FCA"
    FOB = "FOB"
    CFR = "CFR"
    CIF = "CIF"
    DAP = "DAP"
    DDP = "DDP"


class DestinationZone(str, Enum):
    ZONE_1 = "ZONE_1"
    ZONE_2 = "ZONE_2"
    ZONE_3 = "ZONE_3"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLIANCE_PENDING = "COMPLIANCE_PENDING"
    COMPLIANCE_CLEARED = "COMPLIANCE_CLEARED"
    COMPLIANCE_BLOCKED = "COMPLIANCE_BLOCKED"
    BOOKED = "BOOKED"
    SHIPPED = "SHIPPED"
    SHORT_SHIPPED = "SHORT_SHIPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSECURED = "UNSECURED"
    LC_ACCEPTED = "LC_ACCEPTED"
    DOCS_PRESENTED = "DOCS_PRESENTED"
    PAID = "PAID"
    DISHONORED = "DISHONORED"
    CLAIM_FILED = "CLAIM_FILED"
    INDEMNIFIED = "INDEMNIFIED"
    WRITTEN_OFF = "WRITTEN_OFF"


class Uom(str, Enum):
    EA = "EA"
    KG = "KG"
    LTR = "LTR"
    MTR = "MTR"
    SET = "SET"


class LcStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AMENDMENT_REQUESTED = "AMENDMENT_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UTILISED = "UTILISED"


class Availability(str, Enum):
    SIGHT = "SIGHT"
    USANCE = "USANCE"


class DocType(str, Enum):
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    CERTIFICATE_OF_ORIGIN = "CERTIFICATE_OF_ORIGIN"
    BILL_OF_LADING = "BILL_OF_LADING"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"
    INSPECTION_CERTIFICATE = "INSPECTION_CERTIFICATE"


class ReviewStatus(str, Enum):
    DRAFTING = "DRAFTING"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class Recommendation(str, Enum):
    ACCEPT = "ACCEPT"
    AMEND = "AMEND"
    REJECT = "REJECT"


class FindingSource(str, Enum):
    TERMS = "TERMS"
    DOCUMENT = "DOCUMENT"


class FindingCode(str, Enum):
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    EXPIRY_UNWORKABLE = "EXPIRY_UNWORKABLE"
    LATEST_SHIPMENT_UNWORKABLE = "LATEST_SHIPMENT_UNWORKABLE"
    PARTIAL_SHIPMENT_BARRED = "PARTIAL_SHIPMENT_BARRED"
    DOC_TYPE_MISSING = "DOC_TYPE_MISSING"
    DESCRIPTION_MISMATCH = "DESCRIPTION_MISMATCH"
    WEIGHT_MISMATCH = "WEIGHT_MISMATCH"
    ORIGIN_MISMATCH = "ORIGIN_MISMATCH"
    LATE_PRESENTATION = "LATE_PRESENTATION"
    SHORT_DRAWING = "SHORT_DRAWING"
    DOC_VOIDED = "DOC_VOIDED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ClauseRef(str, Enum):
    AMOUNT = "AMOUNT"
    EXPIRY = "EXPIRY"
    LATEST_SHIPMENT = "LATEST_SHIPMENT"
    DOCUMENTS = "DOCUMENTS"
    GOODS = "GOODS"
    OTHER = "OTHER"


class CureStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    WAIVED = "WAIVED"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ScreeningStatus(str, Enum):
    INITIATED = "INITIATED"
    PENDING_LICENSE = "PENDING_LICENSE"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class LicenseDetermination(str, Enum):
    NLR = "NLR"
    LICENSE_REQUIRED = "LICENSE_REQUIRED"
    PROHIBITED = "PROHIBITED"


class LicenseAuthority(str, Enum):
    BIS = "BIS"
    DDTC = "DDTC"
    OFAC = "OFAC"
    NATIONAL_OTHER = "NATIONAL_OTHER"


class LicenseStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class SailingStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CUTOFF_PASSED = "CUTOFF_PASSED"
    DEPARTED = "DEPARTED"


class ContainerType(str, Enum):
    LCL = "LCL"
    DRY_20 = "DRY_20"
    DRY_40 = "DRY_40"
    REEFER_40 = "REEFER_40"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class PresentationStatus(str, Enum):
    PRESENTED = "PRESENTED"
    COMPLIED = "COMPLIED"
    DISCREPANT = "DISCREPANT"
    CURING = "CURING"
    REFUSED = "REFUSED"
    HONOURED = "HONOURED"


class LinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPLACED = "REPLACED"
    INVALIDATED = "INVALIDATED"


class ExposureTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class DisputeType(str, Enum):
    SHORT_SHIPMENT = "SHORT_SHIPMENT"
    QUALITY = "QUALITY"
    NON_PAYMENT = "NON_PAYMENT"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    SETTLED = "SETTLED"
    ESCALATED = "ESCALATED"
    CLOSED_NO_SETTLEMENT = "CLOSED_NO_SETTLEMENT"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ForeignBuyer(CommonFields):
    legal_name: str
    country_code: str
    credit_rating: str
    sanctions_tier: str
    restricted_party_flag: bool
    restricted_party_reason: Optional[str]
    aggregate_exposure_usd: float
    open_order_count: int


class ExportOrder(CommonFields):
    buyer_id: str
    prepared_by_user_id: str
    incoterm: str
    incoterm_named_place: str
    origin_country_code: str
    destination_country_code: str
    destination_zone: str
    invoice_currency: str
    fx_rate_usd_to_invoice: float
    ship_by_date: str
    fulfillment_status: str
    settlement_status: str
    ordered_goods_value_usd: float
    shipped_goods_value_usd: float
    provisional_seller_cost_usd: float
    provisional_buyer_cost_usd: float
    final_seller_cost_usd: float
    final_buyer_cost_usd: float
    cost_allocation_variance_usd: float
    outstanding_receivable_usd: float
    licensed_value_allocated_usd: float
    insured_exposure_usd: float
    short_shipped_value_usd: float


class ShipmentLine(CommonFields):
    export_order_id: str
    line_no: int
    goods_description: str
    hs_code: str
    quantity: float
    uom: str
    unit_price_usd: float
    line_discount_pct: float
    net_weight_kg: float
    gross_weight_kg: float
    package_count: int
    shipped_quantity: float
    line_extended_usd: float
    line_net_usd: float
    apportioned_freight_usd: float


class LetterOfCredit(CommonFields):
    export_order_id: str
    supersedes_lc_id: Optional[str]
    captured_by_user_id: str
    lc_number: str
    issuing_bank_swift: str
    amount_usd: float
    tolerance_pct: float
    availability: str
    usance_days: int
    expiry_date: str
    latest_shipment_date: str
    presentation_period_days: int
    partial_shipment_allowed: bool
    transshipment_allowed: bool
    required_document_types: List[str]
    status: str
    amendment_round: int
    max_drawable_usd: float
    min_drawable_usd: float
    drawn_amount_usd: float


class LCTermsReview(CommonFields):
    letter_of_credit_id: str
    reviewer_user_id: str
    reviewed_lc_version: int
    recommendation: Optional[str]
    terms_risk_score: float
    finding_count: int
    status: str


class DiscrepancyFinding(CommonFields):
    letter_of_credit_id: str
    lc_terms_review_id: Optional[str]
    document_presentation_id: Optional[str]
    source: str
    code: str
    severity: str
    clause_ref: str
    detail: str
    cure_status: str
    waived_by_buyer_id: Optional[str]
    buyer_reference: Optional[str]
    raised_in_round: int


class TradeDocument(CommonFields):
    export_order_id: str
    supersedes_document_id: Optional[str]
    generated_by_user_id: str
    doc_type: str
    revision: int
    status: str
    pinned_order_version: int
    declared_total_usd: float
    declared_total_invoice_currency: float
    total_gross_weight_kg: float
    total_package_count: int
    origin_country_code: str
    on_board_date: Optional[str]
    void_reason: Optional[str]


class ExportControlScreening(CommonFields):
    export_order_id: str
    ruleset_version: int
    decided_by_user_id: Optional[str]
    eccn: Optional[str]
    denied_party_hits: int
    license_determination: Optional[str]
    export_license_id: Optional[str]
    status: str
    cleared_at: Optional[str]


class ExportLicense(CommonFields):
    export_control_screening_id: str
    license_number: str
    authority: str
    eccn: str
    valid_from: str
    valid_to: str
    licensed_value_usd: float
    consumed_value_usd: float
    remaining_value_usd: float
    status: str


class VesselSailing(CommonFields):
    carrier_scac: str
    vessel_name: str
    voyage_no: str
    port_of_loading: str
    port_of_discharge: str
    destination_zone: str
    cutoff_at: str
    etd: str
    eta: str
    capacity_weight_kg: float
    booked_weight_kg: float
    tariff_rate_per_1000kg_usd: float
    status: str


class FreightBooking(CommonFields):
    export_order_id: str
    vessel_sailing_id: str
    booked_weight_kg: float
    container_type: str
    effective_window_start: str
    effective_window_end: str
    chargeable_weight_kg: float
    status: str
    cancel_reason: Optional[str]


class DocumentPresentation(CommonFields):
    letter_of_credit_id: str
    export_order_id: str
    presented_by_user_id: str
    examined_by_user_id: Optional[str]
    presented_at: str
    presentation_round: int
    days_after_on_board: Optional[int]
    presented_amount_usd: float
    examination_risk_score: float
    negotiable_amount_usd: float
    received_amount_usd: Optional[float]
    value_date: Optional[str]
    refusal_reason: Optional[str]
    open_finding_count: int
    status: str


class PresentationDocumentLink(TypedDict):
    """Append-only junction: only ``id`` and ``created_at`` are carried."""

    id: str
    created_at: str
    document_presentation_id: str
    trade_document_id: str
    doc_type: str
    pinned_document_revision: int
    linked_in_round: int
    link_status: str


class CreditInsurancePolicy(CommonFields):
    buyer_id: str
    policy_number: str
    credit_limit_usd: float
    insured_pct: float
    deductible_usd: float
    effective_from: str
    effective_to: str
    exposure_tier: str
    premium_usd: float
    utilized_usd: float
    available_limit_usd: float
    indemnified_total_usd: float
    status: str


class DisputeCase(CommonFields):
    export_order_id: str
    credit_insurance_policy_id: Optional[str]
    opened_by_role: str
    dispute_type: str
    claimed_amount_usd: float
    current_offer_usd: Optional[float]
    negotiation_round: int
    settlement_amount_usd: Optional[float]
    receivable_offset_usd: float
    insurance_indemnity_usd: float
    seller_credit_note_usd: float
    status: str


Json = Dict[str, Any]
