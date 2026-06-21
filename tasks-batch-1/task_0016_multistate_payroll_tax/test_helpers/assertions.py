"""Entity assertions and domain invariant checkers (PRD §2.4 + §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-fields assertions (id, created_at, updated_at, version) ──────

def _assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an int, got {type(data.get('version'))}"
    assert data["version"] >= 0


def _assert_min_fields(data: dict) -> None:
    """For entities with common_fields=false (GarnishmentDeduction, TaxRateTable)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data or data.get("updated_at") is None or \
        is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be absent or null for append-only entities"


# ─── Entity-specific assertions ───────────────────────────────────────────

def assert_employee(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "TERMINATED")
    assert data["work_state_code"] in ("CA", "NY", "TX", "WA")
    assert data["residence_state_code"] in ("CA", "NY", "TX", "WA")
    assert data["locality_code"] in ("NONE", "NYC", "SF")
    assert isinstance(data["full_name"], str) and data["full_name"]
    for k in ("ytd_wages_cents", "ytd_fed_withheld_cents",
              "ytd_ss_wages_cents", "ytd_medicare_wages_cents"):
        assert isinstance(data[k], int), f"{k} must be int"
        assert data[k] >= 0, f"{k} must be non-negative"


def assert_w4_form(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "FILED", "SUPERSEDED")
    assert data["filing_status"] in ("SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD")
    assert data["tax_year"] in (2025, 2026)
    for k in ("dependents_amount_cents", "other_income_cents",
              "deductions_cents", "extra_withholding_cents"):
        assert isinstance(data[k], int), f"{k} must be int"
        assert data[k] >= 0
    # filed_at is null in DRAFT, non-null once FILED or SUPERSEDED
    if data["status"] == "DRAFT":
        assert data.get("filed_at") is None
    else:
        assert data.get("filed_at") is None or is_iso8601_timestamp(data["filed_at"])


def assert_paycheck_run(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PAID", "VOID")
    assert is_iso8601_timestamp(data["pay_period_start"])
    assert is_iso8601_timestamp(data["pay_period_end"])
    assert is_iso8601_timestamp(data["pay_date"])
    assert isinstance(data["total_gross_cents"], int)
    assert data["total_gross_cents"] >= 0
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    # approved_by_user_id is null in DRAFT, non-null once APPROVED/PAID/VOID
    if data["status"] == "DRAFT":
        assert data.get("approved_by_user_id") is None


def assert_paycheck(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "PAID", "VOID")
    assert data["pay_type"] in ("REGULAR", "OVERTIME", "DOUBLE", "RETRO")
    # All numeric fields must be present and non-negative integers
    int_fields = [
        "gross_wages_cents", "fed_withheld_cents", "state_withheld_cents",
        "local_withheld_cents", "ss_withheld_cents", "medicare_withheld_cents",
        "addl_medicare_cents", "garnishment_total_cents", "net_pay_cents",
    ]
    for k in int_fields:
        assert isinstance(data[k], int), f"{k} must be int, got {type(data[k])}"
        assert data[k] >= 0, f"{k} must be non-negative, got {data[k]}"
    # net_pay is floored at zero (PRD §3.4)
    assert data["net_pay_cents"] >= 0


def assert_garnishment_order(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SATISFIED", "RELEASED", "SUSPENDED")
    assert data["order_type"] in ("CHILD_SUPPORT", "IRS_LEVY", "STUDENT_LOAN", "CREDITOR")
    # priority_rank is pinned at creation per PRD §3.5
    expected_rank = {
        "CHILD_SUPPORT": 1, "IRS_LEVY": 2, "STUDENT_LOAN": 3, "CREDITOR": 4,
    }[data["order_type"]]
    assert data["priority_rank"] == expected_rank, \
        f"priority_rank for {data['order_type']} must be {expected_rank}, got {data['priority_rank']}"
    assert data["balance_remaining_cents"] >= 0
    assert data["weekly_cap_cents"] >= 0


def assert_garnishment_deduction(data: dict) -> None:
    _assert_min_fields(data)
    assert is_valid_uuid(data["paycheck_id"])
    assert is_valid_uuid(data["garnishment_order_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_remittance(data: dict) -> None:
    _assert_common_fields(data)
    assert data["status"] in ("ACCRUING", "RECONCILED", "REMITTED")
    assert data["tax_type"] in ("FED_INCOME", "FICA_EMPLOYEE", "STATE_INCOME", "LOCAL_INCOME")
    # period_month is YYYY-MM
    pm = data["period_month"]
    assert isinstance(pm, str) and len(pm) == 7 and pm[4] == "-"
    for k in ("accrued_cents", "reconciled_cents", "paid_cents"):
        assert isinstance(data[k], int)


# ─── Domain invariants (PRD §3.4 net pay floor + §3.5 waterfall) ─────────

def assert_paycheck_net_pay_invariant(data: dict) -> None:
    """PRD §3.4: net_pay = gross - sum(withholdings) - garnishment_total, floored at 0."""
    expected_subtract = (
        data["fed_withheld_cents"]
        + data["state_withheld_cents"]
        + data["local_withheld_cents"]
        + data["ss_withheld_cents"]
        + data["medicare_withheld_cents"]
        + data["addl_medicare_cents"]
        + data["garnishment_total_cents"]
    )
    expected_net = max(0, data["gross_wages_cents"] - expected_subtract)
    assert data["net_pay_cents"] == expected_net, (
        f"net_pay invariant violated: gross={data['gross_wages_cents']}, "
        f"sum_subtract={expected_subtract}, expected_net={expected_net}, "
        f"got net_pay={data['net_pay_cents']}"
    )
