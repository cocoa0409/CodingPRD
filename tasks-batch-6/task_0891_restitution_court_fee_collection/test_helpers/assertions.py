"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0
    assert isinstance(data["defendant_name"], str) and len(data["defendant_name"]) > 0
    assert data["status"] in ("OPEN", "SATISFIED")
    assert data["delinquency_status"] in ("CURRENT", "DELINQUENT")
    for f in ("total_assessed_cents", "total_paid_cents", "total_waived_cents",
              "total_written_off_cents", "balance_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_victim(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["payable_balance_cents"], int)
    assert data["payable_balance_cents"] >= 0, "payable_balance_cents never negative"


def assert_obligation(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["obligation_type"] in ("RESTITUTION", "COURT_FEE", "FINE", "SURCHARGE")
    assert isinstance(data["assessed_amount_cents"], int) and data["assessed_amount_cents"] > 0
    assert isinstance(data["priority_rank"], int)
    for f in ("paid_amount_cents", "waived_amount_cents", "balance_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["status"] in ("OUTSTANDING", "PARTIALLY_PAID", "SATISFIED", "WAIVED", "WRITTEN_OFF")


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["monthly_income_cents"], int)
    assert isinstance(data["monthly_expenses_cents"], int)
    assert data["ability_to_pay_method"] in ("NET_DISPOSABLE", "GROSS_INCOME")
    assert isinstance(data["monthly_amount_cents"], int)
    assert isinstance(data["missed_payment_count"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "DEFAULTED", "COMPLETED", "SUPERSEDED")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["allocation_method"] in ("STATUTORY_PRIORITY", "PRO_RATA")
    assert isinstance(data["allocations"], list)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert isinstance(data["victim_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PENDING", "VOIDED")


def assert_wage_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["employer_name"], str) and len(data["employer_name"]) > 0
    assert isinstance(data["monthly_withhold_cents"], int) and data["monthly_withhold_cents"] > 0
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_enforcement_action(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["type"] in ("CIVIL_JUDGMENT", "LICENSE_HOLD")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ACTIVE", "LIFTED")


def assert_waiver_request(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["obligation_id"], str)
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_amnesty_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["waiver_pct"], (int, float))
    assert 0 < data["waiver_pct"] <= 1


def assert_case_ledger_consistent(case: dict):
    """Domain invariant: a case balance never goes negative and its
    SATISFIED status agrees with a zero balance and positive assessment."""
    assert case["balance_cents"] >= 0, "case balance_cents never negative"
    assert case["total_assessed_cents"] >= 0
    if case["status"] == "SATISFIED":
        assert case["total_assessed_cents"] > 0 and case["balance_cents"] == 0
