"""Entity -> JSON projections.  Internal bookkeeping keys (prefixed '_') never leak."""

from datetime import date, datetime
from decimal import Decimal

from util import fmt_dt

COURSE_FIELDS = (
    "id", "name", "region_code", "annual_water_allocation_gal",
    "water_restricted_threshold_pct", "water_suspended_threshold_pct",
    "water_used_gal", "water_posture", "play_posture", "frost_delay_minutes",
    "created_at", "updated_at", "version",
)

TURF_AREA_FIELDS = (
    "id", "course_id", "area_type", "hole_number", "area_sq_ft", "mowing_height_mm",
    "distance_to_water_ft", "soil_type", "target_moisture_pct", "current_moisture_pct",
    "agronomic_status", "nitrogen_applied_lb_per_1000_ytd",
    "nitrogen_projected_lb_per_1000", "rei_expires_at",
    "created_at", "updated_at", "version",
)

PLAN_FIELDS = (
    "id", "course_id", "plan_year", "nitrogen_budget_lb", "committed_nitrogen_lb",
    "status", "return_count", "submitted_by_user_id",
    "created_at", "updated_at", "version",
)

PLAN_TASK_FIELDS = (
    "id", "plan_id", "turf_area_id", "task_type", "nitrogen_lb_per_1000",
    "commitment_lb", "planned_window_start", "planned_window_end", "status",
    "created_at", "updated_at", "version",
)

APPLICATOR_FIELDS = (
    "id", "full_name", "license_number", "license_category", "license_expires_on",
    "license_status", "suspended_at", "created_at", "updated_at", "version",
)

PRODUCT_FIELDS = (
    "id", "trade_name", "epa_reg_no", "requires_license_category", "rei_hours",
    "min_buffer_ft", "max_wind_speed_mph", "posting_required", "nitrogen_pct",
    "created_at",
)

APPLICATION_FIELDS = (
    "id", "turf_area_id", "product_id", "applicator_id", "plan_task_id", "applied_at",
    "rate_lb_per_acre", "wind_speed_mph", "distance_to_water_ft", "total_lb",
    "nitrogen_lb", "rei_expires_at", "record_status", "posting_status",
    "verified_by_applicator_id", "void_reason", "created_at", "updated_at", "version",
)

PUMP_STATION_FIELDS = (
    "id", "course_id", "source_type", "max_flow_gpm", "max_concurrent_zones",
    "daily_withdrawal_cap_gal", "withdrawn_today_gal", "status",
    "created_at", "updated_at", "version",
)

IRRIGATION_RUN_FIELDS = (
    "id", "pump_station_id", "turf_area_id", "window_start", "window_end",
    "target_moisture_deficit_pct", "allotted_gal", "flow_gpm", "volume_gal", "status",
    "created_at", "updated_at", "version",
)

WINDOW_FIELDS = (
    "id", "course_id", "turf_area_id", "plan_task_id", "task_type", "window_start",
    "window_end", "crew_size", "required_unit_type", "crew_hours", "status",
    "deferral_count", "created_at", "updated_at", "version",
)

PLAY_EVENT_FIELDS = (
    "id", "course_id", "event_type", "start_at", "end_at", "holes_in_play",
    "field_size", "delayed_minutes", "effective_start_at", "readiness_index",
    "readiness_status", "status", "created_at", "updated_at", "version",
)

EQUIPMENT_FIELDS = (
    "id", "course_id", "replaced_by_unit_id", "unit_type", "model_year",
    "purchase_cost", "expected_life_hours", "service_interval_hours",
    "avg_daily_hours", "initial_engine_hours", "engine_hours", "hours_since_service",
    "engine_hours_at_last_service", "replacement_score", "replacement_score_projected",
    "replacement_flag", "status", "created_at", "updated_at", "version",
)

READING_FIELDS = (
    "id", "turf_area_id", "measured_at", "green_speed_ft", "firmness_gravities",
    "moisture_pct", "within_tournament_spec", "created_at",
)

WEATHER_EVENT_FIELDS = (
    "id", "course_id", "event_type", "delay_minutes", "expected_clear_at",
    "affected_turf_area_ids", "declared_at", "cleared_at", "deferred_window_count",
    "status", "created_at", "updated_at", "version",
)


def _value(raw):
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, datetime):
        return fmt_dt(raw)
    if isinstance(raw, date):
        return raw.isoformat()
    if isinstance(raw, Decimal):
        return float(raw)
    if isinstance(raw, list):
        return [_value(item) for item in raw]
    return raw


def _project(record, fields):
    return {name: _value(record.get(name)) for name in fields}


def course_out(record):
    return _project(record, COURSE_FIELDS)


def turf_area_out(record):
    from calc import turf_nitrogen_load

    # Both ledgers are *reported when the area is read* (PRD 3.3) and the applied
    # figure is scoped to "the logical clock's calendar year", so the reported value
    # has to follow the clock even when no write has touched the row -- and the
    # projected figure must drop a fertility task the moment it leaves
    # PLANNED/SCHEDULED ("Completed fertility tasks are deliberately not added
    # again").  Derived here rather than read from the persisted snapshot, exactly as
    # applicator_out derives license_status; a read never bumps `version`.
    payload = _project(record, TURF_AREA_FIELDS)
    applied, projected = turf_nitrogen_load(record)
    payload["nitrogen_applied_lb_per_1000_ytd"] = _value(applied)
    payload["nitrogen_projected_lb_per_1000"] = _value(projected)
    return payload


def plan_out(record):
    return _project(record, PLAN_FIELDS)


def plan_task_out(record):
    return _project(record, PLAN_TASK_FIELDS)


def applicator_out(record):
    from calc import license_status

    payload = _project(record, APPLICATOR_FIELDS)
    payload["license_status"] = license_status(record)
    return payload


def product_out(record):
    return _project(record, PRODUCT_FIELDS)


def application_out(record):
    return _project(record, APPLICATION_FIELDS)


def pump_station_out(record):
    return _project(record, PUMP_STATION_FIELDS)


def irrigation_run_out(record):
    return _project(record, IRRIGATION_RUN_FIELDS)


def window_out(record):
    return _project(record, WINDOW_FIELDS)


def play_event_out(record):
    return _project(record, PLAY_EVENT_FIELDS)


def equipment_out(record):
    return _project(record, EQUIPMENT_FIELDS)


def reading_out(record):
    return _project(record, READING_FIELDS)


def weather_event_out(record):
    return _project(record, WEATHER_EVENT_FIELDS)
