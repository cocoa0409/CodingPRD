"""Typed shapes and enumerations for the Emergency Food Assistance Allocation API.

Field inventories and enum value lists are taken from the PRD's entity and
workflow sections. All TypedDicts are ``total=False`` because reads return the
whole row while writes only ever carry the input subset.
"""

from typing import Any, Dict, List, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — spelled exactly as shown)
# ---------------------------------------------------------------------------

class Role:
    STATE_ADMIN = "StateAdmin"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    AGENCY_COORDINATOR = "AgencyCoordinator"
    STATE_WAREHOUSE_OPERATOR = "StateWarehouseOperator"


ALL_ROLES = [
    Role.STATE_ADMIN,
    Role.COMPLIANCE_REVIEWER,
    Role.AGENCY_COORDINATOR,
    Role.STATE_WAREHOUSE_OPERATOR,
]


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class UrbanRural:
    URBAN = "URBAN"
    RURAL = "RURAL"
    MIXED = "MIXED"


class AgreementStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class TrainingStatus:
    REQUIRED = "REQUIRED"
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"


class EligibilityPosture:
    ELIGIBLE = "ELIGIBLE"
    PROBATION = "PROBATION"
    INELIGIBLE = "INELIGIBLE"


class StorageClass:
    DRY = "DRY"
    COLD = "COLD"
    FROZEN = "FROZEN"


class MonitorPolicy:
    TURNOVER_BASED = "TURNOVER_BASED"
    SHELF_LIFE_BASED = "SHELF_LIFE_BASED"


class LotStatus:
    RECEIVED = "RECEIVED"
    AVAILABLE = "AVAILABLE"
    WATCH = "WATCH"
    HOLD = "HOLD"
    DISPOSED = "DISPOSED"
    DEPLETED = "DEPLETED"


class MonitorFlag:
    NONE = "NONE"
    SLOW_MOVING = "SLOW_MOVING"
    EXCESS = "EXCESS"


class FormulaVariant:
    STANDARD = "STANDARD"
    HOLD_HARMLESS = "HOLD_HARMLESS"


class CycleStatus:
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class DrawPosture:
    """PRD §2.11 — the only three values a cycle's ``draw_posture`` reads."""

    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    FULLY_DRAWN = "FULLY_DRAWN"


class AllocationStatus:
    ENTITLED = "ENTITLED"
    PARTIALLY_DRAWN = "PARTIALLY_DRAWN"
    FULLY_DRAWN = "FULLY_DRAWN"
    RECONCILED = "RECONCILED"


class OrderStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    HELD = "HELD"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CancelReason:
    SUPERSEDED = "SUPERSEDED"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    AGREEMENT_TERMINATED = "AGREEMENT_TERMINATED"
    LOT_DISPOSED = "LOT_DISPOSED"


class AppointmentStatus:
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TransferStatus:
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class RecallClass:
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class HoldScope:
    LOT_ONLY = "LOT_ONLY"
    COMMODITY_WIDE = "COMMODITY_WIDE"


class RecallStatus:
    INITIATED = "INITIATED"
    NOTIFYING = "NOTIFYING"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class RecallActionStatus:
    PENDING_NOTICE = "PENDING_NOTICE"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPOSITIONED = "DISPOSITIONED"


class Disposition:
    DESTROYED = "DESTROYED"
    RETURNED_TO_STATE = "RETURNED_TO_STATE"
    NOT_RECEIVED = "NOT_RECEIVED"


class EligibilityDetermination:
    ELIGIBLE = "ELIGIBLE"
    CATEGORICALLY_ELIGIBLE = "CATEGORICALLY_ELIGIBLE"


class DistributionStatus:
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

class ServiceArea(TypedDict, total=False):
    id: str
    name: str
    county_code: str
    poverty_population: int
    urban_rural: str
    eligible_agency_count: int
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict, total=False):
    id: str
    name: str
    service_area_id: str
    cold_storage_pallet_capacity: int
    prior_period_pounds_distributed: float
    prior_period_allocated_cases: int
    agreement_status: str
    agreement_start_date: str
    agreement_end_date: str
    training_status: str
    last_training_completed_at: str
    training_expires_at: str
    eligibility_posture: str
    agency_cases_on_hand: int
    delivered_cases_ytd: int
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Commodity(TypedDict, total=False):
    """PRD §2.5: a commodity carries only ``id`` and ``created_at``."""

    id: str
    code: str
    name: str
    storage_class: str
    net_weight_lbs_per_case: float
    cases_per_pallet: int
    entitlement_value_cents_per_case: int
    shelf_life_days: int
    excess_case_ceiling: int
    created_at: str


