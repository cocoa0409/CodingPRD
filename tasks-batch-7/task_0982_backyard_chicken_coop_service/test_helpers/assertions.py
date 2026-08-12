"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    assert isinstance(value, str), f"Expected ISO string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_same_instant(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 strings denote the same UTC instant.

    The PRD pins datetime VALUES (e.g. period end = start + 1 calendar month)
    but not their string serialization, so compare parsed instants.
    """
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_config_fields(data: dict):
    """Immutable config/subordinate resources carry only id + created_at (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "updated_at must be absent on this resource"
    assert "version" not in data, "version must be absent on this resource"


def assert_household(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["address"], str) and data["address"]
    assert data["zone_code"] in ("URBAN", "SUBURBAN", "RURAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["wallet_credit_cents"], int)


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data["used_cleanings"], int) and data["used_cleanings"] >= 0
    assert isinstance(data["used_health_checks"], int) and data["used_health_checks"] >= 0
    assert is_iso8601_timestamp(data["current_period_start"])
    assert is_iso8601_timestamp(data["current_period_end"])


def assert_coop_site(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["site_label"], str)
    assert isinstance(data["coop_capacity_hens"], int)
    assert data["predator_grade"] in ("NONE", "B", "A")
    assert data["status"] in ("PLANNED", "INSTALLED")


def assert_service_visit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["coop_site_id"])
    assert data["visit_type"] in (
        "COOP_CLEANING", "FLOCK_HEALTH_CHECK", "PREDATOR_PROOFING", "SETUP_INSTALL",
    )
    assert data["coverage"] in ("SUBSCRIPTION_COVERED", "BILLABLE")
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "RESCHEDULE_REQUESTED", "ON_SITE",
        "COMPLETED", "NO_SHOW", "CANCELLED",
    )
    assert isinstance(data["provisional_price_cents"], int)
    assert isinstance(data["reschedule_count"], int)


def assert_sitting_engagement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["coop_site_id"])
    assert data["status"] in ("REQUESTED", "QUOTED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert isinstance(data["cancellation_fee_cents"], int)


def assert_sitting_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["technician_id"], str) and data["technician_id"]
    assert data["zone_code"] in ("URBAN", "SUBURBAN", "RURAL")
    assert data["status"] in ("PLANNED", "PUBLISHED", "CANCELLED")
    assert isinstance(data["max_stops"], int)
    assert isinstance(data["committed_stops"], int)
    assert 0 <= data["committed_stops"] <= data["max_stops"]


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["engagement_id"])
    assert data["status"] in ("PENDING", "DONE", "SKIPPED", "REMOVED")
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1


def assert_supply_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert data["status"] in ("DRAFT", "PLACED", "FULFILLED")
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["product_sku"], str)
        assert isinstance(line["quantity"], int) and line["quantity"] > 0
        assert isinstance(line["unit_price_cents"], int)
        assert line["line_total_cents"] == line["unit_price_cents"] * line["quantity"]
    assert data["subtotal_cents"] == sum(l["line_total_cents"] for l in data["lines"])


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "VOID")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_invoice_line(data: dict):
    _assert_config_fields(data)
    assert is_valid_uuid(data["invoice_id"])
    assert data["source_type"] in (
        "VISIT", "SITTING", "ORDER", "SUBSCRIPTION_FEE", "CANCELLATION_FEE", "ADJUSTMENT",
    )
    assert isinstance(data["source_id"], str) and data["source_id"]
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int)


def assert_subscription_plan(data: dict):
    _assert_config_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["included_cleanings_per_period"], int)
    assert isinstance(data["included_health_checks_per_period"], int)


def assert_product(data: dict):
    _assert_config_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("FEED", "BEDDING", "EGG_SUPPLIES", "HEALTH")
    assert isinstance(data["unit_price_cents"], int)


def assert_seasonal_window(data: dict):
    _assert_config_fields(data)
    assert isinstance(data["window_code"], str) and data["window_code"]
    assert data["zone_code"] in ("URBAN", "SUBURBAN", "RURAL")


def assert_invoice_money_invariants(invoice: dict):
    """Invoice composition invariants (PRD §3.9): total = subtotal + tax;
    amount_due = total - credit_applied."""
    assert invoice["total_cents"] == invoice["subtotal_cents"] + invoice["tax_cents"]
    assert invoice["amount_due_cents"] == invoice["total_cents"] - invoice["credit_applied_cents"]
    assert invoice["credit_applied_cents"] >= 0


def assert_wallet_non_negative(household: dict):
    """Wallet ledger invariant (PRD §3.1): balance never goes below zero."""
    assert household["wallet_credit_cents"] >= 0
