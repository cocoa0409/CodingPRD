"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_customer(data: dict):
    assert isinstance(data, dict), "Customer must be an object"
    assert is_valid_uuid(data.get("id", "")), "Customer.id must be a valid UUID"
    assert isinstance(data.get("legal_name"), str) and data["legal_name"], "legal_name required"
    assert isinstance(data.get("epa_generator_id"), str), "epa_generator_id required"
    assert data.get("market_zone") in ("NORTH", "SOUTH", "COASTAL"), "market_zone must be a declared enum"
    assert data.get("credit_terms") in ("PREPAY", "NET30", "CHARGE_ONLY"), "credit_terms must be a declared enum"
    assert isinstance(data.get("prepaid_balance_cents"), int), "prepaid_balance_cents must be int"
    assert isinstance(data.get("outstanding_charge_cents"), int), "outstanding_charge_cents must be int"
    assert isinstance(data.get("halogen_violation_count"), int), "halogen_violation_count must be int"
    assert data.get("status") in ("PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_tank_site(data: dict):
    assert isinstance(data, dict), "TankSite must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be UUID"
    assert isinstance(data.get("site_address"), str) and data["site_address"]
    assert data.get("density_zone") in ("URBAN", "SUBURBAN", "RURAL")
    assert isinstance(data.get("route_eligibility_override"), bool)
    assert data.get("status") in ("ACTIVE", "INACTIVE", "CONTAMINATED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_tank(data: dict):
    assert isinstance(data, dict), "Tank must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("tank_site_id", ""))
    assert data.get("tank_kind") in ("USED_OIL", "ANTIFREEZE", "MIXED")
    assert isinstance(data.get("capacity_gallons"), int) and data["capacity_gallons"] > 0
    assert isinstance(data.get("current_volume_gallons"), int)
    assert 0 <= data["current_volume_gallons"] <= data["capacity_gallons"], "current_volume must be within capacity"
    assert data.get("ownership") in ("COMPANY_OWNED", "CUSTOMER_OWNED")
    assert data.get("ownership_status") in ("PENDING_INSTALL", "INSTALLED", "DECOMMISSION_PENDING", "DECOMMISSIONED")
    assert data.get("quarantine_status") in ("CLEAR", "QUARANTINED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_route(data: dict):
    assert isinstance(data, dict), "Route must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("route_code"), str) and data["route_code"]
    assert isinstance(data.get("scheduled_date"), str)
    assert is_valid_uuid(data.get("driver_id", ""))
    assert isinstance(data.get("vehicle_capacity_gallons"), int) and data["vehicle_capacity_gallons"] > 0
    assert isinstance(data.get("loaded_gallons"), int)
    assert 0 <= data["loaded_gallons"] <= data["vehicle_capacity_gallons"], "loaded_gallons must not exceed capacity"
    assert data.get("density_zone") in ("URBAN", "SUBURBAN", "RURAL")
    assert data.get("posture") in ("OPEN", "AT_CAPACITY", "CLOSED_OUT")
    assert data.get("status") in ("PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETE", "CANCELLED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_driver(data: dict):
    assert isinstance(data, dict), "Driver must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("driver_name"), str) and data["driver_name"]
    assert data.get("cdl_class") in ("A", "B", "C")
    assert isinstance(data.get("hazmat_endorsement"), bool)
    assert data.get("status") in ("ACTIVE", "SUSPENDED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_route_stop(data: dict):
    assert isinstance(data, dict), "RouteStop must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("tank_site_id", ""))
    assert is_valid_uuid(data.get("tank_id", ""))
    assert isinstance(data.get("scheduled_window_start"), str)
    assert isinstance(data.get("scheduled_window_end"), str)
    assert isinstance(data.get("sequence"), int) and data["sequence"] >= 1
    assert isinstance(data.get("estimated_volume_gallons"), int)
    assert data.get("status") in (
        "SCHEDULED", "EN_ROUTE", "SCREENING", "READY_TO_PUMP", "COMPLETED",
        "SKIPPED_BELOW_MINIMUM", "CANCELLED_HALOGEN", "CANCELLED_ROUTE", "CANCELLED_CUSTOMER",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_sample_screening(data: dict):
    assert isinstance(data, dict), "SampleScreening must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("route_stop_id", ""))
    assert isinstance(data.get("halogen_ppm"), int)
    assert isinstance(data.get("water_pct"), (int, float))
    assert isinstance(data.get("ph_level"), (int, float))
    assert data.get("result") in ("PASS", "FAIL_HALOGEN", "FAIL_WATER", "FAIL_PH")
    assert isinstance(data.get("screened_by_user_id"), str)
    assert is_iso8601_timestamp(data.get("screening_recorded_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_pickup_ticket(data: dict):
    assert isinstance(data, dict), "PickupTicket must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("route_stop_id", ""))
    assert isinstance(data.get("client_request_id"), str)
    assert isinstance(data.get("metered_volume_gallons"), int)
    assert isinstance(data.get("commodity_price_cents_per_gal"), int)
    assert data.get("settlement_direction") in ("PAY_CUSTOMER", "CHARGE_CUSTOMER", "ZERO_NET")
    assert isinstance(data.get("gross_amount_cents"), int)
    assert isinstance(data.get("surcharge_cents"), int)
    assert isinstance(data.get("density_fee_cents"), int)
    assert isinstance(data.get("net_amount_cents"), int)
    assert data.get("payment_status") in ("PROVISIONAL", "SETTLED", "DISPUTED", "ADJUSTED")
    assert isinstance(data.get("frozen_halogen_count"), int)
    assert data.get("tank_kind") in ("USED_OIL", "ANTIFREEZE", "MIXED")
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_manifest(data: dict):
    assert isinstance(data, dict), "Manifest must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data.get("manifest_tracking_number"), str)
    assert is_valid_uuid(data.get("disposal_facility_id", ""))
    assert isinstance(data.get("total_gallons_manifested"), int)
    assert isinstance(data.get("halogen_flag"), bool)
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "IN_TRANSIT", "DELIVERED",
        "AMENDMENT_PENDING", "AMENDED", "CLOSED", "REJECTED_BY_FACILITY",
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_disposal_facility(data: dict):
    assert isinstance(data, dict), "DisposalFacility must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("facility_name"), str)
    assert isinstance(data.get("epa_id"), str)
    assert isinstance(data.get("accepted_streams"), list)
    assert isinstance(data.get("daily_capacity_gallons"), int)
    assert isinstance(data.get("scheduled_gallons_today"), int)
    assert data.get("status") in ("ACTIVE", "SUSPENDED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_blend_batch(data: dict):
    assert isinstance(data, dict), "BlendBatch must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("batch_code"), str)
    assert data.get("target_product") in ("RE_REFINED_BASE_OIL", "RECYCLED_ANTIFREEZE", "FUEL_BLENDING_STOCK")
    assert isinstance(data.get("input_pickup_ticket_ids"), list)
    assert isinstance(data.get("input_gallons_total"), int)
    assert isinstance(data.get("yield_pct"), (int, float))
    assert isinstance(data.get("output_gallons"), int)
    assert isinstance(data.get("planned_output_gallons"), int)
    assert isinstance(data.get("resale_price_cents_per_gal"), int)
    assert isinstance(data.get("gross_resale_revenue_cents"), int)
    assert data.get("status") in ("PLANNED", "BLENDING", "QUALITY_HOLD", "RELEASED_FOR_SALE", "SOLD", "CANCELLED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_spill_incident(data: dict):
    assert isinstance(data, dict), "SpillIncident must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("tank_site_id", ""))
    assert isinstance(data.get("reported_by_user_id"), str)
    assert isinstance(data.get("gallons_spilled"), int) and data["gallons_spilled"] > 0
    assert isinstance(data.get("reportable_quantity_exceeded"), bool)
    assert isinstance(data.get("liability_cents"), int)
    assert data.get("responsible_party") in ("COMPANY", "CUSTOMER", "SHARED")
    assert data.get("cause_code") in ("EQUIPMENT_FAILURE", "CUSTOMER_OVERFILL", "DRIVER_ERROR", "THIRD_PARTY", "UNKNOWN")
    assert data.get("status") in ("OPEN", "UNDER_INVESTIGATION", "REMEDIATED", "CLOSED_NO_ACTION", "CLOSED_WITH_LIABILITY")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_market_price(data: dict):
    """MarketPrice is immutable; carries only id + created_at — NO updated_at/version."""
    assert isinstance(data, dict), "MarketPrice must be an object"
    assert is_valid_uuid(data.get("id", ""))
    assert data.get("market_zone") in ("NORTH", "SOUTH", "COASTAL")
    assert data.get("tank_kind") in ("USED_OIL", "ANTIFREEZE", "MIXED")
    assert isinstance(data.get("effective_date"), str)
    assert isinstance(data.get("price_cents_per_gal"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    # Immutable: no version / updated_at fields per PRD §2.4
    assert "updated_at" not in data, "MarketPrice must not carry updated_at"
    assert "version" not in data, "MarketPrice must not carry version"


# ---------- Domain invariant checkers ----------

def assert_route_posture_invariants(route_data: dict):
    """PRD §2.9: posture is derived — CLOSED_OUT once COMPLETE/CANCELLED,
    else AT_CAPACITY when loaded >= capacity, else OPEN."""
    status = route_data.get("status")
    posture = route_data.get("posture")
    loaded = route_data.get("loaded_gallons", 0)
    capacity = route_data.get("vehicle_capacity_gallons", 0)
    if status in ("COMPLETE", "CANCELLED"):
        assert posture == "CLOSED_OUT", f"Expected CLOSED_OUT for status {status}, got {posture}"
    elif loaded >= capacity:
        assert posture == "AT_CAPACITY", f"Expected AT_CAPACITY at loaded={loaded} capacity={capacity}, got {posture}"
    else:
        assert posture == "OPEN", f"Expected OPEN at loaded={loaded} capacity={capacity}, got {posture}"


def assert_customer_balance_non_negative(customer_data: dict):
    """PRD §3.6: prepaid_balance_cents must never go negative."""
    assert customer_data.get("prepaid_balance_cents", 0) >= 0, "prepaid_balance_cents must not be negative"
