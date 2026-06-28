"""Entity assertions and domain invariant checkers for the Pet Cremation API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_fields(data: dict):
    """Full audit fields present on a versioned resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_minimal_append_only(data: dict):
    """Append-only resource carries only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only resource must not expose version"
    assert "updated_at" not in data, "append-only resource must not expose updated_at"


def assert_clinic(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["account_code"], str) and len(data["account_code"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, "outstanding balance never negative"
    assert data["account_status"] in ("CURRENT", "DELINQUENT")


def assert_petowner(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["phone"], str)


def assert_cooler(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["total_capacity"], int) and data["total_capacity"] >= 1
    assert isinstance(data["occupied_count"], int) and data["occupied_count"] >= 0
    assert isinstance(data["available_capacity"], int)
    assert data["available_capacity"] >= 0, "available_capacity floored at zero"
    assert data["status"] in ("AVAILABLE", "FULL")


def assert_retort(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["max_load_lbs"], int) and data["max_load_lbs"] >= 1


def assert_batch(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("retort_id", "")), "retort_id must be a UUID"
    assert data["service_type"] in ("PRIVATE", "COMMUNAL")
    assert data["status"] in ("OPEN", "LOADED", "FIRING", "COMPLETED", "RECONCILED")
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert isinstance(data["loaded_weight_lbs"], int) and data["loaded_weight_lbs"] >= 0
    assert isinstance(data["communal_firing_total_cents"], int)


def assert_case(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("owner_id", "")), "owner_id must be a UUID"
    assert isinstance(data["pet_name"], str) and len(data["pet_name"]) > 0
    assert data["species"] in ("DOG", "CAT", "OTHER")
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] >= 1
    assert data["weight_tier"] in ("SMALL", "MEDIUM", "LARGE", "XLARGE")
    assert data["service_type"] in ("PRIVATE", "COMMUNAL")
    assert isinstance(data["expedited"], bool)
    assert data["pickup_kind"] in ("CLINIC", "HOME")
    assert data["bill_to"] in ("CLINIC_ACCOUNT", "OWNER")
    assert data["custody_status"] in (
        "INTAKE_PENDING", "IN_TRANSIT", "RECEIVED", "IN_COOLER", "STAGED",
        "CREMATED", "READY_FOR_RETURN", "RETURNED", "CANCELLED",
    )
    assert data["billing_status"] in ("NOT_BILLABLE", "BILLABLE", "INVOICED", "SETTLED")
    assert isinstance(data["cremation_charge_cents"], int)
    assert isinstance(data["custody_chain_open"], bool)


def assert_transport_leg(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["origin_kind"] in ("CLINIC", "HOME")
    assert isinstance(data["origin_label"], str)
    assert isinstance(data["driver_name"], str)
    assert data["status"] in ("ASSIGNED", "EN_ROUTE", "ARRIVED", "CANCELLED")


def assert_keepsake(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["item_type"] in (
        "PAW_PRINT", "CLAY_IMPRESSION", "FUR_CLIPPING", "URN", "PENDANT")
    assert isinstance(data["unit_price_cents"], int)
    assert data["status"] in ("ORDERED", "IN_PRODUCTION", "READY", "CANCELLED")


def assert_return_route(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["return_method"] in (
        "PICKUP_AT_FACILITY", "COURIER_TO_CLINIC", "COURIER_TO_HOME")
    assert isinstance(data["destination_label"], str)
    assert data["status"] in ("PLANNED", "DISPATCHED", "DELIVERED", "CANCELLED")


def assert_memorial_addon(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["addon_type"] in ("ONLINE_MEMORIAL", "VIEWING_SESSION", "TRIBUTE_VIDEO")
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ("BOOKED", "FULFILLED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data["bill_to"] in ("CLINIC_ACCOUNT", "OWNER")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["handling_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["handling_fee_cents"], \
        "total must equal subtotal + handling fee"
    assert data["status"] in ("ISSUED", "PAID", "VOID")


def assert_custody_event(data: dict):
    _assert_minimal_append_only(data)
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert isinstance(data["event_type"], str)
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_certificate(data: dict):
    _assert_minimal_append_only(data)
    assert isinstance(data["certificate_number"], str) or isinstance(data["certificate_number"], int)
    assert data["status"] in ("ISSUED", "VOID")
