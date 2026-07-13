"""Entity assertions and domain invariant checkers for the Charity
Donation-Pickup contract. Uses the framework's generic format validators.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_charity_partner(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str)
    assert isinstance(data["tax_id"], str)
    assert isinstance(data["accepted_categories"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["ytd_donation_value_cents"], int)
    assert isinstance(data["diverted_weight_lbs"], int)


def assert_vehicle(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["capacity_cf"], int) and data["capacity_cf"] > 0
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_route(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED")
    assert isinstance(data["reserved_volume_cf"], int) and data["reserved_volume_cf"] >= 0
    assert isinstance(data["total_stop_count"], int) and data["total_stop_count"] >= 0
    assert isinstance(data["serviced_stop_count"], int) and data["serviced_stop_count"] >= 0


def assert_donor(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["email"], str)
    assert data["status"] == "ACTIVE"


def assert_recurring_plan(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert data["default_disposition"] in ("DONATION", "HAUL")
    assert data["frequency"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert data["pickup_mode"] in ("ATTENDED", "UNATTENDED")


def assert_pickup_request(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["disposition"] in ("DONATION", "HAUL")
    assert data["pickup_mode"] in ("ATTENDED", "UNATTENDED")
    assert isinstance(data["declared_volume_cf"], int) and data["declared_volume_cf"] >= 0
    assert isinstance(data["is_free_donation"], bool)
    assert isinstance(data["estimated_haul_fee_cents"], int)


def assert_donation_item(data: dict):
    _assert_audit_fields(data)
    assert data["category"] in ("FURNITURE", "CLOTHING", "ELECTRONICS", "APPLIANCE", "HOUSEHOLD")
    assert isinstance(data["volume_cf"], int) and data["volume_cf"] > 0
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] >= 0
    assert data["declared_condition"] in ("NEW", "GOOD", "FAIR", "POOR")


def assert_route_stop(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("RESERVED", "SERVICED", "CANCELLED")
    assert isinstance(data["reserved_volume_cf"], int)


def assert_donation_receipt(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("ISSUED", "VOIDED")
    assert isinstance(data["provisional_value_cents"], int)
    assert isinstance(data["final_value_cents"], int)


def assert_haul_invoice(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ("INVOICED", "PAID")
    assert isinstance(data["estimate_cents"], int)
    assert isinstance(data["final_cents"], int)
    assert isinstance(data["diversion_credit_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    # amount_due is never below zero (Section 3.6).
    assert data["amount_due_cents"] >= 0
