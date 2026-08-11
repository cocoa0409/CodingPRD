"""Entity serializers.  Field sets come straight from SCAFFOLD 1.1."""

import calc

COMMON = ("id", "created_at", "updated_at", "version")
APPEND_ONLY = ("id", "created_at")

FIELDS = {
    "client": COMMON + (
        "display_name", "email", "phone", "client_type", "home_zone_code",
        "account_credit_cents", "status"),
    "location": COMMON + (
        "client_id", "label", "zone_code", "address_key", "stair_flights",
        "has_service_elevator", "climate_controlled", "distance_miles_from_shop",
        "out_of_band_flag", "readings_in_window", "out_of_band_count"),
    "climate_reading": APPEND_ONLY + (
        "location_id", "recorded_at_utc", "relative_humidity_pct",
        "temperature_f", "in_band"),
    "instrument": COMMON + (
        "client_id", "current_location_id", "consignment_agreement_id", "make",
        "model", "serial_number", "instrument_class", "usage_tier",
        "target_pitch_hz", "last_tuning_date", "pitch_deviation_cents",
        "raw_pitch_tier", "pitch_raise_tier", "planned_visit_count",
        "condition_status", "custody_status", "unauthorized_move_flag",
        "tuning_cycle_interval_days"),
    "tuning_recall": COMMON + (
        "instrument_id", "cycle_start_date", "interval_days", "due_date",
        "days_overdue", "overdue_tier", "status", "notified_at"),
    "technician": COMMON + (
        "display_name", "certification_level", "move_certified", "zone_codes",
        "daily_capacity_minutes", "status"),
    "route_day": COMMON + (
        "technician_id", "service_date", "capacity_minutes", "committed_minutes",
        "stop_count", "status"),
    "appointment": COMMON + (
        "instrument_id", "route_day_id", "location_id", "service_order_id",
        "tuning_recall_id", "service_type", "scheduled_start_utc",
        "service_minutes", "travel_buffer_minutes", "total_block_minutes",
        "same_address_chained", "estimated_price_cents", "cancellation_fee_cents",
        "reschedule_count", "scheduling_status", "fulfillment_status"),
    "quote": COMMON + (
        "instrument_id", "client_id", "supersedes_quote_id", "service_type",
        "version_number", "line_count", "base_price_cents", "line_discount_cents",
        "zone_surcharge_cents", "subtotal_cents", "loyalty_discount_cents",
        "total_cents", "deposit_required_cents", "deposit_variant",
        "pricing_variant", "issued_at", "expires_at", "status"),
    "service_order": COMMON + (
        "quote_id", "instrument_id", "client_id", "assigned_technician_id",
        "service_type", "contract_total_cents", "billed_cents", "unbilled_cents",
        "deposit_held_cents", "deposit_applied_cents", "deposit_refunded_cents",
        "deposit_forfeited_cents", "estimated_minutes", "visit_plan_variant",
        "started_at", "completed_at", "status"),
    "milestone": COMMON + (
        "service_order_id", "sequence_index", "label", "amount_cents",
        "rejection_count", "released_by_user_id", "released_at", "accepted_at",
        "status"),
    "move_job": COMMON + (
        "instrument_id", "client_id", "origin_location_id",
        "destination_location_id", "move_technician_id", "distance_miles",
        "distance_band", "distance_variant", "stair_flights_total",
        "crane_required", "climate_controlled_transport",
        "scheduled_window_start_utc", "scheduled_window_end_utc", "base_cents",
        "stair_cents", "crane_cents", "distance_cents", "climate_cents",
        "total_cents", "status"),
    "warranty": COMMON + (
        "service_order_id", "instrument_id", "client_id", "service_type",
        "term_days", "start_date", "end_date", "covered_price_cents",
        "claim_count", "transferred_from_client_id", "void_reason", "status"),
    "warranty_claim": COMMON + (
        "warranty_id", "service_order_id", "reported_issue", "elapsed_fraction",
        "resolution_variant", "credit_cents", "adjudicated_by_user_id", "status"),
    "consignment_agreement": COMMON + (
        "instrument_id", "consignor_client_id", "buyer_client_id",
        "reserve_price_cents", "advanced_restoration_cents", "start_date",
        "expires_at", "sale_price_cents", "split_variant",
        "advance_recovered_cents", "shop_commission_cents",
        "consignor_payout_cents", "created_by_user_id", "status"),
    "parts_lot": COMMON + (
        "part_type", "lot_code", "initial_qty", "on_hand_qty", "allocated_qty",
        "consumed_qty", "status"),
    "parts_allocation": COMMON + (
        "parts_lot_id", "service_order_id", "requested_qty", "allocated_qty",
        "status"),
    "ledger_entry": APPEND_ONLY + (
        "client_id", "service_order_id", "warranty_claim_id",
        "consignment_agreement_id", "reverses_entry_id", "entry_type",
        "amount_cents", "memo", "posted_at_utc"),
}


def _project(kind, row):
    return {k: row.get(k) for k in FIELDS[kind]}


def client(row):
    return _project("client", row)


def location(row):
    return _project("location", row)


def climate_reading(row):
    return _project("climate_reading", row)


def instrument(row):
    return _project("instrument", row)


def tuning_recall(row):
    return _project("tuning_recall", row)


def technician(row):
    return _project("technician", row)


def route_day(row):
    return _project("route_day", row)


def appointment(row):
    return _project("appointment", row)


def quote(row):
    return _project("quote", row)


def service_order(row):
    out = _project("service_order", row)
    # PRD 3.6: the nominal parts requirement is surfaced for the shop's planning
    # when a REBUILD order is created.
    if row.get("service_type") == "REBUILD" and row.get("_parts_requirement"):
        out["parts_requirement"] = dict(row["_parts_requirement"])
    return out


def milestone(row):
    return _project("milestone", row)


def move_job(row):
    return _project("move_job", row)


def warranty(row):
    return _project("warranty", row)


def warranty_claim(row):
    return _project("warranty_claim", row)


def consignment_agreement(row):
    return _project("consignment_agreement", row)


def parts_lot(row):
    return _project("parts_lot", row)


def parts_allocation(row):
    return _project("parts_allocation", row)


def ledger_entry(row):
    return _project("ledger_entry", row)
