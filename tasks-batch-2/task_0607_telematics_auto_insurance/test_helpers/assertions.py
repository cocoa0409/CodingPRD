"""Entity assertions and domain invariant checkers (PRD §2, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for non-append-only entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """id + created_at only for append-only audit facts (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_rate_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["base_premium_cents"], int) and data["base_premium_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["telematics_opted_out"], bool)
    assert isinstance(data["lifetime_safe_miles"], (int, float))
    assert data["lifetime_safe_miles"] >= 0, "lifetime_safe_miles is a conserved odometer >= 0"
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["rate_plan_id"], str)
    assert isinstance(data["scoring_days"], int)
    assert data["status"] in ("SCORING", "READY_TO_QUOTE", "QUOTED", "EXPIRED", "ABANDONED")
    assert isinstance(data["captured_trip_count"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["rate_plan_id"], str)
    assert isinstance(data["quoted_annual_premium_cents"], int)
    assert data["status"] in ("OPEN", "BOUND", "EXPIRED", "DECLINED")


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["rate_plan_id"], str)
    assert isinstance(data["bound_premium_cents"], int)
    assert isinstance(data["period_index"], int)
    assert data["billing_status"] in ("PERIOD_OPEN", "PERIOD_CLOSING", "PERIOD_SETTLED")
    assert data["telematics_status"] in ("CAPTURING", "SUSPENDED")
    assert data["lifecycle_status"] in ("ACTIVE", "LAPSED", "CANCELLED")


def assert_trip(data: dict):
    _assert_common(data)
    assert isinstance(data["distance_miles"], (int, float))
    assert isinstance(data["hard_brake_count"], int)
    assert isinstance(data["speeding_count"], int)
    assert isinstance(data["phone_use_count"], int)
    assert isinstance(data["crash_detected"], bool)
    assert data["status"] in ("OPEN", "ACCEPTED", "REJECTED", "VOIDED")


def assert_trip_event(data: dict):
    _assert_append_only(data)
    assert data["event_type"] in ("HARD_BRAKE", "SPEEDING", "PHONE_USE", "CRASH")
    assert isinstance(data["severity"], int)
    assert isinstance(data["trip_id"], str)


def assert_risk_snapshot(data: dict):
    _assert_append_only(data)
    assert isinstance(data["policy_id"], str)
    assert data["trigger_reason"] in ("TRIP_ACCEPTED", "TRIP_VOIDED", "RENEWAL", "MANUAL")
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["risk_multiplier"], (int, float))


def assert_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["base_charge_cents"], int)
    assert isinstance(data["mileage_charge_cents"], int)
    assert isinstance(data["applied_discount_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["total_due_cents"] >= 0, "total_due_cents non-negative by construction (PRD §3.6)"
    assert data["status"] in ("DRAFT", "ISSUED", "SETTLED", "VOIDED")


def assert_renewal(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["prior_premium_cents"], int)
    assert isinstance(data["recalculated_premium_cents"], int)
    assert data["status"] in ("PROPOSED", "ACCEPTED", "DECLINED")


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert data["origin"] in ("AUTO_FNOL", "MANUAL")
    assert isinstance(data["reported_severity"], int)
    assert isinstance(data["reserve_cents"], int)
    assert isinstance(data["reopen_count"], int)
    assert data["status"] in ("FNOL", "UNDER_REVIEW", "CLOSED", "REOPENED")


def assert_discount_bank(data: dict):
    _assert_common(data)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["earned_cents"], int)
    assert isinstance(data["redeemed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert_discount_bank_invariants(data)


def assert_discount_bank_invariants(data: dict):
    """available = earned - redeemed, and available never negative (PRD §2.6, §3.10)."""
    assert data["available_cents"] == data["earned_cents"] - data["redeemed_cents"], \
        "available_cents == earned_cents - redeemed_cents"
    assert data["available_cents"] >= 0, "available_cents may never go negative"


def assert_discount_grant(data: dict):
    _assert_append_only(data)
    assert isinstance(data["discount_bank_id"], str)
    assert data["leg"] in ("EARN", "REDEEM", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert data["source_reason"] in (
        "SAFE_TRIP", "STATEMENT_REDEEM", "RENEWAL_REDEEM", "TRIP_VOID_REVERSAL"
    )
