"""Two selectable variants that read the same underlying history differently."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures


def test_accrual_and_cash_bases_bill_the_same_cost_history_differently(api):
    """The same three charges bill 1,672,000 cents on the accrual basis and 1,252,000 on the cash basis.

    Under the `ACCRUAL` basis, an entry qualifies when its `cost_status` is `ACCRUED` or `PAID` and its `incurred_date` falls on or after `billing_period_start` and on or before `billing_period_end`.
    Under the `CASH` basis, an entry qualifies only when its `cost_status` is `PAID`, its `paid_date` is not null, and that `paid_date` falls on or after `billing_period_start` and on or before `billing_period_end`.

    Design: Difficulty/dual_variant_calc/jib_cost_basis_accrual_versus_cash_on_identical_cost_history
    """
    context = fixtures.setup_pooled_producing_well(api, clock="2026-08-10T00:00:00Z")
    well_id = context["well_id"]

    # Incurred in June, settled in July: accrual only.
    fixtures.book_cost(
        api, well_id, "DRILLING", "CAPITAL", 1_200_000, "2026-06-10", "2026-07-05"
    )
    # Incurred and settled in June: both bases.
    fixtures.book_cost(
        api, well_id, "LEASE_OPERATING", "OPERATING", 400_000, "2026-06-20", "2026-06-25"
    )
    # Incurred in May, settled in June: cash only.
    fixtures.book_cost(
        api, well_id, "COMPLETION", "CAPITAL", 800_000, "2026-05-15", "2026-06-05"
    )

    accrual = fixtures.open_statement(
        api, well_id, statement_number="JIB-2026-06-A", cost_basis="ACCRUAL"
    )
    issued_accrual = validate_success(
        api.issue_jib_statement(accrual["id"], fixtures.JIB_ACCOUNTANT), 200
    )

    assert issued_accrual["capital_direct_cents"] == 1_200_000
    assert issued_accrual["operating_direct_cents"] == 400_000
    assert issued_accrual["direct_cost_cents"] == 1_600_000
    assert issued_accrual["overhead_cents"] == 72_000
    assert issued_accrual["total_billed_cents"] == 1_672_000

    validate_success(
        api.void_jib_statement(
            accrual["id"],
            fixtures.JIB_ACCOUNTANT,
            factories.statement_void_payload("REBILL_ON_CASH_BASIS"),
        ),
        200,
    )

    cash = validate_success(
        api.create_jib_statement(
            well_id,
            factories.create_jib_statement_payload(
                statement_number="JIB-2026-06-C", cost_basis="CASH"
            ),
            fixtures.JIB_ACCOUNTANT,
        ),
        201,
    )
    issued_cash = validate_success(
        api.issue_jib_statement(cash["id"], fixtures.JIB_ACCOUNTANT), 200
    )

    assert issued_cash["capital_direct_cents"] == 800_000
    assert issued_cash["operating_direct_cents"] == 400_000
    assert issued_cash["direct_cost_cents"] == 1_200_000
    assert issued_cash["overhead_cents"] == 52_000
    assert issued_cash["total_billed_cents"] == 1_252_000

    assert (
        issued_accrual["total_billed_cents"] - issued_cash["total_billed_cents"]
        == 420_000
    )

    well = validate_success(api.get_well(well_id, fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 1_252_000


def test_late_interest_from_due_date_and_from_proceeds_receipt_diverge(api):
    """The same 1,494,109 cent payment accrues 19,649 cents of interest on one basis and 24,315 on the other.

    Under `FROM_DUE_DATE`, days late are the whole days from `statutory_due_date` to the date part of `paid_at`, and the annual rate is 12 percent.
    Under `FROM_PROCEEDS_RECEIPT`, days late are the whole days from the day **after** the last calendar day of `production_month` to the date part of `paid_at`, and the annual rate is 6 percent.

    Design: Difficulty/dual_variant_calc/statutory_interest_from_due_date_versus_from_proceeds_receipt
    """
    context = fixtures.setup_two_released_revenue_months(
        api, clock="2026-08-05T00:00:00Z"
    )

    june = validate_success(
        api.get_production_revenue(context["june_revenue_id"], fixtures.JIB_ACCOUNTANT),
        200,
    )
    july = validate_success(
        api.get_production_revenue(context["july_revenue_id"], fixtures.JIB_ACCOUNTANT),
        200,
    )
    assert june["statutory_due_date"] == "2026-08-29"
    assert july["statutory_due_date"] == "2026-09-29"

    june_row = context["june_disbursement"]
    july_row = context["july_disbursement"]
    assert june_row["net_amount_cents"] == 1_494_109
    assert july_row["net_amount_cents"] == 1_494_109

    fixtures.set_clock(api, "2026-10-08T00:00:00Z")
    paid_june = validate_success(
        api.pay_owner_disbursement(
            june_row["id"],
            fixtures.JIB_ACCOUNTANT,
            factories.disbursement_payment_payload(interest_basis="FROM_DUE_DATE"),
        ),
        200,
    )

    fixtures.set_clock(api, "2026-11-08T00:00:00Z")
    paid_july = validate_success(
        api.pay_owner_disbursement(
            july_row["id"],
            fixtures.JIB_ACCOUNTANT,
            factories.disbursement_payment_payload(
                interest_basis="FROM_PROCEEDS_RECEIPT"
            ),
        ),
        200,
    )

    assert paid_june["interest_basis"] == "FROM_DUE_DATE"
    assert paid_june["late_interest_cents"] == 19_649
    assert paid_july["interest_basis"] == "FROM_PROCEEDS_RECEIPT"
    assert paid_july["late_interest_cents"] == 24_315
    assert paid_july["late_interest_cents"] - paid_june["late_interest_cents"] == 4_666
