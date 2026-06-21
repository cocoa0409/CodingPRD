"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


STUDENT_STATUSES = [
    "PROSPECT", "ENROLLED", "PERMITTED", "ROAD_READY", "CERTIFIED", "LICENSED",
]
ENROLLMENT_STATUSES = ["DRAFT", "ACTIVE", "COMPLETED", "CANCELLED", "REFUNDED"]
LESSON_STATUSES = ["SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]
LESSON_TYPES = ["CLASSROOM", "ONLINE", "ROAD"]
CONSENT_STATUSES = ["PENDING", "GRANTED", "REVOKED"]
CERTIFICATE_STATUSES = ["ISSUED", "SUBMITTED", "ACCEPTED", "REJECTED"]
WALLET_REASONS = ["REFUND_CREDIT", "NO_SHOW_DEBIT", "ADMIN_ADJUSTMENT"]


def _assert_common_full(data: dict):
    """Full resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_common_ledger(data: dict):
    """Ledger-style resources carry ONLY id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"


# ---------------------------------------------------------------------------
# Full resources
# ---------------------------------------------------------------------------
def assert_student(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] in STUDENT_STATUSES, f"bad status {data['status']}"
    assert isinstance(data["is_minor"], bool)
    for ledger in (
        "completed_classroom_hours", "completed_online_hours",
        "completed_road_hours", "scheduled_road_hours",
    ):
        assert data[ledger] >= 0, f"{ledger} must be >= 0"
    assert 0.0 <= data["readiness_score"] <= 1.0, "readiness_score in [0,1]"
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert isinstance(data["wallet_balance_cents"], int)


def assert_guardian_consent(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be UUID"
    assert data["status"] in CONSENT_STATUSES
    assert data["relationship"] in ["PARENT", "LEGAL_GUARDIAN"]


def assert_enrollment(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be UUID"
    assert is_valid_uuid(data.get("package_id", "")), "package_id must be UUID"
    assert data["status"] in ENROLLMENT_STATUSES
    assert isinstance(data["final_price_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    if data.get("refund_method") is not None:
        assert data["refund_method"] in ["PRO_RATA", "SCHEDULE_TIER"]


def assert_instructor(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["certified_road"], bool)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_vehicle(data: dict):
    _assert_common_full(data)
    assert isinstance(data["plate"], str) and len(data["plate"]) > 0
    assert isinstance(data["dual_control"], bool)
    assert isinstance(data["prep_buffer_minutes"], int) and data["prep_buffer_minutes"] >= 0
    assert isinstance(data["out_of_service"], bool)


def assert_lesson(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be UUID"
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert data["lesson_type"] in LESSON_TYPES
    assert data["status"] in LESSON_STATUSES
    assert is_iso8601_timestamp(data["start_at"]), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data["end_at"]), "end_at must be ISO 8601"
    assert data["duration_hours"] >= 0


def assert_certificate(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be UUID"
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be UUID"
    assert data["status"] in CERTIFICATE_STATUSES


# ---------------------------------------------------------------------------
# Ledger-style resources
# ---------------------------------------------------------------------------
def assert_course_package(data: dict):
    _assert_common_ledger(data)
    assert "updated_at" not in data, "CoursePackage must NOT expose updated_at"
    assert "version" not in data, "CoursePackage must NOT expose version"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["enrollment_fee_cents"], int)
    assert 0 <= data["enrollment_fee_cents"] <= data["price_cents"]
    for hrs in ("included_classroom_hours", "included_online_hours", "included_road_hours"):
        assert data[hrs] >= 0
    assert isinstance(data["active"], bool)


def assert_no_show_strike(data: dict):
    _assert_common_ledger(data)
    assert "updated_at" not in data, "NoShowStrike must NOT expose updated_at"
    assert "version" not in data, "NoShowStrike must NOT expose version"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be UUID"
    assert is_valid_uuid(data.get("lesson_id", "")), "lesson_id must be UUID"
    assert isinstance(data["strike_index"], int) and data["strike_index"] >= 1
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0


def assert_wallet_entry(data: dict):
    _assert_common_ledger(data)
    assert "updated_at" not in data, "WalletEntry must NOT expose updated_at"
    assert "version" not in data, "WalletEntry must NOT expose version"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in WALLET_REASONS


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_money_conserved(amount_paid_cents: int, refunded_cents: int,
                           wallet_balance_cents: int):
    """§2.9 wallet principle: after a wallet-only refund, the money the school
    keeps (amount_paid - refunded) plus the student's wallet balance equals the
    original amount paid — no money created or destroyed."""
    recognized = amount_paid_cents - refunded_cents
    assert recognized + wallet_balance_cents == amount_paid_cents, (
        f"money drift: recognized {recognized} + wallet {wallet_balance_cents} "
        f"!= amount_paid {amount_paid_cents}"
    )


def assert_road_hours_conserved(completed: float, scheduled: float,
                                available: float, included: float):
    """Road-hour ledger conservation: completed + scheduled + available == included."""
    assert completed + scheduled + available == included, (
        f"hour drift: completed {completed} + scheduled {scheduled} + "
        f"available {available} != included {included}"
    )
