"""Typed shapes for request payloads and response rows.

These are ``TypedDict`` descriptions used purely for editor and reader
clarity; the HTTP layer sends and receives plain dictionaries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

JsonDict = Dict[str, Any]

ModelLine = Literal["LX500", "TX300", "EV900"]
RouteZone = Literal["A", "B", "C"]
DamageZone = Literal["GLASS", "BODY_PANEL", "INTERIOR", "UNDERBODY"]
HoldType = Literal["RECALL", "STOP_SHIP"]
ScopeType = Literal["MODEL_LINE", "SINGLE_VIN"]
CarrierStatus = Literal["ACTIVE", "SUSPENDED"]
ClaimOutcome = Literal["ACCEPT", "DISPUTE", "DENY"]
RepairDecision = Literal["AUTHORIZE", "REJECT"]
InspectionOutcome = Literal["PASS", "FAIL"]


# --------------------------------------------------------------------------
# Request payloads
# --------------------------------------------------------------------------
class ProcessingCenterPayload(TypedDict, total=False):
    name: str
    port_code: str
    yard_capacity_slots: int
    daily_storage_rate_cents: int
    labor_rate_cents_per_hour: int
    fuel_surcharge_pct: float
    free_storage_days: int


class BerthPayload(TypedDict, total=False):
    processing_center_id: str
    berth_code: str
    turnaround_buffer_minutes: int


class VesselPayload(TypedDict, total=False):
    processing_center_id: str
    berth_id: str
    voyage_code: str
    carrier_scac: str
    berth_window_start: str
    berth_window_end: str
    declared_unit_count: int


class VehiclePayload(TypedDict, total=False):
    vin: str
    model_line: ModelLine
    pio_program_code: Optional[str]


class DamageLineItem(TypedDict, total=False):
    damage_zone: DamageZone
    severity_points: int
    repair_estimate_cents: int


class DamageSurveyPayload(TypedDict, total=False):
    line_items: List[DamageLineItem]


class CarrierClaimPayload(TypedDict, total=False):
    carrier_scac: str
    expected_damage_survey_version: int


class CarrierResponsePayload(TypedDict, total=False):
    outcome: ClaimOutcome
    disputed_amount_cents: int


class ClaimResubmitPayload(TypedDict, total=False):
    revised_claim_amount_cents: int


class ClaimSettlePayload(TypedDict, total=False):
    settled_amount_cents: int


class RepairOrderPayload(TypedDict, total=False):
    description: str
    estimate_cents: int
    carrier_claim_id: Optional[str]


class RepairAuthorizePayload(TypedDict, total=False):
    decision: RepairDecision


class RepairCompletePayload(TypedDict, total=False):
    actual_cost_cents: int


class AccessoryKitPayload(TypedDict, total=False):
    kit_code: str
    program_code: str
    received_qty_total: int
    unit_cost_cents: int
    install_minutes_per_unit: int


class AccessoryWorkOrderPayload(TypedDict, total=False):
    accessory_kit_id: str
    qty: int


class InspectionCompletePayload(TypedDict, total=False):
    outcome: InspectionOutcome
    defect_count: int


class HoldOrderPayload(TypedDict, total=False):
    hold_type: HoldType
    scope_type: ScopeType
    reference_code: str
    model_line: Optional[ModelLine]
    vehicle_id: Optional[str]


class DealerPayload(TypedDict, total=False):
    dealer_code: str
    name: str
    route_zone: RouteZone
    distance_miles: int
    allocation_quota: int


class TruckCarrierPayload(TypedDict, total=False):
    carrier_code: str
    name: str
    served_route_zones: List[RouteZone]
    linehaul_rate_cents_per_mile: int
    slot_capacity: int
    concurrent_load_capacity: int
    status: CarrierStatus


class TruckCarrierPatchPayload(TypedDict, total=False):
    status: CarrierStatus
    linehaul_rate_cents_per_mile: int
    concurrent_load_capacity: int


class AllocationPayload(TypedDict, total=False):
    dealer_id: str
    pickup_window_start: str
    pickup_window_end: str
    expected_vehicle_version: int


class ClockPayload(TypedDict, total=False):
    current_utc: str


# --------------------------------------------------------------------------
# Response rows (partial: only the fields the tests read)
# --------------------------------------------------------------------------
class PaginationMeta(TypedDict):
    limit: int
    offset: int
    total_count: int
    has_more: bool
