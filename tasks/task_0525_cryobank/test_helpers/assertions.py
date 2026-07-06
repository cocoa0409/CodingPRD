"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_donor(data: dict):
    _assert_common(data)
    assert isinstance(data["display_code"], str) and data["display_code"]
    assert data["donor_type"] in ("SPERM", "OOCYTE")
    assert data["blood_type"] in ("A_POS", "A_NEG", "B_POS", "B_NEG",
                                  "AB_POS", "AB_NEG", "O_POS", "O_NEG")
    assert data["status"] in ("APPLICANT", "SCREENING", "APPROVED",
                              "ACTIVE", "DEFERRED", "RETIRED")
    assert isinstance(data["family_limit"], int)
    assert isinstance(data["reported_family_count"], int)
    assert isinstance(data["is_family_limit_reached"], bool)


def assert_donor_inventory(data: dict):
    _assert_common(data)
    assert data["hold_status"] in ("OPEN", "FROZEN")
    assert isinstance(data["total_vials"], int)
    assert isinstance(data["reserved_vials"], int)
    assert isinstance(data["shipped_vials"], int)
    assert isinstance(data["available_vials"], int)
    assert isinstance(data["committed_available_vials"], int)
    assert isinstance(data["is_listed"], bool)


def assert_inventory_pool_conserved(data: dict):
    """PRD §3.5 vial-pool invariant: total == available + reserved + shipped."""
    assert data["total_vials"] == (
        data["available_vials"] + data["reserved_vials"] + data["shipped_vials"]
    ), (f"pool not conserved: total={data['total_vials']} != "
        f"available={data['available_vials']} + reserved={data['reserved_vials']} "
        f"+ shipped={data['shipped_vials']}")


def assert_vial_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "CONFIRMED", "SHIPPED", "CANCELLED", "EXPIRED")
    assert isinstance(data["vial_count"], int)


def assert_storage_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert data["billing_mode"] in ("RENEWAL", "LAPSE")
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer cents"


def assert_storage_account(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "LAPSED", "CLOSED")


def assert_screening_application(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DEFERRED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PREPARING", "DISPATCHED", "DELIVERED", "CANCELLED")


def assert_regulatory_report(data: dict):
    _assert_common(data)
    assert data["status"] == "FILED"
    assert isinstance(data["total_families_at_report"], int)
    assert isinstance(data["total_vials_shipped_at_report"], int)
