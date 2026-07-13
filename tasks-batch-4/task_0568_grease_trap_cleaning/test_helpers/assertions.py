"""Entity assertions and domain invariant checkers for the FOG Compliance Service API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["municipality_code"], str)
    assert data["compliance_status"] in ("COMPLIANT", "AT_RISK", "NON_COMPLIANT")
    assert data["projected_compliance_status"] in ("COMPLIANT", "AT_RISK", "NON_COMPLIANT")


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert data["equipment_type"] in ("GREASE_TRAP", "HOOD")
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")
    assert data["service_state"] in ("CURRENT", "DUE_SOON", "OVERDUE")
    assert isinstance(data["lifetime_pumped_gallons"], (int, float))
    assert data["lifetime_pumped_gallons"] >= 0


def assert_service_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["billing_cycle"] in ("MONTHLY", "QUARTERLY")
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["tax_rate_bps"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CANCELLED")


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["certification_level"] in ("BASIC", "NFPA96_CERTIFIED")
    assert data["status"] in ("AVAILABLE", "INACTIVE")


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["equipment_id"], str)
    assert data["service_type"] in ("SCHEDULED", "EMERGENCY")
    assert data["priority"] in ("ROUTINE", "URGENT")
    assert data["status"] in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["emergency_surcharge_cents"], int)


def assert_manifest(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert data["compliance_flag"] in ("COMPLIANT", "NON_COMPLIANT")
    assert data["status"] in ("RECORDED", "VOIDED")
    assert isinstance(data["disposal_fee_cents"], int)
    assert isinstance(data["volume_gallons"], (int, float))


def assert_hood_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["work_order_id"], str)
    assert data["cleanliness_grade"] in ("BARE_METAL_CLEAN", "ACCEPTABLE", "FAILING")


def assert_compliance_report(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert isinstance(data["total_amount_cents"], int)
