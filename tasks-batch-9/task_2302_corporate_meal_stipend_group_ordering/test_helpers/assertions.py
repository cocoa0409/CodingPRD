"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DE_MINIMIS_PER_MEAL_CENTS, TAX_RATE


# --- helpers ----------------------------------------------------------------
def round_half_up(value: float) -> int:
    """Round a product to a whole cent, half away from zero (PRD §2.6)."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_tax_cents(unit_price_cents: int, quantity: int) -> int:
    """Per-line tax: base * 8.75%, rounded half-up once for this line."""
    return round_half_up(unit_price_cents * quantity * TAX_RATE)


def expected_tax_cents(lines: list) -> int:
    """Sum of per-line rounded tax, in positional order (PRD §3.5 stage one)."""
    return sum(line_tax_cents(l["unit_price_cents"], l["quantity"]) for l in lines)


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# --- per-entity assertions --------------------------------------------------
def assert_meal_program(data: dict):
    _assert_common_fields(data, "MealProgram")
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    assert isinstance(data["billing_account_ref"], str) and data["billing_account_ref"]
    assert isinstance(data["eligible_cuisines"], list) and data["eligible_cuisines"]
    assert data["taxable_benefit_method"] in ("DE_MINIMIS_EXCLUSION", "FULL_INCLUSION")
    assert data["rollover_policy"] in ("NONE", "CAPPED_PCT", "FULL")
    assert data["forecast_basis"] in ("COMMITMENT", "RUN_RATE")
    for field in (
        "program_spent_cents",
        "program_reserved_cents",
        "mtd_employer_captured_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"MealProgram.{field} must be a non-negative integer number of cents"
        )


def assert_employee_group(data: dict):
    _assert_common_fields(data, "EmployeeGroup")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["headcount_planned"], int) and data["headcount_planned"] >= 1
    assert data["active_rule_count"] in (0, 1), (
        f"EmployeeGroup.active_rule_count is invariantly 0 or 1, got {data['active_rule_count']}"
    )


def assert_budget_rule(data: dict):
    _assert_common_fields(data, "BudgetRule")
    assert isinstance(data["group_id"], str) and data["group_id"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["per_meal_cap_cents"], int) and data["per_meal_cap_cents"] >= 1
    assert 1 <= data["daily_meal_limit"] <= 5
    assert data["monthly_allocation_cents"] >= 0
    assert isinstance(data["eligible_weekdays"], list) and data["eligible_weekdays"]
    assert all(1 <= d <= 7 for d in data["eligible_weekdays"])
    assert 0 <= data["eligible_window_start_minute"] <= 1440
    assert (
        data["eligible_window_start_minute"]
        < data["eligible_window_end_minute"]
        <= 1440
    )
    assert data["overage_policy"] in ("PERSONAL_CARD", "BLOCK")
    assert data["tip_coverage_policy"] in ("EMPLOYEE_PAYS_TIP", "EMPLOYER_COVERS_TIP")


def assert_employee(data: dict):
    _assert_common_fields(data, "Employee")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["group_id"], str) and data["group_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["personal_card_on_file"], bool)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["tax_treatment_flag"] in ("NONE", "W2_IMPUTED")
    assert isinstance(data["ytd_imputed_cents"], int) and data["ytd_imputed_cents"] >= 0


def assert_benefit_period(data: dict):
    _assert_common_fields(data, "BenefitPeriod")
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert data["status"] in ("OPEN", "GRACE", "CLOSED")
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert_budget_partition(data)


def assert_restaurant(data: dict):
    _assert_common_fields(data, "Restaurant")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cuisine"], str) and data["cuisine"] == data["cuisine"].upper()
    assert data["delivery_radius_km"] > 0
    assert data["max_concurrent_group_deliveries"] >= 1
    assert data["status"] in ("ELIGIBLE", "SUSPENDED")


def assert_delivery_location(data: dict):
    _assert_common_fields(data, "DeliveryLocation")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["label"], str) and data["label"]
    assert 0 <= data["dock_buffer_minutes"] <= 120


def assert_group_order(data: dict):
    _assert_common_fields(data, "GroupOrder")
    assert data["status"] in ("COLLECTING", "LOCKED", "SUBMITTED", "CANCELLED")
    assert data["cutoff_at"] < data["window_start"] < data["window_end"]
    assert data["per_person_limit_cents"] >= 1
    assert data["member_order_count"] >= 0
    assert data["reopen_count"] >= 0
    assert data["allocated_delivery_fee_cents"] >= 0


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["benefit_period_id"], str) and data["benefit_period_id"]
    assert isinstance(data["restaurant_id"], str) and data["restaurant_id"]
    assert isinstance(data["delivery_location_id"], str) and data["delivery_location_id"]
    assert isinstance(data["lines"], list) and 1 <= len(data["lines"]) <= 20
    assert data["fulfillment_status"] in (
        "DRAFT",
        "PLACED",
        "CONFIRMED",
        "DELIVERED",
        "CANCELLED",
    )
    assert data["settlement_status"] in (
        "UNSETTLED",
        "SPLIT_AUTHORIZED",
        "CAPTURED",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
        "VOIDED",
    )


def assert_credit_claim(data: dict):
    _assert_common_fields(data, "CreditClaim")
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert data["claim_type"] in ("MISSING_ITEM", "QUALITY_ISSUE", "NEVER_DELIVERED")
    assert data["claimed_cents"] >= 1
    assert data["status"] in (
        "SUBMITTED",
        "ROUTED_EMPLOYEE_FIRST",
        "ROUTED_PROPORTIONAL",
        "SETTLED",
        "DENIED",
    )


def assert_imputed_income_record(data: dict):
    _assert_common_fields(data, "ImputedIncomeRecord")
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["tax_month"], str) and len(data["tax_month"]) == 7
    assert data["method"] in ("DE_MINIMIS_EXCLUSION", "FULL_INCLUSION")
    assert data["status"] in ("ACCRUING", "LOCKED", "EXPORTED")
    assert data["taxable_cents"] >= 0
    assert data["gross_employer_paid_cents"] >= 0


def assert_expense_export(data: dict):
    _assert_common_fields(data, "ExpenseExport")
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["format"] in ("CSV_EXPENSE_REPORT", "PAYROLL_IMPUTED_FEED")
    assert data["status"] in ("GENERATED", "ACKNOWLEDGED", "FAILED")
    assert data["receipt_count"] >= 0
    assert (
        data["net_of_refunds_cents"]
        == data["employer_gross_cents"] - data["employer_refund_cents"]
    ), "net_of_refunds_cents is employer_gross_cents minus employer_refund_cents"


def assert_refund_ledger_entry(data: dict):
    """A refund ledger entry carries only id and created_at as system fields."""
    assert is_valid_uuid(data.get("id", "")), "RefundLedgerEntry.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "RefundLedgerEntry.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, (
        "RefundLedgerEntry is append-only and has no updated_at"
    )
    assert "version" not in data, "RefundLedgerEntry is append-only and has no version"
    assert isinstance(data["order_id"], str) and data["order_id"]
    assert data["direction"] in ("EMPLOYER_CREDIT", "EMPLOYEE_CARD_REFUND")
    assert data["reason"] in ("CLAIM_SETTLEMENT", "ORDER_VOID")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1, (
        "amount_cents is always a positive number of cents"
    )


# --- domain invariants ------------------------------------------------------
def assert_budget_partition(period: dict):
    """PRD §2.7: allocated_cents equals the sum of the five buckets."""
    total = (
        period["available_cents"]
        + period["reserved_cents"]
        + period["spent_cents"]
        + period["forfeited_cents"]
        + period["rollover_out_cents"]
    )
    assert period["allocated_cents"] == total, (
        "Budget partition broken: allocated_cents="
        f"{period['allocated_cents']} but available+reserved+spent+forfeited+"
        f"rollover_out={total}"
    )


def assert_cash_conservation(order: dict, ledger_entries: list = None):
    """PRD §2.7: net_charged_cents equals gross_total_cents less both refunds,
    and the ledger sums to the two cumulative refund figures."""
    expected_net = (
        order["gross_total_cents"]
        - order["employer_refunded_cents"]
        - order["employee_refunded_cents"]
    )
    assert order["net_charged_cents"] == expected_net, (
        f"Cash conservation broken: net_charged_cents={order['net_charged_cents']} "
        f"but gross_total - employer_refunded - employee_refunded={expected_net}"
    )
    if ledger_entries is not None:
        ledger_total = sum(e["amount_cents"] for e in ledger_entries)
        expected_ledger = (
            order["employer_refunded_cents"] + order["employee_refunded_cents"]
        )
        assert ledger_total == expected_ledger, (
            f"Refund ledger sums to {ledger_total} but employer_refunded + "
            f"employee_refunded={expected_ledger}"
        )


def assert_imputed_conservation(employee: dict, records: list):
    """PRD §2.7: ytd_imputed_cents equals the sum of taxable_cents over the
    employee's imputed-income records."""
    total = sum(r["taxable_cents"] for r in records)
    assert employee["ytd_imputed_cents"] == total, (
        f"Imputed conservation broken: ytd_imputed_cents="
        f"{employee['ytd_imputed_cents']} but sum of record taxable_cents={total}"
    )


def assert_routing_split_exact(claim: dict):
    """PRD §3.8: employee_refund_cents plus employer_credit_cents always
    equals approved_cents exactly."""
    assert (
        claim["employee_refund_cents"] + claim["employer_credit_cents"]
        == claim["approved_cents"]
    ), (
        f"Routing split does not reconcile: {claim['employee_refund_cents']} + "
        f"{claim['employer_credit_cents']} != {claim['approved_cents']}"
    )


def expected_de_minimis_taxable(employer_share_cents: int) -> int:
    """Only the part of the employer share above the 2,000-cent per-meal floor
    is taxable, and never below zero."""
    return max(0, employer_share_cents - DE_MINIMIS_PER_MEAL_CENTS)


def assert_money_fields_are_integers(data: dict):
    """No monetary field is ever fractional (PRD §2.6)."""
    for key, value in data.items():
        if key.endswith("_cents"):
            assert isinstance(value, int), (
                f"{key} must be an integer number of cents, got {value!r}"
            )
