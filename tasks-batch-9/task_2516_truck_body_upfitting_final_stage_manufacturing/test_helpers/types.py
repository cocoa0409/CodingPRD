"""TypedDict shapes for every persisted entity of the PRD.

``ComplianceLabel`` is deliberately the only entity without ``updated_at`` and
``version``: PRD §2.4 declares a label immutable, carrying only ``id`` and
``created_at`` alongside its own fields.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ChassisModel(CommonFields):
    code: str
    make: str
    gvwr_lb: int
    front_gawr_lb: int
    rear_gawr_lb: int
    wheelbase_in: int
    cab_to_axle_in: int
    curb_front_axle_lb: int
    curb_rear_axle_lb: int
    max_aux_amp_draw: int
    electrical_bus: str
    pto_provision: str
    pto_max_flow_gpm: int
    body_builder_book_rev: str
    incomplete_vehicle_document_rev: str


class Chassis(CommonFields):
    vin: str
    chassis_model_id: str
    ownership: str
    availability_date: str
    status: str
    measured_front_axle_weight_lb: Optional[int]
    measured_rear_axle_weight_lb: Optional[int]
    allocated_upfit_order_id: Optional[str]
    quarantine_reason: Optional[str]


class BodySpec(CommonFields):
    code: str
    body_type: str
    weight_lb: int
    cg_from_body_front_in: int
    cargo_cg_from_body_front_in: int
    length_in: int
    required_min_ca_in: int
    required_min_wheelbase_in: int
    aux_amp_draw: int
    requires_hydraulics: bool
    list_price_cents: int


class EquipmentSpec(CommonFields):
    code: str
    equipment_class: str
    weight_lb: int
    requires_pto: bool
    required_flow_gpm: int
    aux_amp_draw: int
    duty_priority: int
    mount_zone: str
    requires_can_gateway: bool
    list_price_cents: int


class WorkBay(CommonFields):
    code: str
    concurrent_capacity: int
    supported_body_types: List[str]
    status: str


class Customer(CommonFields):
    name: str
    account_code: str
    fleet_contact_email: str


class BuildConfiguration(CommonFields):
    config_code: str
    chassis_model_id: str
    body_spec_id: str
    standardization_tier: str
    standard_equipment_spec_ids: List[str]
    status: str
    published_at: Optional[str]


class UpfitOrder(CommonFields):
    order_number: str
    build_configuration_id: str
    body_spec_id: str
    customer_id: Optional[str]
    chassis_id: Optional[str]
    order_type: str
    body_mount_offset_from_front_axle_in: int
    required_payload_lb: int
    requested_in_service_date: Optional[str]
    warranty_liability_cap_cents: int
    build_status: str
    compliance_status: str
    body_install_status: str
    body_actual_weight_lb: Optional[int]
    rework_round: int
    engineering_submitted_by_user_id: Optional[str]
    chassis_warranty_status: str
    committed_pto_flow_gpm: int
    committed_aux_amp_draw: int
    invoice_total_cents: int
    chassis_liability_cents: int
    upfitter_liability_cents: int
    customer_goodwill_cents: int


class EquipmentInstallation(CommonFields):
    upfit_order_id: str
    equipment_spec_id: str
    mount_cg_from_front_axle_in: int
    hydraulic_circuit: str
    status: str
    actual_weight_lb: Optional[int]
    allocated_flow_gpm: int
    hydraulic_status: str


class ElectricalInterface(CommonFields):
    upfit_order_id: str
    interface_method: str
    circuit_amp_draw: int
    signal_source: str
    customer_warranty_waiver_ack: bool
    status: str
    warranty_impact: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]


class BuildSlot(CommonFields):
    upfit_order_id: str
    work_bay_id: str
    chassis_id: Optional[str]
    slot_type: str
    start_date: str
    end_date: str
    status: str
    promoted_from_queue_at: Optional[str]


class WeightCertification(CommonFields):
    upfit_order_id: str
    basis: str
    status: str
    front_axle_load_lb: int
    rear_axle_load_lb: int
    gvw_lb: int
    payload_capacity_lb: int
    included_component_count: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    voided_reason: Optional[str]


class ComplianceLabel(TypedDict):
    """Immutable artifact: no ``updated_at`` and no ``version`` (PRD §2.4)."""

    id: str
    created_at: str
    upfit_order_id: str
    weight_certification_id: str
    supersedes_label_id: Optional[str]
    label_type: str
    responsible_party: str
    certified_gvwr_lb: int
    certified_front_gawr_lb: int
    certified_rear_gawr_lb: int
    certified_payload_lb: int
    issued_by_user_id: str
    voided_at: Optional[str]


class WarrantyClaim(CommonFields):
    upfit_order_id: str
    claim_number: str
    failure_system: str
    claim_cost_cents: int
    status: str
    split_basis: str
    taint_confirmed: bool
    dispute_round: int
    chassis_pct: int
    upfitter_pct: int
    goodwill_pct: int
    chassis_liability_cents: int
    upfitter_liability_cents: int
    customer_goodwill_cents: int


class WeightProjection(TypedDict):
    """Inline, non-persisted object returned by the weight-projection read."""

    basis: str
    front_axle_load_lb: int
    rear_axle_load_lb: int
    gvw_lb: int
    payload_capacity_lb: int
    included_component_count: int
    front_gawr_lb: int
    rear_gawr_lb: int
    gvwr_lb: int
