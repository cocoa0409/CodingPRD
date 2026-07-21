"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "TERMINATED", "CLOSED")
    assert isinstance(data["individual_deductible_cents"], int)
    assert isinstance(data["oop_max_cents"], int)


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["in_network"], bool)
    assert isinstance(data["ytd_paid_cents"], int)


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    for f in ("deductible_met_cents", "oop_met_cents",
              "member_plan_paid_ytd_cents", "spec_reimbursed_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"


def assert_stop_loss_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SETTLED")
    assert data["contract_basis"] in ("PAID", "INCURRED")


def assert_laser(data: dict):
    _assert_common(data)
    assert isinstance(data["laser_deductible_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "PENDED", "ADJUDICATED", "DENIED", "PAID", "REVERSED")
    assert isinstance(data["billed_total_cents"], int)


def assert_fund_account(data: dict):
    _assert_common(data)
    for f in ("balance_cents", "total_deposited_cents", "total_disbursed_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"


def assert_check_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "RELEASED", "VOIDED")


def assert_reimbursement(data: dict):
    _assert_common(data)
    assert data["reimbursement_type"] in ("SPECIFIC", "AGGREGATE")
    assert isinstance(data["amount_cents"], int)


def assert_form_1099(data: dict):
    _assert_common(data)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["reportable"], bool)


def assert_fund_cash_identity(data: dict):
    """The fund cash identity: deposited - disbursed == balance (zero drift)."""
    assert data["total_deposited_cents"] - data["total_disbursed_cents"] == data["balance_cents"], (
        f"fund cash identity violated: {data['total_deposited_cents']} - "
        f"{data['total_disbursed_cents']} != {data['balance_cents']}")
