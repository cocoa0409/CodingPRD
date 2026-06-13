"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common envelope fields (id, timestamps,
version) plus the entity-specific fields and enum domains declared in the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_resort(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["points_per_week_base"], int)
    assert isinstance(data["annual_fee_cents_per_1000_points"], int)
    assert isinstance(data["rescission_days"], int)
    assert isinstance(data["delinquency_grace_days"], int)
    assert isinstance(data["foreclosure_threshold_periods"], int)
    assert isinstance(data["current_use_year"], int)


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("GOOD_STANDING", "DELINQUENT", "SUSPENDED")
    assert isinstance(data["open_balance_cents"], int)


def assert_inventory_unit(data: dict):
    _assert_common(data)
    assert 1 <= data["week_number"] <= 52
    assert data["season"] in ("PLATINUM", "GOLD", "SILVER")
    assert isinstance(data["points_value"], int)
    assert data["status"] in ("AVAILABLE", "RESERVED", "DEPOSITED_TO_EXCHANGE")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["ownership_type"] in ("DEEDED", "RIGHT_TO_USE")
    assert data["inventory_model"] in ("POINTS", "FIXED_WEEK")
    assert data["status"] in (
        "PENDING_RESCISSION", "ACTIVE", "SUSPENDED", "RESCINDED",
        "TERMINATED", "FORECLOSED", "TRANSFERRED",
    )


def assert_points_account(data: dict):
    _assert_common(data)
    assert isinstance(data["allotment_points"], int)
    assert isinstance(data["banked_in_points"], int)
    assert isinstance(data["banked_out_points"], int)
    assert isinstance(data["borrowed_out_points"], int)
    assert isinstance(data["committed_points"], int)
    assert isinstance(data["available_points"], int)
    assert data["status"] in ("OPEN", "ROLLED_OVER")


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["points_cost"], int)
    assert isinstance(data["borrowed_points"], int)
    assert data["status"] in (
        "HELD", "CONFIRMED", "CANCELLED", "COMPLETED",
        "DEPOSITED_TO_EXCHANGE", "EXPIRED",
    )


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["source_type"] in ("ANNUAL", "SPECIAL_ASSESSMENT")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["late_charge_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "DELINQUENT", "WRITTEN_OFF")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("INITIATED", "CLEARED", "FAILED", "REVERSED")


def assert_special_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["total_amount_cents"], int)
    assert data["status"] in ("DRAFT", "LEVIED")


def assert_exchange_deposit(data: dict):
    _assert_common(data)
    assert data["exchange_network"] in ("RCI", "II")
    assert isinstance(data["exchange_credits"], int)
    assert data["status"] in ("DEPOSITED", "REDEEMED", "RECALLED")


def assert_resale_transfer(data: dict):
    _assert_common(data)
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["transfer_use_year"], int)
    assert isinstance(data["transfer_day_of_year"], int)
    assert data["status"] in ("PENDING_RESCISSION", "COMPLETED", "RESCINDED")


def assert_delinquency_case(data: dict):
    _assert_common(data)
    assert isinstance(data["escalation_periods"], int)
    assert data["late_charge_basis"] in ("SIMPLE", "COMPOUNDING")
    assert data["status"] in ("NOTICE", "LIEN", "FORECLOSURE", "TERMINATION", "CURED")


def assert_available_points_identity(data: dict):
    """available_points == allotment + banked_in - banked_out - borrowed_out - committed.

    PRD §3.3: 'The reported available_points is a derived figure: it is
    allotment_points plus banked_in_points, minus banked_out_points, minus
    borrowed_out_points, minus committed_points.'"""
    expected = (
        data["allotment_points"]
        + data["banked_in_points"]
        - data["banked_out_points"]
        - data["borrowed_out_points"]
        - data["committed_points"]
    )
    assert data["available_points"] == expected, (
        f"available_points {data['available_points']} != derived {expected}"
    )


def assert_amount_due_identity(data: dict):
    """amount_due_cents == amount_cents + late_charge_cents - amount_paid_cents.

    PRD §3.7: 'a derived amount_due_cents equal to amount_cents plus
    late_charge_cents minus amount_paid_cents.'"""
    expected = data["amount_cents"] + data["late_charge_cents"] - data["amount_paid_cents"]
    assert data["amount_due_cents"] == expected, (
        f"amount_due_cents {data['amount_due_cents']} != derived {expected}"
    )
