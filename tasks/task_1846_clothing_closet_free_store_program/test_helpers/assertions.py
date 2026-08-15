"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every entity carries the standard four
system-managed fields (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["eligibility_tier"] in ("STANDARD", "HARDSHIP")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["last_checkout_at"] is None or is_iso8601_timestamp(data["last_checkout_at"])
    assert isinstance(data["visits_in_30d"], int) and data["visits_in_30d"] >= 0
    assert isinstance(data["items_in_30d"], int) and data["items_in_30d"] >= 0


def assert_client_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert data["voucher_id"] is None or isinstance(data["voucher_id"], str)
    assert data["status"] in ("CHECKED_IN", "CHECKED_OUT", "VOIDED")
    assert is_iso8601_timestamp(data["checked_in_at"])
    assert data["checked_out_at"] is None or is_iso8601_timestamp(data["checked_out_at"])
    assert isinstance(data["general_allowance"], int) and data["general_allowance"] >= 0
    assert isinstance(data["voucher_bonus_applied"], int) and data["voucher_bonus_applied"] >= 0


def assert_distribution_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["item_id"], str)
    assert data["category_snapshot"] in (
        "ADULT_TOPS", "ADULT_BOTTOMS", "CHILDRENS", "COATS",
        "INTERVIEW_ATTIRE", "ACCESSORIES",
    )
    assert isinstance(data["is_drive_line"], bool)
    assert data["drive_id"] is None or isinstance(data["drive_id"], str)
    assert data["status"] in ("ACTIVE", "DISTRIBUTED", "RELEASED", "RETURNED")


def assert_donation_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["donor_name"], str) and data["donor_name"]
    assert data["donor_email"] is None or isinstance(data["donor_email"], str)
    assert isinstance(data["item_count_declared"], int) and data["item_count_declared"] >= 1
    assert isinstance(data["items_created_count"], int) and data["items_created_count"] >= 0
    assert data["status"] in ("RECEIVED", "IN_SORT", "SORTED", "CLOSED")
    assert data["sorted_by_user_id"] is None or isinstance(data["sorted_by_user_id"], str)
    assert data["closed_by_user_id"] is None or isinstance(data["closed_by_user_id"], str)


def assert_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["donation_batch_id"], str)
    assert data["category"] in (
        "ADULT_TOPS", "ADULT_BOTTOMS", "CHILDRENS", "COATS",
        "INTERVIEW_ATTIRE", "ACCESSORIES",
    )
    assert data["season"] in ("WINTER", "SUMMER", "ALL_SEASON")
    assert data["quality_grade"] in ("NEW_WITH_TAGS", "GOOD", "FAIR", "REJECT")
    assert data["drive_id"] is None or isinstance(data["drive_id"], str)
    assert data["status"] in (
        "PENDING_STOCK", "STOCKED", "RESERVED", "DISTRIBUTED",
        "OFF_SEASON", "QUARANTINED", "REJECTED", "RECYCLED",
    )
    assert data["storage_zone_id"] is None or isinstance(data["storage_zone_id"], str)
    assert data["reserved_visit_id"] is None or isinstance(data["reserved_visit_id"], str)
    assert data["recycling_batch_id"] is None or isinstance(data["recycling_batch_id"], str)
    assert isinstance(data["graded_by_user_id"], str)
    assert data["stocked_at"] is None or is_iso8601_timestamp(data["stocked_at"])
    assert data["distributed_at"] is None or is_iso8601_timestamp(data["distributed_at"])
    assert data["distributed_from_zone_id"] is None or isinstance(
        data["distributed_from_zone_id"], str)


def assert_storage_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["season_policy"] in ("WINTER", "SUMMER", "ALL_SEASON")
    assert isinstance(data["capacity_items"], int) and data["capacity_items"] >= 1
    assert isinstance(data["current_stock"], int) and data["current_stock"] >= 0
    assert data["posture"] in ("AVAILABLE", "NEAR_FULL", "FULL")


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["is_lead"], bool)
    assert data["status"] == "ACTIVE"


