"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 0, "version must be non-negative"


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["badge_total"], int) and data["badge_total"] >= 0
    assert isinstance(data["badge_in_use"], int)
    assert isinstance(data["badge_available"], int)
    # Badge-inventory invariant (PRD 2.9).
    assert data["badge_total"] == data["badge_in_use"] + data["badge_available"], (
        f"badge invariant broken: {data['badge_total']} != "
        f"{data['badge_in_use']} + {data['badge_available']}"
    )


def assert_floor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["current_occupancy"], int)
    assert isinstance(data["available_slots"], int)
    # Floor-occupancy invariant (PRD 2.9).
    assert data["capacity"] == data["current_occupancy"] + data["available_slots"], (
        f"floor invariant broken: {data['capacity']} != "
        f"{data['current_occupancy']} + {data['available_slots']}"
    )


def assert_host(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["department"] in ["ENGINEERING", "SALES", "FACILITIES", "EXECUTIVE"]
    assert isinstance(data["notify_count"], int) and data["notify_count"] >= 0


def assert_watchlist_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert data["match_type"] in ["NAME", "COMPANY"]
    assert isinstance(data["match_value_normalized"], str)
    assert data["severity"] in ["REVIEW", "DENY"]
    assert isinstance(data["active"], bool)


def assert_meeting_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["floor_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["seats"], int) and data["seats"] >= 1


def assert_parking_space(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["bay_label"], str)


def assert_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["host_id"], str)
    assert isinstance(data["floor_id"], str)
    assert isinstance(data["visitor_full_name"], str)
    assert isinstance(data["visitor_company"], str)
    assert isinstance(data["id_scanned"], bool)
    assert data["status"] in [
        "PREREGISTERED", "SCREENING", "FLAGGED", "DENIED",
        "CLEARED", "SIGNED_IN", "SIGNED_OUT",
    ]
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100, "risk_score must be clamped to [0,100]"


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["visit_id"], str)
    assert data["document_kind"] in ["NDA", "SAFETY_WAIVER", "DATA_POLICY"]
    assert isinstance(data["document_version"], str)
    assert data["status"] in ["PENDING", "SIGNED", "VOID"]


def assert_contractor_pass(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["host_id"], str)
    assert isinstance(data["contractor_name"], str)
    assert isinstance(data["contractor_company"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REVOKED"]
    assert isinstance(data["covered_visit_count"], int) and data["covered_visit_count"] >= 0


def assert_delivery(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["host_id"], str)
    assert data["carrier"] in ["FEDEX", "UPS", "USPS", "DHL", "COURIER"]
    assert isinstance(data["parcel_fees_cents"], list)
    assert data["status"] in ["RECEIVED", "PICKED_UP"]
    assert isinstance(data["handling_invoice_cents"], int)


def assert_evacuation_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["floor_id"], str)
    assert data["triggered_reason"] in ["FIRE_DRILL", "FIRE_ALARM", "GAS_LEAK", "OTHER"]
    assert isinstance(data["roster_visit_ids"], list)
    assert isinstance(data["roster_head_count"], int)
    assert data["roster_head_count"] == len(data["roster_visit_ids"]), (
        "roster_head_count must equal length of roster_visit_ids"
    )


def assert_badge_invariant(site: dict):
    """Badge-inventory conserved quantity (PRD 2.9)."""
    assert site["badge_total"] == site["badge_in_use"] + site["badge_available"]


def assert_floor_invariant(floor: dict):
    """Floor-occupancy conserved quantity (PRD 2.9)."""
    assert floor["capacity"] == floor["current_occupancy"] + floor["available_slots"]
