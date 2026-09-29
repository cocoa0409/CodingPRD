"""Entity assertions and domain invariant checkers.

The versioned entities carry ``id``, ``created_at``, ``updated_at`` and
``version``; the three append-only entities (MetalPriceQuote, CableTest,
ReelReturn) carry only ``id`` and ``created_at``, and the assertions below hold
the implementation to that split in both directions.
"""

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import SCRAP_ALERT_PCT

# ---------------------------------------------------------------------------
# Common-field shape
# ---------------------------------------------------------------------------


def assert_versioned_common_fields(data: dict) -> None:
    """Every entity the PRD does not declare append-only exposes all four."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_common_fields(data: dict) -> None:
    """Append-only records expose id and created_at and nothing else system-managed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "append-only records must not expose version"
    assert "updated_at" not in data, "append-only records must not expose updated_at"


def assert_envelope_meta(body: dict) -> None:
    """The response envelope's meta block, per the PRD response structure."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be ISO 8601 UTC"
    )


def assert_pagination_meta(meta: dict, expected_total_count=None, expected_limit=None,
                           expected_offset=None, expected_has_more=None) -> None:
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)
    if expected_total_count is not None:
        assert meta["total_count"] == expected_total_count, (
            f"Expected total_count {expected_total_count}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"Expected limit {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"Expected offset {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"Expected has_more {expected_has_more}, got {meta['has_more']}"
        )


def assert_error_envelope_only_carries_error_fields(body: dict) -> None:
    """An error payload is exactly error_id plus a non-empty message."""
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"Error data must carry exactly error_id and message, got "
        f"{sorted(body['data'].keys())}"
    )
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip(), "message must be non-empty"
    assert_envelope_meta(body)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_metal_price_quote(data: dict) -> None:
    assert_append_only_common_fields(data)
    assert data["metal"] in ("COPPER", "ALUMINUM")
    assert isinstance(data["effective_date"], str) and len(data["effective_date"]) == 10
    assert isinstance(data["settlement_price_usd_per_lb"], (int, float))
    assert data["source"] in ("COMEX", "LME", "MW_TRANSACTION")


def assert_rod_purchase_lot(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["metal"] in ("COPPER", "ALUMINUM")
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert data["pricing_basis"] in ("SPOT", "MONTH_AVG")
    assert data["status"] in ("RECEIVED", "CONSUMED", "QUARANTINED")
    assert_rod_mass_conserved(data)


def assert_compound(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["layer_role"] in ("INSULATION", "JACKET")
    assert data["flame_test"] in ("NONE", "VW_1", "FT4", "CT")
    assert data["status"] in ("DRAFT", "QUALIFIED", "SUSPENDED")
    assert isinstance(data["temp_rating_c"], int)
    assert isinstance(data["max_voltage_v"], int)
    assert isinstance(data["wet_rated"], bool)


def assert_listing_certification(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["agency"] in ("UL", "CSA", "ETL")
    assert data["status"] in ("PENDING", "ACTIVE", "VARIATION_NOTICE", "SUSPENDED")
    assert isinstance(data["inspection_interval_days"], int)
    assert isinstance(data["open_variation_count"], int)
    assert data["open_variation_count"] >= 0


def assert_factory_inspection(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["outcome"] in ("PASS", "VARIATION", "SUSPEND")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["findings_count"], int)


def assert_catalog_product(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["conductor_metal"] in ("COPPER", "ALUMINUM")
    assert data["conductor_construction"] in (
        "SOLID", "STRANDED_7", "STRANDED_19", "COMPRESSED_37",
    )
    assert data["application_rating"] in (
        "THHN", "THWN_2", "XHHW_2", "USE_2", "MV_105", "SOOW",
    )
    assert data["voltage_class"] in ("LV_600", "MV_5KV", "MV_15KV", "MV_35KV")
    assert data["status"] in ("DRAFT", "RELEASED", "SUSPENDED", "OBSOLETE")
    assert isinstance(data["voltage_rating_v"], int)
    assert isinstance(data["marking_required"], bool)
    assert isinstance(data["pd_test_required"], bool)


def assert_customer(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["market_region"] in ("NORTHEAST", "SOUTHEAST", "MIDWEST", "WEST")
    assert data["reel_program"] in ("RETURNABLE", "NON_RETURNABLE")
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert isinstance(data["pass_through_enabled"], bool)
    assert_credit_exposure_identity(data)
    assert_deposit_ledger_identity(data)


def assert_customer_order(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["price_basis"] in ("ORDER_DATE_LOCK", "SHIP_DATE_FLOAT")
    assert data["pricing_status"] in ("QUOTED", "LOCKED", "HELD", "INVOICED")
    assert data["fulfillment_status"] in (
        "OPEN", "PARTIALLY_SHIPPED", "FULFILLED", "CANCELLED",
    )
    assert isinstance(data["cut_to_length_service"], bool)
    assert isinstance(data["requested_cut_lengths_ft"], list)
    assert_cost_precision(data["quoted_total_usd"])


def assert_production_lot(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["process_state"] in (
        "QUEUED", "DRAWN", "STRANDED", "EXTRUDED", "TESTED", "PACKAGED",
        "SHIPPED", "SCRAP_CLOSED",
    )
    assert data["quality_state"] in (
        "PENDING", "CONFORMING", "NONCONFORMING", "REWORK", "QUARANTINED", "SCRAPPED",
    )
    assert isinstance(data["rework_count"], int)
    assert isinstance(data["traceability_code"], str) and data["traceability_code"]


def assert_cable_test(data: dict) -> None:
    assert_append_only_common_fields(data)
    assert data["test_type"] in ("SPARK", "HIPOT", "PARTIAL_DISCHARGE")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["operator_user_id"], str) and data["operator_user_id"]
    assert is_iso8601_timestamp(data["tested_at"]), "tested_at must be ISO 8601 UTC"


def assert_reel(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["reel_type"] in (
        "WOOD_RETURNABLE", "STEEL_RETURNABLE", "NON_RETURNABLE",
    )
    assert data["status"] in (
        "AVAILABLE", "LOADED", "SHIPPED", "RETURN_PENDING", "DAMAGED", "RETIRED",
    )
    assert isinstance(data["cycle_count"], int)
    assert data["loaded_length_ft"] <= data["capacity_ft"], (
        f"loaded_length_ft {data['loaded_length_ft']} exceeds capacity_ft "
        f"{data['capacity_ft']}"
    )


def assert_shipment(data: dict) -> None:
    assert_versioned_common_fields(data)
    assert data["status"] in ("STAGED", "INVOICED")
    assert isinstance(data["cuts_count"], int)
    if data["status"] == "INVOICED":
        assert data["price_variant_applied"] in (
            "ORDER_DATE_LOCK", "SHIP_DATE_FLOAT",
        )
        assert_cost_precision(data["invoice_amount_usd"])


def assert_reel_return(data: dict) -> None:
    assert_append_only_common_fields(data)
    assert data["condition"] in ("GOOD", "DAMAGED")
    assert data["refund_variant_applied"] in ("FLAT_STEP", "DAILY_DECAY", "NONE")
    assert isinstance(data["days_out"], int)
    assert_cost_precision(data["refund_usd"])
    assert_cost_precision(data["forfeited_usd"])


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_rod_mass_conserved(rod_lot: dict) -> None:
    """Every pound of a heat is always in exactly one of three buckets."""
    total = (
        rod_lot["remaining_lbs"] + rod_lot["committed_lbs"] + rod_lot["scrapped_lbs"]
    )
    assert total == pytest.approx(rod_lot["purchase_weight_lbs"], abs=0.01), (
        f"remaining {rod_lot['remaining_lbs']} + committed "
        f"{rod_lot['committed_lbs']} + scrapped {rod_lot['scrapped_lbs']} "
        f"= {total}, expected purchase_weight_lbs "
        f"{rod_lot['purchase_weight_lbs']}"
    )
    assert rod_lot["remaining_lbs"] >= 0
    assert rod_lot["committed_lbs"] >= 0
    assert rod_lot["scrapped_lbs"] >= 0


def assert_scrap_rate_below_alert(rod_lot: dict) -> None:
    pct = round(100.0 * rod_lot["scrapped_lbs"] / rod_lot["purchase_weight_lbs"], 2)
    assert pct <= SCRAP_ALERT_PCT, (
        f"scrap rate {pct} exceeds the alert threshold {SCRAP_ALERT_PCT}"
    )


def assert_credit_exposure_identity(customer: dict) -> None:
    expected = (
        customer["open_ar_usd"]
        + customer["reel_deposit_balance_usd"]
        - customer["credit_memo_balance_usd"]
    )
    assert customer["credit_exposure_usd"] == pytest.approx(expected, abs=0.01), (
        f"credit_exposure_usd {customer['credit_exposure_usd']} != open_ar_usd "
        f"{customer['open_ar_usd']} + reel_deposit_balance_usd "
        f"{customer['reel_deposit_balance_usd']} - credit_memo_balance_usd "
        f"{customer['credit_memo_balance_usd']}"
    )


def assert_deposit_ledger_identity(customer: dict) -> None:
    expected = (
        customer["reel_deposit_balance_usd"]
        + customer["credit_memo_balance_usd"]
        + customer["forfeited_deposit_total_usd"]
    )
    assert customer["deposit_charged_total_usd"] == pytest.approx(expected, abs=0.01), (
        f"deposit_charged_total_usd {customer['deposit_charged_total_usd']} != "
        f"reel_deposit_balance_usd {customer['reel_deposit_balance_usd']} + "
        f"credit_memo_balance_usd {customer['credit_memo_balance_usd']} + "
        f"forfeited_deposit_total_usd "
        f"{customer['forfeited_deposit_total_usd']}"
    )


def assert_money(actual, expected, label="amount") -> None:
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_decimal_price(actual, expected, label="price") -> None:
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_extrusion_measurements_cleared(lot: dict) -> None:
    """A rework rewind clears every extrusion observation on the lot."""
    for field in (
        "measured_min_wall_mils",
        "measured_max_wall_mils",
        "measured_avg_od_mm",
        "surface_marking_text",
        "concentricity_pct",
    ):
        assert lot[field] is None, f"{field} must be cleared by a rework, got {lot[field]}"


def assert_lot_dimensions(lot: dict, process_state: str, quality_state: str) -> None:
    assert lot["process_state"] == process_state, (
        f"Expected process_state {process_state}, got {lot['process_state']}"
    )
    assert lot["quality_state"] == quality_state, (
        f"Expected quality_state {quality_state}, got {lot['quality_state']}"
    )


def assert_order_dimensions(order: dict, pricing_status: str,
                            fulfillment_status: str) -> None:
    assert order["pricing_status"] == pricing_status, (
        f"Expected pricing_status {pricing_status}, got {order['pricing_status']}"
    )
    assert order["fulfillment_status"] == fulfillment_status, (
        f"Expected fulfillment_status {fulfillment_status}, got "
        f"{order['fulfillment_status']}"
    )
