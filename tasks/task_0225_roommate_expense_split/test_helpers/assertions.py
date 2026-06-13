"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_SLEEP = {"EARLY_BIRD", "NIGHT_OWL", "FLEXIBLE"}
_SPLIT_POLICY = {"EQUAL", "BY_ROOM_SIZE", "BY_INCOME"}


def _assert_common(data: dict):
    """id / created_at / updated_at / version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_roommate_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 0
    assert isinstance(data["cleanliness"], int) and 1 <= data["cleanliness"] <= 5
    assert data["sleep_schedule"] in _SLEEP
    assert isinstance(data["smoker"], bool)
    assert isinstance(data["pets"], bool)
    assert isinstance(data["net_balance_cents"], int)


def assert_room_listing(data: dict):
    _assert_common(data)
    assert isinstance(data["lister_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0
    assert isinstance(data["capacity"], int) and 1 <= data["capacity"] <= 8
    assert isinstance(data["room_size_sqft"], int) and data["room_size_sqft"] > 0
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["split_policy"] in _SPLIT_POLICY


def assert_match_request(data: dict):
    _assert_common(data)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert data["scoring_mode"] in ("STRICT", "LENIENT")
    assert isinstance(data["compatibility_score"], int) and 0 <= data["compatibility_score"] <= 100
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED", "WITHDRAWN")


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["manager_id"], str)
    assert data["split_policy"] in _SPLIT_POLICY
    assert data["status"] in ("FORMING", "ACTIVE", "FROZEN", "DISSOLVED")
    assert isinstance(data["active_member_count"], int) and data["active_member_count"] >= 0
    assert isinstance(data["ledger_sum_cents"], int)


def assert_membership(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["profile_id"], str)
    assert isinstance(data["occupied_days_estimate"], int)
    assert isinstance(data["occupied_days_actual"], int)
    assert data["status"] in ("PENDING", "ACTIVE", "MOVED_OUT")


def assert_bill(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert data["bill_type"] in ("RENT", "UTILITIES")
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] > 0
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID")
    assert data["reminder_status"] in ("NONE", "SCHEDULED", "SENT")


def assert_expense(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] > 0
    assert data["split_mode"] in ("EQUAL", "CUSTOM")
    assert data["status"] in ("POSTED", "VOIDED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["from_profile_id"], str)
    assert isinstance(data["to_profile_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PROPOSED", "CONFIRMED", "DISPUTED", "CANCELLED")


def assert_payment_reminder(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert data["status"] in ("SCHEDULED", "SENT", "ACKNOWLEDGED", "CANCELLED")


def assert_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["filed_by_id"], str)
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED", "REJECTED")


def assert_immutable_child_row(data: dict):
    """BillSplit / ExpenseShare carry only id + created_at — never updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "child row id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable child row must not expose updated_at"
    assert "version" not in data, "immutable child row must not expose version"


# ─── Domain helpers ──────────────────────────────────────

def find_split_for_profile(splits: list, profile_id: str) -> dict:
    """Return the BillSplit / ExpenseShare row owed by profile_id (or fail)."""
    for row in splits:
        if row.get("profile_id") == profile_id:
            return row
    raise AssertionError(f"No share row found for profile_id {profile_id} in {splits}")


def assert_ledger_conserved(household: dict):
    """The conservation invariant: ledger_sum_cents must be exactly 0 (PRD §2.6)."""
    assert household["ledger_sum_cents"] == 0, (
        f"ledger_sum_cents must be 0, got {household['ledger_sum_cents']}"
    )