def assert_volunteer_shift(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["role_type"] in ("SORTING", "INTAKE", "FLOOR")
    assert isinstance(data["capacity_volunteers"], int) and data["capacity_volunteers"] >= 1
    assert isinstance(data["active_signup_count"], int) and data["active_signup_count"] >= 0
    assert data["status"] in ("OPEN", "LOCKED", "COMPLETED", "CANCELLED")


def assert_shift_signup(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["shift_id"], str)
    assert isinstance(data["volunteer_id"], str)
    assert data["status"] in ("SIGNED_UP", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["checked_in_at"] is None or is_iso8601_timestamp(data["checked_in_at"])


def assert_referral_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_voucher_quota"], int) and data["base_voucher_quota"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["activated_month_key"], str) and len(data["activated_month_key"]) == 7
    assert isinstance(data["vouchers_issued_current_month"], int)
    assert data["vouchers_issued_current_month"] >= 0
    assert isinstance(data["current_month_quota"], int) and data["current_month_quota"] >= 0


def assert_voucher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["partner_id"], str)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["bonus_items"], int) and 1 <= data["bonus_items"] <= 10
    assert isinstance(data["waives_frequency"], bool)
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("ISSUED", "REDEEMED", "REVOKED", "EXPIRED")
    assert isinstance(data["issued_month_key"], str) and len(data["issued_month_key"]) == 7
    assert data["redeemed_at"] is None or is_iso8601_timestamp(data["redeemed_at"])


def assert_special_drive(data: dict):
    _assert_common_fields(data)
    assert data["drive_type"] in ("INTERVIEW_ATTIRE", "WINTER_COATS")
    assert data["target_category"] in (
        "ADULT_TOPS", "ADULT_BOTTOMS", "CHILDRENS", "COATS",
        "INTERVIEW_ATTIRE", "ACCESSORIES",
    )
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["bonus_items_per_client"], int) and data["bonus_items_per_client"] >= 1
    assert data["status"] in ("UPCOMING", "ACTIVE", "CLOSED")


def assert_seasonal_rotation(data: dict):
    _assert_common_fields(data)
    assert data["target_season"] in ("WINTER", "SUMMER")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["executed_at"] is None or is_iso8601_timestamp(data["executed_at"])
    assert isinstance(data["moved_out_count"], int) and data["moved_out_count"] >= 0
    assert isinstance(data["moved_in_count"], int) and data["moved_in_count"] >= 0


def assert_recycling_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["recycler_name"], str) and data["recycler_name"]
    assert data["capacity_kg"] > 0
    assert data["status"] in ("ACCUMULATING", "SEALED", "PICKED_UP")
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    assert data["est_weight_kg"] is not None and data["est_weight_kg"] >= 0
    assert data["provisional_credit_cents"] is None or isinstance(
        data["provisional_credit_cents"], int)
    assert data["actual_weight_kg"] is None or data["actual_weight_kg"] > 0
    assert data["final_credit_cents"] is None or isinstance(data["final_credit_cents"], int)
    assert data["sealed_by_user_id"] is None or isinstance(data["sealed_by_user_id"], str)
    assert data["picked_up_by_user_id"] is None or isinstance(data["picked_up_by_user_id"], str)


def assert_zone_posture_invariants(data: dict):
    """Zone occupancy invariants from the PRD zone-occupancy section: posture
    must agree with current_stock relative to capacity."""
    import math

    stock = data["current_stock"]
    capacity = data["capacity_items"]
    if stock >= capacity:
        expected = "FULL"
    elif stock >= math.ceil(0.8 * capacity):
        expected = "NEAR_FULL"
    else:
        expected = "AVAILABLE"
    assert data["posture"] == expected, (
        f"posture {data['posture']} inconsistent with stock {stock}/{capacity}; "
        f"expected {expected}"
    )
