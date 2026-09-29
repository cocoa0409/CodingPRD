"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------- #
# Shared system-managed field checks
# --------------------------------------------------------------------------- #
def assert_system_fields(data: dict):
    """`id` is a server-minted UUID; `created_at`/`updated_at` are ISO 8601 UTC;
    `version` starts at 1 and increments by 1 on every mutation."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict):
    """Append-only computation records carry only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records omit updated_at"
    assert "version" not in data, "append-only records omit version"


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #
def assert_seller_account(data: dict):
    assert_system_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["seller_status"] in ("ACTIVE", "SUSPENDED")
    for field in (
        "restock_reserved_units", "open_discrepancy_units", "suppressed_listing_count",
        "storage_fee_accrued_cents", "reimbursement_credit_cents", "mcf_fee_accrued_cents",
        "unit_cost_cap_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert float(data["storage_cubic_feet_entitlement"]) > 0
    assert float(data["storage_utilization_ratio"]) >= 0


def assert_fulfillment_center(data: dict):
    assert_system_fields(data)
    assert isinstance(data["fc_code"], str) and data["fc_code"]
    assert data["prep_profile"] in ("POLYBAG_REQUIRED", "LABEL_ONLY", "CASE_PACK_STRICT")
    assert data["receiving_status"] in ("OPEN", "THROTTLED", "SUSPENDED")
    assert data["case_pack_min_units"] >= 1
    assert data["receiving_capacity_units_per_window"] >= 1
    assert data["monthly_storage_rate_cents_per_cubic_foot"] >= 0
    assert data["ltsf_rate_cents_per_cubic_foot"] >= 0
    assert data["committed_receiving_units"] >= 0


def assert_sku_listing(data: dict):
    assert_system_fields(data)
    assert is_valid_uuid(data["seller_account_id"])
    assert data["listing_status"] in ("ACTIVE", "SUPPRESSED")
    assert data["inventory_health"] in ("HEALTHY", "EXCESS_AGED", "STRANDED", "OUT_OF_STOCK")
    assert data["suppression_reason"] in (
        "NONE", "MISSING_INVENTORY", "STRANDED_INVENTORY", "ZERO_FULFILLABLE"
    )
    assert isinstance(data["lot_ever_created"], bool)
    for field in ("fulfillable_units", "unfulfillable_units", "missing_units",
                  "aged_over_365_units", "recommended_replenishment_units"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert float(data["unit_cubic_feet"]) > 0
    assert data["unit_cost_cents"] >= 0


def assert_restock_quota(data: dict):
    assert_system_fields(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED")
    assert data["base_capacity_units"] >= 1
    assert 0 <= data["iprs_score"] <= 1000
    assert data["base_capacity_tier"] in ("TIER_ELEVATED", "TIER_STANDARD", "TIER_RESTRICTED")
    assert data["capacity_tier"] in ("TIER_ELEVATED", "TIER_STANDARD", "TIER_RESTRICTED")
    assert data["capacity_tier_downgrade_steps"] >= 0
    assert data["restock_limit_units"] >= 0
    assert data["utilized_units"] >= 0


def assert_inbound_shipment_plan(data: dict):
    assert_system_fields(data)
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "IN_TRANSIT", "PARTIALLY_RECEIVED",
        "RECEIVED_COMPLETE", "CANCELLED", "CLOSED",
    )
    assert data["allocation_status"] in ("WITHIN_LIMIT", "OVER_LIMIT")
    assert data["prep_compliance_status"] in ("PENDING", "COMPLIANT")
    for field in ("declared_units", "provisional_allocated_units", "final_allocated_units",
                  "allocated_units", "received_units", "missing_units"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert is_iso8601_timestamp(data["appointment_window_start"])
    assert is_iso8601_timestamp(data["appointment_window_end"])


def assert_shipment_line_item(data: dict):
    assert_system_fields(data)
    assert data["units"] >= 1
    assert data["case_pack_units"] >= 1
    assert isinstance(data["polybagged"], bool)
    assert data["label_type"] in ("FNSKU", "MANUFACTURER_BARCODE", "NONE")
    for field in ("provisional_allocated_units", "final_allocated_units",
                  "received_units", "shortfall_units"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )


def assert_inventory_lot(data: dict):
    assert_system_fields(data)
    assert data["lot_status"] in ("ACTIVE", "PARTIALLY_REMOVED", "DEPLETED")
    assert data["reconciliation_status"] in (
        "RECONCILED", "DISCREPANCY_OPEN", "DISCREPANCY_CLAIMED", "DISCREPANCY_RESOLVED"
    )
    assert data["aged_bucket"] in ("UNDER_181", "D181_270", "D271_365", "OVER_365")
    assert isinstance(data["ltsf_exposed"], bool)
    assert is_iso8601_timestamp(data["first_received_at"])
    assert data["age_days"] >= 0
    for field in ("units_received_total", "fulfillable_units", "unfulfillable_units",
                  "units_reserved_for_removal", "units_removed", "units_shipped_mcf",
                  "missing_units", "storage_fee_accrued_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )
    assert_lot_unit_conservation(data)


def assert_removal_order(data: dict):
    assert_system_fields(data)
    assert data["removal_method"] in ("DISPOSAL", "RETURN_TO_SELLER", "LIQUIDATION")
    assert data["unit_pool"] in ("FULFILLABLE", "UNFULFILLABLE")
    assert data["status"] in ("REQUESTED", "COMPLETED", "CANCELLED")
    assert data["requested_units"] >= 1
    assert isinstance(data["removal_fee_cents"], int)
    assert isinstance(data["liquidation_recovery_cents"], int)
    assert isinstance(data["net_settlement_cents"], int)


def assert_reimbursement_claim(data: dict):
    assert_system_fields(data)
    assert data["claim_type"] in ("LOST_INBOUND", "DAMAGED_WAREHOUSE", "LOST_REMOVAL")
    assert data["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert data["claimed_units"] >= 1
    assert data["evidence_document_count"] >= 0
    assert isinstance(data["evidence_reference"], str) and data["evidence_reference"]
    assert is_iso8601_timestamp(data["filing_deadline_at"])
    assert 0 <= data["resubmission_count"] <= 2
    for field in ("eligible_units", "approved_units", "reimbursement_amount_cents"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_storage_fee_assessment(data: dict):
    assert_append_only_fields(data)
    assert data["billing_run_sequence"] >= 1
    assert is_iso8601_timestamp(data["assessed_at"])
    assert data["age_days_at_assessment"] >= 0
    assert data["aged_bucket"] in ("UNDER_181", "D181_270", "D271_365", "OVER_365")
    assert data["monthly_storage_fee_cents"] >= 0
    assert data["ltsf_surcharge_cents"] >= 0
    assert data["total_fee_cents"] == (
        data["monthly_storage_fee_cents"] + data["ltsf_surcharge_cents"]
    ), "total_fee_cents is monthly_storage_fee_cents plus ltsf_surcharge_cents"


def assert_velocity_forecast(data: dict):
    assert_append_only_fields(data)
    assert data["forecast_variant"] in ("TRAILING_30", "SEASONAL_WEIGHTED")
    assert float(data["daily_velocity"]) >= 0
    assert data["target_units"] >= 0
    assert data["in_flight_units"] >= 0
    assert data["quota_headroom_units"] >= 0
    assert data["recommended_replenishment_units"] >= 0
    assert isinstance(data["stranded_risk_flag"], bool)


def assert_multi_channel_order(data: dict):
    assert_system_fields(data)
    assert data["destination_zone"] in ("ZONE_1", "ZONE_2", "ZONE_3")
    assert data["fulfillment_channel"] in ("MCF", "SELF_FULFILLED")
    assert data["recommended_channel"] in ("MCF", "SELF_FULFILLED")
    assert data["order_status"] in ("MCF_SHIPPED", "SELF_SHIPPED")
    assert isinstance(data["is_peak_period"], bool)
    assert data["units"] >= 1
    assert data["mcf_fee_cents"] >= 0
    assert isinstance(data["consumed_lot_allocations"], list)


def assert_billing_run_summary(data: dict):
    for field in ("billing_run_sequence", "assessment_count", "total_assessed_cents",
                  "downgraded_quota_count", "expired_quota_count", "closed_plan_count"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)!r}"
        )
    assert data["billing_run_sequence"] >= 1


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #
def assert_lot_unit_conservation(lot: dict):
    """`units_received_total` equals the sum of the five unit pools."""
    pooled = (
        lot["fulfillable_units"] + lot["unfulfillable_units"]
        + lot["units_reserved_for_removal"] + lot["units_removed"]
        + lot["units_shipped_mcf"]
    )
    assert lot["units_received_total"] == pooled, (
        "units_received_total must equal fulfillable + unfulfillable + reserved "
        f"+ removed + shipped_mcf; got {lot['units_received_total']} vs {pooled}"
    )


def assert_seller_reservation_ledger(seller: dict, expected_reserved: int):
    assert seller["restock_reserved_units"] == expected_reserved, (
        f"restock_reserved_units expected {expected_reserved}, "
        f"got {seller['restock_reserved_units']}"
    )


def assert_fc_commitment_ledger(fc: dict, expected_committed: int):
    assert fc["committed_receiving_units"] == expected_committed, (
        f"committed_receiving_units expected {expected_committed}, "
        f"got {fc['committed_receiving_units']}"
    )


def assert_error_envelope(response):
    """The error envelope carries only api_request_id/api_request_timestamp in meta
    plus a machine-readable error_id and a human-readable message."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) >= {"api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert isinstance(body["data"]["error_id"], str) and body["data"]["error_id"]
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    return body["data"]


def assert_success_envelope(response):
    body = response.json()
    assert body["response_type"] in ("object", "array")
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    return body["data"]
