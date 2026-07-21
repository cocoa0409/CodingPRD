"""Domain types: entity TypedDicts, status enums, role enum for the property-tax appeal API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    ANALYST = "Analyst"
    BILLING = "Billing"
    CLIENT = "Client"


class ClientEntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"


class FeeAgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"


class PropertyClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"
    LAND = "LAND"


class AssessmentStatus(str, Enum):
    NOTICED = "NOTICED"
    UNDER_APPEAL = "UNDER_APPEAL"
    FINALIZED = "FINALIZED"


class ExemptionType(str, Enum):
    HOMESTEAD = "HOMESTEAD"
    SENIOR = "SENIOR"
    VETERAN = "VETERAN"
    AGRICULTURAL = "AGRICULTURAL"
    DISABLED = "DISABLED"


class ExemptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ValuationMethod(str, Enum):
    SALES_COMPARISON = "SALES_COMPARISON"
    ASSESSMENT_EQUITY = "ASSESSMENT_EQUITY"


class AppealStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    INFORMAL_REVIEW = "INFORMAL_REVIEW"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    DECIDED = "DECIDED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class OutcomeSource(str, Enum):
    HEARING_DECISION = "HEARING_DECISION"
    SETTLEMENT = "SETTLEMENT"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class OfferProposedBy(str, Enum):
    FIRM = "FIRM"
    JURISDICTION = "JURISDICTION"


class OfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    CARD = "CARD"
    ACH = "ACH"


# ---- Entity TypedDicts ----
# Entities with the full quartet (id/created_at/updated_at/version):

class Analyst(TypedDict):
    id: str
    full_name: str
    email: str
    license_number: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    entity_type: str
    portal_enabled: bool
    lifetime_fees_billed_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    name: str
    state_code: str
    filing_window_days: int
    equalization_ratio: float
    informal_review_available: bool
    hearing_room_capacity: int
    rep_travel_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class FeeAgreement(TypedDict):
    id: str
    client_id: str
    contingency_tier1_pct: float
    contingency_tier2_pct: float
    contingency_tier3_pct: float
    tier1_ceiling_cents: int
    tier2_ceiling_cents: int
    minimum_fee_cents: int
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    client_id: str
    jurisdiction_id: str
    apn: str
    address: str
    property_class: str
    building_area_sqft: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    parcel_id: str
    tax_year: int
    original_assessed_value_cents: int
    land_value_cents: int
    improvement_value_cents: int
    millage_rate: float
    notice_date: str
    assessed_value_cents: int
    total_approved_exemption_cents: int
    projected_annual_tax_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExemptionClaim(TypedDict):
    id: str
    parcel_id: str
    tax_year: int
    exemption_type: str
    exemption_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    assessment_id: str
    analyst_id: str
    fee_agreement_id: str
    valuation_method: str
    requested_value_cents: int
    filed_date: Optional[str]
    decision_value_cents: Optional[int]
    settlement_value_cents: Optional[int]
    projected_savings_cents: int
    projected_fee_cents: int
    projected_client_tax_bill_cents: int
    realized_savings_cents: Optional[int]
    outcome_source: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Evidence(TypedDict):
    id: str
    appeal_id: str
    comp_address: str
    sale_price_cents: int
    sale_date: str
    comp_assessed_value_cents: int
    adjustment_pct: float
    adjusted_sale_value_cents: int
    included: bool
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    appeal_id: str
    representative_id: str
    docket_room: str
    scheduled_start: str
    scheduled_end: str
    status: str
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict):
    id: str
    appeal_id: str
    proposed_by: str
    offer_value_cents: int
    round_number: int
    created_by_analyst_id: str
    accepted_by_analyst_id: Optional[str]
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    appeal_id: str
    gross_savings_cents: int
    fee_amount_cents: int
    amount_paid_cents: int
    issued_date: Optional[str]
    paid_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only immutable audit fact — carries ONLY id + created_at (no updated_at, no version).
class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    received_date: str
    created_at: str
