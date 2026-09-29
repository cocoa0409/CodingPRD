"""Resource representations.

Ten of the eleven resource kinds carry the full audit triple
(created_at / updated_at / version).  TelemetryReading is the single
exception: it carries id and created_at only (PRD 2.5).
"""

from decimal import Decimal

OUTLET_FIELDS = (
    "id",
    "name",
    "account_code",
    "region_code",
    "throughput_tier",
    "water_hardness_gpg",
    "status",
    "service_posture",
    "open_compliance_hold_count",
    "overdue_task_count",
    "last_hold_placed_by_user_id",
    "created_at",
    "updated_at",
    "version",
)

AGREEMENT_FIELDS = (
    "id",
    "outlet_id",
    "term_start_date",
    "term_end_date",
    "annual_commitment_gallons",
    "free_on_loan",
    "shortfall_fee_cents_per_gallon",
    "equipment_value_cents",
    "status",
    "assessed_shortfall_gallons",
    "assessed_fee_cents",
    "exposure_variant",
    "recall_exposure_cents",
    "assessment_period_start",
    "assessment_period_end",
    "shortfall_assessed_by_user_id",
    "recall_decided_by_user_id",
    "created_at",
    "updated_at",
    "version",
)

UNIT_FIELDS = (
    "id",
    "outlet_id",
    "agreement_id",
    "serial_number",
    "model_code",
    "installed_at",
    "status",
    "calibration_status",
    "lifetime_dispensed_gallons",
    "gallons_at_last_filter_change",
    "brix_ratio_last_measured",
    "created_at",
    "updated_at",
    "version",
)

SUPPLY_ITEM_FIELDS = (
    "id",
    "sku_code",
    "brand_name",
    "supply_form",
    "case_pack_units",
    "ounces_per_unit",
    "promotional",
    "promo_window_start",
    "promo_window_end",
    "national_allocation_units",
    "reserved_pool_units",
    "created_at",
    "updated_at",
    "version",
)

READING_FIELDS = (
    "id",
    "dispenser_unit_id",
    "supply_item_id",
    "dispensed_ounces",
    "reading_at",
    "window_days",
    "source",
    "created_at",
)

POSITION_FIELDS = (
    "id",
    "outlet_id",
    "supply_item_id",
    "on_hand_units",
    "forecast_variant",
    "forecast_units",
    "requested_units",
    "allocated_units",
    "planned_route_stop_id",
    "alert_level",
    "promo_suppressed",
    "alert_acknowledged_by_user_id",
    "created_at",
    "updated_at",
    "version",
)

ROUTE_FIELDS = (
    "id",
    "route_code",
    "depot_region_code",
    "service_date",
    "van_code",
    "capacity_units",
    "status",
    "committed_units",
    "delivered_units",
    "created_at",
    "updated_at",
    "version",
)

STOP_FIELDS = (
    "id",
    "route_id",
    "outlet_id",
    "sequence_index",
    "window_start",
    "window_end",
    "status",
    "delivered_units",
    "skip_reason_code",
    "created_at",
    "updated_at",
    "version",
)

TASK_FIELDS = (
    "id",
    "dispenser_unit_id",
    "task_type",
    "due_at",
    "gallon_interval",
    "status",
    "breach_kind",
    "effective_gallon_interval",
    "completed_at",
    "completed_by_user_id",
    "measured_brix_ratio",
    "calibration_outcome",
    "waiver_reason",
    "waived_by_user_id",
    "created_at",
    "updated_at",
    "version",
)

CALL_FIELDS = (
    "id",
    "dispenser_unit_id",
    "reported_at",
    "symptom_code",
    "severity_score",
    "severity",
    "status",
    "van_code",
    "scheduled_window_start",
    "scheduled_window_end",
    "assigned_tech_user_id",
    "reserved_part_stock_id",
    "reserved_part_units",
    "consumed_part_units",
    "escalation_count",
    "resolution_code",
    "created_at",
    "updated_at",
    "version",
)

VAN_STOCK_FIELDS = (
    "id",
    "van_code",
    "part_sku",
    "on_van_units",
    "reserved_units",
    "consumed_units",
    "initial_units",
    "restocked_units",
    "created_at",
    "updated_at",
    "version",
)


def _pack(entity, fields):
    out = {}
    for field in fields:
        value = entity.get(field)
        if isinstance(value, Decimal):
            value = float(value)
        out[field] = value
    return out


def ser_outlet(row):
    return _pack(row, OUTLET_FIELDS)


def ser_agreement(row):
    return _pack(row, AGREEMENT_FIELDS)


def ser_unit(row):
    return _pack(row, UNIT_FIELDS)


def ser_item(row):
    return _pack(row, SUPPLY_ITEM_FIELDS)


def ser_reading(row):
    return _pack(row, READING_FIELDS)


def ser_position(row):
    return _pack(row, POSITION_FIELDS)


def ser_route(row):
    return _pack(row, ROUTE_FIELDS)


def ser_stop(row):
    return _pack(row, STOP_FIELDS)


def ser_task(row):
    return _pack(row, TASK_FIELDS)


def ser_call(row):
    return _pack(row, CALL_FIELDS)


def ser_van_stock(row):
    return _pack(row, VAN_STOCK_FIELDS)
