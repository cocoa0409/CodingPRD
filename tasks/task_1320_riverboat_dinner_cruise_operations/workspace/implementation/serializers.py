"""Response serializers: whitelist exactly the fields the PRD declares per
entity. Internal bookkeeping keys (cancelled_by_event_id, was_placed_at_cancel,
quoted_at_dt, last_actor_user_id, accepted_by_user_id, departed_at,
is_charter_booking) never leave the server."""

_COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "vessel": _COMMON + ["name", "coast_guard_capacity", "home_dock_id", "status"],
    "dock": _COMMON + ["name", "parking_capacity", "parking_in_use"],
    "menu_tier": _COMMON + ["code", "base_price_cents", "galley_load_per_cover", "bar_package_price_cents"],
    "cruise": _COMMON + ["vessel_id", "menu_tier_id", "depart_at", "return_at", "season",
                         "is_holiday", "reserved_covers", "boarded_count",
                         "bar_service_enabled", "charter_booking_id", "status"],
    "customer": _COMMON + ["email", "full_name", "credit_balance_cents"],
    "booking": _COMMON + ["cruise_id", "customer_id", "party_size", "booking_total_cents",
                          "bar_package_count", "bar_package_total_cents",
                          "payment_status", "booking_status"],
    "passenger": ["id", "created_at", "booking_id", "full_name", "date_of_birth",
                  "is_minor", "boarded_at"],
    "manifest": _COMMON + ["cruise_id", "passenger_count", "coast_guard_capacity", "status"],
    "staff_member": _COMMON + ["full_name", "role_code", "alcohol_cert_expires_at"],
    "assignment": _COMMON + ["cruise_id", "staff_member_id", "assigned_role", "status"],
    "provision_order": _COMMON + ["cruise_id", "provisional_covers", "final_covers",
                                  "provision_load_units", "restocking_rebate_cents", "status"],
    "inquiry": _COMMON + ["cruise_id", "customer_id", "quoted_total_cents",
                          "quote_round", "status"],
    "weather_event": _COMMON + ["declared_at", "severity", "window_start",
                                "window_end", "status"],
    "credit": ["id", "created_at", "customer_id", "booking_id", "amount_cents",
               "final_amount_cents", "credit_status"],
    "dock_slot": _COMMON + ["dock_id", "vessel_id", "slot_start", "slot_end"],
    "parking_pass": _COMMON + ["dock_id", "booking_id", "cruise_id", "status"],
}


def serialize(kind, record):
    if record is None:
        return None
    allowed = FIELDS[kind]
    return {k: record.get(k) for k in allowed}


def serialize_list(kind, records):
    return [serialize(kind, r) for r in records]
