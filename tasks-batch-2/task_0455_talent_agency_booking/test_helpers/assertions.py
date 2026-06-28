"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every entity carries id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments per mutation"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["commission_rate_bps"], int)
    assert 0 <= data["commission_rate_bps"] <= 5000
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["booked_day_count"], int)


def assert_casting_director(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["studio"], str)


def assert_talent(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["union_status"] in ("SAG", "NON_UNION")
    assert data["status"] in ("PROSPECT", "ROSTERED", "SUSPENDED", "ARCHIVED")
    assert isinstance(data["scale_rate_cents"], int)
    assert isinstance(data["booked_day_count"], int)


def assert_comp_card(data: dict):
    _assert_common(data)
    assert isinstance(data["talent_id"], str)
    assert isinstance(data["headshot_url"], str)
    assert isinstance(data["height_cm"], int) and data["height_cm"] >= 1
    assert isinstance(data["skills"], list)
    assert isinstance(data["is_primary"], bool)


def assert_casting_call(data: dict):
    _assert_common(data)
    assert isinstance(data["casting_director_id"], str)
    assert isinstance(data["title"], str)
    assert data["media_type"] in ("BROADCAST_TV", "CABLE", "STREAMING", "PRINT", "DIGITAL")
    assert isinstance(data["usage_term_months"], int) and data["usage_term_months"] >= 1
    assert data["status"] in ("OPEN", "CLOSED", "FILLED")


def assert_submission(data: dict):
    _assert_common(data)
    assert isinstance(data["casting_call_id"], str)
    assert isinstance(data["talent_id"], str)
    assert isinstance(data["comp_card_id"], str)
    assert data["status"] in (
        "SUBMITTED", "AUDITION_SCHEDULED", "CALLBACK_SCHEDULED",
        "OFFER_EXTENDED", "DECLINED", "WITHDRAWN",
    )


def assert_audition_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["submission_id"], str)
    assert isinstance(data["casting_director_id"], str)
    assert data["slot_kind"] in ("AUDITION", "CALLBACK")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "RELEASED")


def assert_availability_hold(data: dict):
    _assert_common(data)
    assert isinstance(data["talent_id"], str)
    assert data["hold_kind"] in ("FIRST_REFUSAL", "CONFIRMED_BOOKING")
    assert data["status"] in ("ACTIVE", "RELEASED", "CONFLICTED")


def assert_deal_memo(data: dict):
    _assert_common(data)
    assert isinstance(data["casting_call_id"], str)
    assert isinstance(data["talent_id"], str)
    assert isinstance(data["submission_id"], str)
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data["status"] in (
        "DRAFT", "OFFERED", "COUNTERED", "ACCEPTED", "REJECTED", "VOIDED",
    )


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["deal_memo_id"], str)
    assert isinstance(data["talent_id"], str)
    assert isinstance(data["casting_call_id"], str)
    assert isinstance(data["availability_hold_id"], str)
    assert data["booking_status"] in ("PENDING", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "PAID")


def assert_commission_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["held_cents"], int)
    assert isinstance(data["earned_cents"], int)
    assert data["status"] in ("HELD", "RELEASED", "REVERSED")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["talent_id"], str)
    assert isinstance(data["gross_amount_cents"], int)
    assert data["union_status_snapshot"] in ("SAG", "NON_UNION")
    assert data["status"] == "POSTED"


def assert_residual_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["payment_id"], str)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["residual_amount_cents"], int)
    assert data["status"] in ("DUE", "PAID", "VOID")


def assert_escrow_reconciled(agency: dict, expected_cents: int):
    """Agency.escrow_balance_cents must equal sum of HELD commission held_cents (PRD §2.5)."""
    assert agency["escrow_balance_cents"] == expected_cents, (
        f"Expected escrow_balance_cents == {expected_cents}, "
        f"got {agency['escrow_balance_cents']}"
    )
