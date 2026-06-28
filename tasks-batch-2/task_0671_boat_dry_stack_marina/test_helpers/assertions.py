"""Entity assertions and domain invariant checkers.

Uses framework generic validators (is_valid_uuid, is_iso8601_timestamp) internally.
Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_marina(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["forklift_service_minutes"], int)
    assert data["forklift_service_minutes"] >= 1
    assert isinstance(data["forklift_buffer_minutes"], int)
    assert data["forklift_buffer_minutes"] >= 0


def assert_forklift(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["max_lift_weight_lbs"], int) and data["max_lift_weight_lbs"] > 0
    assert data["status"] in ("AVAILABLE",)


def assert_rack(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_label"], str) and len(data["bay_label"]) > 0
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["status"] in ("AVAILABLE", "OCCUPIED")
    assert data["max_loa_ft"] > 0
    assert data["max_beam_ft"] > 0
    assert isinstance(data["max_weight_lbs"], int) and data["max_weight_lbs"] > 0


def assert_vessel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["loa_ft"] > 0
    assert data["beam_ft"] > 0
    assert isinstance(data["dry_weight_lbs"], int) and data["dry_weight_lbs"] > 0
    assert data["location_status"] in ("OFF_SITE", "RACKED", "IN_WATER")
    assert data["billing_status"] in (
        "UNBILLED", "ACTIVE_STORAGE", "WINTER_HOLD", "DELINQUENT", "CLOSED",
    )


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["account_balance_cents"], int)
    assert data["account_balance_cents"] >= 0, "account_balance_cents is never below zero"


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_name"], str) and len(data["carrier_name"]) > 0
    assert isinstance(data["liability_limit_cents"], int) and data["liability_limit_cents"] > 0
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")


def assert_storage_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_COI", "ACTIVE", "WINTERIZED", "TERMINATED")
    assert isinstance(data["monthly_base_cents"], int)
    assert isinstance(data["oversize_surcharge_applied"], bool)


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["requested_size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert isinstance(data["deposit_paid"], bool)
    assert isinstance(data["priority_score"], int)
    assert data["status"] in ("WAITING", "OFFERED", "PLACED", "EXPIRED", "WITHDRAWN")


def assert_launch_request(data: dict):
    _assert_common(data)
    assert isinstance(data["with_valet_splash"], bool)
    assert isinstance(data["launch_fee_cents"], int)
    assert data["status"] in ("REQUESTED", "SCHEDULED", "SPLASHED", "RACKED", "CANCELLED")


def assert_forklift_slot(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["window_start"]), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data["window_end"]), "window_end must be ISO 8601"
    assert is_iso8601_timestamp(data["busy_until"]), "busy_until must be ISO 8601"
    assert data["status"] in ("BOOKED", "COMPLETED", "RELEASED")


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["service_kind"] in ("FUEL", "VALET_SPLASH", "WINTERIZATION", "HAUL_OUT")
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("ORDERED", "FULFILLED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["source_kind"] in ("STORAGE_AGREEMENT", "LAUNCH_REQUEST", "SERVICE_ORDER")
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ISSUED", "PAID", "VOIDED")
