"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §2.7).

Each assert_{entity}() validates the common-field contract and entity-specific shape.
Mutable entities (PRD §2.4) carry id/created_at/updated_at/version; the two immutable
entities (Certificate, RevenueLedgerEntry) carry only id/created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def _assert_common_immutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable entity must NOT carry version (PRD §2.4)"
    assert "updated_at" not in data, "immutable entity must NOT carry updated_at (PRD §2.4)"


def assert_instructor(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert 0.0 <= data["revenue_share_pct"] <= 1.0, "revenue_share_pct in [0,1] (PRD §3.1)"
    assert isinstance(data["payout_balance_cents"], int)
    assert isinstance(data["pending_balance_cents"], int)
    assert isinstance(data["lifetime_earned_cents"], int)
    assert data["payout_balance_cents"] >= 0, "payout_balance_cents floored at 0 (PRD §2.6)"


def assert_learner(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents floored at 0 (PRD §2.6)"


def assert_course(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["instructor_id"]), "instructor_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "UNPUBLISHED", "RETIRED")
    assert isinstance(data["lesson_count"], int)
    assert isinstance(data["published_lesson_count"], int)
    assert isinstance(data["enrollment_count"], int)
    assert 0.0 <= data["passing_score_pct"] <= 1.0
    assert data["refund_window_days"] >= 0
    assert isinstance(data["drip_enabled"], bool)
    assert data["average_rating"] is None or isinstance(data["average_rating"], (int, float))


def assert_lesson(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["course_id"]), "course_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["order_index"], int) and data["order_index"] >= 1
    assert isinstance(data["is_graded"], bool)
    assert isinstance(data["is_published"], bool)


def assert_coupon(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["instructor_id"])
    assert is_valid_uuid(data["course_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert data["discount_type"] in ("PERCENT", "FLAT")
    assert data["status"] in ("ACTIVE", "DISABLED", "EXHAUSTED")
    assert isinstance(data["redeemed_count"], int) and data["redeemed_count"] >= 0
    assert isinstance(data["max_redemptions"], int) and data["max_redemptions"] >= 1


def assert_bundle(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["instructor_id"])
    assert isinstance(data["course_ids"], list) and len(data["course_ids"]) >= 2
    assert isinstance(data["bundle_price_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["sum_list_price_cents"], int)
    assert isinstance(data["savings_cents"], int)


def assert_enrollment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["learner_id"])
    assert data["status"] in ("ACTIVE", "COMPLETED", "REFUNDED", "EXPIRED")
    assert isinstance(data["gross_price_cents"], int)
    assert isinstance(data["instructor_share_cents"], int)
    assert isinstance(data["platform_fee_cents"], int)
    assert data["platform_fee_cents"] == data["gross_price_cents"] - data["instructor_share_cents"], (
        "platform_fee_cents == gross_price_cents - instructor_share_cents (PRD §3.4)"
    )
    assert is_iso8601_timestamp(data["enrolled_at"]), "enrolled_at must be ISO 8601"


def assert_lesson_completion(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["lesson_id"])
    assert isinstance(data["score_pct"], (int, float))
    assert isinstance(data["passed"], bool)


def assert_review(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert 1 <= data["stars"] <= 5, "stars in [1,5] (PRD §3.10)"
    assert data["status"] in ("PUBLISHED", "HIDDEN", "RETRACTED")


def assert_payout(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["instructor_id"])
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] >= 1
    assert isinstance(data["paid_amount_cents"], int)
    assert data["status"] in ("REQUESTED", "PAID", "REJECTED")


def assert_certificate(data: dict):
    _assert_common_immutable(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["learner_id"])
    assert isinstance(data["ceu_credits"], (int, float))
    assert isinstance(data["final_score_pct"], (int, float))
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"


def assert_ledger_entry(data: dict):
    _assert_common_immutable(data)
    assert is_valid_uuid(data["instructor_id"])
    assert data["entry_type"] in ("SALE", "REFUND", "PAYOUT")
    assert data["status"] in ("PENDING", "AVAILABLE", "CLAWED_BACK", "PAID")
    assert isinstance(data["amount_cents"], int)
