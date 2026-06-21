"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape and field domains the PRD promises
for that resource. The invariant checkers encode the PRD's ledger-conservation
and never-negative-balance rules.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments"


def assert_subject(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["category"] in ["STEM", "LANGUAGE", "HUMANITIES", "TEST_PREP", "MUSIC"]
    assert isinstance(data["requires_credential"], bool)
    assert data["status"] == "ACTIVE"


def assert_commission_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tier_breakpoints_cents"], list)
    assert isinstance(data["tier_rates_bps"], list)
    assert isinstance(data["trial_commission_bps"], int)
    assert isinstance(data["trial_max_billed_minutes"], int)
    assert isinstance(data["refund_window_hours"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]


def assert_tutor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["base_hourly_rate_cents"], int)
    assert data["verification_status"] in [
        "UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "REJECTED", "SUSPENDED"
    ]
    assert isinstance(data["lifetime_net_earnings_cents"], int)
    assert isinstance(data["payout_balance_cents"], int)
    assert data["payout_balance_cents"] >= 0, "payout_balance is never negative"
    assert isinstance(data["clawback_owed_cents"], int)
    assert data["clawback_owed_cents"] >= 0, "clawback is never negative"
    assert isinstance(data["active_subject_count"], int)
    assert isinstance(data["is_payable"], bool)


def assert_credential(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["tutor_id"])
    assert is_valid_uuid(data["subject_id"])
    assert data["kind"] in ["DEGREE", "CERTIFICATION", "TEACHING_LICENSE", "TRANSCRIPT"]
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "EXPIRED"]


def assert_subject_tag(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["tutor_id"])
    assert is_valid_uuid(data["subject_id"])
    assert data["status"] in ["PROPOSED", "APPROVED", "REVOKED"]


def assert_parent_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] == "ACTIVE"
    assert_parent_ledger_invariants(data)


def assert_student(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["parent_account_id"])
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["grade_level"], int)
    assert 1 <= data["grade_level"] <= 13
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["parent_account_id"])
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["tutor_id"])
    assert is_valid_uuid(data["subject_id"])
    assert isinstance(data["planned_minutes"], int)
    assert isinstance(data["is_trial"], bool)
    assert isinstance(data["quoted_rate_cents"], int)
    assert isinstance(data["hold_amount_cents"], int)
    assert data["status"] in [
        "SCHEDULED", "RESCHEDULE_REQUESTED", "DELIVERED", "SETTLED", "CANCELLED", "NO_SHOW"
    ]
    assert isinstance(data["reschedule_count"], int)


def assert_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["tutor_id"])
    assert isinstance(data["billed_minutes"], int)
    assert data["settlement_status"] in [
        "DELIVERED", "SETTLED", "REFUND_OPEN", "REFUNDED", "PARTIALLY_REFUNDED"
    ]
    assert data["delivery_status"] in ["REPORTED", "CONFIRMED", "DISPUTED"]


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["tutor_id"])
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["commission_bps"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["tutor_net_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in ["SETTLED", "REVERSED", "PARTIALLY_REVERSED"]
    # Net is gross minus commission.
    assert data["tutor_net_cents"] == data["gross_amount_cents"] - data["commission_cents"]


def assert_refund_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["parent_account_id"])
    assert is_valid_uuid(data["tutor_id"])
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["parent_offer_cents"], int)
    assert isinstance(data["round_count"], int)
    assert isinstance(data["granted_amount_cents"], int)
    assert data["status"] in [
        "PARENT_PROPOSED", "TUTOR_COUNTERED", "AGREED", "ARBITRATION",
        "RESOLVED_REFUND", "RESOLVED_DENY", "WITHDRAWN"
    ]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_parent_ledger_invariants(data: dict):
    """PRD Section 2.9: wallet == available + held; available is never negative;
    available == wallet - held."""
    wallet = data["wallet_balance_cents"]
    held = data["held_balance_cents"]
    available = data["available_balance_cents"]
    assert available >= 0, "available_balance_cents is never negative"
    assert held >= 0, "held_balance_cents is never negative"
    assert wallet == available + held, (
        f"wallet ({wallet}) must equal available ({available}) + held ({held})"
    )
    assert available == wallet - held, (
        f"available ({available}) must equal wallet ({wallet}) - held ({held})"
    )
