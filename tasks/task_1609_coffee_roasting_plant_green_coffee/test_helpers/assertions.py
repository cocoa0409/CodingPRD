"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. PriceFixEvent is append-only and must NOT
expose updated_at/version (PRD: common resource properties).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_counterparty(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["counterparty_ref"], str) and data["counterparty_ref"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["counterparty_kind"] in ("SUPPLIER", "IMPORTER", "CUSTOMER")
    assert data["counterparty_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["credit_limit_usd"], (int, float))
    assert isinstance(data["open_exposure_usd"], (int, float))


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["counterparty_id"], str)
    assert isinstance(data["contract_ref"], str) and data["contract_ref"]
    assert data["pricing_mode"] in ("DIFFERENTIAL_PTBF", "FIXED_OUTRIGHT")
    assert data["coffee_grade"] in ("SHB", "HG", "NY2_3", "ROBUSTA_GRADE1")
    assert isinstance(data["total_lbs"], int) and data["total_lbs"] > 0
    assert data["pricing_status"] in ("UNFIXED", "PARTIALLY_FIXED", "FULLY_FIXED",
                                       "NOT_APPLICABLE")
    assert data["fulfillment_status"] in ("OPEN", "PARTIALLY_RECEIVED",
                                           "FULLY_RECEIVED", "SHORT_CLOSED",
                                           "CANCELLED")
    assert isinstance(data["fixed_lbs_accum"], int)
    assert isinstance(data["received_lbs_accum"], int)
    assert isinstance(data["unpriced_lbs"], int)


def assert_price_fix_event(data: dict):
    # Append-only: carries only id + created_at as system fields.
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "price-fix events must not expose updated_at"
    assert "version" not in data, "price-fix events must not expose version"
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["fix_lbs"], int) and data["fix_lbs"] > 0
    assert isinstance(data["futures_price_usd_per_lb"], (int, float))


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["shipment_ref"], str) and data["shipment_ref"]
    assert isinstance(data["planned_lbs"], int) and data["planned_lbs"] > 0
    assert isinstance(data["scheduled_arrival"], str)
    assert data["transit_status"] in ("BOOKED", "IN_TRANSIT", "ARRIVED",
                                       "RECEIVED", "CANCELLED")
    assert data["qc_status"] in ("PENDING_CUP", "CUP_PASSED", "CUP_FAILED",
                                  "NOT_REQUIRED")
    assert data["dispute_status"] in ("NONE", "DISPUTED", "RESOLVED_ACCEPTED",
                                       "RESOLVED_REJECTED")


def assert_green_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["received_lbs"], int) and data["received_lbs"] > 0
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["warehouse_location"], str)
    assert isinstance(data["landed_cost_usd_per_lb"], (int, float))
    assert isinstance(data["available_lbs"], int)
    assert data["lot_status"] in ("QUARANTINE", "RELEASED", "REJECTED", "DEPLETED")


def assert_warehouse_position(data: dict):
    assert is_iso8601_timestamp(data.get("position_as_of", "")), (
        "position_as_of must be ISO 8601"
    )
    for field in ("physical_lbs", "committed_lbs", "reserved_for_financing_lbs",
                  "open_to_sell_lbs"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["open_to_sell_lbs"] >= 0, (
        f"open_to_sell_lbs must remain >= 0, got {data['open_to_sell_lbs']}"
    )
    assert data["open_to_sell_lbs"] == (
        data["physical_lbs"] - data["committed_lbs"]
        - data["reserved_for_financing_lbs"]
    ), (
        "open_to_sell_lbs must equal physical_lbs - committed_lbs "
        "- reserved_for_financing_lbs"
    )


def assert_financing_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lender_name"], str) and data["lender_name"]
    assert isinstance(data["facility_limit_usd"], (int, float))
    assert isinstance(data["advance_rate_pct"], (int, float))
    assert 0 <= data["advance_rate_pct"] <= 1
    assert isinstance(data["utilized_usd"], (int, float))
    assert isinstance(data["collateral_value_usd"], (int, float))
    assert data["financing_status"] in ("OPEN", "SUSPENDED", "CLOSED")


def assert_financing_reserve(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["financing_line_id"], str)
    assert isinstance(data["green_lot_id"], str)
    assert isinstance(data["reserved_lbs"], int) and data["reserved_lbs"] > 0
    assert isinstance(data["reserve_advance_usd"], (int, float))
    assert data["reserve_status"] in ("ACTIVE", "RELEASED")


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["display_name"], str)
    assert data["channel"] in ("PRIVATE_LABEL", "SUBSCRIPTION", "WHOLESALE")
    assert isinstance(data["target_roast_profile_id"], str)
    assert isinstance(data["freshness_days"], int) and data["freshness_days"] > 0
    assert data["product_status"] == "ACTIVE"


