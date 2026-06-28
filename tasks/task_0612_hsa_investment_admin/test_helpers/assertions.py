"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full-common-field entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_accountholder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) > 0


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["payroll_contributions_enabled"], bool)


def assert_payroll_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_start_day"], int)
    assert isinstance(data["period_end_day"], int)
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_account(data: dict):
    _assert_common_fields(data)
    assert data["lifecycle_status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "FROZEN", "CLOSED")
    assert data["contribution_posture"] in ("OPEN", "LOCKED")
    for f in ("cash_balance_cents", "invested_balance_cents",
              "contributions_ytd_cents", "applicable_limit_cents",
              "excess_contribution_cents", "invest_threshold_cents",
              "sweep_increment_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert isinstance(data["plan_year"], int)


def assert_account_ledger_invariants(data: dict):
    """Invariants that must hold on the account after any operation."""
    assert data["cash_balance_cents"] >= 0, "cash balance cannot go negative"
    assert data["invested_balance_cents"] >= 0, "invested balance cannot go negative"
    assert data["excess_contribution_cents"] >= 0, "excess cannot go negative"
    # Posture is derived: OPEN iff ACTIVE and excess == 0, LOCKED otherwise (PRD §2.6).
    if data["lifecycle_status"] == "ACTIVE" and data["excess_contribution_cents"] == 0:
        assert data["contribution_posture"] == "OPEN", \
            "posture must be OPEN when ACTIVE and no excess"
    else:
        assert data["contribution_posture"] == "LOCKED", \
            "posture must be LOCKED when not ACTIVE or excess exists"


def assert_coverage_period(data: dict):
    _assert_common_fields(data)
    assert data["coverage_tier"] in ("SELF_ONLY", "FAMILY")
    assert isinstance(data["effective_month"], int)
    assert isinstance(data["end_month"], int)
    assert data["status"] in ("ATTESTED", "SUPERSEDED")


def assert_contribution(data: dict):
    _assert_common_fields(data)
    assert data["channel"] in ("PAYROLL", "INDIVIDUAL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["contribution_kind"] in ("REGULAR", "CATCH_UP")
    assert data["status"] in ("PENDING", "POSTED", "REVERSED")


def assert_sweep(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["swept_amount_cents"], int)
    assert data["status"] in ("EXECUTED", "UNWOUND")


def assert_distribution(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ("DEBIT_CARD", "REIMBURSEMENT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["substantiation_status"] in (
        "UNSUBSTANTIATED", "QUALIFIED", "NONQUALIFIED")
    assert data["status"] in ("REQUESTED", "CLEARED", "DENIED", "REVERSED")


def assert_receipt(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["merchant"], str) and len(data["merchant"]) > 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["is_qualified_medical"], bool)
    assert data["status"] in ("VAULTED", "CONSUMED")


def assert_debit_card(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["last_four"], str)
    assert data["status"] in ("ISSUED", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_excess_correction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["requested_amount_cents"], int)
    assert data["status"] in ("REQUESTED", "COMPLETED", "REJECTED")


def assert_tax_form(data: dict):
    """TaxForm is an immutable snapshot: id + created_at only, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["form_type"] in ("FORM_1099_SA", "FORM_5498_SA")
    assert isinstance(data["tax_year"], int)
    for f in ("gross_amount_cents", "nonqualified_amount_cents",
              "fair_market_value_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
