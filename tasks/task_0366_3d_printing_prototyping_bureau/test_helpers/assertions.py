"""Entity assertions and domain invariant checkers.

Generic structural validators (UUID, ISO8601) come from the framework. These
per-entity assertions check field presence/types and the conservation
invariants stated in the PRD (§2.4, §2.6, §2.8).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version on every mutable entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1 (PRD §2.4)"


def assert_bureau(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cooldown_buffer_min"], int)
    assert isinstance(data["shift_capacity_minutes"], int)
    assert is_iso8601_timestamp(data["clock_utc"]), "clock_utc must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["display_name"], str)
    for f in ("lifetime_deposits_cents", "wallet_balance_cents",
              "escrow_held_cents", "captured_revenue_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert_wallet_conservation(data)


def assert_wallet_conservation(data: dict):
    """lifetime_deposits_cents == wallet + escrow_held + captured_revenue (PRD §2.8)."""
    total = (data["wallet_balance_cents"] + data["escrow_held_cents"]
             + data["captured_revenue_cents"])
    assert data["lifetime_deposits_cents"] == total, (
        f"wallet conservation broken: lifetime {data['lifetime_deposits_cents']} != "
        f"wallet {data['wallet_balance_cents']} + escrow {data['escrow_held_cents']} + "
        f"captured {data['captured_revenue_cents']}"
    )


def assert_material(data: dict):
    _assert_common(data)
    assert data["process"] in ("SLA", "FDM", "SLS")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_machine(data: dict):
    _assert_common(data)
    assert data["process"] in ("SLA", "FDM", "SLS")
    assert data["status"] in ("ONLINE", "MAINTENANCE")
    for f in ("scheduled_minutes", "active_minutes", "utilization_pct",
              "active_utilization_pct"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_spool(data: dict):
    _assert_common(data)
    assert data["status"] in ("LOADED", "DEPLETED")
    for f in ("grams_total", "grams_committed", "grams_consumed", "grams_remaining"):
        assert isinstance(data[f], int), f"{f} must be int grams"
    assert_spool_conservation(data)


def assert_spool_conservation(data: dict):
    """grams_remaining + grams_committed + grams_consumed == grams_total (PRD §2.6)."""
    total = data["grams_committed"] + data["grams_consumed"] + data["grams_remaining"]
    assert data["grams_total"] == total, (
        f"spool conservation broken: total {data['grams_total']} != "
        f"committed {data['grams_committed']} + consumed {data['grams_consumed']} + "
        f"remaining {data['grams_remaining']}"
    )


def assert_print_file(data: dict):
    _assert_common(data)
    assert data["status"] in ("UPLOADED", "PRINTABLE", "FLAGGED", "REJECTED")
    assert isinstance(data["is_manifold"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in (
        "DRAFT", "QUOTED", "CONFIRMED", "IN_PRODUCTION",
        "POST_PROCESSING", "READY", "SHIPPED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "ESCROWED", "CAPTURED", "REFUNDED")
    for f in ("parts_subtotal_cents", "finishing_subtotal_cents",
              "rush_surcharge_cents", "grand_total_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "VOID")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    for f in ("print_minutes", "per_part_cents", "line_total_cents",
              "finishing_total_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_finishing_task(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SCHEDULED", "DONE", "SKIPPED")
    assert data["kind"] in (
        "SUPPORT_REMOVAL", "SANDING", "DYE_BLACK", "UV_CURE", "POLISH")


def assert_print_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "PRINTING", "DONE", "FAILED", "CANCELLED")
    assert isinstance(data["run_grams"], int)


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("CREATED", "DISPATCHED")
    assert data["carrier"] in ("UPS", "FEDEX", "DHL")
