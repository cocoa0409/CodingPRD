"""Combinatorial formulas: per-finding rounding order on violation accruals,
and the pinned five-step liability-cap evaluation with extended coverage."""
from test_helpers import (
    CHEAP_DEPARTMENTS,
    CONFIG_A_DEPARTMENTS,
    FINDINGS_EMPTY,
    create_search_order,
    deliver,
    get_order,
    make_research_analyst_headers,
    record_findings,
    setup_identified_order,
    setup_with_ready_delivery,
    validate_success,
)

ANALYST = make_research_analyst_headers("analyst_1")


def test_violation_accruals_rounded_per_finding_then_summed(api):
    """PRD 3.4: "for each finding whose `finding_kind` is `CODE_VIOLATION` and
    that carries both a daily accrual and a day count, the finding's effective
    amount is its `amount_cents` plus the product of `daily_accrual_cents` and
    `days_outstanding` rounded half up to whole cents; every other finding
    contributes its `amount_cents` unchanged. The per-finding effective amounts
    are rounded first and only then summed into `unpaid_balance_cents`. The
    `open_violation_count` is the count of findings whose kind is
    `CODE_VIOLATION`."

    Design: Difficulty/combinatorial_formula/violation_accrual_rounded_per_finding_then_summed
    """
    ctx = setup_identified_order(
        "P-R1", departments=CONFIG_A_DEPARTMENTS, with_association=False
    )
    # Departments spawn in creation order: [UTILITY, CODE_ENFORCEMENT, PERMIT].
    code_task = ctx["tasks"][1]
    assert code_task["dept_type"] == "CODE_ENFORCEMENT"

    response = api.record_findings(
        code_task["id"],
        {
            "expected_research_task_version": code_task["version"],
            "findings": [
                {
                    "finding_kind": "CODE_VIOLATION",
                    "amount_cents": 10000,
                    "daily_accrual_cents": 133.5,
                    "days_outstanding": 7,
                },
                {
                    "finding_kind": "CODE_VIOLATION",
                    "amount_cents": 5000,
                    "daily_accrual_cents": 66.5,
                    "days_outstanding": 3,
                },
                {"finding_kind": "UNPAID_UTILITY", "amount_cents": 3000},
            ],
        },
        ANALYST,
    )
    task = validate_success(response, 200)
    # 10000 + round_half_up(934.5) = 10935; 5000 + round_half_up(199.5) = 5200;
    # + 3000 plain = 19135. Summing first would yield 19134.
    assert task["unpaid_balance_cents"] == 19135, (
        f"Per-finding round-then-sum must give 19135, got "
        f"{task['unpaid_balance_cents']}"
    )
    assert task["open_violation_count"] == 2
    assert task["status"] == "IN_PROGRESS"
    assert task["findings_recorded"] is True


def test_half_cent_accrual_rounds_half_up(api):
    """PRD 2.6: "Where a computation can produce a fractional intermediate — the
    daily accrual on a code-violation finding, and the extended-coverage fee —
    the fractional value is rounded half up to whole cents at a pinned point in
    the calculation: for findings, each finding's accrual is rounded to whole
    cents before any summation takes place, and only those rounded per-finding
    amounts are summed"
    PRD 3.4: "The `open_violation_count` is the count of findings whose kind is
    `CODE_VIOLATION`."

    Design: Difficulty/combinatorial_formula/violation_accrual_rounded_per_finding_then_summed
    """
    ctx = setup_identified_order(
        "P-R2", departments=CONFIG_A_DEPARTMENTS, with_association=False
    )
    code_task = ctx["tasks"][1]
    # 133.5 x 7 = 934.5 -> half-up to 935 exactly (the .5 boundary goes up).
    updated = record_findings(
        code_task,
        [
            {
                "finding_kind": "CODE_VIOLATION",
                "amount_cents": 10000,
                "daily_accrual_cents": 133.5,
                "days_outstanding": 7,
            }
        ],
    )
    assert updated["unpaid_balance_cents"] == 10935
    assert updated["open_violation_count"] == 1


def test_extended_coverage_fee_derives_from_provisional_cap(api):
    """PRD 3.6: "Step one takes the order's current `total_fees_cents` as the
    base. Step two derives the provisional cap: ten times the base, clamped
    below by a floor of 25000 cents and above by a ceiling of 100000 cents —
    that is, the larger of the floor and the smaller of ten-times-base and the
    ceiling. Step three computes the extended-coverage fee: when the order's
    `extended_coverage` is true, the fee is ten percent of the provisional cap
    rounded half up to whole cents; when false, it is zero."
    PRD 3.6: "At the moment of release the delivery freezes its evidence:
    `snapshot_payoff_cents` and `snapshot_fees_cents` copy the order's totals,
    the liability-cap algorithm runs and its results are frozen into
    `coverage_fee_cents` and `liability_cap_cents`"

    Design: Difficulty/combinatorial_formula/liability_cap_evaluation_order_with_extended_coverage
    """
    ctx = setup_with_ready_delivery(
        "P-C1",
        departments=CHEAP_DEPARTMENTS,
        with_association=False,
        findings_per_task=[FINDINGS_EMPTY, FINDINGS_EMPTY, FINDINGS_EMPTY],
        order_overrides={"extended_coverage": True},
    )
    delivery = deliver(ctx["delivery"]["id"])
    # Base = 400 + 350 + 250 = 1000 -> provisional cap max(25000, 10000) = 25000.
    assert delivery["snapshot_fees_cents"] == 1000
    assert delivery["coverage_fee_cents"] == 2500, (
        "Coverage fee is 10% of the MIN-bound provisional cap 25000, not of "
        "the raw base"
    )


def test_final_cap_uses_coverage_inclusive_base(api):
    """PRD 3.6: "Step four adds the coverage fee to the base. Step five derives
    the final cap by applying the identical clamp to ten times that
    coverage-inclusive sum: the larger of 25000 cents and the smaller of
    ten-times-the-sum and 100000 cents."
    PRD 3.6: "the order itself moves from `READY_FOR_DELIVERY` to `DELIVERED`."

    Design: Difficulty/combinatorial_formula/liability_cap_evaluation_order_with_extended_coverage
    """
    ctx = setup_with_ready_delivery(
        "P-C2",
        departments=CHEAP_DEPARTMENTS,
        with_association=False,
        findings_per_task=[FINDINGS_EMPTY, FINDINGS_EMPTY, FINDINGS_EMPTY],
        order_overrides={"extended_coverage": True},
    )
    delivery = deliver(ctx["delivery"]["id"])
    # Final cap = clamp(10 x (1000 + 2500)) = 35000 — above the 25000 floor,
    # reachable only when step five consumes the coverage-inclusive base.
    assert delivery["liability_cap_cents"] == 35000, (
        f"Final cap must be 35000 (escaping the floor via the coverage fee), "
        f"got {delivery['liability_cap_cents']}"
    )
    assert get_order(ctx["order"]["id"])["status"] == "DELIVERED"
