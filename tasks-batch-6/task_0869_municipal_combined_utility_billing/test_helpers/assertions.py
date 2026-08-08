"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in ["ACTIVE", "DELINQUENT", "SHUTOFF", "FINALED", "LIEN_TRANSFERRED"]
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["delinquent_balance_cents"], int)
    assert isinstance(data["deposit_on_hand_cents"], int)


def assert_meter(data: dict):
    _common(data)
    assert data["service_type"] in ["WATER", "SEWER", "ELECTRIC", "REFUSE"]
    assert data["status"] in ["ACTIVE", "REMOVED"]


def assert_meter_reading(data: dict):
    """MeterReading is append-only: only id + created_at, no updated_at / version."""
    _common(data)
    assert "updated_at" not in data, "MeterReading must not carry updated_at"
    assert "version" not in data, "MeterReading must not carry version"
    assert data["read_type"] in ["ACTUAL", "ESTIMATED"]
    assert isinstance(data["reading_value"], int)


def assert_bill(data: dict):
    _common(data)
    assert data["payment_status"] in ["UNPAID", "PARTIAL", "PAID"]
    assert data["collection_status"] in ["CURRENT", "DELINQUENT", "IN_LIEN"]
    assert data["read_basis"] in ["ACTUAL", "ESTIMATED"]
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["pre_discount_total_cents"], int)


def assert_payment(data: dict):
    _common(data)
    assert data["status"] in ["POSTED", "REVERSED"]
    assert data["method"] in ["CASH", "CARD", "ACH", "CHECK"]
    assert isinstance(data["allocation"], list)


def assert_deposit(data: dict):
    _common(data)
    assert data["status"] in ["HELD", "APPLIED", "REFUNDED"]
    assert isinstance(data["amount_cents"], int)


def assert_adjustment(data: dict):
    _common(data)
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED"]
    assert data["adjustment_type"] in ["LEAK", "ESTIMATE_CORRECTION", "GOODWILL"]


def assert_arrangement(data: dict):
    _common(data)
    assert data["status"] in ["ACTIVE", "DEFAULTED", "SUPERSEDED"]


def assert_shutoff_order(data: dict):
    _common(data)
    assert data["status"] in ["SCHEDULED", "EXECUTED", "CANCELLED"]
    assert data["origin"] in ["MANUAL", "CASCADE"]


def assert_lien_transfer(data: dict):
    _common(data)
    assert data["status"] in ["PENDING", "CERTIFIED", "TRANSFERRED"]


def assert_deposit_conservation(data: dict):
    """PRD §3.9: a deposit's amount_cents equals applied_cents plus refunded_cents."""
    assert data["applied_cents"] + data["refunded_cents"] == data["amount_cents"], (
        f"deposit conservation broken: {data['applied_cents']} + {data['refunded_cents']} "
        f"!= {data['amount_cents']}"
    )
