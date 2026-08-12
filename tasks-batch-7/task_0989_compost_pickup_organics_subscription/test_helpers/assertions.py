"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3).

Only fields the PRD guarantees are asserted here. ServicePlan (configuration)
and CompostCreditEntry (append-only ledger event) carry only id + created_at —
no updated_at, no version (PRD §2.5).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_light_fields(data: dict):
    """For ServicePlan and CompostCreditEntry: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "light resources carry no updated_at (PRD §2.5)"
    assert "version" not in data, "light resources carry no version (PRD §2.5)"


def assert_service_plan(data: dict):
    _assert_light_fields(data)
    assert data["subscriber_type"] in ("RESIDENTIAL", "COMMERCIAL")
    assert data["bin_type"] in ("BIN_35L", "BIN_70L", "BIN_240L", "BIN_960L")
    assert isinstance(data["included_bins"], int)
    assert isinstance(data["weekly_price_cents"], int)
    assert isinstance(data["metered_base_cents"], int)
    assert isinstance(data["per_kg_rate_cents"], int)
    assert isinstance(data["credit_rate_cents_per_kg"], int)
    assert isinstance(data["skip_allowance_per_quarter"], int)


def assert_subscriber(data: dict):
    _assert_common_fields(data)
    assert data["subscriber_type"] in ("RESIDENTIAL", "COMMERCIAL")
    assert data["account_standing"] in ("GOOD_STANDING", "DELINQUENT")
    assert isinstance(data["credit_balance_cents"], int)


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert data["service_status"] in ("ACTIVE", "PAUSED", "SUSPENDED", "CANCELLED")
    assert isinstance(data["strike_count"], int)
    assert isinstance(data["skips_used_this_quarter"], int)
    assert isinstance(data["pause_windows"], list)


def assert_route(data: dict):
    _assert_common_fields(data)
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["max_stops"], int)
    assert isinstance(data["active_subscriptions_count"], int)


def assert_bin(data: dict):
    _assert_common_fields(data)
    assert data["bin_type"] in ("BIN_35L", "BIN_70L", "BIN_240L", "BIN_960L")
    assert data["status"] in ("IN_DEPOT", "AT_CUSTOMER")
    assert data["condition"] in ("CLEAN", "NEEDS_WASH")


def assert_pickup(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED",
        "COMPLETED",
        "SKIPPED",
        "MISSED",
        "REJECTED_CONTAMINATION",
        "CANCELLED_SYSTEM",
        "VOIDED",
    )


def assert_contamination_tag(data: dict):
    _assert_common_fields(data)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["category"] in ("PLASTIC", "GLASS", "METAL", "LIQUIDS", "OTHER")
    assert data["status"] in ("TAGGED", "DISPUTED", "CONFIRMED", "WAIVED")


def assert_weigh_ticket(data: dict):
    _assert_common_fields(data)
    assert data["status"] == "POSTED"
    assert data["net_kg"] > 0, "net_kg must be greater than zero"


def assert_credit_entry(data: dict):
    _assert_light_fields(data)
    assert data["entry_type"] in (
        "EARNED_ESTIMATED",
        "EARNED_FINAL_ADJUSTMENT",
        "REDEMPTION_DEBIT",
        "INVOICE_APPLICATION_DEBIT",
        "MANUAL_ADJUSTMENT",
        "REVERSAL",
    )
    assert isinstance(data["amount_cents"], int)


def assert_redemption(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "FULFILLED", "CANCELLED")
    assert isinstance(data["bags"], int) and data["bags"] >= 1
    assert data["total_kg"] == data["bags"] * 10, "total_kg is bags x 10 (PRD §3.8)"
    assert data["total_cents"] == data["bags"] * 500, "total_cents is bags x 500 (PRD §3.8)"


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert line["line_type"] in (
            "WEEKLY_FLAT",
            "METERED_BASE",
            "OVERAGE_KG",
            "CONTAMINATION_SURCHARGE",
        )
        assert isinstance(line["amount_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] - data["credit_applied_cents"]


def assert_ledger_sum_matches_balance(entries: list, balance_cents: int):
    """PRD §2.6: credit_balance_cents is exactly the signed sum of the
    subscriber's CompostCreditEntry amount_cents values."""
    signed_sum = sum(e["amount_cents"] for e in entries)
    assert signed_sum == balance_cents, (
        f"ledger sum {signed_sum} != credit_balance_cents {balance_cents}"
    )
