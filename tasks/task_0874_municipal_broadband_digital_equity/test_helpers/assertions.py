"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_grant(data: dict):
    _assert_common(data)
    assert data["funding_source"] in ("BEAD", "ARPA", "LOCAL")
    assert data["status"] in ("ACTIVE", "MILESTONE_MET", "CLOSED")
    for f in ("award_amount_cents", "committed_balance_cents", "disbursed_balance_cents", "available_balance_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert_grant_partition(data)


def assert_grant_partition(data: dict):
    """Hard invariant (§2.10): available == award - committed - disbursed."""
    assert data["available_balance_cents"] == (
        data["award_amount_cents"] - data["committed_balance_cents"] - data["disbursed_balance_cents"]
    ), "grant fund partition broken: available != award - committed - disbursed"


def assert_service_area(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "CONSTRUCTION", "SERVICEABLE", "SUSPENDED")
    assert isinstance(data["homes_passed"], int)
    assert isinstance(data["fiber_ready"], bool)


def assert_service_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert isinstance(data["monthly_price_cents"], int)


def assert_subsidy_program(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_discount_cents"], int)


def assert_subscriber(data: dict):
    _assert_common(data)
    assert data["status"] == "ACTIVE"


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["service_status"] in ("PENDING_INSTALL", "ACTIVE", "SUSPENDED", "CANCELLED")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE")
    assert isinstance(data["monthly_price_cents"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ACTIVE", "DENIED", "RECERT_DUE", "TERMINATED")
    assert isinstance(data["fpl_pct"], (int, float))


def assert_technician(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "INACTIVE")


def assert_install_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["reschedule_count"], int)


def assert_device(data: dict):
    _assert_common(data)
    assert data["status"] in ("IN_STOCK", "ASSIGNED", "DEPLOYED", "RETURNED")
    assert data["device_class"] in ("CPE_MODEM", "TABLET", "LAPTOP", "HOTSPOT")


def assert_outage(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED")
    assert data["severity"] in ("PARTIAL", "FULL")


def assert_sla_credit(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPLIED", "REVERSED")
    assert isinstance(data["credit_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    for f in ("base_amount_cents", "subsidy_discount_cents", "sla_credit_cents",
              "total_due_cents", "amount_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["total_due_cents"] >= 0, "total_due_cents must never be negative"


def assert_grant_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["amount_claimed_cents"], int)
