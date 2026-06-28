"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full-common-field entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["home_zone_code"] in ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7", "Z8", "Z9"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_fleet_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert 0 <= data["labor_discount_pct"] <= 0.40
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_mechanic(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["zone_code"] in ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7", "Z8", "Z9"]
    assert data["skill_tier"] in ["TIER1", "TIER2", "TIER3"]
    assert isinstance(data["labor_rate_cents_per_hour"], int) and data["labor_rate_cents_per_hour"] > 0
    assert data["status"] in ["AVAILABLE", "OFF_DUTY"]


def assert_service_request(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["vehicle_vin"], str)
    assert data["severity"] in ["ROUTINE", "URGENT", "EMERGENCY"]
    assert data["status"] in [
        "INTAKE", "QUOTED", "APPROVED", "DISPATCHED", "IN_PROGRESS",
        "AWAITING_ADDON_APPROVAL", "COMPLETED", "CANCELLED",
    ]
    if data.get("routing_mode") is not None:
        assert data["routing_mode"] in ["ON_SITE", "TOW_TO_SHOP"]


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["service_request_id"], str)
    assert data["estimated_labor_hours"] > 0
    assert data["estimated_parts_cents"] >= 0
    assert data["tow_fee_cents"] >= 0
    assert data["labor_rate_cents_per_hour"] > 0
    assert data["status"] in [
        "DRAFT", "SENT", "REVISION_REQUESTED", "APPROVED", "REJECTED", "SUPERSEDED",
    ]


def assert_job_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["service_request_id"], str)
    assert isinstance(data["mechanic_id"], str)
    assert data["routing_mode"] in ["ON_SITE", "TOW_TO_SHOP"]
    assert data["visit_status"] in [
        "SCHEDULED", "EN_ROUTE", "ON_SITE_WORKING", "AT_SHOP", "FINISHED", "ABORTED",
    ]


def assert_part_line(data: dict):
    _assert_common(data)
    assert isinstance(data["service_request_id"], str)
    assert isinstance(data["catalog_part_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["is_addon"], bool)
    assert data["status"] in ["SOURCED", "INSTALLED", "VOIDED"]


def assert_catalog_part(data: dict):
    """CatalogPart is immutable: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["wholesale_cost_cents"], int) and data["wholesale_cost_cents"] > 0


def assert_inspection_finding(data: dict):
    _assert_common(data)
    assert isinstance(data["service_request_id"], str)
    assert isinstance(data["job_visit_id"], str)
    assert isinstance(data["description"], str)
    assert data["status"] in ["PROPOSED", "APPROVED", "DECLINED"]


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["service_request_id"], str)
    assert isinstance(data["total_due_cents"], int)
    assert data["method"] in ["CARD", "FLEET_CREDIT"]
    assert data["status"] in ["INVOICED", "SETTLED", "REFUNDED"]


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["service_request_id"], str)
    assert isinstance(data["reason_text"], str)
    assert data["status"] in ["UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED"]


def assert_fleet_ledger_invariant(fleet_account: dict, invoiced_payments: list):
    """Ledger invariant (PRD §2.9): outstanding_balance_cents equals the sum of
    total_due_cents over the fleet's payments still in INVOICED status."""
    expected = sum(p["total_due_cents"] for p in invoiced_payments
                   if p.get("status") == "INVOICED")
    assert fleet_account["outstanding_balance_cents"] == expected, (
        f"ledger invariant violated: outstanding="
        f"{fleet_account['outstanding_balance_cents']} expected={expected}"
    )
