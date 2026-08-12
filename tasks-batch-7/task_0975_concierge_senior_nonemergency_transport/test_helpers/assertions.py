"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DEACTIVATED")
    assert data["mobility_aid"] in ("NONE", "WALKER", "FOLDING_WHEELCHAIR", "POWER_WHEELCHAIR")
    assert data["assist_level_default"] in ("DOOR_TO_DOOR", "DOOR_THROUGH_DOOR")
    assert isinstance(data["home_zone"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["billing_hold_limit_cents"], int)
    assert isinstance(data["no_show_count"], int)


def assert_family_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["relation"], str)
    assert data["access_level"] in ("VIEW_ONLY", "BOOK_FOR_CLIENT", "BILLING_PAYER")
    assert isinstance(data["notify_on_ride_events"], bool)
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_driver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("APPLICANT", "ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert data["vehicle_class"] in ("SEDAN", "WAV")
    assert data["assist_certification"] in ("NONE", "DOOR_TO_DOOR", "DOOR_THROUGH_DOOR")
    assert isinstance(data["home_zone"], str)
    assert isinstance(data["max_daily_service_minutes"], int)


def assert_compliance_doc(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a UUID"
    assert data["doc_type"] in ("BACKGROUND_CHECK", "BONDING", "INSURANCE", "MOTOR_VEHICLE_RECORD")
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "REJECTED", "EXPIRED")
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)


def assert_rate_card(data: dict):
    _assert_common_fields(data)
    assert data["service_class"] in ("STANDARD", "WAV")
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    for field in ("hourly_rate_cents", "per_mile_cents", "wait_per_minute_cents",
                  "included_wait_minutes", "minimum_charge_cents",
                  "after_hours_multiplier_bp", "after_hours_start_minute",
                  "wav_surcharge_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_standing_ride(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["pickup_time_of_day_minutes"], int)
    assert data["kind"] in ("GROCERY", "APPOINTMENT", "COMPANION_OUTING")
    assert isinstance(data["estimated_duration_minutes"], int)
    assert isinstance(data["estimated_distance_miles"], int)
    assert data["status"] in ("ACTIVE", "PAUSED", "ENDED")


def assert_ride(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["kind"] in ("GROCERY", "APPOINTMENT", "COMPANION_OUTING")
    assert is_iso8601_timestamp(data.get("scheduled_pickup_at", "")), \
        "scheduled_pickup_at must be ISO 8601"
    assert isinstance(data["estimated_duration_minutes"], int)
    assert isinstance(data["estimated_distance_miles"], int)
    assert isinstance(data["requires_wav"], bool)
    assert data["service_class"] in ("STANDARD", "WAV")
    assert data["assist_level"] in ("DOOR_TO_DOOR", "DOOR_THROUGH_DOOR")
    assert data["status"] in ("SCHEDULED", "DISPATCHING", "ASSIGNED", "EN_ROUTE",
                              "ARRIVED", "IN_SERVICE", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["dispatch_round"], int)
    assert isinstance(data["excluded_driver_ids"], list)
    assert isinstance(data["quoted_fare_cents"], int)
    assert isinstance(data["cancellation_fee_cents"], int)
    assert isinstance(data["no_show_fee_cents"], int)


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("ride_id", "")), "ride_id must be a UUID"
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a UUID"
    assert isinstance(data["round"], int)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "RELEASED")
    assert is_iso8601_timestamp(data.get("offered_at", "")), "offered_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("offer_expires_at", "")), \
        "offer_expires_at must be ISO 8601"
    assert data["matched_by"] == "COORDINATOR"


def assert_ride_event(data: dict):
    # RideEvent is an immutable ledger entry: only id + created_at of the
    # common fields; updated_at and version are absent by design (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "RideEvent must not expose updated_at"
    assert "version" not in data, "RideEvent must not expose version"
    assert is_valid_uuid(data.get("ride_id", "")), "ride_id must be a UUID"
    assert data["event_type"] in (
        "CREATED", "DISPATCHED", "OFFERED", "ACCEPTED", "DECLINED", "RELEASED",
        "EN_ROUTE", "ARRIVED", "WAIT_STARTED", "WAIT_ENDED", "SERVICE_STARTED",
        "COMPLETED", "CANCELLED", "NO_SHOW_RECORDED",
    )
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["issuance_status"] in ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOIDED")
    assert data["dispute_status"] in ("NONE", "DISPUTED", "RESOLVED_ACCEPTED", "RESOLVED_REJECTED")
    for field in ("charges_cents", "credit_applied_cents", "total_due_cents",
                  "paid_cents", "resolution_credit_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["due_date"], str)
    assert isinstance(data["past_due"], bool)


def assert_invoice_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("invoice_id", "")), "invoice_id must be a UUID"
    assert is_valid_uuid(data.get("ride_id", "")), "ride_id must be a UUID"
    assert data["line_kind"] in ("HOURLY", "MILEAGE", "WAIT", "WAV_SURCHARGE",
                                 "MINIMUM_ADJUSTMENT", "CANCELLATION_FEE", "NO_SHOW_FEE")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_rate_cents"], int)
    assert isinstance(data["amount_cents"], int)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in ("CARD", "ACH", "CHECK")
    assert data["status"] in ("SETTLED", "PARTIALLY_REFUNDED", "REFUNDED")
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["applications"], list)


def assert_invoice_money_invariants(invoice: dict):
    """Money invariants that must hold on any invoice row."""
    assert invoice["total_due_cents"] == invoice["charges_cents"] - invoice["credit_applied_cents"], \
        "total_due_cents must equal charges_cents - credit_applied_cents"
    assert invoice["credit_applied_cents"] >= 0
    assert invoice["paid_cents"] >= 0
