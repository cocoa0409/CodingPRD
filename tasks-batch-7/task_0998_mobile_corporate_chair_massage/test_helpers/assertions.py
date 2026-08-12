"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_ledger_style(data: dict):
    """Immutable records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger-style record must not carry updated_at"
    assert "version" not in data, "ledger-style record must not carry version"


def assert_region(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_mileage_rate_cents"], int) and data["base_mileage_rate_cents"] >= 0
    assert isinstance(data["travel_included_miles"], int) and data["travel_included_miles"] >= 0
    assert isinstance(data["setup_buffer_minutes"], int) and data["setup_buffer_minutes"] >= 0
    assert isinstance(data["teardown_buffer_minutes"], int) and data["teardown_buffer_minutes"] >= 0
    assert isinstance(data["is_active"], bool)


def assert_corporate_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert is_valid_uuid(data["region_id"])
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["lifetime_billed_cents"], int)


def assert_wellness_program(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["corporate_account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["cadence"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert isinstance(data["chair_count"], int) and data["chair_count"] >= 1
    assert isinstance(data["slot_minutes"], int) and data["slot_minutes"] >= 5
    assert isinstance(data["window_start_time"], str) and data["window_start_time"]
    assert isinstance(data["window_duration_minutes"], int)
    assert 0.0 <= data["recurrence_discount_pct"] <= 0.50
    assert data["status"] in ("ACTIVE", "PAUSED", "TERMINATED")
    assert isinstance(data["occurrences_materialized"], int)


def assert_therapist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_valid_uuid(data["home_region_id"])
    assert isinstance(data["per_hour_rate_cents"], int) and data["per_hour_rate_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DEACTIVATED")
    assert isinstance(data["max_minutes_per_day"], int) and data["max_minutes_per_day"] >= 30
    assert isinstance(data["rating_avg_x100"], int) and data["rating_avg_x100"] >= 0


def assert_therapist_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["therapist_id"])
    assert is_valid_uuid(data["region_id"])
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["issued_on"], str) and data["issued_on"]
    assert isinstance(data["expires_on"], str) and data["expires_on"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED")
    assert isinstance(data["suspension_reason"], str)


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["corporate_account_id"])
    assert data["booking_kind"] in ("EVENT", "RECURRING_OCCURRENCE")
    assert is_valid_uuid(data["region_id"])
    assert isinstance(data["site_address"], str)
    assert isinstance(data["event_date"], str) and data["event_date"]
    assert 0 <= data["window_start_minutes"] < 1440
    assert data["window_duration_minutes"] >= 30
    assert data["chair_count"] >= 1
    assert data["slot_minutes"] >= 5
    assert data["per_minute_rate_cents"] >= 1
    assert data["status"] in (
        "DRAFT", "SCHEDULING", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID", "DISPUTED", "VOID")
    assert isinstance(data["booked_chair_minutes"], int) and data["booked_chair_minutes"] >= 0
    assert isinstance(data["delivered_chair_minutes"], int) and data["delivered_chair_minutes"] >= 0
    assert isinstance(data["cancellation_fee_cents"], int) and data["cancellation_fee_cents"] >= 0


def assert_chair_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["chair_index"], int) and data["chair_index"] >= 0
    assert data["status"] in (
        "UNASSIGNED", "ASSIGNED", "EN_ROUTE", "ON_SITE",
        "COMPLETED", "NO_SHOW", "RELEASED",
    )


def assert_slot_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["chair_slot_id"])
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["recipient_name"], str) and data["recipient_name"]
    assert isinstance(data["recipient_email"], str) and data["recipient_email"]
    assert isinstance(data["slot_ordinal"], int) and data["slot_ordinal"] >= 0
    assert isinstance(data["start_offset_minutes"], int) and data["start_offset_minutes"] >= 0
    assert data["status"] in ("CLAIMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_travel_leg(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["therapist_id"])
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] >= 0
    assert isinstance(data["travel_fee_cents"], int) and data["travel_fee_cents"] >= 0
    assert data["travel_fee_variant"] in ("QUOTED", "SETTLED")
    assert data["status"] in ("PLANNED", "REIMBURSED", "WAIVED")


def assert_waiver(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["slot_claim_id"])
    assert isinstance(data["signer_email"], str) and data["signer_email"]
    assert is_iso8601_timestamp(data["signed_at"])
    assert isinstance(data["signature_payload"], str) and data["signature_payload"]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["corporate_account_id"])
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "DISPUTED", "VOID")
    assert isinstance(data["chair_minutes_billed"], int) and data["chair_minutes_billed"] >= 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["recurrence_discount_cents"], int) and data["recurrence_discount_cents"] >= 0
    assert isinstance(data["travel_fees_cents"], int) and data["travel_fees_cents"] >= 0
    assert isinstance(data["cancellation_fee_cents"], int) and data["cancellation_fee_cents"] >= 0
    assert isinstance(data["satisfaction_credit_cents"], int) and data["satisfaction_credit_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert data["pricing_variant"] in ("PROVISIONAL", "FINAL")


def assert_satisfaction_survey(data: dict):
    _assert_ledger_style(data)
    assert is_valid_uuid(data["slot_claim_id"])
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert isinstance(data["comment"], str)
    assert is_iso8601_timestamp(data["submitted_at"])


def assert_payout_ledger_entry(data: dict):
    _assert_ledger_style(data)
    assert is_valid_uuid(data["therapist_id"])
    assert is_valid_uuid(data["booking_id"])
    assert data["entry_kind"] in ("EARNING", "TRAVEL_REIMBURSEMENT", "ADJUSTMENT")
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["memo"], str)
