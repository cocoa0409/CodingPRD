"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_MEMBERSHIP_STATES = ["PENDING", "ACTIVE", "FROZEN", "CANCELLED"]
_DUES_STATES = ["CURRENT", "PAST_DUE", "DELINQUENT", "SUSPENDED"]
_CONTRACT_STATES = ["IN_COOLING_OFF", "IN_TERM", "FULFILLED", "TERMINATED"]
_SESSION_STATES = ["SCHEDULED", "CANCELLED", "COMPLETED"]
_BOOKING_STATES = ["BOOKED", "WAITLISTED", "ATTENDED", "CANCELLED", "NO_SHOW"]
_PT_PACKAGE_STATES = ["ACTIVE", "EXHAUSTED", "VOID"]
_PT_SESSION_STATES = ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]
_INVOICE_STATES = ["OPEN", "PAID", "VOID"]
_GUEST_PASS_STATES = ["ISSUED", "REDEEMED", "EXPIRED", "REVOKED"]
_CHECKIN_STATES = ["OPEN", "CLOSED"]


def assert_membership_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "plan id must be valid UUID"
    assert data["tier"] in ["BASIC", "PLUS", "ELITE"], f"unexpected tier {data.get('tier')}"
    assert isinstance(data["monthly_dues_cents"], int) and data["monthly_dues_cents"] >= 0
    assert isinstance(data["included_class_credits"], int) and data["included_class_credits"] >= 0
    assert 0.0 <= data["pt_discount_pct"] <= 0.5
    assert isinstance(data["contract_term_months"], int) and data["contract_term_months"] >= 1
    assert isinstance(data["early_termination_fee_cents"], int) and data["early_termination_fee_cents"] >= 0
    assert isinstance(data["max_freeze_days_per_term"], int) and data["max_freeze_days_per_term"] >= 0
    assert isinstance(data["guest_passes_per_cycle"], int) and data["guest_passes_per_cycle"] >= 0
    assert isinstance(data["archived"], bool)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_location(data: dict):
    assert is_valid_uuid(data.get("id", "")), "location id must be valid UUID"
    assert isinstance(data["name"], str)
    assert isinstance(data["occupancy_cap"], int) and data["occupancy_cap"] >= 1
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be valid UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be valid UUID"
    assert is_valid_uuid(data.get("home_location_id", "")), "home_location_id must be valid UUID"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["membership_status"] in _MEMBERSHIP_STATES
    assert data["dues_status"] in _DUES_STATES
    assert data["contract_status"] in _CONTRACT_STATES
    assert isinstance(data["class_credits_remaining"], int) and data["class_credits_remaining"] >= 0
    assert isinstance(data["guest_passes_remaining"], int) and data["guest_passes_remaining"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["cumulative_freeze_days"], int) and data["cumulative_freeze_days"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_member_invariants(data: dict):
    """Money/occupancy floors and credit sanity that must hold after any operation."""
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents has a hard floor of zero"
    assert data["class_credits_remaining"] >= 0, "class_credits_remaining never negative"
    assert data["guest_passes_remaining"] >= 0, "guest_passes_remaining never negative"
    assert data["cumulative_freeze_days"] >= 0, "cumulative_freeze_days never negative"
    if data["dues_status"] == "CURRENT":
        assert data["past_due_since"] is None, "past_due_since is null when CURRENT"


def assert_class_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "session id must be valid UUID"
    assert is_valid_uuid(data.get("location_id", ""))
    assert isinstance(data["title"], str)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["waitlist_cap"], int) and data["waitlist_cap"] >= 0
    assert data["status"] in _SESSION_STATES
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["waitlisted_count"], int) and data["waitlisted_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_session_count_invariants(data: dict):
    """booked_count <= capacity and waitlisted_count <= waitlist_cap (PRD §2.6)."""
    assert data["booked_count"] <= data["capacity"], "booked_count never exceeds capacity"
    assert data["waitlisted_count"] <= data["waitlist_cap"], "waitlisted_count never exceeds waitlist_cap"


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "booking id must be valid UUID"
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["status"] in _BOOKING_STATES
    assert isinstance(data["credit_charged"], bool)
    if data["status"] == "WAITLISTED":
        assert isinstance(data["waitlist_position"], int) and data["waitlist_position"] >= 1
    else:
        assert data["waitlist_position"] is None, "waitlist_position is null unless WAITLISTED"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pt_package(data: dict):
    assert is_valid_uuid(data.get("id", "")), "package id must be valid UUID"
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["sessions_purchased"], int) and data["sessions_purchased"] >= 1
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["price_paid_cents"], int) and data["price_paid_cents"] >= 0
    assert isinstance(data["sessions_remaining"], int) and data["sessions_remaining"] >= 0
    assert data["status"] in _PT_PACKAGE_STATES
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pt_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "pt session id must be valid UUID"
    assert is_valid_uuid(data.get("package_id", ""))
    assert isinstance(data["trainer_name"], str)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert data["status"] in _PT_SESSION_STATES
    assert isinstance(data["deducted"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_dues_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "invoice id must be valid UUID"
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 0
    assert isinstance(data["wallet_applied_cents"], int) and data["wallet_applied_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert data["status"] in _INVOICE_STATES
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_guest_pass(data: dict):
    assert is_valid_uuid(data.get("id", "")), "guest pass id must be valid UUID"
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["guest_name"], str)
    assert is_valid_uuid(data.get("location_id", ""))
    assert data["status"] in _GUEST_PASS_STATES
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_check_in(data: dict):
    """CheckIn is append-only: carries only id and created_at (no version, no updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "check-in id must be valid UUID"
    assert is_valid_uuid(data.get("location_id", ""))
    assert data["actor_kind"] in ["MEMBER", "GUEST"]
    assert data["status"] in _CHECKIN_STATES
    assert is_iso8601_timestamp(data.get("created_at", ""))
