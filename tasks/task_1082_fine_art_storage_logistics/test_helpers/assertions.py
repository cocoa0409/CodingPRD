"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_client(data: dict):
    _common(data)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_vault(data: dict):
    _common(data)
    assert data["status"] in ("OPERATIONAL", "MAINTENANCE", "DECOMMISSIONED")
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert data["occupied_slots"] <= data["capacity_slots"], "occupied_slots never exceeds capacity"


def assert_artwork(data: dict):
    _common(data)
    assert data["custody_status"] in (
        "IN_INTAKE", "IN_STORAGE", "IN_TRANSIT", "ON_LOAN", "DEACCESSIONED")
    assert data["condition_status"] in ("SOUND", "MINOR_DAMAGE", "MAJOR_DAMAGE")
    assert isinstance(data["appraised_value_cents"], int)


def assert_placement(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RELEASED")
    assert isinstance(data["provisional_fee_cents"], int)


def assert_condition_report(data: dict):
    # common_fields:false — only id + created_at guaranteed, no version/updated_at.
    _common(data, with_version=False)
    assert data["report_type"] in ("INTAKE", "PRE_TRANSIT", "POST_TRANSIT", "PERIODIC", "LOAN_RETURN")


def assert_appraisal(data: dict):
    _common(data)
    assert data["status"] in ("FINALIZED", "SUPERSEDED")
    assert isinstance(data["appraised_value_cents"], int)


def assert_policy(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED", "SUPERSEDED", "LAPSED")
    assert isinstance(data["premium_cents"], int)


def assert_transport_job(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["transport_charge_cents"], int)


def assert_loan(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "ACTIVE", "RETURNED", "CANCELLED")


def assert_carnet(data: dict):
    _common(data)
    assert data["status"] in ("ISSUED", "ACTIVATED", "DISCHARGED", "EXPIRED")


def assert_booking(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_invoice(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"], \
        "total_cents == subtotal_cents + tax_cents"
