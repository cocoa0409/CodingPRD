"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_creator(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for f in (
        "lifetime_gross_cents", "lifetime_refunded_cents", "lifetime_creator_net_cents",
        "pending_net_cents", "settled_net_cents", "earnings_reserved_cents",
        "earnings_paid_cents", "available_for_payout_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["available_for_payout_cents"] >= 0, "available balance is floored at zero"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_course(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "UNPUBLISHED", "ARCHIVED")
    assert data["refund_window_days"] >= 0
    for f in ("published_lesson_count", "required_quiz_lesson_count",
              "enrollment_count", "completion_count",
              "gross_revenue_cents", "net_settled_revenue_cents"):
        assert isinstance(data[f], int)


def assert_lesson(data: dict):
    _assert_common(data)
    assert data["position"] >= 1
    assert isinstance(data["is_published"], bool)
    assert data["drip_offset_days"] >= 0
    assert isinstance(data["is_quiz_required"], bool)
    assert 0 <= data["quiz_passing_score"] <= 100


def assert_price_plan(data: dict):
    _assert_common(data)
    assert data["plan_type"] in ("ONE_TIME", "SUBSCRIPTION", "PAYMENT_PLAN")
    assert data["amount_cents"] >= 1
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_coupon(data: dict):
    _assert_common(data)
    assert data["discount_type"] in ("PERCENT", "FIXED")
    assert data["discount_value"] >= 1
    assert data["max_redemptions"] >= 1
    assert data["redeemed_count"] >= 0
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_affiliate(data: dict):
    _assert_common(data)
    assert 0 <= data["commission_pct"] <= 100
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for f in ("commission_pending_cents", "commission_clawed_back_cents",
              "referred_revenue_cents"):
        assert isinstance(data[f], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["access_status"] in ("LOCKED", "ACTIVE", "COMPLETED", "REVOKED")
    assert data["billing_status"] in ("PENDING", "CURRENT", "CANCELLED", "REFUNDED")
    assert isinstance(data["raw_progress_pct"], int)
    assert isinstance(data["is_mastery_complete"], bool)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["kind"] in ("INITIAL", "INSTALLMENT", "CYCLE")
    assert data["status"] in ("PENDING", "PAID", "REFUNDED", "VOID")
    assert data["sequence_index"] >= 1
    assert data["amount_cents"] >= 1


def assert_payout(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "PROCESSING", "PAID", "FAILED", "CANCELLED")
    assert data["amount_cents"] >= 1


def assert_quiz_attempt(data: dict):
    """QuizAttempt is an immutable event record: only id + created_at (no version)."""
    _assert_common(data)
    assert 0 <= data["score"] <= 100
    assert isinstance(data["passed"], bool)
