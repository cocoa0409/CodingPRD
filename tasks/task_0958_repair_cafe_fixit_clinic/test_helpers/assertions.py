"""Entity assertions and domain invariant checkers (PRD §2.7, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

EVENT_STATUSES = ["DRAFT", "PUBLISHED", "INTAKE_OPEN", "REPAIR_ACTIVE",
                  "CLOSED", "REPORTED", "CANCELLED"]
STATION_STATUSES = ["SETUP", "OPEN", "PAUSED", "CLOSED"]
FIXER_STATUSES = ["ACTIVE", "SUSPENDED", "INACTIVE"]
SHIFT_STATUSES = ["SIGNED_UP", "CONFIRMED", "CHECKED_IN", "COMPLETED",
                  "LEFT_EARLY", "CANCELLED", "NO_SHOW"]
WAIVER_STATUSES = ["ACTIVE", "REVOKED", "EXPIRED"]
ITEM_STATUSES = ["REGISTERED", "TRIAGED", "QUEUED", "ASSIGNED", "IN_REPAIR",
                 "OUTCOME_RECORDED", "VERIFIED", "WITHDRAWN"]
RESERVATION_STATUSES = ["RESERVED", "COMMITTED", "RELEASED", "EXPIRED"]
VERIFICATION_STATUSES = ["RECORDED", "VERIFIED", "REJECTED"]
INCIDENT_STATUSES = ["REPORTED", "RESOLVED", "DISMISSED"]
DONATION_STATUSES = ["PLEDGED", "RECEIVED", "RECEIPTED", "REFUNDED"]
REPAIR_CATEGORIES = ["ELECTRONICS", "TEXTILE", "BIKE"]
PART_CATEGORIES = ["ELECTRONICS", "TEXTILE", "BIKE", "GENERIC"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_repair_event(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["intake_item_cap"], int) and data["intake_item_cap"] >= 1
    assert data["status"] in EVENT_STATUSES
    assert data["posture"] in ["ACCEPTING", "RESTRICTED"]
    assert isinstance(data["active_item_count"], int) and data["active_item_count"] >= 0
    assert isinstance(data["diversion_kg_verified"], (int, float))
    assert isinstance(data["diversion_kg_projected"], (int, float))
    assert isinstance(data["parts_committed_cents"], int)


def assert_station(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["event_id"])
    assert data["category"] in REPAIR_CATEGORIES
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in STATION_STATUSES
    assert isinstance(data["checked_in_fixer_count"], int)
    assert data["checked_in_fixer_count"] >= 0


def assert_fixer_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in FIXER_STATUSES
    assert is_iso8601_timestamp(data["safety_induction_completed_at"])
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100


def assert_fixer_skill(data: dict):
    # FixerSkill is light: id + created_at only (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["fixer_id"])
    assert data["category"] in REPAIR_CATEGORIES
    assert isinstance(data["level"], int) and 1 <= data["level"] <= 5
    assert isinstance(data["certified"], bool)


def assert_fixer_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fixer_id"])
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["event_id"])
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])
    assert data["status"] in SHIFT_STATUSES
    if data["status"] in ("CHECKED_IN", "COMPLETED", "LEFT_EARLY"):
        assert data.get("checked_in_at") is not None


def assert_visitor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_waiver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["visitor_id"])
    assert is_iso8601_timestamp(data["signed_at"])
    assert isinstance(data["safety_clause_accepted"], bool)
    assert data["status"] in WAIVER_STATUSES


def assert_repair_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["visitor_id"])
    assert data["category"] in REPAIR_CATEGORIES
    assert isinstance(data["description"], str)
    assert isinstance(data["hazard_flag"], bool)
    assert isinstance(data["weight_kg_estimated"], (int, float))
    assert data["status"] in ITEM_STATUSES
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= 100
    assert isinstance(data["required_skill_level"], int)
    if data["status"] in ("ASSIGNED", "IN_REPAIR"):
        assert data["assigned_fixer_id"] is not None
        assert data["assigned_station_id"] is not None


def assert_triage_record(data: dict):
    # TriageRecord is immutable history: id + created_at only (no updated_at / version).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 10
    assert isinstance(data["estimated_difficulty"], int)
    assert 1 <= data["estimated_difficulty"] <= 5
    assert isinstance(data["diagnosis"], str)
    assert isinstance(data["is_current"], bool)


def assert_part_stock(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in PART_CATEGORIES
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] >= 0
    assert isinstance(data["quantity_available"], int)
    assert_part_stock_conservation(data)


def assert_part_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["part_stock_id"])
    assert is_valid_uuid(data["repair_item_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["cost_cents"], int)
    assert data["cost_cents"] == data["quantity"] * data["unit_cost_cents"]
    assert data["status"] in RESERVATION_STATUSES
    assert is_iso8601_timestamp(data["expires_at"])


def assert_repair_outcome(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["item_id"])
    assert data["outcome"] in ["FIXED", "PARTIALLY_FIXED", "NOT_REPAIRABLE"]
    assert isinstance(data["parts_cost_cents"], int)
    assert isinstance(data["suggested_donation_cents"], int)
    assert data["verification_status"] in VERIFICATION_STATUSES


def assert_safety_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["reported_by_user_id"], str)
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert isinstance(data["description"], str)
    assert data["status"] in INCIDENT_STATUSES


def assert_donation(data: dict):
    _assert_common(data)
    assert data["donation_type"] in ["MONETARY", "IN_KIND"]
    assert data["status"] in DONATION_STATUSES
    if data["donation_type"] == "MONETARY":
        assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    else:
        assert isinstance(data["in_kind_lines"], list) and len(data["in_kind_lines"]) >= 1


def assert_event_report(data: dict):
    # EventReport is a frozen snapshot: id + created_at only.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["event_id"])
    assert is_iso8601_timestamp(data["generated_at"])
    for field in ("items_total", "items_fixed", "items_partially_fixed",
                  "items_not_repairable", "parts_cost_total_cents",
                  "donations_receipt_total_cents", "donations_campaign_total_cents"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["success_rate_strict"], (int, float))
    assert isinstance(data["success_rate_lenient"], (int, float))
    assert isinstance(data["diversion_kg_verified"], (int, float))
    assert isinstance(data["diversion_kg_projected"], (int, float))


def assert_part_stock_conservation(stock: dict):
    """PRD §2.10: quantity_available == quantity_on_hand - quantity_reserved,
    and on_hand never dips below reserved."""
    assert stock["quantity_available"] == stock["quantity_on_hand"] - stock["quantity_reserved"], (
        f"quantity_available {stock['quantity_available']} != "
        f"on_hand {stock['quantity_on_hand']} - reserved {stock['quantity_reserved']}"
    )
    assert stock["quantity_on_hand"] >= stock["quantity_reserved"]
