"""Entity assertions: shape + invariant checkers.

Every entity carries id (UUID), created_at/updated_at (ISO 8601), and an integer
version that begins at 1 (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_garden(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["reciprocal_network_code"], str)
    assert isinstance(data["household_member_cap"], int)
    assert isinstance(data["guest_pass_grant_household"], int)
    assert isinstance(data["guest_pass_grant_patron"], int)


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("INDIVIDUAL", "HOUSEHOLD", "PATRON")
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0
    assert isinstance(data["admission_included"], bool)
    assert isinstance(data["active"], bool)


def assert_membership(data: dict):
    _assert_common(data)
    assert isinstance(data["primary_member_name"], str)
    assert isinstance(data["household_member_names"], list)
    assert data["status"] in ("PENDING", "ACTIVE", "LAPSED", "CANCELLED")
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["paid_total_cents"], int) and data["paid_total_cents"] >= 0
    assert isinstance(data["guest_passes_remaining"], int) and data["guest_passes_remaining"] >= 0
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_time_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["ga_price_cents"], int) and data["ga_price_cents"] >= 0
    assert isinstance(data["held_count"], int) and data["held_count"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")
    # Invariant: held_count never exceeds capacity (PRD §3.3).
    assert data["held_count"] <= data["capacity"], (
        f"held_count {data['held_count']} must not exceed capacity {data['capacity']}"
    )


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["member_heads"], int) and data["member_heads"] >= 0
    assert isinstance(data["guest_heads"], int) and data["guest_heads"] >= 0
    assert isinstance(data["paid_heads"], int) and data["paid_heads"] >= 0
    assert isinstance(data["party_size"], int)
    # party_size is the sum of the three head counts (PRD §3.3).
    assert data["party_size"] == data["member_heads"] + data["guest_heads"] + data["paid_heads"], (
        "party_size must equal member_heads + guest_heads + paid_heads"
    )
    assert isinstance(data["admission_cents"], int) and data["admission_cents"] >= 0
    assert data["status"] in ("HELD", "CHECKED_IN", "EXPIRED", "CANCELLED")


def assert_event_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["charged_cents"], int) and data["charged_cents"] >= 0
    assert data["status"] in ("PURCHASED", "REFUNDED")


def assert_program_session(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["tuition_cents"], int) and data["tuition_cents"] >= 0
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["participant_name"], str)
    assert isinstance(data["charged_cents"], int) and data["charged_cents"] >= 0
    assert data["status"] in ("ENROLLED", "WAITLISTED", "WITHDRAWN")
    assert isinstance(data["waitlist_rank"], int) and data["waitlist_rank"] >= 0


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0


def assert_rental(data: dict):
    _assert_common(data)
    assert isinstance(data["quoted_cents"], int) and data["quoted_cents"] >= 0
    assert isinstance(data["final_cents"], int) and data["final_cents"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "REJECTED", "CANCELLED")


def assert_donation(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["designation"] in ("GENERAL", "CONSERVANCY", "CAPITAL")
    assert isinstance(data["tax_deductible_cents"], int) and data["tax_deductible_cents"] >= 0
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_conservancy_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["pledged_total_cents"], int) and data["pledged_total_cents"] >= 0
    assert isinstance(data["matched_total_cents"], int) and data["matched_total_cents"] >= 0
    assert data["campaign_status"] in ("OPEN", "CLOSED")
    # Invariant: matched never exceeds the cap (PRD §3.7).
    assert data["matched_total_cents"] <= data["match_cap_cents"] or data["match_cap_cents"] == 0, (
        "matched_total_cents must not exceed match_cap_cents"
    )
