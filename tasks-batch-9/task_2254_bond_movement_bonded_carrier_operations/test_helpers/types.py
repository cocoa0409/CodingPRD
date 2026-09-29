"""Response shapes returned by the In-Bond Movement & Bonded Carrier API.

These TypedDicts document the fields each read exposes. Three record types are
append-only witnesses and carry only ``id`` and ``created_at`` — they have no
``updated_at`` and no ``version``: ``BondObligationLedgerEntry``, ``SealEvent``
and ``ComplianceSweep``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class BondedCarrier(TypedDict):
    id: str
    name: str
    irs_number: str
    custodial_status: str
    sanction_points: float
    overdue_movement_count: int
    open_claim_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomsBond(TypedDict):
    id: str
    carrier_id: str
    bond_type: str
    limit_amount: float
    obligated_amount: float
    available_amount: float
    status: str
    effective_date: str
    expiry_date: str
    surety_code: str
    open_movement_count: int
    created_at: str
    updated_at: str
    version: int


class Port(TypedDict):
    id: str
    port_code: str
    name: str
    region_code: str
    exam_capacity_slots: int
    go_warehouse_available: bool
    open_hold_count: int
    created_at: str
    updated_at: str
    version: int


class InBondMovement(TypedDict):
    id: str
    carrier_id: str
    bond_id: str
    origin_port_id: str
    destination_port_id: str
    arrival_port_id: Optional[str]
    predecessor_movement_id: Optional[str]
    in_bond_type: str
    manifest_reference: str
    cargo_value: float
    gross_weight_kg: float
    package_count: int
    transit_status: str
    custody_status: str
    obligation_amount: float
    transit_days_allowed: int
    deadline_anchor_utc: str
    transit_deadline_utc: str
    extension_days_granted: int
    overdue_days: int
    filed_at: str
    seal_number: Optional[str]
    seal_intact: bool
    arrival_reported_at: Optional[str]
    export_reported_at: Optional[str]
    go_deadline_utc: Optional[str]
    go_grace_applied: bool
    diversion_flag: bool
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BondObligationLedgerEntry(TypedDict):
    """Append-only witness: exposes only ``id`` and ``created_at``."""

    id: str
    bond_id: str
    movement_id: Optional[str]
    claim_id: Optional[str]
    entry_type: str
    amount: float
    balance_after: float
    reason_code: str
    recorded_at: str
    created_at: str


class SealEvent(TypedDict):
    """Append-only witness: exposes only ``id`` and ``created_at``."""

    id: str
    movement_id: str
    seal_number: str
    event_type: str
    port_code: str
    recorded_by_user_id: str
    occurred_at: str
    resulting_seal_intact: bool
    created_at: str


class ExaminationHold(TypedDict):
    id: str
    movement_id: str
    port_id: str
    hold_type: str
    status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    reason_code: str
    placed_by_user_id: str
    released_at: Optional[str]
    findings_code: Optional[str]
    discrepancy_pieces: int
    created_by_system: bool
    created_at: str
    updated_at: str
    version: int


class AmendmentRequest(TypedDict):
    id: str
    movement_id: str
    amendment_type: str
    requested_destination_port_code: Optional[str]
    requested_in_bond_type: Optional[str]
    requested_days: Optional[int]
    justification_code: str
    status: str
    granted_days: Optional[int]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_reason_code: Optional[str]
    resulting_deadline_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MovementReport(TypedDict):
    id: str
    movement_id: str
    port_id: str
    report_type: str
    packages_reported: Optional[int]
    proof_of_export_ref: Optional[str]
    export_conveyance_ref: Optional[str]
    status: str
    reported_at: str
    package_discrepancy: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LiquidatedDamagesClaim(TypedDict):
    id: str
    movement_id: str
    bond_id: str
    claim_type: str
    overdue_days_at_issue: int
    assessed_amount: float
    mitigated_amount: Optional[float]
    paid_amount: Optional[float]
    status: str
    issued_by_officer_id: str
    issued_at: str
    sanction_points_applied: float
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MitigationPetition(TypedDict):
    id: str
    claim_id: str
    mitigation_factors: List[str]
    narrative_reference: str
    round: int
    status: str
    mitigation_pct: float
    net_before_fee: float
    processing_fee: float
    offer_amount: float
    prior_violation_count: int
    decided_by_user_id: Optional[str]
    decision_reason_code: Optional[str]
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ComplianceSweep(TypedDict):
    """Append-only witness: exposes only ``id`` and ``created_at``."""

    id: str
    run_at: str
    executed_by_officer_id: str
    overdue_marked_count: int
    bonds_expired_count: int
    general_order_count: int
    overdue_movement_ids: List[str]
    note: Optional[str]
    created_at: str


class PaginationMeta(TypedDict):
    total_count: int
    has_more: bool
    limit: int
    offset: int


JsonDict = Dict[str, Any]
