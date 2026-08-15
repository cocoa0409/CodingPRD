"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ORDER_STATUSES = [
    "RECEIVED",
    "VALIDATED",
    "EMPLOYEE_NOTIFIED",
    "ACTIVE",
    "ANSWER_FILED",
    "SUSPENDED",
    "SATISFIED",
    "TERMINATED",
    "REJECTED",
]
REMIT_POSTURES = ["REMITTING", "HELD", "CLOSED"]
RUN_STATUSES = ["OPEN", "PAID", "VOIDED"]
REMITTANCE_STATUSES = ["PENDING", "CONFIRMED", "LATE_CONFIRMED", "CANCELLED"]
EVENT_TYPES = ["WITHHOLD", "REFUND"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean_fields(data: dict):
    """Append-only / configuration resources carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resource must not carry updated_at"
    assert "version" not in data, "append-only resource must not carry version"


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]
    assert data["remittance_timing"] in ["SAME_DAY", "NEXT_BUSINESS_DAY", "THREE_BUSINESS_DAYS"]
    assert data["administrative_fee_policy"] in ["NONE", "PER_ORDER"]
    assert isinstance(data["admin_fee_cents"], int) and data["admin_fee_cents"] >= 0
    cal = data["payroll_calendar"]
    for key in ("period_start", "period_end", "pay_date"):
        assert isinstance(cal.get(key), str) and cal[key], f"payroll_calendar.{key} required"


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["work_state_code"], str) and len(data["work_state_code"]) == 2
    assert data["pay_frequency"] in ["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"]
    assert isinstance(data["hourly_rate_cents"], int)


def assert_payroll_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert isinstance(data["pay_date"], str) and data["pay_date"]
    assert data["status"] in RUN_STATUSES


def assert_pay_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["payroll_run_id"], str) and data["payroll_run_id"]
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["gross_earnings_cents"], int) and data["gross_earnings_cents"] > 0
    assert isinstance(data["mandatory_deductions_cents"], int)
    assert isinstance(data["disposable_earnings_cents"], int)
    assert (
        data["disposable_earnings_cents"]
        == data["gross_earnings_cents"] - data["mandatory_deductions_cents"]
    ), "disposable_earnings_cents must equal gross minus mandatory deductions"


def assert_issuing_authority(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["authority_type"] in [
        "COURT",
        "CHILD_SUPPORT_AGENCY",
        "FEDERAL_AGENCY",
        "STATE_AGENCY",
    ]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["accepted_case_number_pattern"], str)


def assert_garnishment_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["issuing_authority_id"], str) and data["issuing_authority_id"]
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["order_type"] in [
        "CHILD_SUPPORT",
        "FEDERAL_TAX_LEVY",
        "STUDENT_LOAN",
        "CREDITOR",
    ]
    assert data["amount_model"] in [
        "PERCENT_OF_DISPOSABLE",
        "FIXED_AMOUNT_PER_PERIOD",
        "LUMP_SUM_BALANCE",
    ]
    assert isinstance(data["total_balance_cents"], int) and data["total_balance_cents"] > 0
    assert isinstance(data["withheld_cents"], int) and data["withheld_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0
    assert isinstance(data["remaining_balance_cents"], int)
    assert data["processing_status"] in ORDER_STATUSES
    assert data["remit_posture"] in REMIT_POSTURES


def assert_state_rule(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["caps"], dict)
    assert isinstance(data["min_wage_multiplier"], (int, float))
    assert isinstance(data["hourly_floor_cents"], int)
    assert isinstance(data["fee_deductible_from_wages"], bool)


def assert_withholding_event(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["garnishment_order_id"], str) and data["garnishment_order_id"]
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["payroll_run_id"], str) and data["payroll_run_id"]
    assert isinstance(data["pay_statement_id"], str) and data["pay_statement_id"]
    assert data["event_type"] in EVENT_TYPES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    if data["event_type"] == "WITHHOLD":
        assert data["amount_cents"] > 0, "WITHHOLD amount_cents must be positive"
    else:
        assert data["amount_cents"] < 0, "REFUND amount_cents must be negative"


def assert_remittance(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["authority_id"], str) and data["authority_id"]
    assert isinstance(data["payroll_run_id"], str) and data["payroll_run_id"]
    assert isinstance(data["amount_due_cents"], int)
    assert data["status"] in REMITTANCE_STATUSES
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert isinstance(data["member_event_ids"], list)


def assert_audit_log_entry(data: dict):
    _assert_lean_fields(data)
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert isinstance(data["payload_hash"], str) and len(data["payload_hash"]) == 64
    assert isinstance(data["prev_hash"], str) and data["prev_hash"]
    assert isinstance(data["entry_hash"], str) and len(data["entry_hash"]) == 64


def assert_order_balance_conserved(order: dict):
    """Conserved ledger: total == withheld - refunded + remaining (PRD §3.6)."""
    assert (
        order["total_balance_cents"]
        == order["withheld_cents"]
        - order["refunded_cents"]
        + order["remaining_balance_cents"]
    ), (
        f"balance ledger broken: total={order['total_balance_cents']} "
        f"withheld={order['withheld_cents']} refunded={order['refunded_cents']} "
        f"remaining={order['remaining_balance_cents']}"
    )
