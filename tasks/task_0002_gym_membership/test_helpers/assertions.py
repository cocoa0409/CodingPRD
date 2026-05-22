"""Entity assertions and domain invariant checkers for the gym membership platform."""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountPosture,
    BookingKind,
    BookingStatus,
    ClassSessionStatus,
    CouponApplicableTo,
    CouponKind,
    CouponStatus,
    MemberAccessStatus,
    MemberBillingStatus,
    MemberTier,
    PaymentOutcome,
    ReferralRewardStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)


def _enum_values(enum_cls) -> list:
    return [m.value for m in enum_cls]


def _assert_common_audit(data: Dict[str, Any]) -> None:
    """PRD §2.4: every common-fields entity has id (UUID), created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def _assert_id_and_created_only(data: Dict[str, Any]) -> None:
    """PRD §2.4: PaymentAttempt is append-only and carries only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ──────────────────────────────────────────────────────────
# Entity assertions
# ──────────────────────────────────────────────────────────

def assert_member(data: Dict[str, Any]) -> None:
    """Validate a Member response object against PRD §2.4, §2.6, §3.1."""
    _assert_common_audit(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    # password_hash must never be returned per PRD §3.1.
    assert "password_hash" not in data, "password_hash must never be returned in responses"
    assert "password" not in data, "password must never be returned in responses"
    assert isinstance(data["home_store_id"], str) and len(data["home_store_id"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code must be uppercase ISO 3166-2:US"
    assert data["billing_status"] in _enum_values(MemberBillingStatus)
    assert data["access_status"] in _enum_values(MemberAccessStatus)
    assert data["account_posture"] in _enum_values(AccountPosture)
    # tier is server-set from subscription plan once activated; may be null before.
    if data.get("tier") is not None:
        assert data["tier"] in _enum_values(MemberTier)
    assert isinstance(data["no_show_strike_count"], int)
    assert data["no_show_strike_count"] >= 0
    assert isinstance(data["wallet_credit_cents"], int)


def assert_subscription(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["member_id"], str) and len(data["member_id"]) > 0
    assert data["plan"] in _enum_values(SubscriptionPlan)
    assert data["billing_cycle"] in ("MONTHLY", "ANNUAL")
    assert isinstance(data["base_price_cents"], int)
    assert data["base_price_cents"] > 0
    assert data["status"] in _enum_values(SubscriptionStatus)
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["failed_payment_attempts"], int)
    assert data["failed_payment_attempts"] >= 0


def assert_payment_attempt(data: Dict[str, Any]) -> None:
    """PRD §2.4: PaymentAttempt carries only id + created_at; no updated_at, no version."""
    _assert_id_and_created_only(data)
    assert "updated_at" not in data, "PaymentAttempt must not expose updated_at (append-only)"
    assert "version" not in data, "PaymentAttempt must not expose version (append-only)"
    assert isinstance(data["subscription_id"], str) and len(data["subscription_id"]) > 0
    assert isinstance(data["member_id"], str) and len(data["member_id"]) > 0
    assert isinstance(data["attempt_number"], int)
    assert data["attempt_number"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert isinstance(data["gateway_txn_id"], str)
    assert isinstance(data["idempotency_key"], str)
    assert data["outcome"] in _enum_values(PaymentOutcome)


def assert_store(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["opens_at_local"], str)
    assert isinstance(data["closes_at_local"], str)
    assert isinstance(data["gate_device_id"], str)


def assert_class_session(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["class_type"], str)
    assert isinstance(data["trainer_id"], str)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert data["minimum_tier"] in _enum_values(MemberTier)
    if data.get("equipment_pool_id") is not None:
        assert isinstance(data["equipment_pool_id"], str)
    assert isinstance(data["equipment_units_required"], int)
    assert data["equipment_units_required"] >= 0
    assert isinstance(data["reserved_seat_count"], int)
    assert data["reserved_seat_count"] >= 0
    assert data["status"] in _enum_values(ClassSessionStatus)


def assert_trainer(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["home_store_id"], str)
    assert isinstance(data["certifications"], list)
    assert isinstance(data["hourly_rate_cents"], int)


def assert_equipment_pool(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["equipment_type"], str)
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0


def assert_booking(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["member_id"], str)
    assert data["booking_kind"] in _enum_values(BookingKind)
    assert data["status"] in _enum_values(BookingStatus)
    assert isinstance(data["provisional_price_cents"], int)
    assert data["provisional_price_cents"] >= 0
    # final_price_cents is null until terminal — per PRD §3.6.
    if data.get("final_price_cents") is not None:
        assert isinstance(data["final_price_cents"], int)
        assert data["final_price_cents"] >= 0


def assert_coupon(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["code"], str)
    assert 6 <= len(data["code"]) <= 12, (
        f"PRD §3.8: code length must be 6–12 characters, got {len(data['code'])}"
    )
    assert data["code"].isupper() or all(c.isdigit() or c.isupper() for c in data["code"]), (
        "PRD §3.8: code must be uppercase A–Z and 0–9"
    )
    assert data["kind"] in _enum_values(CouponKind)
    assert isinstance(data["value"], int)
    assert data["applicable_to"] in _enum_values(CouponApplicableTo)
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert isinstance(data["max_redemptions"], int)
    assert data["max_redemptions"] >= 0
    assert isinstance(data["redemption_count"], int)
    assert data["redemption_count"] >= 0
    assert data["status"] in _enum_values(CouponStatus)


def assert_referral_reward(data: Dict[str, Any]) -> None:
    _assert_common_audit(data)
    assert isinstance(data["sponsor_member_id"], str)
    assert isinstance(data["invitee_member_id"], str)
    assert data["status"] in _enum_values(ReferralRewardStatus)


# ──────────────────────────────────────────────────────────
# Domain invariants
# ──────────────────────────────────────────────────────────


def assert_account_posture_invariant(member: Dict[str, Any]) -> None:
    """PRD §2.6 (verbatim derivation): account_posture is FROZEN if access_status is
    SUSPENDED/FROZEN/CANCELLED; else RESTRICTED if billing_status is
    PAST_DUE/GRACE/DELINQUENT; else OPEN if billing in {CURRENT,REINSTATED} and
    access is ACTIVE; else RESTRICTED.
    """
    access = member["access_status"]
    billing = member["billing_status"]
    posture = member["account_posture"]
    if access in ("SUSPENDED", "FROZEN", "CANCELLED"):
        expected = "FROZEN"
    elif billing in ("PAST_DUE", "GRACE", "DELINQUENT"):
        expected = "RESTRICTED"
    elif billing in ("CURRENT", "REINSTATED") and access == "ACTIVE":
        expected = "OPEN"
    else:
        expected = "RESTRICTED"
    assert posture == expected, (
        f"account_posture mismatch (PRD §2.6): "
        f"billing={billing}, access={access} → expected {expected}, got {posture}"
    )
