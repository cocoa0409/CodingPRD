"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_membership_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["included_session_credits"], int)
    assert isinstance(data["party_discount_pct"], (int, float))
    assert isinstance(data["cafe_discount_pct"], (int, float))
    assert isinstance(data["socks_included"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_guardian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["membership_status"] in ["NONE", "ACTIVE", "CANCELLED"]
    # The guardian record always presents its computed credit and loyalty
    # fields alongside the stored ones (PRD §3.1).
    for f in ("credits_granted", "credits_consumed", "credits_held",
              "credits_available", "credits_statement",
              "lifetime_points", "points_balance"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"
    assert data["loyalty_tier"] in ["BRONZE", "SILVER", "GOLD"]


def assert_child(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["guardian_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["allergies"], list)


def assert_waiver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["guardian_id"], str)
    assert is_iso8601_timestamp(data.get("signed_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in ["SIGNED", "SUPERSEDED", "EXPIRED"]


def assert_session_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["slot_date"], str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["capacity"], int)
    assert isinstance(data["reservation_quota"], int)
    assert isinstance(data["reserved_count"], int)
    assert isinstance(data["checked_in_count"], int)
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED"]


def assert_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["session_slot_id"], str)
    assert isinstance(data["child_id"], str)
    assert isinstance(data["guardian_id"], str)
    assert data["visit_type"] in ["RESERVATION", "WALK_IN"]
    assert data["admission_status"] in [
        "RESERVED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW", "EVACUATED"]
    assert data["payment_status"] in ["PENDING", "PREPAID", "SETTLED", "REFUNDED"]
    assert data["sock_method"] in ["NONE", "OWN_GRIP_SOCKS", "PURCHASED", "MEMBERSHIP_PROVIDED"]


def assert_party_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_children"], int)
    assert data["status"] in ["ACTIVE", "MAINTENANCE", "CLOSED"]


def assert_party_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["included_children"], int)
    assert isinstance(data["extra_child_price_cents"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_party_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["party_room_id"], str)
    assert isinstance(data["party_package_id"], str)
    assert isinstance(data["guardian_id"], str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["child_count"], int)
    assert data["status"] in [
        "HELD", "CONFIRMED", "RESCHEDULE_REQUESTED", "COMPLETED", "CANCELLED", "EXPIRED"]
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["deposit_paid"], bool)


def assert_cafe_menu_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["allergen_tags"], list)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_cafe_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["guardian_id"], str)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert isinstance(line["menu_item_id"], str)
        assert isinstance(line["quantity"], int)
        assert isinstance(line["unit_price_cents"], int)
        assert isinstance(line["line_total_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["points_redeemed"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["points_earned"], int)
    assert data["status"] in ["PLACED", "PREPARING", "SERVED", "CANCELLED"]


def assert_loyalty_transaction(data: dict):
    # Ledger entries are immutable once written: they carry only id and
    # created_at of the common fields; updated_at and version are absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entry must not carry updated_at"
    assert "version" not in data, "ledger entry must not carry version"
    assert isinstance(data["guardian_id"], str)
    assert data["kind"] in ["EARN", "REDEEM", "REVERSAL", "ADJUSTMENT"]
    assert isinstance(data["points"], int)
    assert isinstance(data["balance_after"], int)


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role"] in ["FRONT_DESK", "CAFE_STAFF", "MANAGER"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_sanitation_task(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["party_room_id"], str)
    assert data["kind"] in ["DEEP_CLEAN", "BALL_PIT_WASH", "SURFACE_WIPE"]
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "OVERDUE", "COMPLETED"]


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ["LOST_CHILD", "INJURY", "PROPERTY_DAMAGE", "BEHAVIOR"]
    assert data["severity"] in ["LOW", "MEDIUM", "CRITICAL"]
    assert isinstance(data["description"], str)
    assert data["status"] in ["OPEN", "TRIAGED", "RESOLVED", "CLOSED"]


def assert_credit_balance_invariants(guardian: dict):
    """Credit accounting identity: available == granted - consumed - held (PRD §3.2)."""
    assert guardian["credits_available"] == (
        guardian["credits_granted"]
        - guardian["credits_consumed"]
        - guardian["credits_held"]
    ), "credits_available must equal granted - consumed - held"
    assert guardian["credits_statement"] == (
        guardian["credits_granted"] - guardian["credits_consumed"]
    ), "credits_statement must equal granted - consumed"


def assert_slot_counters_non_negative(slot: dict):
    assert slot["reserved_count"] >= 0
    assert slot["checked_in_count"] >= 0
    assert slot["reservation_quota"] >= 0
