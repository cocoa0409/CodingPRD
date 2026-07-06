"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def calendar_date(iso: str) -> str:
    """Return the calendar-day (YYYY-MM-DD) portion of an ISO 8601 datetime."""
    assert isinstance(iso, str) and len(iso) >= 10, f"expected ISO datetime, got {iso!r}"
    return iso[:10]


def assert_same_calendar_date(actual_iso: str, expected_iso: str, label: str = "date"):
    assert calendar_date(actual_iso) == calendar_date(expected_iso), (
        f"{label}: expected calendar day {calendar_date(expected_iso)}, got {actual_iso!r}"
    )


def assert_work(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["registration_status"] in ("UNREGISTERED", "PENDING", "REGISTERED")
    assert isinstance(data["owner_shares"], list) and len(data["owner_shares"]) >= 1
    total = sum(s["share_bps"] for s in data["owner_shares"])
    assert total == 10000, f"owner_shares must sum to 10000, got {total}"
    assert isinstance(data["current_owner_name"], str) and len(data["current_owner_name"]) > 0


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_EXAMINATION", "CORRESPONDENCE",
        "REGISTERED", "REFUSED", "WITHDRAWN",
    )
    assert isinstance(data["claimant_count"], int) and data["claimant_count"] >= 1
    # net_fee_cents is a conserved quantity: fee_paid - fee_refunded (PRD §2.9).
    assert data["net_fee_cents"] == data["fee_paid_cents"] - data["fee_refunded_cents"], (
        "net_fee_cents must equal fee_paid_cents - fee_refunded_cents"
    )


def assert_deposit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DEFICIENT")
    assert isinstance(data["copy_count"], int)


def assert_certificate(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "RENEWED")
    assert isinstance(data["registration_number"], str) and len(data["registration_number"]) > 0
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["decision_date"])


def assert_recordation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "SUPERSEDED")


def assert_license(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "UNDER_REVIEW", "TERMINATED")
    assert data["escrow_balance_cents"] >= 0, "escrow_balance_cents must never be negative"


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "POSTED", "DISTRIBUTED", "REVERSED", "VOIDED")


def assert_dmca_takedown(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "EFFECTIVE", "COUNTERED", "RESTORED", "WITHDRAWN")


def assert_counter_notice(data: dict):
    _assert_common(data)
    assert data["status"] in ("FORWARDED", "COMPLETE")


def assert_termination(data: dict):
    _assert_common(data)
    assert data["status"] in ("NOTICE_SERVED", "EFFECTIVE")
