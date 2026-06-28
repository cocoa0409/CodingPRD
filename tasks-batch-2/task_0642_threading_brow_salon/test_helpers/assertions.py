"""Entity assertions and domain invariant checkers for the salon API."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(s):
    """Parse an ISO 8601 UTC instant (trailing 'Z', optional fractional digits)."""
    assert isinstance(s, str) and s, f"expected an ISO 8601 string, got {s!r}"
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def same_instant(actual, expected) -> bool:
    """True when two ISO 8601 strings denote the same UTC instant.

    PRD §2.4 renders instants with three fractional digits, so a value the server
    computes (e.g. a chair's `sanitation_ready_at` = clock + sanitation_minutes)
    is returned as e.g. '2026-02-01T10:05:00.000Z'. The PRD fixes the *instant*
    (§3.9: "the visit's end instant plus the chair's sanitation_minutes") but not a
    fractional-digit-free rendering, so equality must be compared on the instant,
    not the literal string.
    """
    return _parse_instant(actual) == _parse_instant(expected)


def assert_salon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "salon id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("OPEN", "CLOSED"), f"bad salon status {data['status']}"
    assert data["license_status"] in ("ACTIVE", "LAPSED")
    assert isinstance(data["loyalty_earn_rate_bps"], int) and data["loyalty_earn_rate_bps"] >= 0
    assert isinstance(data["active_occupancy_count"], int) and data["active_occupancy_count"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_technician(data: dict):
    assert is_valid_uuid(data.get("id", "")), "technician id must be a valid UUID"
    assert isinstance(data["salon_id"], str)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["certified_addon_codes"], list)
    assert data["status"] in ("AVAILABLE", "BUSY", "OFF_SHIFT")


def assert_chair(data: dict):
    assert is_valid_uuid(data.get("id", "")), "chair id must be a valid UUID"
    assert isinstance(data["salon_id"], str)
    assert isinstance(data["sanitation_minutes"], int) and data["sanitation_minutes"] >= 0
    assert data["status"] in ("OPEN", "OCCUPIED", "SANITIZING", "OUT_OF_SERVICE")


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be a valid UUID"
    assert isinstance(data["salon_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["loyalty_balance"], int) and data["loyalty_balance"] >= 0
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "BANNED")


def assert_service_menu_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "service item id must be a valid UUID"
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["est_minutes"], int) and data["est_minutes"] > 0
    assert isinstance(data["package_eligible"], bool)
    assert data["status"] in ("LISTED", "RETIRED")


def assert_add_on(data: dict):
    assert is_valid_uuid(data.get("id", "")), "add-on id must be a valid UUID"
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["requires_certification"], bool)
    assert data["status"] in ("LISTED", "RETIRED")


def assert_retail_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "retail product id must be a valid UUID"
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0


def assert_membership_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "package id must be a valid UUID"
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["discount_bps"], int) and data["discount_bps"] >= 0
    assert isinstance(data["total_credits"], int) and data["total_credits"] >= 0
    assert isinstance(data["credits_remaining"], int) and data["credits_remaining"] >= 0
    assert data["status"] in ("PENDING", "ACTIVE", "DEPLETED", "CANCELLED")


def assert_queue_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ticket id must be a valid UUID"
    assert isinstance(data["position"], int) and data["position"] >= 0
    assert isinstance(data["called_count"], int) and data["called_count"] >= 0
    assert data["status"] in ("WAITING", "CALLED", "SEATED", "NO_SHOW", "CANCELLED")


def assert_service_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "visit id must be a valid UUID"
    assert data["service_status"] in ("IN_SERVICE", "COMPLETED", "VOIDED")
    assert data["payment_status"] in ("UNPAID", "SETTLED", "REFUNDED")
    assert isinstance(data["estimate_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)
    assert isinstance(data["loyalty_earned"], int)
    assert isinstance(data["used_package_credit"], bool)


def assert_visit_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "line id must be a valid UUID"
    assert data["line_type"] in ("ADDON", "RETAIL")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_loyalty_ledger_entry(data: dict):
    """LoyaltyLedgerEntry is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("EARN", "REDEEM", "REVERSAL", "ADJUSTMENT")
    assert isinstance(data["points"], int)
    assert "version" not in data, "append-only ledger entry must not carry version"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
