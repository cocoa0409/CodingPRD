"""Entity assertions and domain invariant checkers for the Water Softener Service API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields for the ten primary resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    """Customer carries only id + created_at (no version / updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Customer must not carry a version field"
    assert "updated_at" not in data, "Customer must not carry an updated_at field"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]


def assert_field_tech(data: dict):
    """FieldTech carries only id + created_at (no version / updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "FieldTech must not carry a version field"
    assert "updated_at" not in data, "FieldTech must not carry an updated_at field"


def assert_service_account(data: dict):
    _assert_common(data)
    assert data["property_type"] in ("MUNICIPAL_WHOLE_HOUSE", "WELL_WHOLE_HOUSE", "POINT_OF_USE")
    assert isinstance(data["service_zone"], str) and data["service_zone"]
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents is floored at 0"
    assert data["standing"] in ("GOOD", "DELINQUENT")


def assert_water_test(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "RECOMMENDED", "ACCEPTED", "SUPERSEDED")
    assert data["hardness_gpg"] >= 0
    assert data["iron_ppm"] >= 0
    assert data["tds_ppm"] >= 0
    assert data["household_size"] >= 1


def assert_softener_system(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in ("ORDERED", "INSTALLED", "ACTIVE", "DECOMMISSIONED")
    assert data["regen_health"] in ("NOMINAL", "DUE", "OVERDUE")
    assert data["acquisition_mode"] in ("PURCHASE", "RENTAL")
    assert data["grain_capacity"] >= 16000
    assert data["gallons_since_regen"] >= 0
    assert 0 <= data["salt_level_pct"] <= 100


def assert_rental_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["monthly_rate_cents"] >= 0
    assert data["term_months"] >= 1
    assert data["months_billed"] >= 0
    assert data["early_termination_fee_cents"] >= 0


def assert_route(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED")
    assert data["capacity_stops"] >= 1
    assert 0 <= data["stop_count"] <= data["capacity_stops"], "stop_count must never exceed capacity_stops"


def assert_route_stop(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "SKIPPED")
    assert data["stop_type"] in ("SALT_DELIVERY", "FILTER_SWAP", "REGEN_SERVICE", "INSPECTION")


def assert_cartridge_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in ("ON_TRACK", "DUE_SOON", "OVERDUE")
    assert data["cartridge_type"] in ("RO_MEMBRANE", "SEDIMENT_FILTER", "CARBON_FILTER", "UV_LAMP")
    assert data["interval_days"] >= 1
    assert data["replacements_logged"] >= 0


def assert_service_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("LOGGED", "CONFIRMED", "VOIDED")
    assert data["visit_type"] in ("REGEN", "CARTRIDGE_REPLACE", "SALT_REFILL", "REPAIR", "INSPECTION")
    assert data["billable_cents"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "TRIAGED", "REPAIR", "REPLACE", "CLOSED", "DENIED")
    assert data["defect_class"] in ("VALVE_FAILURE", "RESIN_FOULING", "CONTROL_BOARD", "LEAK", "UV_BALLAST")
    assert data["settlement_cents"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID", "VOID", "PAST_DUE")
    assert data["invoice_kind"] in ("RENTAL_CYCLE", "SERVICE_REPAIR", "TERMINATION", "PRORATION")
    assert data["amount_cents"] >= 0
