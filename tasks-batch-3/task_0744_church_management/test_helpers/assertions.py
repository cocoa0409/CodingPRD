"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def assert_household(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"invalid household id: {data.get('id')}"
    assert data["name"], "household name required"
    assert data["address_line1"]
    assert data["postal_code"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["household_id"]
    assert data["full_name"]
    assert data["member_type"] in ("ADULT", "CHILD")
    assert data["membership_status"] in ("VISITOR", "REGULAR", "MEMBER", "DEPARTED")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_pledge_campaign(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert isinstance(data["target_amount_cents"], int) and data["target_amount_cents"] > 0
    assert isinstance(data["pledged_total_cents"], int)
    assert isinstance(data["received_total_cents"], int)
    assert isinstance(data["fulfilled_pledge_count"], int) and data["fulfilled_pledge_count"] >= 0


def assert_pledge(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("ACTIVE", "FULFILLED", "CANCELLED")
    assert data["pledged_amount_cents"] > 0
    assert data["received_amount_cents"] >= 0
    assert data["remaining_amount_cents"] == max(
        0, data["pledged_amount_cents"] - data["received_amount_cents"]
    )


def assert_donation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("PENDING", "POSTED", "REFUNDED", "FAILED")
    assert data["payment_method"] in ("CASH", "CHECK", "CARD", "ACH")
    assert data["amount_cents"] > 0


def assert_year_end_statement(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("DRAFT", "ISSUED", "VOIDED")
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["total_deductible_cents"], int) and data["total_deductible_cents"] >= 0
    assert isinstance(data["donation_count"], int) and data["donation_count"] >= 0


def assert_event(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("SCHEDULED", "CANCELLED", "COMPLETED")
    assert data["event_type"] in ("SERVICE", "CLASS", "MEETING", "OUTREACH")
    assert data["volunteer_slots"] >= 0
    assert data["expected_attendance"] >= 0


def assert_facility(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["capacity"] > 0
    assert data.get("buffer_minutes", 0) >= 0


def assert_facility_booking(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("CONFIRMED", "CANCELLED")
    assert data["booking_type"] in ("EVENT", "EXTERNAL")
    assert data["headcount"] > 0


def assert_volunteer_assignment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in (
        "INVITED", "ACCEPTED", "DECLINED", "CHECKED_IN", "COMPLETED", "CANCELLED"
    )
    assert data["role_type"] in ("USHER", "GREETER", "CHILDCARE", "AUDIO_VISUAL", "TEACHER")


def assert_small_group(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] == "ACTIVE"
    assert data["capacity"] > 0
    assert data["ministry_area"] in ("WORSHIP", "STUDY", "OUTREACH", "CARE", "YOUTH")
    assert data["roster_count"] >= 0


def assert_group_membership(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("ACTIVE", "PAST")
    assert data["role"] in ("LEADER", "CO_LEADER", "MEMBER")


def assert_child_checkin(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("CHECKED_IN", "SECURITY_HOLD", "CHECKED_OUT")
    if data["status"] == "SECURITY_HOLD":
        assert data.get("hold_reason") in ("PIN_MISMATCH", "UNAUTHORIZED_PICKUP", "STAFF_HOLD")
