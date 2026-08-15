"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer_cents(value) -> bool:
    """PRD section 2.7: all line-level amounts and stored totals are
    integer cents."""
    return _is_number(value) and float(value).is_integer()


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert _is_integer_cents(data["credit_limit_cents"]), \
        "credit_limit_cents must be integer cents"
    assert data["credit_limit_cents"] > 0
    for field in ("invoiced_balance_cents", "committed_balance_cents",
                  "credit_used_cents"):
        assert _is_integer_cents(data[field]), f"{field} must be integer cents"
    assert data["credit_used_cents"] == (
        data["invoiced_balance_cents"] + data["committed_balance_cents"]
    ), "credit_used_cents must equal invoiced + committed (PRD section 2.6)"


def assert_catalog_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["manufacturer_name"], str)
    assert data["sell_uom"] in ("EA", "FOOT")
    assert _is_number(data["list_price_cents"])
    if data["sell_uom"] == "FOOT":
        for field in ("reel_length_ft", "min_cut_ft", "cut_charge_cents"):
            assert isinstance(data.get(field), int) and data[field] > 0, (
                f"{field} must be a positive integer for FOOT items, "
                f"got {data.get(field)!r}")
    else:
        # EA: reel fields are either omitted or null in the representation.
        for field in ("reel_length_ft", "min_cut_ft", "cut_charge_cents"):
            assert data.get(field) in (None,), (
                f"{field} must be absent/null for EA items, "
                f"got {data.get(field)!r}")
    assert _is_number(data["stock_on_hand"]) and data["stock_on_hand"] >= 0
    assert _is_number(data["stock_allocated"]) and data["stock_allocated"] >= 0


def assert_job_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["contractor_id"])
    assert isinstance(data["job_name"], str) and len(data["job_name"]) > 0
    assert isinstance(data["jobsite_address"], str)
    assert data["pricing_mode"] in ("FIRM_PRICE", "ESCALATION")
    assert data.get("escalation_cap_pct") is None or \
        _is_number(data["escalation_cap_pct"])
    assert isinstance(data["lien_waiver_required"], bool)
    assert data.get("lien_waiver_expires_on") is None or \
        isinstance(data["lien_waiver_expires_on"], str)
    assert data["status"] in ("OPEN", "CREDIT_HOLD", "CLOSED")


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_account_id"])
    assert isinstance(data["valid_until"], str)
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "AWARDED", "EXPIRED")
    assert data.get("award_month") is None or isinstance(data["award_month"], str)
    assert data.get("award_index_value") is None or \
        _is_number(data["award_index_value"])


def assert_quote_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["catalog_item_id"])
    assert _is_number(data["qty"]) and data["qty"] > 0
    assert _is_number(data["unit_price_cents"])


def assert_substitution_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["quote_line_id"])
    assert is_valid_uuid(data["proposed_item_id"])
    assert isinstance(data["reason"], str)
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED")


def assert_release(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["job_account_id"])
    assert is_valid_uuid(data["quote_id"])
    assert data["status"] in (
        "REQUESTED", "CREDIT_APPROVED", "PARTIALLY_ALLOCATED", "ALLOCATED",
        "SCHEDULED", "DELIVERED", "INVOICED", "CANCELLED")
    assert _is_integer_cents(data["estimated_total_cents"]), \
        "estimated_total_cents must be integer cents"
    assert data.get("billed_total_cents") is None or \
        _is_integer_cents(data["billed_total_cents"])
    assert data.get("truck_id") is None or isinstance(data["truck_id"], str)
    assert data.get("delivery_date") is None or \
        isinstance(data["delivery_date"], str)
    assert data.get("window_start_hour") is None or \
        isinstance(data["window_start_hour"], int)
    assert data.get("window_end_hour") is None or \
        isinstance(data["window_end_hour"], int)
    assert data.get("invoiced_on") is None or isinstance(data["invoiced_on"], str)


def assert_release_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["release_id"])
    assert is_valid_uuid(data["catalog_item_id"])
    assert _is_number(data["qty_requested"]) and data["qty_requested"] > 0
    assert _is_number(data["qty_allocated"]) and data["qty_allocated"] >= 0
    assert _is_number(data["qty_shipped"]) and data["qty_shipped"] >= 0
    assert data.get("billed_amount_cents") is None or \
        _is_integer_cents(data["billed_amount_cents"])
    assert data["status"] in ("OPEN", "ALLOCATED", "SHIPPED", "INVOICED",
                              "CANCELLED")


def assert_backorder_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["release_line_id"])
    assert is_valid_uuid(data["catalog_item_id"])
    assert _is_number(data["qty_open"]) and data["qty_open"] >= 0
    assert data["status"] in ("OPEN", "FILLED", "CANCELLED")


def assert_rebate_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["manufacturer_name"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["tiers"], list) and len(data["tiers"]) > 0
    for tier in data["tiers"]:
        assert _is_integer_cents(tier["threshold_cents"])
        assert _is_number(tier["rebate_pct"])


def assert_rebate_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["rebate_program_id"])
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert _is_integer_cents(data["provisional_amount_cents"])
    assert data.get("qualifying_base_cents") is None or \
        _is_integer_cents(data["qualifying_base_cents"])
    assert data.get("tier_pct_applied") is None or \
        _is_number(data["tier_pct_applied"])
    assert data.get("final_amount_cents") is None or \
        _is_integer_cents(data["final_amount_cents"])


def assert_stock_conserved(item: dict, total_received):
    """Stock is conserved: on_hand + allocated always equals total received."""
    assert item["stock_on_hand"] + item["stock_allocated"] == total_received, (
        f"stock not conserved: on_hand {item['stock_on_hand']} + allocated "
        f"{item['stock_allocated']} != received {total_received}")