def assert_roast_profile(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["profile_code"], str) and data["profile_code"]
    assert isinstance(data["charge_temp_c"], int)
    assert isinstance(data["target_drop_temp_c"], int)
    assert data["target_drop_temp_c"] > data["charge_temp_c"]
    assert 0 <= data["expected_yield_loss_pct"] <= 1
    assert 0 <= data["shrinkage_alert_band_pct"] <= 0.10


def assert_blend_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["recipe_version"], int) and data["recipe_version"] >= 1
    assert data["recipe_status"] in ("DRAFT", "APPROVED", "SUPERSEDED", "RETIRED")


def assert_recipe_component(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["recipe_id"], str)
    assert data["required_grade"] in ("SHB", "HG", "NY2_3", "ROBUSTA_GRADE1")
    assert isinstance(data["component_pct"], (int, float))
    assert 0 < data["component_pct"] <= 1


def assert_roast_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["recipe_id"], str)
    assert isinstance(data["scheduled_green_lbs"], int)
    assert data["scheduled_green_lbs"] > 0
    assert data["production_status"] in ("SCHEDULED", "IN_DRUM", "ROASTED",
                                          "PACKED", "VOIDED")
    assert data["qc_status"] in ("PENDING_QC", "QC_PASSED", "QC_FAILED",
                                  "NOT_REQUIRED")
    assert isinstance(data["recipe_version_pinned"], int)
    assert data["yield_variance_flag"] in ("WITHIN_BAND", "ABOVE_BAND",
                                            "BELOW_BAND", "UNKNOWN")


def assert_roast_input_allocation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["roast_batch_id"], str)
    assert isinstance(data["green_lot_id"], str)
    assert isinstance(data["component_id"], str)
    assert isinstance(data["allocated_lbs"], int) and data["allocated_lbs"] > 0
    assert isinstance(data["is_substitution"], bool)
    assert data["allocation_status"] in ("ACTIVE", "CONSUMED", "RELEASED")


def assert_finished_goods_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["roast_batch_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["packed_lbs"], int) and data["packed_lbs"] > 0
    assert isinstance(data["packed_at"], str)
    assert isinstance(data["sellable_until"], str)
    assert isinstance(data["available_lbs"], int)
    assert data["lot_status"] in ("FRESH", "STALE", "DEPLETED", "RECALLED")


def assert_cupping_session(data: dict):
    _assert_common_fields(data)
    assert data["subject_kind"] in ("GREEN_LOT", "ROAST_BATCH")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["panelist_count"], int)
    for f in ("score_aroma", "score_flavor", "score_aftertaste", "score_acidity",
              "score_body", "score_balance", "score_uniformity",
              "score_clean_cup", "score_sweetness", "score_overall"):
        v = data[f]
        assert isinstance(v, (int, float)) and 0 <= v <= 10
    assert isinstance(data["defects_subtracted"], int)
    assert data["defects_subtracted"] >= 0
    assert data["session_verdict"] in ("PASS", "FAIL", "PENDING_REVIEW")


def assert_fulfillment_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_counterparty_id"], str)
    assert data["channel"] in ("PRIVATE_LABEL", "SUBSCRIPTION", "WHOLESALE")
    assert isinstance(data["requested_ship_date"], str)
    assert data["order_status"] in ("DRAFT", "RESERVED", "PACKED", "SHIPPED",
                                     "CANCELLED")
    assert isinstance(data["total_reserved_lbs"], int)


def assert_fulfillment_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["finished_goods_lot_id"], str)
    assert isinstance(data["allocated_lbs"], int) and data["allocated_lbs"] > 0
    assert data["line_status"] in ("ACTIVE", "SHIPPED", "RELEASED")


def assert_futures_hedge(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str)
    assert data["hedge_side"] in ("BUY_FUTURES", "SELL_FUTURES")
    assert isinstance(data["hedge_lbs"], int) and data["hedge_lbs"] > 0
    assert isinstance(data["entry_price_usd_per_lb"], (int, float))
    assert data["hedge_status"] in ("WORKING", "APPROVED", "LIFTED", "CANCELLED")
