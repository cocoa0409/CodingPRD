"""Resource serializers — explicit field lists, datetimes normalized to ISO."""
from response import iso

_DATETIME_FIELDS = {
    "berth_window_start",
    "berth_window_end",
    "yard_in_at",
    "gate_out_at",
    "damage_opened_at",
    "damage_cleared_at",
    "pickup_window_start",
    "pickup_window_end",
    "allocated_at",
    "dispatched_at",
    "gated_out_at",
}


def _emit(record, fields):
    out = {}
    for name in fields:
        value = record.get(name)
        if name in _DATETIME_FIELDS:
            value = iso(value)
        out[name] = value
    return out


CENTER_FIELDS = [
    "id",
    "name",
    "port_code",
    "yard_capacity_slots",
    "yard_occupied_slots",
    "yard_free_slots",
    "yard_posture",
    "free_storage_days",
    "daily_storage_rate_cents",
    "labor_rate_cents_per_hour",
    "fuel_surcharge_pct",
    "provisional_storage_accrued_cents",
    "realized_storage_revenue_cents",
    "repair_spend_cents",
    "created_at",
    "updated_at",
    "version",
]

BERTH_FIELDS = [
    "id",
    "processing_center_id",
    "berth_code",
    "turnaround_buffer_minutes",
    "created_at",
]

VESSEL_FIELDS = [
    "id",
    "processing_center_id",
    "berth_id",
    "voyage_code",
    "carrier_scac",
    "berth_window_start",
    "berth_window_end",
    "declared_unit_count",
    "discharged_unit_count",
    "discharge_status",
    "created_at",
    "updated_at",
    "version",
]

VEHICLE_FIELDS = [
    "id",
    "processing_center_id",
    "vessel_id",
    "vin",
    "model_line",
    "pio_program_code",
    "yard_presence",
    "yard_in_at",
    "gate_out_at",
    "processing_status",
    "damage_status",
    "damage_opened_at",
    "damage_cleared_at",
    "severity_index",
    "claim_mandatory",
    "stop_ship_blocked",
    "blocking_hold_order_id",
    "rework_cycle_count",
    "blocked_credit_days",
    "storage_charge_provisional_cents",
    "storage_charge_final_cents",
    "accessory_billed_cents",
    "created_at",
    "updated_at",
    "version",
]

SURVEY_FIELDS = [
    "id",
    "vehicle_id",
    "surveyed_by_user_id",
    "line_items",
    "line_count",
    "severity_index",
    "claimed_amount_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
]

CLAIM_FIELDS = [
    "id",
    "damage_survey_id",
    "carrier_scac",
    "filed_by_user_id",
    "claimed_amount_cents",
    "recoverable_amount_cents",
    "recoverable_basis",
    "disputed_amount_cents",
    "revision_round",
    "settled_amount_cents",
    "settled_by_user_id",
    "status",
    "created_at",
    "updated_at",
    "version",
]

REPAIR_ORDER_FIELDS = [
    "id",
    "vehicle_id",
    "carrier_claim_id",
    "description",
    "estimate_cents",
    "actual_cost_cents",
    "authorization_tier",
    "estimated_by_user_id",
    "authorized_by_user_id",
    "status",
    "created_at",
    "updated_at",
    "version",
]

KIT_FIELDS = [
    "id",
    "processing_center_id",
    "kit_code",
    "program_code",
    "received_qty_total",
    "on_hand_qty",
    "reserved_qty",
    "available_qty",
    "consumed_qty",
    "unit_cost_cents",
    "install_minutes_per_unit",
    "created_at",
    "updated_at",
    "version",
]

WORK_ORDER_FIELDS = [
    "id",
    "vehicle_id",
    "accessory_kit_id",
    "qty",
    "billed_cents",
    "installed_by_user_id",
    "reopen_count",
    "status",
    "created_at",
    "updated_at",
    "version",
]

INSPECTION_FIELDS = [
    "id",
    "vehicle_id",
    "inspector_user_id",
    "outcome",
    "defect_count",
    "status",
    "created_at",
    "updated_at",
    "version",
]

HOLD_ORDER_FIELDS = [
    "id",
    "processing_center_id",
    "hold_type",
    "scope_type",
    "model_line",
    "vehicle_id",
    "reference_code",
    "affected_vehicle_count",
    "applied_by_user_id",
    "lifted_by_user_id",
    "status",
    "created_at",
    "updated_at",
    "version",
]

DEALER_FIELDS = [
    "id",
    "dealer_code",
    "name",
    "route_zone",
    "distance_miles",
    "allocation_quota",
    "open_allocation_count",
    "created_at",
    "updated_at",
    "version",
]

CARRIER_FIELDS = [
    "id",
    "carrier_code",
    "name",
    "served_route_zones",
    "linehaul_rate_cents_per_mile",
    "slot_capacity",
    "committed_slots",
    "available_slots",
    "concurrent_load_capacity",
    "status",
    "created_at",
    "updated_at",
    "version",
]

RELEASE_ORDER_FIELDS = [
    "id",
    "vehicle_id",
    "dealer_id",
    "truck_carrier_id",
    "superseded_release_order_id",
    "cancelled_by_hold_order_id",
    "pickup_window_start",
    "pickup_window_end",
    "route_zone",
    "base_linehaul_cents",
    "fuel_surcharge_cents",
    "zone_accessorial_cents",
    "gross_freight_cents",
    "freight_discount_cents",
    "freight_total_cents",
    "allocated_at",
    "dispatched_at",
    "gated_out_at",
    "status",
    "created_at",
    "updated_at",
    "version",
]


def center(rec):
    return _emit(rec, CENTER_FIELDS)


def berth(rec):
    return _emit(rec, BERTH_FIELDS)


def vessel(rec):
    return _emit(rec, VESSEL_FIELDS)


def vehicle(rec):
    return _emit(rec, VEHICLE_FIELDS)


def survey(rec):
    data = _emit(rec, SURVEY_FIELDS)
    data["line_items"] = [dict(line) for line in rec["line_items"]]
    return data


def claim(rec):
    return _emit(rec, CLAIM_FIELDS)


def repair_order(rec):
    return _emit(rec, REPAIR_ORDER_FIELDS)


def kit(rec):
    return _emit(rec, KIT_FIELDS)


def work_order(rec):
    return _emit(rec, WORK_ORDER_FIELDS)


def inspection(rec):
    return _emit(rec, INSPECTION_FIELDS)


def hold_order(rec):
    return _emit(rec, HOLD_ORDER_FIELDS)


def dealer(rec):
    return _emit(rec, DEALER_FIELDS)


def carrier(rec):
    data = _emit(rec, CARRIER_FIELDS)
    data["served_route_zones"] = list(rec["served_route_zones"])
    return data


def release_order(rec):
    return _emit(rec, RELEASE_ORDER_FIELDS)
