"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_instant_equal(actual: str, expected: str):
    """Clock-stamped instants compare by value, not by string format.

    The PRD pins three fractional digits only for api_request_timestamp,
    created_at, and updated_at; domain fields stamped from the logical clock
    (ginned_at, storage_start_date, pledged_date, ...) are stored as a date at
    00:00:00Z, so equality is evaluated on the parsed instant.
    """
    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse(actual) == _parse(expected), f"{actual!r} != {expected!r} as instants"


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_grower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["membership_number"], str) and data["membership_number"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["patronage_rate"], (int, float))


def assert_grade_schedule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert isinstance(data["premium_discount_points"], int)
    assert isinstance(data["loan_rate_points"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_warehouse(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_bales"], int) and data["capacity_bales"] >= 0
    assert isinstance(data["stored_bale_count"], int) and data["stored_bale_count"] >= 0
    assert isinstance(data["dock_count"], int) and data["dock_count"] >= 0


def assert_gin_shift(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season"], str) and data["season"]
    assert isinstance(data["stand_label"], str) and data["stand_label"]
    assert data["status"] in ["OPEN", "CLOSED", "RECONCILED"]


def assert_module(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grower_id"], str) and data["grower_id"]
    assert isinstance(data["season"], str) and data["season"]
    assert isinstance(data["ticket_number"], str) and data["ticket_number"]
    assert isinstance(data["module_tag"], str) and data["module_tag"]
    assert isinstance(data["gross_weight_lbs"], int)
    assert isinstance(data["tare_weight_lbs"], int)
    assert isinstance(data["net_weight_lbs"], int)
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["foreign_matter_pct"], (int, float))
    assert data["status"] in [
        "RECEIVED", "CONDITIONING", "QUEUED", "GINNING", "GINNED", "REJECTED",
    ]
    assert isinstance(data["est_lint_lbs"], int)
    assert isinstance(data["est_seed_lbs"], int)
    assert isinstance(data["actual_lint_lbs"], int)


def assert_bale(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["module_id"], str) and data["module_id"]
    assert isinstance(data["bale_tag"], str) and data["bale_tag"]
    assert isinstance(data["net_weight_lbs"], int) and data["net_weight_lbs"] >= 1
    assert data["classing_status"] in ["UNCLASSED", "CLASSED"]
    assert data["custody_status"] in ["ON_GIN_FLOOR", "WAREHOUSED", "SHIPPED"]


def assert_classing_result(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bale_id"], str) and data["bale_id"]
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert isinstance(data["micronaire"], (int, float))
    assert isinstance(data["strength_gpt"], (int, float))
    assert isinstance(data["staple_32nds"], int)
    assert isinstance(data["classing_office"], str) and data["classing_office"]
    assert is_iso8601_timestamp(data["result_date"])
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]
    assert isinstance(data["quality_points"], int)
    assert isinstance(data["adjustment_cents"], int)


def assert_warehouse_receipt(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bale_id"], str) and data["bale_id"]
    assert isinstance(data["warehouse_id"], str) and data["warehouse_id"]
    assert isinstance(data["receipt_number"], str) and data["receipt_number"]
    assert is_iso8601_timestamp(data["storage_start_date"])
    assert data["status"] in [
        "ACTIVE", "PLEDGED", "RELEASED", "SHIPPED", "FORFEITED", "CANCELLED",
    ]


def assert_loan_pledge(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["warehouse_receipt_id"], str) and data["warehouse_receipt_id"]
    assert isinstance(data["loan_rate_points"], int)
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert is_iso8601_timestamp(data["pledged_date"])
    assert data["status"] in ["ACTIVE", "REPAID", "FORFEITED"]


def assert_seed_sale(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["gin_shift_id"], str) and data["gin_shift_id"]
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert isinstance(data["price_cents_per_lb"], int) and data["price_cents_per_lb"] >= 1
    assert isinstance(data["sold_lbs"], int)
    assert isinstance(data["net_pool_cents"], int)


def assert_shipping_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["warehouse_id"], str) and data["warehouse_id"]
    assert isinstance(data["grower_id"], str) and data["grower_id"]
    assert isinstance(data["bale_ids"], list) and len(data["bale_ids"]) >= 1
    assert isinstance(data["dock_number"], int) and data["dock_number"] >= 1
    assert is_iso8601_timestamp(data["load_start"])
    assert is_iso8601_timestamp(data["load_end"])
    assert data["status"] in ["DRAFT", "CONFIRMED", "SHIPPED", "CANCELLED"]


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grower_id"], str) and data["grower_id"]
    assert isinstance(data["season"], str) and data["season"]
    assert data["computation_variant"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in ["DRAFT", "FINAL", "PAID", "SUPERSEDED"]
    for line in ("lint_value_cents", "quality_adjustment_cents", "seed_credit_cents",
                 "ginning_charge_cents", "storage_charge_cents", "loan_net_cents",
                 "adjustment_net_cents", "patronage_cents", "net_payable_cents"):
        assert isinstance(data[line], int), f"{line} must be an integer"


def assert_ledger_entry(data: dict):
    """Append-only ledger entry: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries carry no updated_at"
    assert "version" not in data, "ledger entries carry no version"
    assert isinstance(data["grower_id"], str) and data["grower_id"]
    assert isinstance(data["season"], str) and data["season"]
    assert data["entry_type"] in [
        "GINNING_CHARGE", "SEED_CREDIT", "STORAGE_CHARGE", "LOAN_ADVANCE",
        "LOAN_REPAYMENT", "ADJUSTMENT", "PATRONAGE", "SETTLEMENT_PAYMENT",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["memo"], str)


def assert_balance_equals_ledger(grower: dict, entries: list):
    """credit_balance_cents is the plain sum of the grower's posted entries."""
    total = sum(e["amount_cents"] for e in entries)
    assert grower["credit_balance_cents"] == total, (
        f"credit_balance_cents {grower['credit_balance_cents']} != "
        f"SUM(amount_cents) {total}"
    )
