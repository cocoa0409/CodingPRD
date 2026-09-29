"""
TypedDict shapes for every resource type in the warehouse receipt &
commodity collateral API.

Every resource type in this system carries the four common fields (id,
created_at, updated_at, version), so each shape inherits CommonFields.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four fields carried by every resource type in this system."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(CommonFields, total=False):
    name: str
    operator_name: str
    state_code: str
    license_program: str
    licensed_capacity_bushels: int
    bond_amount_cents: int
    net_worth_cents: int
    loadout_lane_count: int
    registry_participant: bool
    license_state: str
    insolvency_state: str
    licensed_by_user_id: Optional[str]
    license_effective_date: Optional[str]
    license_expiry_date: Optional[str]
    required_net_worth_cents: int
    net_worth_shortfall_cents: int
    net_worth_tolerance_cents: int
    required_bond_cents: int
    bond_deficiency_cents: int
    obligation_bushels: int
    receipted_obligation_bushels: int
    system_physical_bushels: int
    sound_physical_bushels: int
    position_variance_bushels: int
    examination_tolerance_bushels: int
    operational_posture: str
    insolvency_declared_at: Optional[str]
    insolvency_price_cents_per_bushel: Optional[int]
    allowed_claim_total_cents: int
    bond_allocated_cents: int
    fund_allocated_cents: int
    allocated_total_cents: int
    unpaid_claim_total_cents: int


class Party(CommonFields, total=False):
    name: str
    party_kind: str
    state_code: str
    credit_line_cents: int
    committed_advance_cents: int
    available_credit_cents: int
    settlement_balance_cents: int


class StorageAgreement(CommonFields, total=False):
    warehouse_id: str
    depositor_party_id: str
    commodity: str
    storage_kind: str
    min_grade: str
    max_moisture_pct: float
    storage_rate_millicents_per_bushel_day: int
    receiving_charge_cents_per_bushel: int
    loadout_charge_cents_per_bushel: int
    free_storage_days: int
    declared_value_cents_per_bushel: int
    agreement_state: str
    termination_reason: Optional[str]


class Bin(CommonFields, total=False):
    warehouse_id: str
    bin_code: str
    capacity_bushels: int
    commodity: str
    commingling_allowed: bool
    dedicated_agreement_id: Optional[str]
    stored_bushels: int
    held_bushels: int
    available_bushels: int
    scheduled_inbound_bushels: int
    condition_state: str
    last_moisture_pct: Optional[float]
    last_temperature_f: Optional[float]
    last_treatment_action: Optional[str]
    last_assessed_at: Optional[str]
    cumulative_shrink_bushels: int
    blended_grade: Optional[str]


class DepositTicket(CommonFields, total=False):
    storage_agreement_id: str
    bin_id: str
    gross_bushels: int
    test_weight_lbs: float
    moisture_pct: float
    damage_pct: float
    foreign_material_pct: float
    dockage_pct: float
    fill_start_at: str
    fill_end_at: str
    assigned_grade: str
    dockage_bushels: int
    clean_bushels: int
    shrink_bushels: int
    net_bushels: int
    settlement_variant: str
    ticket_state: str
    rejection_reason: Optional[str]
    accepted_at: Optional[str]


class WarehouseReceipt(CommonFields, total=False):
    warehouse_id: str
    deposit_ticket_id: str
    storage_agreement_id: str
    bin_id: str
    holder_party_id: str
    registry_control_party_id: Optional[str]
    receipt_number: str
    form: str
    medium: str
    quantity_bushels: int
    grade: str
    moisture_pct: float
    face_price_cents_per_bushel: int
    receiving_charge_cents: int
    issued_at: str
    receipt_state: str
    encumbrance_state: str
    quality_flag: str
    provisional_storage_charge_cents: int
    transfer_log: List[Dict[str, Any]]


class CollateralLien(CommonFields, total=False):
    receipt_id: str
    lender_party_id: str
    pledgor_party_id: Optional[str]
    principal_cents: int
    valuation_basis: str
    mark_price_cents_per_bushel: int
    perfection_method: str
    gross_value_cents: int
    grade_discount_bps: int
    eligible_value_cents: int
    admin_fee_cents: int
    warehouseman_lien_cents: int
    net_collateral_cents: int
    advance_rate_bps: int
    advance_limit_cents: int
    margin_deficiency_cents: int
    margin_status: str
    lien_state: str
    perfected_at: Optional[str]
    released_at: Optional[str]
    payoff_received_cents: Optional[int]


class PositionReport(CommonFields, total=False):
    warehouse_id: str
    period_start_date: str
    period_end_date: str
    as_of_date: str
    reported_physical_bushels: Optional[int]
    reported_obligation_bushels: Optional[int]
    obligation_bushels: Optional[int]
    system_physical_bushels: Optional[int]
    sound_physical_bushels: Optional[int]
    position_variance_bushels: Optional[int]
    count_discrepancy_bushels: Optional[int]
    obligation_misstatement_bushels: Optional[int]
    examination_tolerance_bushels: Optional[int]
    examination_required: Optional[bool]
    report_state: str
    revision_count: int
    examination_result: Optional[str]
    examined_by_user_id: Optional[str]
    findings_note: Optional[str]
    submitted_at: Optional[str]


class DeliveryOrder(CommonFields, total=False):
    receipt_id: str
    requester_party_id: str
    requested_bushels: int
    appointment_start_at: str
    appointment_end_at: str
    lane_index: int
    delivered_bushels: Optional[int]
    delivered_test_weight_lbs: Optional[float]
    delivered_moisture_pct: Optional[float]
    delivered_damage_pct: Optional[float]
    delivered_foreign_material_pct: Optional[float]
    delivered_grade: Optional[str]
    grade_delta_bps: Optional[int]
    settlement_price_cents_per_bushel: Optional[int]
    quality_adjustment_cents: Optional[int]
    storage_charge_cents: Optional[int]
    loadout_charge_cents: Optional[int]
    net_settlement_cents: Optional[int]
    delivery_state: str
    loaded_at: Optional[str]
    settled_at: Optional[str]
    cancelled_at: Optional[str]
    cancellation_reason: Optional[str]


class IndemnityClaim(CommonFields, total=False):
    warehouse_id: str
    receipt_id: str
    claimant_party_id: str
    claimed_cents: int
    entitlement_cents: Optional[int]
    allowed_cents: int
    fund_eligible: Optional[bool]
    bond_share_cents: int
    fund_share_cents: int
    unpaid_cents: int
    claim_state: str
    adjudicated_by_user_id: Optional[str]
    adjudication_note: Optional[str]


class BaseScenario(TypedDict, total=False):
    """Identifiers produced by the shared base-chain fixtures."""

    warehouse_id: str
    depositor_party_id: str
    lender_party_id: str
    agreement_id: str
    bin_id: str
    ticket_id: str
    receipt_id: str
