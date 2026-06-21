COMMON = ["id", "created_at", "updated_at", "version"]

ENTITY_FIELDS = {
    "customer": COMMON + ["email", "full_name", "service_zip", "wallet_credit_cents"],
    "property": COMMON + ["customer_id", "address", "lawn_area_sqft", "zip"],
    "preference": COMMON + ["property_id", "grass_height_mm", "fertilization_enabled", "snow_opt_out"],
    "contract": COMMON + ["customer_id", "property_id", "season", "contract_price_cents",
                          "term_months", "prepaid_deposit_cents", "status", "accrued_balance_cents"],
    "route": COMMON + ["region_zip", "daily_capacity_minutes", "status", "last_dispatch_load_minutes"],
    "route_stop": COMMON + ["route_id", "property_id", "sequence", "base_service_minutes",
                            "travel_minutes", "active"],
    "crew": COMMON + ["name", "home_route_id", "status"],
    "equipment": COMMON + ["asset_tag", "equipment_type", "assigned_route_id",
                           "cumulative_runtime_hours", "runtime_at_last_service_hours",
                           "dispatch_count_since_service", "age_months", "wear_score", "status"],
    "weather_reading": ["id", "created_at", "region_zip", "snow_depth_in", "observed_at", "processed"],
    "visit": COMMON + ["contract_id", "route_stop_id", "equipment_id", "service_type",
                       "snow_depth_in", "runtime_hours", "surcharge_cents", "status"],
    "skip_request": COMMON + ["visit_id", "reason", "credit_cents", "status"],
    "invoice": COMMON + ["contract_id", "subtotal_cents", "tax_cents", "total_due_cents", "status"],
}


def serialize(kind, rec):
    fields = ENTITY_FIELDS[kind]
    return {k: rec.get(k) for k in fields}
