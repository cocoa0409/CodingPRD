"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Each assert_{entity} verifies the structural contract: a UUID id, an ISO 8601
created_at/updated_at, an integer version >= 1, and the entity-specific fields
with their declared types and enum domains.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every entity (PRD §2.4): id, created_at,
    updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_service_area(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["disposal_fee_cents_per_ton"], int)
    assert data["disposal_fee_cents_per_ton"] >= 0
    assert isinstance(data["requires_permit_authority"], bool)
    assert data["heritage_surcharge_pct"] >= 0


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["service_area_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["certified_utility_clearance"], bool)
    assert data["status"] in ("AVAILABLE", "RETIRED")


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["service_area_id"], str)
    assert data["kind"] in ("CRANE", "CHIPPER", "STUMP_GRINDER")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["mobilization_buffer_minutes"], int)
    assert data["mobilization_buffer_minutes"] >= 0
    assert data["status"] in ("AVAILABLE", "RETIRED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["service_area_id"], str)
    assert isinstance(data["client_user_id"], str)
    assert isinstance(data["site_address"], str)
    assert data["pricing_mode"] in ("PER_JOB", "HOURLY")
    assert isinstance(data["is_emergency"], bool)
    assert data["hazard_level"] in ("LOW", "MODERATE", "SEVERE")
    assert isinstance(data["requires_permit"], bool)
    assert data["accepted_estimate_id"] is None or isinstance(data["accepted_estimate_id"], str)
    assert isinstance(data["labor_cost_accrued_cents"], int)
    assert isinstance(data["disposal_cost_accrued_cents"], int)
    assert isinstance(data["final_invoice_cents"], int)
    assert data["status"] in (
        "DRAFT", "ASSESSED", "QUOTED", "SCHEDULED", "COMPLETED", "CANCELLED",
    )


def assert_work_order_invariants(data: dict):
    """Ledgers are non-negative integer cents (PRD §2.7); invoice never
    negative (PRD §3.10)."""
    assert data["labor_cost_accrued_cents"] >= 0
    assert data["disposal_cost_accrued_cents"] >= 0
    assert data["final_invoice_cents"] >= 0


def assert_tree_asset(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["species"], str) and data["species"]
    assert data["dbh_inches"] > 0
    assert isinstance(data["is_protected"], bool)
    assert isinstance(data["is_heritage"], bool)
    assert isinstance(data["near_utility_line"], bool)
    assert data["lean_degrees"] >= 0
    assert isinstance(data["has_visible_decay"], bool)
    assert data["hazard_tier"] in ("LOW", "MODERATE", "SEVERE")


def assert_estimate(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert data["pricing_mode"] in ("PER_JOB", "HOURLY")
    assert isinstance(data["line_items_subtotal_cents"], int)
    assert isinstance(data["hazard_surcharge_cents"], int)
    assert isinstance(data["heritage_surcharge_cents"], int)
    assert isinstance(data["utility_surcharge_cents"], int)
    assert isinstance(data["emergency_multiplier_applied"], bool)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED", "DECLINED", "SUPERSEDED")


def assert_line_item(data: dict):
    _assert_common(data)
    assert isinstance(data["estimate_id"], str)
    assert data["service_type"] in (
        "REMOVAL", "STUMP_GRINDING", "HAUL_OFF", "UTILITY_CLEARANCE",
    )
    assert data["quantity"] > 0
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["extended_cost_cents"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["authority_ref"], str)
    assert isinstance(data["covers_heritage"], bool)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED", "DENIED",
    )


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert data["resource_kind"] in ("CREW", "EQUIPMENT")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("RESERVED", "FINALIZED", "RELEASED")


def assert_disposal_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert data["debris_tons"] > 0
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("RECORDED", "FINALIZED", "VOIDED")
