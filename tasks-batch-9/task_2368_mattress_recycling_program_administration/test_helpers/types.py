"""Domain types for the Mattress Recycling Program API: entity TypedDicts,
status enums and the role enum.

Field names mirror the PRD exactly.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    PROGRAM_AUDITOR = "ProgramAuditor"
    REGISTRANT = "Registrant"
    COLLECTION_SITE_OPERATOR = "CollectionSiteOperator"
    HAULER = "Hauler"
    RECYCLER = "Recycler"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------


class EnforcementPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"


class UnitClass(str, Enum):
    MATTRESS = "MATTRESS"
    FOUNDATION = "FOUNDATION"


class FeeRateScheduleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RegistrantType(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    RETAILER = "RETAILER"
    BOTH = "BOTH"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class RemittanceStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    PAID = "PAID"
    UNDER_AUDIT = "UNDER_AUDIT"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"
    AUDIT_CLOSED = "AUDIT_CLOSED"
    REFUNDED = "REFUNDED"


class ExemptionClaimType(str, Enum):
    EXEMPT_SALE = "EXEMPT_SALE"
    OUT_OF_STATE_SHIPMENT = "OUT_OF_STATE_SHIPMENT"


class ExemptionClaimStatus(str, Enum):
    PENDING = "PENDING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISALLOWED = "DISALLOWED"


class DisallowReason(str, Enum):
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    UNITS_UNSUPPORTED = "UNITS_UNSUPPORTED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class SiteType(str, Enum):
    COLLECTION_SITE = "COLLECTION_SITE"
    TRANSFER_STATION = "TRANSFER_STATION"
    PERMANENT_DROPOFF = "PERMANENT_DROPOFF"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class VolumeReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class CertificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class FulfillmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    ESTIMATED = "ESTIMATED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class InfestationFinding(str, Enum):
    NONE = "NONE"
    BED_BUG = "BED_BUG"
    MOLD = "MOLD"


class Disposition(str, Enum):
    PARTIAL_ACCEPT = "PARTIAL_ACCEPT"
    FULL_REJECT = "FULL_REJECT"


class RejectionReason(str, Enum):
    INFESTATION = "INFESTATION"
    CONTAMINATION_THRESHOLD = "CONTAMINATION_THRESHOLD"


class Commodity(str, Enum):
    STEEL = "STEEL"
    FOAM = "FOAM"
    FIBER = "FIBER"
    WOOD = "WOOD"


class CommodityRecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class TakeBackStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OBLIGATION_MET = "OBLIGATION_MET"
    OBLIGATION_BREACHED = "OBLIGATION_BREACHED"
    WAIVED = "WAIVED"


# ---------------------------------------------------------------------------
# Entities
#
# Every persisted resource carries id + created_at. All resources below except
# the load inspection additionally carry updated_at and version (PRD §2.4).
# ---------------------------------------------------------------------------


class StateProgram(TypedDict):
    id: str
    state_code: str
    program_name: str
    forecast_annual_cost_cents: int
    forecast_annual_units: int
    forecast_other_revenue_cents: int
    reserve_target_months: int
    reserve_opening_cents: int
    site_credit_cents_per_unit: int
    volume_bonus_threshold_units: int
    delinquency_alert_threshold: int
    fee_collected_cents: int
    site_credit_paid_cents: int
    hauler_payment_paid_cents: int
    reserve_balance_cents: int
    receivable_cents: int
    reserve_coverage_months: float
    recommended_rate_cents: int
    enrolled_site_count: int
    reported_units_total: int
    delinquent_registrant_count: int
    enforcement_posture: str
    created_at: str
    updated_at: str
    version: int


class FeeRateSchedule(TypedDict):
    id: str
    state_program_id: str
    unit_class: str
    fee_cents_per_unit: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    recommended_rate_cents_at_proposal: int
    band_low_cents: int
    band_high_cents: int
    created_at: str
    updated_at: str
    version: int


class Registrant(TypedDict):
    id: str
    legal_name: str
    registrant_type: str
    home_state_code: str
    compliance_status: str
    delinquent_balance_cents: int
    takeback_breach_count: int
    created_at: str
    updated_at: str
    version: int


class SalesRemittance(TypedDict):
    id: str
    registrant_id: str
    state_program_id: str
    amends_remittance_id: Optional[str]
    period_code: str
    period_start: str
    period_end: str
    units_sold_mattress: int
    units_sold_foundation: int
    amendment_round: int
    filed_at: Optional[str]
    early_filing_qualified: bool
    fee_self_assessed_cents: int
    fee_reconciled_cents: Optional[int]
    fee_paid_cents: int
    fee_refunded_cents: int
    balance_due_cents: int
    status: str
    audit_opened_by_user_id: Optional[str]
    amendment_requested_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionClaim(TypedDict):
    id: str
    remittance_id: str
    claim_type: str
    unit_class: str
    units: int
    documentation_reference: Optional[str]
    status: str
    adjudicated_by_user_id: Optional[str]
    disallow_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollectionSite(TypedDict):
    id: str
    state_program_id: str
    operator_name: str
    site_type: str
    region_code: str
    enrollment_status: str
    contamination_strike_count: int
    infestation_quarantine_until: Optional[str]
    units_on_hand: int
    units_in_transit: int
    units_at_recycler_count: int
    units_recycled_count: int
    units_written_off_count: int
    units_reported_total: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolumeReport(TypedDict):
    id: str
    collection_site_id: str
    period_month: str
    units_mattress: int
    units_foundation: int
    credited_units: int
    credit_cents: int
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hauler(TypedDict):
    id: str
    state_program_id: str
    company_name: str
    service_regions: List[str]
    per_unit_rate_cents: int
    per_km_rate_cents: int
    max_route_payment_cents: int
    max_concurrent_routes: int
    active_route_count: int
    total_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Recycler(TypedDict):
    id: str
    state_program_id: str
    facility_name: str
    accepted_unit_classes: List[str]
    certification_status: str
    certified_at: Optional[str]
    units_received_count: int
    units_processed_count: int
    units_rejected_count: int
    verified_output_weight_kg: float
    diversion_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class PickupOrder(TypedDict):
    id: str
    collection_site_id: str
    hauler_id: str
    recycler_id: str
    units_manifested: int
    units_delivered: Optional[int]
    units_accepted: Optional[int]
    route_distance_km: float
    pickup_window_start: str
    pickup_window_end: str
    fulfillment_status: str
    settlement_status: str
    estimated_payment_cents: Optional[int]
    final_payment_cents: Optional[int]
    hauler_auto_selected: bool
    created_at: str
    updated_at: str
    version: int


class LoadInspection(TypedDict):
    """Append-only inspection event: carries only id and created_at.

    Both updated_at and version are absent from a load inspection (PRD §2.4).
    """

    id: str
    pickup_order_id: str
    contaminated_unit_count: int
    infestation_finding: str
    contamination_pct: float
    disposition: str
    units_accepted: int
    rejection_reason: Optional[str]
    inspected_by_user_id: str
    created_at: str


class CommodityOutputRecord(TypedDict):
    id: str
    recycler_id: str
    commodity: str
    output_weight_kg: float
    source_period_month: str
    record_status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TakeBackDelivery(TypedDict):
    id: str
    registrant_id: str
    collection_site_id: str
    delivery_reference: str
    units_delivered_new: int
    units_takeback_offered: int
    units_takeback_collected: Optional[int]
    waiver_reference: Optional[str]
    status: str
    breach_units: int
    breach_penalty_cents: int
    created_at: str
    updated_at: str
    version: int
