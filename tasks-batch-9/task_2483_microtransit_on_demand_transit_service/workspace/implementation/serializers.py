"""Resource serialisers.

Eleven of the twelve resources carry id / created_at / updated_at / version;
the fare transaction is an append-only ledger row and carries only id and
created_at (PRD Section 2.4).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]

SERVICE_ZONE = [
    "id", "name", "zone_code", "status", "max_walk_meters",
    "detour_tolerance_pct", "detour_tolerance_floor_minutes", "base_fare_cents",
    "fare_cap_cents_daily", "fare_cap_cents_weekly", "on_time_window_minutes",
    "curb_capacity_per_bucket", "completed_trip_count", "unserved_trip_count",
    "avg_wait_minutes", "avg_ride_minutes", "boardings_per_revenue_hour",
    "wav_avg_wait_minutes", "nonwav_avg_wait_minutes", "wav_equivalence_ratio",
    "equivalence_verdict", "created_at", "updated_at", "version",
]

VIRTUAL_STOP = [
    "id", "zone_id", "stop_code", "corridor_index", "walk_shed_meters",
    "accessibility", "paired_stop_id", "status",
    "created_at", "updated_at", "version",
]

TRANSIT_CONNECTION = [
    "id", "zone_id", "stop_id", "mode", "route_code", "scheduled_departure_utc",
    "guaranteed_transfer_buffer_minutes", "transfer_credit_cents",
    "created_at", "updated_at", "version",
]

VEHICLE = [
    "id", "zone_id", "vehicle_code", "seat_capacity", "wav_positions", "is_wav",
    "status", "created_at", "updated_at", "version",
]

DRIVER = [
    "id", "zone_id", "driver_code", "wav_certified", "status",
    "consecutive_decline_count", "created_at", "updated_at", "version",
]

RIDER = [
    "id", "zone_id", "rider_code", "fare_category", "mobility_device",
    "fare_counter_date", "fare_counter_week_start", "daily_fare_paid_cents",
    "weekly_fare_paid_cents", "created_at", "updated_at", "version",
]

DEMAND_FORECAST = [
    "id", "zone_id", "window_start_utc", "window_end_utc", "forecast_trips",
    "peak_factor", "required_base_blocks", "required_surge_blocks", "state",
    "created_at", "updated_at", "version",
]

VEHICLE_BLOCK = [
    "id", "zone_id", "vehicle_id", "driver_id", "block_type", "start_utc",
    "end_utc", "state", "opened_at", "closed_at", "seats_committed",
    "wav_positions_committed", "committed_index_min", "committed_index_max",
    "boardings_count", "scheduled_revenue_hours", "actual_revenue_hours",
    "created_at", "updated_at", "version",
]

TRIP_REQUEST = [
    "id", "zone_id", "rider_id", "origin_stop_id", "destination_stop_id",
    "connection_id", "assigned_block_id", "requested_pickup_utc", "party_size",
    "wav_required", "status", "fare_status", "no_service_reason",
    "match_attempt_count", "baseline_direct_minutes", "projected_detour_minutes",
    "promised_pickup_utc", "promised_dropoff_utc", "actual_pickup_utc",
    "actual_dropoff_utc", "wait_minutes", "ride_minutes", "quoted_fare_cents",
    "charged_fare_cents", "applied_cap", "created_at", "updated_at", "version",
]

POOL_ASSIGNMENT = [
    "id", "block_id", "trip_request_id", "seats_held", "wav_positions_held",
    "seq_pickup", "baseline_direct_minutes", "projected_detour_minutes",
    "match_score", "offer_origin", "state",
    "created_at", "updated_at", "version",
]

FARE_TRANSACTION = [
    "id", "trip_request_id", "rider_id", "kind", "amount_cents", "service_date",
    "applied_cap", "created_at",
]

SUBSIDY_REPORT = [
    "id", "zone_id", "period_start_date", "period_end_date", "variant", "state",
    "submitted_by_user_id", "certified_by_user_id", "rejection_reason",
    "amendment_count", "total_trips", "total_fare_revenue_cents",
    "total_operating_cost_cents", "subsidy_per_trip_cents",
    "created_at", "updated_at", "version",
]


def pick(record, fields):
    return {field: record.get(field) for field in fields}


def many(records, fields):
    return [pick(record, fields) for record in records]
