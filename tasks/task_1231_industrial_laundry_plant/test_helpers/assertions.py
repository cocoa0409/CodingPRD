"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .types import (
    CustomerStatus, CustomerKind, BillingMode, WashFormula, RouteStatus,
    RouteStopStatus, SoiledCartStatus, SortBatchStatus, SortDisposition,
    WashLoadStatus, HygienicTestResult, FinishRunStatus, GarmentState,
    DeliveryStatus, DiscrepancyStatus, InvoiceStatus,
)


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_plant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["reject_rate_alert_pct"], (int, float))
    assert isinstance(data["par_shortage_alert_pieces"], int)
    assert isinstance(data["utility_baseline_kwh_per_lb"], (int, float))
    assert isinstance(data["utility_baseline_gal_per_lb"], (int, float))


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["customer_kind"] in [e.value for e in CustomerKind]
    assert data["billing_mode"] in [e.value for e in BillingMode]
    assert isinstance(data["chip_tracking_enabled"], bool)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["account_balance_cents"], int)
    assert data["status"] in [e.value for e in CustomerStatus]


def assert_linen_category(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["piece_weight_lb"], (int, float))
    assert data["wash_formula_code"] in [e.value for e in WashFormula]
    assert isinstance(data["hygienic_test_required"], bool)
    assert isinstance(data["replacement_cost_cents"], int)
    assert isinstance(data["cog_wash_rate_cents_per_lb"], int)


def assert_par_level(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["par_pieces"], int)
    assert isinstance(data["current_on_site_pieces"], int)


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert isinstance(data["driver_name"], str) and data["driver_name"]
    assert data["status"] in [e.value for e in RouteStatus]


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sequence_index"], int)
    assert isinstance(data["declared_soiled_weight_lb"], (int, float))
    assert isinstance(data["actual_soiled_weight_lb"], (int, float))
    assert data["status"] in [e.value for e in RouteStopStatus]


def assert_soiled_cart(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cart_tag"], str) and data["cart_tag"]
    assert isinstance(data["scale_weight_lb"], (int, float))
    assert data["status"] in [e.value for e in SoiledCartStatus]


def assert_sort_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["total_sorted_pieces"], int)
    assert isinstance(data["accepted_pieces"], int)
    assert isinstance(data["rejected_pieces"], int)
    assert isinstance(data["reject_rate_pct"], (int, float))
    assert isinstance(data["alert_raised"], bool)
    assert data["status"] in [e.value for e in SortBatchStatus]


def assert_sort_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pieces"], int) and data["pieces"] >= 1
    assert data["disposition"] in [e.value for e in SortDisposition]


def assert_wash_load(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str) and data["machine_id"]
    assert data["formula_code"] in [e.value for e in WashFormula]
    assert isinstance(data["rewash_count"], int)
    assert data["hygienic_test_result"] in [e.value for e in HygienicTestResult]
    assert data["status"] in [e.value for e in WashLoadStatus]


def assert_finish_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_id"], str) and data["line_id"]
    assert isinstance(data["pieces_in"], int)
    assert data["status"] in [e.value for e in FinishRunStatus]


def assert_garment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["chip_code"], str) and data["chip_code"]
    assert data["state"] in [e.value for e in GarmentState]


def assert_delivery(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pieces_promised"], int)
    assert isinstance(data["pieces_delivered"], int)
    assert isinstance(data["shortfall_pieces"], int)
    assert isinstance(data["overage_pieces"], int)
    assert data["status"] in [e.value for e in DeliveryStatus]


def assert_discrepancy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claimed_shortfall_pieces"], int)
    assert data["status"] in [e.value for e in DiscrepancyStatus]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["linen_charges_cents"], int)
    assert isinstance(data["lost_item_charges_cents"], int)
    assert isinstance(data["utility_surcharge_cents"], int)
    assert isinstance(data["credits_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["status"] in [e.value for e in InvoiceStatus]


def assert_utility_reading(data: dict):
    """UtilityReading is immutable: only id + created_at are present on top of
    the posted fields; updated_at and version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "UtilityReading must not carry updated_at"
    assert "version" not in data, "UtilityReading must not carry version"
    assert isinstance(data["period_month"], str) and data["period_month"]
    assert isinstance(data["kwh_used"], (int, float))
    assert isinstance(data["gallons_used"], (int, float))
    assert isinstance(data["clean_lbs_processed"], (int, float))
    assert isinstance(data["kwh_rate_cents"], int)
    assert isinstance(data["gallon_rate_cents"], int)


def assert_invoice_total_invariants(data: dict):
    """The invoice total is the four money components netted and floored at
    zero (PRD §3.8)."""
    expected = max(
        0,
        data["linen_charges_cents"]
        + data["lost_item_charges_cents"]
        + data["utility_surcharge_cents"]
        - data["credits_cents"],
    )
    assert data["total_due_cents"] == expected, (
        f"total_due_cents {data['total_due_cents']} != floored component sum {expected}"
    )
    assert data["total_due_cents"] >= 0
