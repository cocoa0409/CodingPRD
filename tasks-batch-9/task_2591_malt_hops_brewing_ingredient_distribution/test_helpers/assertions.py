"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_audit_triple(data: dict):
    """Every resource except a temperature reading carries id + the audit triple."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC with 3 fractional digits: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_brewer(data: dict):
    assert_audit_triple(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["brewery_license_no"], str)
    assert data["credit_terms_days"] in (0, 15, 30, 45)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 1
    assert isinstance(data["cold_chain_certified"], bool)
    assert isinstance(data["legacy_trailing_lbs"], (int, float))
    assert isinstance(data["ar_balance_cents"], int)
    assert isinstance(data["open_order_exposure_cents"], int)
    assert isinstance(data["credit_exposure_cents"], int)
    assert data["credit_status"] in ("GOOD_STANDING", "WATCH", "HOLD")
    assert data["freight_program_tier"] in ("TIER_1", "TIER_2", "TIER_3")


def assert_brewer_credit_identity(data: dict):
    """credit_exposure_cents is ar_balance_cents + open_order_exposure_cents."""
    assert data["credit_exposure_cents"] == (
        data["ar_balance_cents"] + data["open_order_exposure_cents"]
    ), (
        "credit_exposure_cents must equal ar_balance_cents + "
        f"open_order_exposure_cents, got {data['credit_exposure_cents']} vs "
        f"{data['ar_balance_cents']} + {data['open_order_exposure_cents']}"
    )


def assert_crop_year_program(data: dict):
    assert_audit_triple(data)
    assert isinstance(data["crop_year"], int) and 2020 <= data["crop_year"] <= 2100
    assert data["status"] in ("OPEN", "HARVEST_REPORTED", "SETTLED")
    assert is_iso8601_timestamp(data["contract_open_date"])
    assert is_iso8601_timestamp(data["harvest_report_due_date"])


def assert_hop_variety(data: dict):
    assert_audit_triple(data)
    assert isinstance(data["variety_code"], str)
    assert isinstance(data["substitution_group"], str)
    assert 0.01 <= float(data["alpha_acid_target_pct"]) <= 30.00
    assert isinstance(data["cold_storage_required"], bool)
    assert int(data["pallet_quantity_lbs"]) >= 1
    assert int(data["min_order_lbs"]) >= 1
    assert float(data["spot_price_cents_per_lb"]) > 0
    assert float(data["available_spot_lbs"]) >= 0


def assert_hop_contract(data: dict):
    assert_audit_triple(data)
    assert data["contract_type"] in ("FIXED_CROP_YEAR", "SPOT_HOLD")
    assert data["status"] in ("ACTIVE", "SHORTFALL_ADJUSTED",
                             "CARRY_FORWARD_PENDING", "CARRIED_FORWARD",
                             "DEFAULTED", "RESOLD")
    assert float(data["price_per_lb_cents"]) > 0
    assert is_iso8601_timestamp(data["delivery_window_start"])
    assert is_iso8601_timestamp(data["delivery_window_end"])
    assert_contract_conservation(data)


def assert_contract_conservation(data: dict):
    """PRD §2.11: allocated_lbs is partitioned into exactly five buckets."""
    bucket_sum = (data["remaining_lbs"] + data["committed_lbs"]
                  + data["carried_forward_out_lbs"] + data["defaulted_lbs"]
                  + data["resold_lbs"])
    assert data["allocated_lbs"] == bucket_sum, (
        "Conservation broken: allocated_lbs "
        f"{data['allocated_lbs']} != remaining {data['remaining_lbs']} "
        f"+ committed {data['committed_lbs']} "
        f"+ carried_forward_out {data['carried_forward_out_lbs']} "
        f"+ defaulted {data['defaulted_lbs']} + resold {data['resold_lbs']}"
    )


def assert_substitution_offer(data: dict):
    assert_audit_triple(data)
    assert data["status"] in ("OPEN", "ACCEPTED", "DECLINED", "SUPERSEDED")
    assert data["selection_mode"] in ("EXPLICIT", "AUTO_RANKED")
    assert int(data["offered_lbs"]) >= 1


def assert_malt_product(data: dict):
    assert_audit_triple(data)
    assert data["malt_class"] in ("BASE", "SPECIALTY")
    assert float(data["list_price_cents_per_lb"]) > 0
    assert float(data["max_moisture_pct"]) > 0
    assert float(data["min_diastatic_power"]) >= 0
    assert isinstance(data["cold_storage_required"], bool)


def assert_malt_lot(data: dict):
    assert_audit_triple(data)
    assert data["status"] in ("RECEIVED", "PASSED", "QUARANTINED", "RELEASED",
                             "REJECTED")
    assert int(data["quantity_lbs"]) >= 1
    assert isinstance(data["analysis_count"], int) and data["analysis_count"] >= 0
    assert float(data["available_lbs"]) == float(data["quantity_lbs"]) - float(
        data["committed_lbs"]), (
        f"available_lbs {data['available_lbs']} must equal quantity_lbs "
        f"{data['quantity_lbs']} less committed_lbs {data['committed_lbs']}"
    )


def assert_yeast_strain(data: dict):
    assert_audit_triple(data)
    assert data["fermentation_type"] in ("ALE", "LAGER")
    assert int(data["propagation_lead_time_days"]) >= 1
    assert 50.00 <= float(data["viability_pct_at_ship"]) <= 100.00
    assert float(data["cells_per_ml_slurry_billion"]) > 0
    assert float(data["min_batch_l"]) > 0
    assert float(data["list_price_cents_per_l"]) > 0


def assert_brewer_recipe(data: dict):
    assert_audit_triple(data)
    assert float(data["batch_volume_bbl"]) > 0
    assert float(data["original_gravity_plato"]) > 0
    assert 0.00 <= float(data["adjunct_pct"]) <= 60.00
    assert float(data["target_color_lovibond"]) > 0
    assert float(data["target_extract_pct"]) > 0
    assert float(data["target_protein_pct"]) > 0


def assert_propagation_job(data: dict):
    assert_audit_triple(data)
    assert data["status"] in ("REQUESTED", "PROPAGATING", "READY", "FAILED",
                             "SHIPPED")
    assert data["pitch_rate_advice"] in ("UNDERPITCH", "OPTIMAL", "OVERPITCH")
    assert float(data["propagation_volume_l"]) > 0
    assert is_iso8601_timestamp(data["pitch_date"])


def assert_sales_order(data: dict):
    assert_audit_triple(data)
    assert data["fulfillment_status"] in ("DRAFT", "CONFIRMED", "PICKED",
                                         "SHIPPED", "DELIVERED", "CANCELLED")
    assert data["credit_status"] in ("PENDING_REVIEW", "APPROVED", "ON_HOLD")
    assert data["fee_variant"] in (None, "PROVISIONAL", "FINAL")
    assert data["freight_tier_applied"] in (None, "TIER_1", "TIER_2", "TIER_3")
    for money in ("subtotal_cents", "volume_discount_cents", "freight_cents",
                  "pallet_break_fee_cents", "small_order_surcharge_cents",
                  "total_cents", "final_freight_adjustment_cents"):
        assert isinstance(data[money], int), \
            f"{money} must be an integer count of cents, got {data[money]!r}"
    assert isinstance(data["requires_cold_chain"], bool)
    assert isinstance(data["line_count"], int)


def assert_order_total_identity(data: dict):
    """PRD §3.8: total_cents is the discounted subtotal plus the three fees."""
    expected = (data["subtotal_cents"] - data["volume_discount_cents"]
                + data["freight_cents"] + data["pallet_break_fee_cents"]
                + data["small_order_surcharge_cents"])
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} must equal discounted subtotal "
        f"({data['subtotal_cents']} - {data['volume_discount_cents']}) + "
        f"freight {data['freight_cents']} + pallet break "
        f"{data['pallet_break_fee_cents']} + small order "
        f"{data['small_order_surcharge_cents']} = {expected}"
    )


def assert_order_line(data: dict):
    assert_audit_triple(data)
    assert data["item_type"] in ("HOP", "MALT", "YEAST")
    assert data["allocation_source"] in ("CONTRACT", "SPOT")
    assert data["uom"] in ("LB", "L")
    assert data["status"] in ("OPEN", "TRIMMED", "CANCELLED_SHORTFALL",
                             "REMOVED", "QUARANTINED")
    assert isinstance(data["extended_cents"], int)
    assert isinstance(data["pallet_break"], bool)
    assert isinstance(data["cold_chain_required"], bool)


def assert_cold_storage_zone(data: dict):
    assert_audit_triple(data)
    assert -40.00 <= float(data["temp_setpoint_c"]) <= 25.00
    assert float(data["tolerance_c"]) > 0
    assert int(data["capacity_pallets"]) >= 1
    assert isinstance(data["occupied_pallets"], int)
    assert data["occupied_pallets"] >= 0


def assert_cold_chain_shipment(data: dict):
    assert_audit_triple(data)
    assert data["status"] in ("STAGED", "HELD", "IN_TRANSIT", "DELIVERED",
                             "EXCURSION_FLAGGED", "SUPERSEDED")
    assert int(data["pallet_count"]) >= 1
    assert isinstance(data["excursion_minutes"], int)
    assert isinstance(data["reading_count"], int)
    assert -40.00 <= float(data["reefer_setpoint_c"]) <= 25.00


def assert_temperature_reading(data: dict):
    """A reading carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "reading id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "reading created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "a TemperatureReading has no updated_at (PRD §2.5)"
    assert "version" not in data, \
        "a TemperatureReading has no version (PRD §2.5)"
    assert isinstance(data["in_violation"], bool)
    assert isinstance(data["interval_minutes"], int)
    assert isinstance(data["cumulative_excursion_minutes"], int)


def assert_spec_match_result(data: dict):
    assert data["match_grade"] in ("EXACT", "ACCEPTABLE", "SUBSTITUTE_REQUIRED",
                                  "REJECTED")
    assert data["hard_fail_reason"] in (None, "MOISTURE_ABOVE_MAX",
                                       "DIASTATIC_POWER_BELOW_MIN")


def assert_two_decimal_places(value, label="value"):
    assert round(float(value), 2) == float(value), \
        f"{label} must carry at most two decimal places, got {value!r}"


def assert_three_decimal_places(value, label="value"):
    assert round(float(value), 3) == float(value), \
        f"{label} must carry at most three decimal places, got {value!r}"
