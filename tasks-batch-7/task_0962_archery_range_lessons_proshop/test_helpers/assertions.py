"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MEMBER_STATUSES = ["ACTIVE", "SUSPENDED"]
WAIVER_STATUSES = ["ACTIVE", "EXPIRED", "REVOKED"]
SESSION_STATUSES = ["BOOKED", "CHECKED_IN", "CLOSED", "CANCELLED", "NO_SHOW"]
PAYMENT_STATUSES = ["UNPAID", "PAID", "REFUNDED"]
PARTICIPANT_STATUSES = ["ACTIVE", "REFUNDED", "FORFEITED"]
PUNCH_CARD_STATUSES = ["ACTIVE", "EXHAUSTED"]
RENTAL_ITEM_STATUSES = ["AVAILABLE", "RENTED"]
RENTAL_AGREEMENT_STATUSES = ["OPEN", "RETURNED", "SETTLED", "VOIDED"]
COACH_STATUSES = ["ACTIVE", "INACTIVE"]
LESSON_STATUSES = ["REQUESTED", "COUNTERED", "CONFIRMED", "COMPLETED", "CANCELLED"]
LEAGUE_STATUSES = ["OPEN", "CLOSED", "COMPLETED", "CANCELLED"]
LEAGUE_ENTRY_STATUSES = ["CONFIRMED", "CANCELLED"]
SCORECARD_STATUSES = ["SUBMITTED", "VERIFIED", "DISPUTED", "LOCKED"]
REPAIR_ORDER_STATUSES = [
    "INTAKE", "QUOTED", "IN_REPAIR", "DECLINED", "READY", "PICKED_UP",
]


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["tier"] in ["BASIC", "PLUS", "ELITE"]
    assert isinstance(data["is_minor"], bool)
    assert data["status"] in MEMBER_STATUSES
    assert isinstance(data["safety_strikes"], int) and data["safety_strikes"] >= 0
    assert isinstance(data["wallet_balance_cents"], int)


def assert_waiver(data: dict):
    _assert_common(data, "Waiver")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["signed_by_member_id"])
    assert is_iso8601_timestamp(data["signed_at"])
    assert isinstance(data["valid_until"], str)
    assert data["status"] in WAIVER_STATUSES


def assert_lane(data: dict):
    _assert_common(data, "Lane")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["lane_type"] in ["INDOOR", "OUTDOOR"]
    assert isinstance(data["max_archers"], int) and data["max_archers"] >= 1


def assert_range_session(data: dict):
    _assert_common(data, "RangeSession")
    assert is_valid_uuid(data["lane_id"])
    assert data["booking_type"] in ["WALK_IN", "RESERVATION"]
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] > 0
    assert data["session_status"] in SESSION_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    assert isinstance(data["quoted_charge_cents"], int)


def assert_session_participant(data: dict):
    _assert_common(data, "SessionParticipant")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["payment_method"] in ["WALLET", "PUNCH_CARD"]
    assert isinstance(data["quoted_fee_cents"], int)
    assert data["status"] in PARTICIPANT_STATUSES


def assert_punch_card(data: dict):
    _assert_common(data, "PunchCard")
    assert is_valid_uuid(data["member_id"])
    assert data["punches_total"] in [5, 10]
    assert isinstance(data["punches_used"], int) and data["punches_used"] >= 0
    assert data["status"] in PUNCH_CARD_STATUSES


def assert_punch_card_invariants(data: dict):
    """PRD §3.5: punches_remaining is always the pack size minus punches_used."""
    assert data["punches_remaining"] == data["punches_total"] - data["punches_used"]
    assert 0 <= data["punches_used"] <= data["punches_total"]


def assert_rental_item(data: dict):
    _assert_common(data, "RentalItem")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["item_type"] in ["BOW", "ARROW_SET", "ARMGUARD", "RELEASE"]
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert data["status"] in RENTAL_ITEM_STATUSES


def assert_rental_agreement(data: dict):
    _assert_common(data, "RentalAgreement")
    assert is_valid_uuid(data["rental_item_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["due_date"], str)
    assert data["status"] in RENTAL_AGREEMENT_STATUSES


def assert_coach(data: dict):
    _assert_common(data, "Coach")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["disciplines"], list) and len(data["disciplines"]) > 0
    for d in data["disciplines"]:
        assert d in ["RECURVE", "COMPOUND", "TRADITIONAL"]
    assert data["status"] in COACH_STATUSES


def assert_lesson(data: dict):
    _assert_common(data, "Lesson")
    assert is_valid_uuid(data["coach_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["discipline"] in ["RECURVE", "COMPOUND", "TRADITIONAL"]
    assert 30 <= data["duration_minutes"] <= 120
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in LESSON_STATUSES


def assert_league(data: dict):
    _assert_common(data, "League")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["entry_fee_cents"], int) and data["entry_fee_cents"] >= 0
    assert isinstance(data["max_entries"], int) and data["max_entries"] >= 1
    assert data["status"] in LEAGUE_STATUSES
    assert isinstance(data["gross_entry_fees_cents"], int)
    assert isinstance(data["range_share_cents"], int)
    assert isinstance(data["prize_pool_cents"], int)


def assert_league_pool_invariants(data: dict):
    """PRD §3.8: prize pool is gross minus the range share."""
    assert data["prize_pool_cents"] == (
        data["gross_entry_fees_cents"] - data["range_share_cents"]
    )
    assert data["gross_entry_fees_cents"] >= 0
    assert data["range_share_cents"] >= 0


def assert_league_entry(data: dict):
    _assert_common(data, "LeagueEntry")
    assert is_valid_uuid(data["league_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert data["status"] in LEAGUE_ENTRY_STATUSES
    assert data["refund_status"] in ["NONE", "REFUNDED"]


def assert_scorecard(data: dict):
    _assert_common(data, "ScoreCard")
    assert is_valid_uuid(data["league_entry_id"])
    assert isinstance(data["ends"], list) and len(data["ends"]) == 10
    for end in data["ends"]:
        assert isinstance(end, list) and len(end) == 3
        for arrow in end:
            assert isinstance(arrow, int) and 0 <= arrow <= 10
    assert isinstance(data["x_hits"], int) and 0 <= data["x_hits"] <= 30
    assert isinstance(data["total_points"], int)
    assert data["status"] in SCORECARD_STATUSES


def assert_shop_product(data: dict):
    _assert_common(data, "ShopProduct")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_quantity"], int) and data["stock_quantity"] >= 0


def assert_sale(data: dict):
    _assert_common(data, "Sale")
    assert isinstance(data["items"], list) and len(data["items"]) > 0
    assert isinstance(data["line_gross_cents"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["volume_discount_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_sale_invariants(data: dict):
    """PRD §3.9: total is the taxable base plus the tax."""
    assert data["total_cents"] == (
        data["subtotal_cents"] - data["volume_discount_cents"] + data["tax_cents"]
    )


def assert_repair_order(data: dict):
    _assert_common(data, "RepairOrder")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["item_description"], str)
    assert data["status"] in REPAIR_ORDER_STATUSES
    assert isinstance(data["parts_reserved"], list)
