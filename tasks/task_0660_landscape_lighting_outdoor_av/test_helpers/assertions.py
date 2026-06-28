"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields present on every mutable entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["wallet_credit_cents"], int)


def assert_project(data: dict):
    _assert_common(data)
    assert data["design_status"] in ("DRAFT", "ZONED", "DESIGN_LOCKED")
    assert data["commercial_status"] in (
        "PRE_QUOTE", "QUOTED", "ACCEPTED", "INSTALLED", "CLOSED",
    )
    assert isinstance(data["fixture_count"], int)
    assert isinstance(data["total_committed_load_va"], int)


def assert_transformer(data: dict):
    _assert_common(data)
    assert isinstance(data["rated_capacity_va"], int)
    assert isinstance(data["usable_capacity_va"], int)
    assert isinstance(data["committed_load_va"], int)
    assert data["status"] in ("STAGED", "ENERGIZED", "DECOMMISSIONED")


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_load_va"], int)
    assert isinstance(data["transformer_id"], str)


def assert_fixture(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "INSTALLED", "FAILED", "REMOVED")
    assert data["category"] in ("PATH", "SPOT", "WELL", "STEP", "AUDIO", "SECURITY")
    assert isinstance(data["wattage_w"], int)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["warranty_months"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "REJECTED", "EXPIRED")
    for f in ("subtotal_cents", "discount_cents", "tax_cents", "grand_total_cents", "revision_round"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_quote_line(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_install_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "ENERGIZED", "CANCELLED")
    assert data["wiring_status"] in ("PENDING", "WIRED")
    assert data["fixtures_status"] in ("PENDING", "MOUNTED")


def assert_schedule_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "DISABLED")
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)


def assert_service_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "ADJUSTING", "CANCELLED")
    assert data["tier"] in ("BASIC", "PREMIUM")
    assert isinstance(data["annual_fee_cents"], int)
    assert isinstance(data["season_cycle_count"], int)


def assert_service_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "ROUTED", "COMPLETED", "MISSED")


def assert_crew_route(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "DISPATCHED", "COMPLETED")
    assert isinstance(data["visit_count"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")
    assert isinstance(data["credit_cents"], int)


def assert_add_on(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ACTIVE", "REMOVED")
    assert data["kind"] in ("AUDIO", "SECURITY")
    assert isinstance(data["power_draw_va"], int)
