"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full-lifecycle entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_append_only_fields(data: dict):
    """id + created_at only; no version/updated_at for append-only records."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_agency(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["setup_fee_cents"], int)
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["current_cycle_index"], int)


def assert_counselor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["hud_certified"], bool)
    assert data["status"] == "ACTIVE"


def assert_creditor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["default_concession_apr"], (int, float))


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["gross_monthly_income_cents"], int)
    assert data["status"] in [
        "INTAKE", "ACTIVE", "DEFAULTED", "GRADUATED", "WITHDRAWN",
    ]
    assert isinstance(data["front_end_dti"], (int, float))
    assert isinstance(data["back_end_dti"], (int, float))


def assert_session(data: dict):
    assert_common_fields(data)
    assert data["session_type"] in [
        "BUDGET_INTAKE", "BANKRUPTCY_PREFILING",
        "BANKRUPTCY_PREDISCHARGE", "HUD_HOUSING",
    ]
    assert data["status"] in ["OPEN", "NEEDS_REVISION", "COMPLETED", "CERTIFIED"]


def assert_debt_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["original_balance_cents"], int)
    assert data["status"] in [
        "PROPOSED", "COUNTERED", "ACCEPTED", "ENROLLED", "DROPPED", "SETTLED",
    ]


def assert_proposal(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "COUNTERED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["round_index"], int)


def assert_disbursement_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["total_disbursed_cents"], int)
    assert data["status"] == "COMPLETED"


def assert_deposit_record(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["amount_cents"], int)


def assert_disbursement_line(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
