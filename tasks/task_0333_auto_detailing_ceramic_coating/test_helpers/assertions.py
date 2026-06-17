"""Entity assertions and domain invariant checkers.

Per-entity structural assertions validate id/timestamp shape and field types
against the PRD contract. Invariant checkers express the conserved-quantity
rules the PRD states must hold after any operation (the payment-conservation
and credit-conservation identities).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_WORK_STATUSES = [
    "BOOKED", "CHECKED_IN", "IN_PREP", "IN_SERVICE", "CURING",
    "READY", "RELEASED", "CANCELLED", "NO_SHOW",
]
_PAYMENT_STATUSES = ["UNPAID", "DEPOSIT_HELD", "PAID", "REFUNDED"]


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["chronological_lifetime_spend_cents"], int)
    assert isinstance(data["projected_lifetime_spend_cents"], int)
    assert isinstance(data.get("version"), int)


def assert_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["status"] in (
        "PENDING_PAYMENT", "ACTIVE", "PAST_DUE", "CANCELLED", "LAPSED",
    )
    assert data["default_vehicle_size"] in ("SEDAN", "SUV", "TRUCK", "XL")
    assert isinstance(data.get("version"), int)
    assert_credit_conservation(data)


def assert_service_bay(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["bay_code"], str) and len(data["bay_code"]) > 0
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")
    assert isinstance(data["supports_ceramic"], bool)
    assert isinstance(data.get("version"), int)


def assert_mobile_unit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["unit_code"], str) and len(data["unit_code"]) > 0
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")
    assert isinstance(data["travel_buffer_minutes"], int)
    assert isinstance(data.get("version"), int)


def assert_appointment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["tier"] in ("WASH", "FULL", "CERAMIC")
    assert data["vehicle_size"] in ("SEDAN", "SUV", "TRUCK", "XL")
    assert data["location_mode"] in ("SHOP", "MOBILE")
    assert data["work_status"] in _WORK_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_charged_cents"], int)
    assert isinstance(data["amount_refunded_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data.get("version"), int)


def assert_appointment_addon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("appointment_id", "")), "appointment_id must be a UUID"
    assert data["addon_code"] in ("ENGINE_BAY", "PET_HAIR", "HEADLIGHT")
    assert isinstance(data["price_cents_snapshot"], int)
    assert isinstance(data["extra_minutes_snapshot"], int)
    assert data["line_status"] in ("REQUESTED", "PERFORMED", "SKIPPED")


def assert_job_photo(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("appointment_id", "")), "appointment_id must be a UUID"
    assert data["phase"] in ("BEFORE", "AFTER")
    assert isinstance(data["image_url"], str) and len(data["image_url"]) > 0


def assert_rework_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("original_appointment_id", "")), "original_appointment_id must be a UUID"
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "FULFILLED")
    assert isinstance(data.get("version"), int)


def assert_package_catalog(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ("WASH", "FULL", "CERAMIC")
    assert isinstance(data["base_price_cents"], int)


# ─── Domain invariants ────────────────────────────────────────────────

def assert_payment_conservation(data: dict):
    """PRD §3.7: amount_charged - amount_refunded + outstanding ==
    final_total - credit_applied at all times."""
    lhs = (
        data["amount_charged_cents"]
        - data["amount_refunded_cents"]
        + data["outstanding_balance_cents"]
    )
    rhs = data["final_total_cents"] - data["credit_applied_cents"]
    assert lhs == rhs, (
        f"payment conservation broken: charged-refunded+outstanding={lhs}, "
        f"final-credit={rhs}"
    )


def assert_credit_conservation(data: dict):
    """PRD §3.5: credits_granted == credits_consumed + credits_expired +
    credits_remaining, and credits_remaining never negative."""
    granted = data.get("credits_granted_total")
    if granted is None:
        return
    consumed = data["credits_consumed_total"]
    expired = data["credits_expired_total"]
    remaining = data["credits_remaining"]
    assert remaining >= 0, "credits_remaining must never go negative"
    assert granted == consumed + expired + remaining, (
        f"credit conservation broken: granted={granted}, "
        f"consumed+expired+remaining={consumed + expired + remaining}"
    )
