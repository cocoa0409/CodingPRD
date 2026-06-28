"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version must be >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["zip_code"], str)
    assert data["install_region"] in ("NORTH", "SOUTH", "EAST", "WEST")


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "LEAD", "DESIGNING", "QUOTED", "DEPOSIT_PAID", "IN_MANUFACTURE",
        "READY_TO_INSTALL", "INSTALLING", "COMPLETED", "CANCELLED",
    )
    assert data["install_region"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert isinstance(data["balance_due_cents"], int)
    assert data["balance_due_cents"] >= 0, "balance_due_cents must be floored at 0"


def assert_design_consult(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "RENDERED", "COMPLETED", "CANCELLED")


def assert_space_measure(data: dict):
    _assert_common(data)
    assert isinstance(data["confirmed"], bool)


def assert_component_config(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
    assert isinstance(data["total_units"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED", "SUPERSEDED", "EXPIRED", "VOID")
    for f in ("subtotal_cents", "discount_cents", "tax_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_deposit(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "CAPTURED", "REFUNDED")
    assert isinstance(data["amount_cents"], int)


def assert_manufacture_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "IN_PRODUCTION", "READY", "INSTALLED")
    assert isinstance(data["lead_time_days"], int)


def assert_crew(data: dict):
    _assert_common(data)
    assert data["region"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert isinstance(data["daily_capacity_units"], int)
    assert isinstance(data["active"], bool)


def assert_install_job(data: dict):
    _assert_common(data)
    assert data["sched_status"] in ("PROPOSED", "BOOKED", "RESCHEDULING", "CANCELLED")
    assert data["completion_status"] in ("NOT_STARTED", "IN_PROGRESS", "DONE")
    assert isinstance(data["units_booked"], int)


def assert_change_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "APPLIED")
    assert data["change_type"] in ("CONFIG_REVISION", "SCHEDULE_CHANGE")
    assert isinstance(data["delta_cents"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "APPROVED", "REJECTED", "ADJUSTMENT_SCHEDULED",
        "REPLACEMENT_ORDERED", "RESOLVED",
    )
    assert data["defect_type"] in ("HARDWARE", "FINISH", "FIT", "STRUCTURAL")
    assert isinstance(data["covered"], bool)


def assert_financing_application(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DECLINED", "FUNDED")
    assert isinstance(data["approved_amount_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
