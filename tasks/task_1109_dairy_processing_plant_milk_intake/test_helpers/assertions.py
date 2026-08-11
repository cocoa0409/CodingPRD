"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """PRD §2.4: every entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_producer(data: dict):
    _assert_common(data)
    assert isinstance(data["producer_code"], str) and data["producer_code"]
    assert isinstance(data["farm_name"], str) and data["farm_name"]
    assert isinstance(data["base_hauling_rate_cents_per_cwt"], int)
    assert data["quality_flag"] in ("STANDARD", "PREMIUM", "PROBATION")
    assert isinstance(data["rolling_rejection_count_30d"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_hauler(data: dict):
    _assert_common(data)
    assert isinstance(data["hauler_code"], str) and data["hauler_code"]
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert is_iso8601_timestamp(data["license_expires_at"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_tanker_receipt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["producer_id"])
    assert is_valid_uuid(data["hauler_id"])
    assert is_iso8601_timestamp(data["arrived_at"])
    assert isinstance(data["gross_weight_lbs"], (int, float))
    assert isinstance(data["tare_weight_lbs"], (int, float))
    assert isinstance(data["net_weight_lbs"], (int, float))
    assert isinstance(data["temperature_f"], (int, float))
    assert data["antibiotic_result"] in ("PENDING", "NEGATIVE", "POSITIVE")
    assert data["disposition"] in (
        "QUARANTINE", "RELEASED_FOR_PROCESSING", "REJECTED", "DIVERTED",
    )


def assert_lab_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tanker_receipt_id"])
    assert data["test_type"] in ("ANTIBIOTIC", "SCC", "TEMPERATURE_RECHECK")
    assert isinstance(data["result_value"], (int, float))
    assert data["status"] in ("DRAFT", "COMPLETED")


def assert_component_assay(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tanker_receipt_id"])
    for pct_field in ("butterfat_pct", "protein_pct", "other_solids_pct"):
        assert isinstance(data[pct_field], (int, float))
    for lbs_field in ("butterfat_lbs", "protein_lbs", "other_solids_lbs"):
        assert isinstance(data[lbs_field], (int, float))
        assert data[lbs_field] >= 0


def assert_producer_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["producer_id"])
    assert is_iso8601_timestamp(data["period_start_date"])
    assert is_iso8601_timestamp(data["period_end_date"])
    for money_field in (
        "gross_pool_credit_cents",
        "over_order_premium_cents",
        "hauling_deduction_cents",
        "net_payment_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"{money_field} must be integer cents, got {data.get(money_field)!r}"
        )
    assert data["pricing_variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("DRAFT", "APPROVED", "PAID", "CANCELLED")


def assert_pasteurizer_run(data: dict):
    _assert_common(data)
    assert isinstance(data["pasteurizer_id"], str) and data["pasteurizer_id"]
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert isinstance(data["flow_rate_gph"], int)
    assert isinstance(data["min_hold_temp_f"], (int, float))
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETE", "ABORTED", "CANCELLED")


def assert_cip_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pasteurizer_run_id"])
    assert is_iso8601_timestamp(data["started_at"])
    assert isinstance(data["caustic_conductivity_ms"], (int, float))
    assert isinstance(data["rinse_ph"], (int, float))
    assert data["status"] in ("IN_PROGRESS", "VALIDATED", "FAILED")


def assert_product_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pasteurizer_run_id"])
    assert data["product_code"] in (
        "WHOLE_MILK", "TWO_PERCENT", "SKIM", "HEAVY_CREAM", "BUTTER", "CONDENSED_SKIM",
    )
    assert isinstance(data["quantity_gallons"], int)
    assert isinstance(data["shelf_life_days"], int)
    assert data["status"] in ("SCHEDULED", "IN_PRODUCTION", "CODED", "SCRAPPED")


def assert_distribution_route(data: dict):
    _assert_common(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["destination_zip"], str) and data["destination_zip"]
    assert isinstance(data["transit_days"], int)
    assert isinstance(data["min_days_of_code_required"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_grade_a_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["violation_count_12mo"], int)
    assert data["status"] in ("ACTIVE", "UNDER_REVIEW", "SUSPENDED", "REINSTATED", "REVOKED")


def assert_marketing_order_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["pool_month"], str) and len(data["pool_month"]) == 7
    assert isinstance(data["announced_class_i_price_cents"], int)
    assert isinstance(data["butterfat_price_cents_per_lb"], int)
    assert isinstance(data["protein_price_cents_per_lb"], int)
    assert isinstance(data["other_solids_price_cents_per_lb"], int)
    assert isinstance(data["total_pooled_lbs"], (int, float))
    assert data["status"] in ("DRAFT", "ANNOUNCED", "FINALIZED")


def assert_settlement_money_consistency(data: dict):
    """PRD §3.11: net = gross + premium - hauling, integer cents."""
    assert data["net_payment_cents"] == (
        data["gross_pool_credit_cents"]
        + data["over_order_premium_cents"]
        - data["hauling_deduction_cents"]
    ), (
        f"net_payment_cents {data['net_payment_cents']} != gross "
        f"{data['gross_pool_credit_cents']} + premium "
        f"{data['over_order_premium_cents']} - hauling {data['hauling_deduction_cents']}"
    )
