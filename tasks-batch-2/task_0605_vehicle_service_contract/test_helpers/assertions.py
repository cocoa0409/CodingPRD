"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_coverage_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert data["tier"] in ("POWERTRAIN", "ENHANCED", "EXCLUSIONARY")
    assert isinstance(data["version"], int)


def assert_reinsurance_pool(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("OPEN", "CLOSED")
    for f in ("ceded_premium_cents", "paid_loss_cents", "reserve_held_cents", "surplus_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert data["surplus_cents"] == (
        data["ceded_premium_cents"] - data["paid_loss_cents"] - data["reserve_held_cents"]
    ), "surplus must equal ceded - paid_loss - reserve_held"


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PENDING", "ACTIVE", "LAPSED", "CANCELLED", "EXPIRED")
    assert isinstance(data["version"], int)


def assert_ancillary_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("BUNDLED", "REFUNDED", "CLAIMED")
    assert data["product_type"] in ("GAP", "TIRE_WHEEL", "KEY_REPLACEMENT")


def assert_repair_facility(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["network_status"] in ("IN_NETWORK", "OUT_OF_NETWORK")


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["adjudication_status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "PAID", "VOID")


def assert_claim_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["line_type"] in ("PART", "LABOR")


def assert_repair_authorization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PENDING", "DISBURSED", "REVERSED")
    assert data["pay_target"] in ("DIRECT_PAY", "CUSTOMER_REIMBURSE")


def assert_cancellation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("REQUESTED", "APPROVED", "REFUNDED", "REJECTED")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at, no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert "version" not in data, "LedgerEntry must not expose a version field"
    assert "updated_at" not in data, "LedgerEntry must not expose an updated_at field"
    assert data["entry_type"] in (
        "PREMIUM_CEDED", "RESERVE_SET", "RESERVE_RELEASE",
        "LOSS_PAID", "LOSS_REVERSED", "REFUND_CLAWBACK",
    )
