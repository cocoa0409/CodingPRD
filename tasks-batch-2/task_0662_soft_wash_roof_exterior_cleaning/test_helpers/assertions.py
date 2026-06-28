"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Append-only entities (QuoteLineItem,
PhotoSet) are NOT asserted to carry updated_at/version — PRD §2.4 states they carry only
id and created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, "outstanding_balance_cents floored at 0"
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ladder_cert_max_stories"], int)
    assert data["insurance_status"] in ("ACTIVE", "EXPIRED")
    assert isinstance(data["scheduled_minutes"], int)
    assert data["scheduled_minutes"] >= 0


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["travel_buffer_minutes"], int)


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["route_id"], str)
    assert data["stories"] >= 1, "stories must be >= 1"
    assert data["roof_sqft"] >= 0
    assert data["siding_sqft"] >= 0
    assert data["concrete_sqft"] >= 0


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert data["soiling_level"] in ("LIGHT", "MODERATE", "HEAVY")
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "DECLINED", "SUPERSEDED")


def assert_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "line item id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "QuoteLineItem is append-only: no version field"
    assert "updated_at" not in data, "QuoteLineItem is append-only: no updated_at field"
    assert data["surface_type"] in ("ROOF", "SIDING", "CONCRETE")
    assert data["service_type"] in ("ROOF_SOFT_WASH", "HOUSE_WASH", "CONCRETE_CLEAN")
    assert data["measured_sqft"] >= 1
    assert isinstance(data["chemical_dose_oz"], (int, float))
    assert isinstance(data["line_total_cents"], int)


def assert_photo_set(data: dict):
    assert is_valid_uuid(data.get("id", "")), "photo set id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PhotoSet is append-only: no version field"
    assert "updated_at" not in data, "PhotoSet is append-only: no updated_at field"
    assert data["phase"] in ("BEFORE", "AFTER")


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert data["cadence_days"] >= 1
    assert isinstance(data["visits_generated_count"], int)


def assert_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "RECLEAN_REQUESTED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "BILLED", "VOIDED")


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["technician_id"], str)
    assert data["status"] in ("RESERVED", "CONFIRMED", "RELEASED")
    assert isinstance(data["duration_minutes"], int)


def assert_weather_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert data["condition"] in ("CLEAR", "BLOCKED")
    assert data["wind_mph"] >= 0


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["visit_id"], str)
    assert data["status"] in ("ISSUED", "PAID", "DISPUTED", "VOIDED")
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0
    assert isinstance(data["loyalty_discount_cents"], int)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["visit_id"], str)
    assert data["status"] in ("OPEN", "APPROVED", "REJECTED")
