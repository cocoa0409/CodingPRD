"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD section 2.4: every primary resource carries
id/created_at/updated_at/version, except WeightTicket which is immutable
scale evidence and carries only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1 — exactly eight roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    VAN_LINE_ADMIN = "VanLineAdmin"
    BOOKING_AGENT = "BookingAgent"
    ORIGIN_AGENT = "OriginAgent"
    HAULING_AGENT = "HaulingAgent"
    DESTINATION_AGENT = "DestinationAgent"
    CUSTOMER = "Customer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    ARBITRATOR = "Arbitrator"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class TariffStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class MoveOrderStatus(str, Enum):
    REGISTERED = "REGISTERED"
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    IN_SIT = "IN_SIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONALLY_BILLED = "PROVISIONALLY_BILLED"
    FINAL_BILLED = "FINAL_BILLED"
    PAID = "PAID"


class PricingMode(str, Enum):
    BINDING = "BINDING"
    NON_BINDING = "NON_BINDING"


class EstimateStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AssignmentRole(str, Enum):
    BOOKING = "BOOKING"
    ORIGIN = "ORIGIN"
    HAULING = "HAULING"
    DESTINATION = "DESTINATION"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class CoverageType(str, Enum):
    RELEASED_VALUE = "RELEASED_VALUE"
    FULL_VALUE_PROTECTION = "FULL_VALUE_PROTECTION"


class CoverageStatus(str, Enum):
    ELECTED = "ELECTED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class TicketKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    REWEIGH = "REWEIGH"


class ReweighRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PERFORMED = "PERFORMED"
    APPLIED = "APPLIED"
    DECLINED_BY_CUSTOMER = "DECLINED_BY_CUSTOMER"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class RequestedByRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    BOOKING_AGENT = "BOOKING_AGENT"


class WarehouseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SITLotStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    RELEASED = "RELEASED"
    CONVERTED_PERMANENT = "CONVERTED_PERMANENT"


class ServiceEnd(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"


class CrewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    RECONCILED = "RECONCILED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    OFFER_MADE = "OFFER_MADE"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class DisputeStatus(str, Enum):
    OPENED = "OPENED"
    RESPONSE_FILED = "RESPONSE_FILED"
    ARBITRATION_DOCKETED = "ARBITRATION_DOCKETED"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class CommissionTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    PREMIER = "PREMIER"


class FeeAllocation(str, Enum):
    FILER = "FILER"
    RESPONDENT = "RESPONDENT"
    SPLIT = "SPLIT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true — id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Agent(TypedDict, total=False):
    id: str
    legal_name: str
    agent_code: str
    capabilities: List[str]
    home_market: str
    commission_tier: str
    quality_score: int
    ytd_linehaul_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MileageBand(TypedDict):
    min_miles: int
    max_miles: int
    rate_multiplier: float


class Tariff(TypedDict, total=False):
    id: str
    tariff_code: str
    effective_start: str
    effective_end: str
    base_rate_cents_per_cwt: int
    mileage_bands: List[MileageBand]
    fuel_surcharge_pct: float
    sit_daily_rate_cents_per_cwt: int
    hourly_labor_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MoveOrder(TypedDict, total=False):
    id: str
    order_number: str
    customer_id: str
    tariff_id: str
    pricing_mode: str
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    mileage: int
    pickup_date: str
    estimated_weight_lbs: Optional[int]
    actual_weight_lbs: Optional[int]
    authoritative_weight_ticket_id: Optional[str]
    earliest_delivery_date: Optional[str]
    latest_delivery_date: Optional[str]
    delivered_at: Optional[str]
    collected_at_delivery_cents: Optional[int]
    final_charges_cents: Optional[int]
    delivery_amount_due_cents: Optional[int]
    deferred_balance_cents: Optional[int]
    status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict, total=False):
    id: str
    order_id: str
    supersedes_estimate_id: Optional[str]
    estimate_kind: str
    estimated_weight_lbs: int
    packing_services_cents: int
    linehaul_cents: int
    fuel_surcharge_cents: int
    valuation_premium_cents: int
    estimated_charges_cents: int
    revision_number: int
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderAgentAssignment(TypedDict, total=False):
    id: str
    order_id: str
    agent_id: str
    role: str
    split_pct: float
    split_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationCoverage(TypedDict, total=False):
    id: str
    order_id: str
    coverage_type: str
    declared_value_cents: int
    deductible_cents: int
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable scale evidence: ONLY id + created_at.
class WeightTicket(TypedDict, total=False):
    id: str
    order_id: str
    reweigh_request_id: Optional[str]
    supersedes_ticket_id: Optional[str]
    ticket_kind: str
    scale_location: str
    weighed_at: str
    tare_weight_lbs: int
    gross_weight_lbs: int
    net_weight_lbs: int
    created_at: str


class ReweighRequest(TypedDict, total=False):
    id: str
    order_id: str
    requested_by_role: str
    resulting_ticket_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    name: str
    market: str
    capacity_cwt: int
    occupied_cwt: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SITLot(TypedDict, total=False):
    id: str
    order_id: str
    warehouse_id: str
    stored_weight_cwt: int
    checked_in_at: str
    released_at: Optional[str]
    days_stored: int
    accrued_storage_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    order_id: str
    agent_id: str
    service_end: str
    service_date: str
    start_hour: int
    end_hour: int
    crew_size: int
    labor_hours: int
    invoice_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueStatement(TypedDict, total=False):
    id: str
    order_id: str
    linehaul_revenue_cents: int
    accessorial_revenue_cents: int
    booking_share_cents: int
    origin_share_cents: int
    hauling_share_cents: int
    destination_share_cents: int
    van_line_share_cents: int
    chargeback_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    order_id: str
    valuation_coverage_id: str
    filed_at: str
    description: str
    claimed_amount_cents: int
    claimed_item_weight_lbs: int
    offer_amount_cents: Optional[int]
    offered_by_user_id: Optional[str]
    settled_amount_cents: Optional[int]
    round_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    claim_id: Optional[str]
    revenue_statement_id: Optional[str]
    opened_by_role: str
    filer_user_id: str
    subject_amount_cents: int
    responded_at: Optional[str]
    responded_by_user_id: Optional[str]
    escalated_at: Optional[str]
    filing_fee_cents: Optional[int]
    decision_amount_cents: Optional[int]
    fee_allocated_to: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