class Warehouse(TypedDict, total=False):
    id: str
    name: str
    dock_count: int
    dry_pallet_capacity: int
    cold_pallet_capacity: int
    frozen_pallet_capacity: int
    monitor_policy: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    commodity_id: str
    warehouse_id: str
    federal_lot_code: str
    cases_received: int
    cases_on_hand: int
    cases_committed: int
    cases_shipped_to_date: int
    pack_date: str
    best_by_date: str
    entitlement_value_cents: int
    status: str
    monitor_flag: str
    slow_moving_index: float
    last_monitored_at: str
    posted_at: str
    hold_recall_id: str
    created_at: str
    updated_at: str
    version: int


class AllocationCycle(TypedDict, total=False):
    id: str
    cycle_code: str
    formula_variant: str
    allocatable_cases: int
    admin_funds_pool_cents: int
    offered_commodity_codes: List[str]
    order_window_open_at: str
    order_window_close_at: str
    status: str
    draw_posture: str
    allocation_locked_at: str
    total_allocated_cases: int
    eligible_agency_count: int
    admin_funds_allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class AgencyAllocation(TypedDict, total=False):
    id: str
    cycle_id: str
    agency_id: str
    poverty_factor: float
    poverty_share: float
    prior_share: float
    raw_score: float
    floor_cases: int
    allocated_cases: int
    cases_committed: int
    cases_delivered: int
    cases_remaining: int
    distributed_pounds: float
    distribution_record_count: int
    record_compliance_pct: float
    admin_funds_base_cents: int
    admin_funds_withheld_cents: int
    admin_funds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommodityOrder(TypedDict, total=False):
    id: str
    cycle_id: str
    agency_id: str
    warehouse_id: str
    status: str
    line_count: int
    total_cases_requested: int
    total_cases_approved: int
    total_pounds: float
    total_pallets: int
    revision_count: int
    last_returned_by_user_id: str
    approved_by_user_id: str
    submitted_at: str
    approved_at: str
    cancel_reason: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    commodity_id: str
    cases_requested: int
    cases_approved: int
    line_pounds: float
    line_pallets: int
    storage_class: str
    lot_assignments: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class DeliveryAppointment(TypedDict, total=False):
    id: str
    order_id: str
    warehouse_id: str
    agency_id: str
    dock_number: int
    window_start: str
    window_end: str
    dry_pallets: int
    cold_pallets: int
    frozen_pallets: int
    delivered_pounds: float
    status: str
    confirmed_by_user_id: str
    cancel_reason: str
    created_at: str
    updated_at: str
    version: int


class InventoryTransfer(TypedDict, total=False):
    id: str
    from_lot_id: str
    to_agency_id: str
    cases: int
    status: str
    transferred_value_cents: int
    decline_reason: str
    accepted_at: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    source_lot_id: str
    commodity_code: str
    recall_class: str
    hold_scope: str
    reason: str
    initiated_by_user_id: str
    status: str
    held_lot_count: int
    action_count: int
    acknowledged_count: int
    dispositioned_count: int
    accounted_cases: int
    notices_dispatched_at: str
    created_at: str
    updated_at: str
    version: int


class RecallAction(TypedDict, total=False):
    id: str
    recall_id: str
    agency_id: str
    status: str
    exposed_cases: int
    disposition: str
    cases_accounted: int
    notified_at: str
    acknowledged_at: str
    dispositioned_at: str
    created_at: str
    updated_at: str
    version: int


class HouseholdDistribution(TypedDict, total=False):
    id: str
    agency_id: str
    cycle_id: str
    commodity_id: str
    household_size: int
    declared_monthly_income_cents: int
    participates_in_snap: bool
    self_declaration_signed: bool
    cases_distributed: int
    distribution_date: str
    pounds_distributed: float
    income_limit_cents: int
    eligibility_determination: str
    status: str
    void_reason: str
    created_at: str
    updated_at: str
    version: int


class AdminFundsReport(TypedDict, total=False):
    cycle_code: str
    admin_funds_pool_cents: int
    admin_funds_allocated_cents: int
    withheld_cents_total: int
    redistributed_cents_total: int
    allocation_line_count: int
    non_compliant_line_count: int
