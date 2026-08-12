"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_retailer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("store_name"), str)
    assert data.get("jurisdiction_code") in ("CA_NORTH", "CA_SOUTH", "NV_CLARK", "AZ_MARICOPA")
    assert data.get("credit_terms") in ("COD", "NET7", "NET14")
    assert isinstance(data.get("credit_limit_cents"), int)
    assert data.get("credit_status") in ("GOOD_STANDING", "CREDIT_HOLD")
    assert isinstance(data.get("ar_balance_cents"), int)
    assert isinstance(data.get("exposure_forward_cents"), int)
    assert data.get("delivery_day") in ("MON", "TUE", "WED", "THU", "FRI")
    assert isinstance(data.get("version"), int)


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("sku"), str)
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("case_pack_units"), int)
    assert data.get("case_pack_units") >= 1
    assert isinstance(data.get("case_cost_cents"), int)
    assert isinstance(data.get("unit_cost_cents"), int)
    assert isinstance(data.get("split_case_allowed"), bool)
    assert data.get("status") == "ACTIVE"
    assert isinstance(data.get("version"), int)


def assert_order_guide(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("retailer_id"), str)
    assert data.get("delivery_day") in ("MON", "TUE", "WED", "THU", "FRI")
    assert isinstance(data.get("cutoff_hours_before"), int)
    assert isinstance(data.get("lines"), list)
    assert data.get("status") == "ACTIVE"
    assert isinstance(data.get("version"), int)


def assert_promo_event(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("product_id"), str)
    assert data.get("promo_type") in ("OFF_INVOICE", "SCAN_BACK")
    assert isinstance(data.get("discount_pct_bps"), int)
    assert 1 <= data.get("discount_pct_bps") <= 10000
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)
    assert data.get("status") in ("SCHEDULED", "ACTIVE", "EXPIRED")
    assert isinstance(data.get("version"), int)


def assert_retail_price_record(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("retailer_id"), str)
    assert isinstance(data.get("product_id"), str)
    assert isinstance(data.get("shelf_price_cents"), int)
    assert isinstance(data.get("effective_start"), str)
    assert data.get("status") in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data.get("version"), int)


def assert_delivery_window(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("route_code"), str)
    assert isinstance(data.get("window_start"), str)
    assert isinstance(data.get("window_end"), str)
    assert isinstance(data.get("turnaround_buffer_minutes"), int)
    assert isinstance(data.get("version"), int)


def assert_fuel_surcharge_rate(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("week_start_date"), str)
    assert isinstance(data.get("doe_index_usd"), (int, float))
    assert data.get("doe_index_usd") > 0
    assert isinstance(data.get("version"), int)


def assert_tax_stamp_supply(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("jurisdiction_code"), str)
    assert isinstance(data.get("stamp_rate_cents_per_pack"), int)
    assert isinstance(data.get("handling_fee_per_roll_cents"), int)
    assert isinstance(data.get("packs_per_roll"), int)
    assert isinstance(data.get("min_charge_cents"), int)
    assert data.get("status") == "ACTIVE"
    assert isinstance(data.get("version"), int)


def assert_delivery_manifest(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("route_code"), str)
    assert isinstance(data.get("delivery_date"), str)
    assert data.get("status") in ("SCHEDULED", "LOADING", "CLOSED", "COMPLETED")
    assert isinstance(data.get("capacity_lbs"), (int, float))
    assert isinstance(data.get("total_weight_lbs"), (int, float))
    assert isinstance(data.get("overweight_flag"), bool)
    assert isinstance(data.get("version"), int)


def assert_purchase_order(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("retailer_id"), str)
    assert isinstance(data.get("order_guide_id"), str)
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "ASSIGNED", "CLOSED", "DELIVERED", "INVOICED", "CANCELLED",
    )
    assert isinstance(data.get("has_tobacco"), bool)
    assert isinstance(data.get("merch_subtotal_cents"), int)
    assert isinstance(data.get("promo_allowance_cents"), int)
    assert isinstance(data.get("pick_fee_cents"), int)
    assert isinstance(data.get("min_drop_fee_cents"), int)
    assert isinstance(data.get("fuel_surcharge_cents"), int)
    assert isinstance(data.get("tax_stamp_cost_cents"), int)
    assert isinstance(data.get("provisional_total_cents"), int)
    assert isinstance(data.get("final_total_cents"), int)
    assert isinstance(data.get("weight_lbs"), (int, float))
    assert isinstance(data.get("version"), int)


def assert_order_line(data: dict):
    """OrderLine carries only id + created_at as common fields (PRD §2.5);
    version and updated_at MUST be absent."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "OrderLine must not carry version"
    assert "updated_at" not in data, "OrderLine must not carry updated_at"
    assert isinstance(data.get("order_id"), str)
    assert isinstance(data.get("product_id"), str)
    assert isinstance(data.get("cases_qty"), int)
    assert isinstance(data.get("split_units_qty"), int)


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("order_id"), str)
    assert isinstance(data.get("retailer_id"), str)
    assert isinstance(data.get("invoiced_total_cents"), int)
    assert isinstance(data.get("balance_cents"), int)
    assert isinstance(data.get("due_date"), str)
    assert data.get("status") in ("OPEN", "PARTIALLY_PAID", "PAID", "PAST_DUE")
    assert isinstance(data.get("version"), int)


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("invoice_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("amount_cents") > 0
    assert data.get("method") in ("CASH_ON_DELIVERY", "CHECK", "ACH")
    assert data.get("status") in ("APPLIED", "REVERSED")
    assert isinstance(data.get("version"), int)


def assert_credit_memo(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("invoice_id"), str)
    assert data.get("origin") in ("SHORT", "DAMAGE", "MANUAL")
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("amount_cents") > 0
    assert data.get("status") in ("DRAFT", "POSTED", "VOIDED")
    assert isinstance(data.get("version"), int)


def assert_delivery_exception(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("manifest_id"), str)
    assert isinstance(data.get("order_id"), str)
    assert isinstance(data.get("order_line_id"), str)
    assert data.get("exception_type") in ("SHORT", "DAMAGE")
    assert isinstance(data.get("cases_qty"), int)
    assert isinstance(data.get("split_units_qty"), int)
    assert isinstance(data.get("credit_amount_cents"), int)
    assert data.get("status") in ("RECORDED", "CREDITED")
    assert isinstance(data.get("version"), int)


def assert_new_item_request(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("retailer_id"), str)
    assert isinstance(data.get("product_id"), str)
    assert isinstance(data.get("proposed_shelf_price_cents"), int)
    assert data.get("status") in (
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "AUTHORIZED", "REJECTED",
    )
    assert isinstance(data.get("version"), int)


def assert_invoice_conservation(invoice: dict, applied_payments_cents: int, posted_memos_cents: int):
    """Invariant: invoiced_total_cents == balance_cents + applied payments + posted memos."""
    assert invoice["invoiced_total_cents"] == (
        invoice["balance_cents"] + applied_payments_cents + posted_memos_cents
    ), (
        f"Invoice conservation violated: total={invoice['invoiced_total_cents']} "
        f"balance={invoice['balance_cents']} payments={applied_payments_cents} memos={posted_memos_cents}"
    )
