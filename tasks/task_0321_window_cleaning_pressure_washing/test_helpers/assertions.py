"""Entity assertions and domain invariant checkers for the Window Cleaning PRD.

Per-entity assert_* helpers validate response structure against the PRD contract
using the framework's generic format validators. Invariant checkers encode the
PRD's derived-field reconciliation rules (account ledger §2.7, route booked
minutes §2.8).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_REGIONS = ["NORTH", "SOUTH", "EAST", "WEST"]


def _assert_common(data: dict):
    """Common system fields for entities carrying id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only records carry only id + created_at — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert data["region_code"] in _REGIONS
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert data["deposit_held_cents"] >= 0, "deposit_held_cents is a sum of HELD deposits, never negative"
    assert data["status"] == "ACTIVE", "accounts are always ACTIVE (PRD §3.1)"


def assert_property(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["address_line"], str)
    assert isinstance(data["pane_count"], int) and data["pane_count"] >= 0
    assert isinstance(data["glass_sqft"], (int, float)) and data["glass_sqft"] >= 0
    assert isinstance(data["stories"], int) and data["stories"] >= 1
    assert isinstance(data["soft_wash_sqft"], (int, float)) and data["soft_wash_sqft"] >= 0


def assert_quote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["property_id"])
    assert data["pricing_basis"] in ("PANE_COUNT", "SQ_FT")
    assert isinstance(data["addon_codes"], list)
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["addon_total_cents"], int)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["required_deposit_cents"], int)
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED", "CONVERTED")


def assert_service_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["property_id"])
    assert is_valid_uuid(data["quote_id"])
    assert data["schedule_kind"] in ("ONE_TIME", "RECURRING")
    assert isinstance(data["per_visit_price_cents"], int)
    assert isinstance(data["required_deposit_cents"], int)
    assert isinstance(data["visits_generated_count"], int)
    assert data["status"] in ("PENDING_DEPOSIT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED")


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["crew_name"], str)
    assert data["region_code"] in _REGIONS
    assert isinstance(data["skill_codes"], list)
    assert isinstance(data["daily_capacity_minutes"], int) and data["daily_capacity_minutes"] > 0
    assert data["status"] in ("AVAILABLE", "OFFLINE")


def assert_route(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["crew_id"])
    assert data["region_code"] in _REGIONS
    assert isinstance(data["service_date"], str)
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert data["status"] in ("PLANNING", "DISPATCHED", "CLOSED")


def assert_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["planned_date"], str)
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert isinstance(data["duration_minutes"], int)
    assert data["duration_minutes"] == data["window_end_min"] - data["window_start_min"]
    assert isinstance(data["requires_soft_wash"], bool)
    assert isinstance(data["requires_high_rise"], bool)
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert data["schedule_status"] in (
        "UNSCHEDULED", "SCHEDULED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID", "WAIVED")


def assert_visit_add_on(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["visit_id"])
    assert data["addon_code"] in ("GUTTER", "SCREEN", "SOFT_WASH")
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0


def assert_visit_photo(data: dict):
    """VisitPhoto is append-only (PRD §2.4): id + created_at only, no version field."""
    _assert_append_only(data)
    assert is_valid_uuid(data["visit_id"])
    assert data["phase"] in ("BEFORE", "AFTER")
    assert isinstance(data["image_uri"], str)
    assert "version" not in data, "append-only VisitPhoto must not carry a version field"
    assert "updated_at" not in data, "append-only VisitPhoto must not carry an updated_at field"


def assert_reclean_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["visit_id"])
    assert isinstance(data["reason"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "RESOLVED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["visit_id"])
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["deposit_applied_cents"], int)
    assert isinstance(data["net_due_cents"], int)
    assert data["net_due_cents"] >= 0, "net_due_cents is never negative by construction (PRD §3.7)"
    assert data["status"] in ("ISSUED", "PAID", "VOID")


def assert_deposit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("HELD", "APPLIED", "REFUNDED")


def assert_weather_advisory(data: dict):
    _assert_common(data)
    assert data["region_code"] in _REGIONS
    assert isinstance(data["advisory_date"], str)
    assert data["severity"] in ("ADVISORY", "SUSPEND")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only (PRD §2.4): id + created_at only, no version field."""
    _assert_append_only(data)
    assert is_valid_uuid(data["account_id"])
    assert data["source_type"] in ("INVOICE", "PAYMENT", "DEPOSIT", "RECLEAN_CREDIT")
    assert isinstance(data["signed_amount_cents"], int)
    assert "version" not in data, "append-only LedgerEntry must not carry a version field"
